"""Billing: plan summary, Stripe Checkout/Portal handoff, and the webhook.

Design rules:
- The WEBHOOK is the single source of truth for plan and billing-driven
  status changes; the app never sets org.plan from a user request.
- These routes use their own membership dependency that tolerates a
  SUSPENDED org — otherwise a payment-failed owner could never reach the
  portal to fix payment (everything else 404s while suspended).
- Handlers are idempotent by construction (they set fields to target
  values), so Stripe's at-least-once delivery is safe without an event
  ledger.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, SettingsDep
from app.billing import stripe_client
from app.billing.plans import limits_for
from app.core.errors import NotFoundError, PermissionDeniedError, ValidationAppError
from app.core.logging import get_logger
from app.core.permissions import Permission, role_has
from app.models.membership import Membership
from app.models.organization import Organization, OrganizationPlan, OrganizationStatus
from app.repositories.execution import BatchRepository
from app.repositories.organizations import MembershipRepository
from app.schemas.common import MessageResponse

log = get_logger("routes.billing")

org_router = APIRouter(prefix="/organizations/{organization_id}/billing", tags=["billing"])
webhook_router = APIRouter(prefix="/billing", tags=["billing"])

SELF_SERVE_PLANS = (OrganizationPlan.STARTER, OrganizationPlan.GROWTH)


async def get_billing_membership(
    organization_id: Annotated[uuid.UUID, Path()],
    user: CurrentUser,
    session: DBSession,
) -> Membership:
    """Like the normal org scoping, but a SUSPENDED org remains reachable —
    billing is the recovery path. Deleted orgs stay gone."""
    membership = await MembershipRepository(session).get(organization_id, user.id)
    if membership is None:
        raise NotFoundError("Organization not found")
    org = membership.organization
    if org.deleted_at is not None or org.status == OrganizationStatus.DELETED:
        raise NotFoundError("Organization not found")
    return membership


BillingMembership = Annotated[Membership, Depends(get_billing_membership)]


class BillingSummary(BaseModel):
    plan: OrganizationPlan
    plan_label: str
    status: OrganizationStatus
    billing_enabled: bool
    has_subscription: bool
    limits: dict[str, Any]
    ai_spend_today_usd: float
    can_manage: bool


class CheckoutRequest(BaseModel):
    plan: OrganizationPlan


class UrlResponse(BaseModel):
    url: str


@org_router.get("", response_model=BillingSummary)
async def billing_summary(
    membership: BillingMembership, session: DBSession, settings: SettingsDep
) -> BillingSummary:
    org = membership.organization
    limits = limits_for(org.plan)
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    spent = await BatchRepository(session).org_spend_since(org.id, day_start)
    daily_budget = limits.ai_daily_cost_usd
    if settings.ai_daily_cost_limit_usd > 0:
        daily_budget = min(daily_budget, settings.ai_daily_cost_limit_usd)
    return BillingSummary(
        plan=org.plan,
        plan_label=limits.label,
        status=org.status,
        billing_enabled=settings.stripe_secret_key is not None,
        has_subscription=org.stripe_subscription_id is not None,
        limits={
            "projects_per_org": limits.projects_per_org,
            "prompts_per_batch": limits.prompts_per_batch,
            "ai_daily_cost_usd": daily_budget,
            "seo_audits_per_month": limits.seo_audits_per_month,
        },
        ai_spend_today_usd=round(spent, 4),
        can_manage=role_has(membership.role, Permission.BILLING_MANAGE),
    )


def _require_billing_manage(membership: Membership) -> None:
    if not role_has(membership.role, Permission.BILLING_MANAGE):
        raise PermissionDeniedError()


@org_router.post("/checkout", response_model=UrlResponse)
async def start_checkout(
    body: CheckoutRequest,
    membership: BillingMembership,
    user: CurrentUser,
    session: DBSession,
    settings: SettingsDep,
) -> UrlResponse:
    _require_billing_manage(membership)
    if body.plan not in SELF_SERVE_PLANS:
        raise ValidationAppError("This plan is not available for self-serve checkout")
    price_id = stripe_client.plan_to_price(settings, body.plan)
    if price_id is None:
        raise ValidationAppError(f"No Stripe price is configured for the {body.plan.value} plan")
    org = membership.organization
    customer_id = await stripe_client.ensure_customer(settings, org, user.email)
    await session.flush()
    url = await stripe_client.create_checkout_url(
        settings, customer_id=customer_id, price_id=price_id, organization_id=org.id
    )
    return UrlResponse(url=url)


@org_router.post("/portal", response_model=UrlResponse)
async def open_portal(
    membership: BillingMembership,
    user: CurrentUser,
    session: DBSession,
    settings: SettingsDep,
) -> UrlResponse:
    _require_billing_manage(membership)
    org = membership.organization
    customer_id = await stripe_client.ensure_customer(settings, org, user.email)
    await session.flush()
    url = await stripe_client.create_portal_url(settings, customer_id=customer_id)
    return UrlResponse(url=url)


# -- webhook ---------------------------------------------------------------

# Subscription statuses that mean "keep serving" vs "billing hold".
_SERVING = {"active", "trialing", "past_due"}  # past_due: Stripe is retrying
_HOLD = {"unpaid", "incomplete_expired", "paused"}


async def _org_by_customer(session: Any, customer_id: str) -> Organization | None:
    return (
        await session.scalars(
            select(Organization).where(Organization.stripe_customer_id == customer_id)
        )
    ).first()


@webhook_router.post("/webhook", response_model=MessageResponse, include_in_schema=False)
async def stripe_webhook(
    request: Request, session: DBSession, settings: SettingsDep
) -> MessageResponse:
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = stripe_client.construct_event(settings, payload, signature)
    except ValueError as exc:
        raise ValidationAppError(str(exc)) from exc

    kind = str(event.get("type", ""))
    obj: dict[str, Any] = (event.get("data") or {}).get("object") or {}

    if kind == "checkout.session.completed":
        org_id = obj.get("client_reference_id")
        org = await session.get(Organization, uuid.UUID(org_id)) if org_id else None
        if org is not None:
            if obj.get("customer"):
                org.stripe_customer_id = str(obj["customer"])
            if obj.get("subscription"):
                org.stripe_subscription_id = str(obj["subscription"])
            log.info("billing_checkout_completed", organization_id=str(org.id))

    elif kind in ("customer.subscription.created", "customer.subscription.updated"):
        org = await _org_by_customer(session, str(obj.get("customer", "")))
        if org is not None:
            org.stripe_subscription_id = str(obj.get("id") or "") or org.stripe_subscription_id
            items = ((obj.get("items") or {}).get("data")) or []
            price_id = str(((items[0].get("price") or {}).get("id")) if items else "")
            plan = stripe_client.price_to_plan(settings).get(price_id)
            sub_status = str(obj.get("status", ""))
            if plan is not None and sub_status in _SERVING:
                org.plan = plan
            if sub_status in _SERVING and org.status == OrganizationStatus.SUSPENDED:
                org.status = OrganizationStatus.ACTIVE
            elif sub_status in _HOLD:
                org.status = OrganizationStatus.SUSPENDED
            log.info(
                "billing_subscription_synced",
                organization_id=str(org.id),
                plan=org.plan.value,
                sub_status=sub_status,
            )

    elif kind == "customer.subscription.deleted":
        org = await _org_by_customer(session, str(obj.get("customer", "")))
        if org is not None:
            org.plan = OrganizationPlan.FREE
            org.stripe_subscription_id = None
            if org.status == OrganizationStatus.SUSPENDED:
                org.status = OrganizationStatus.ACTIVE  # free tier keeps working
            log.info("billing_subscription_deleted", organization_id=str(org.id))

    # Unhandled event kinds are acknowledged so Stripe stops retrying them.
    return MessageResponse(message="ok")
