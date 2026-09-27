"""Thin, test-stubbable wrapper around the Stripe SDK.

Everything here is synchronous SDK work pushed off the event loop; routes
import THESE functions (not stripe directly) so tests can monkeypatch them.
Billing is enabled exactly when STRIPE_SECRET_KEY is set.
"""

import asyncio
import uuid
from typing import Any

from app.core.config import Settings
from app.core.errors import ConflictError
from app.models.organization import Organization, OrganizationPlan


def price_to_plan(settings: Settings) -> dict[str, OrganizationPlan]:
    mapping: dict[str, OrganizationPlan] = {}
    if settings.stripe_price_starter:
        mapping[settings.stripe_price_starter] = OrganizationPlan.STARTER
    if settings.stripe_price_growth:
        mapping[settings.stripe_price_growth] = OrganizationPlan.GROWTH
    return mapping


def plan_to_price(settings: Settings, plan: OrganizationPlan) -> str | None:
    return {
        OrganizationPlan.STARTER: settings.stripe_price_starter,
        OrganizationPlan.GROWTH: settings.stripe_price_growth,
    }.get(plan)


def _require_key(settings: Settings) -> str:
    if settings.stripe_secret_key is None:
        raise ConflictError("Billing is not configured on this deployment")
    return settings.stripe_secret_key.get_secret_value()


async def ensure_customer(settings: Settings, org: Organization, email: str) -> str:
    """The org's Stripe customer id, creating the customer on first use."""
    if org.stripe_customer_id:
        return org.stripe_customer_id
    import stripe

    key = _require_key(settings)

    def _create() -> Any:
        return stripe.Customer.create(
            api_key=key,
            name=org.name,
            email=email,
            metadata={"organization_id": str(org.id)},
        )

    customer = await asyncio.to_thread(_create)
    org.stripe_customer_id = customer["id"]
    return org.stripe_customer_id


async def create_checkout_url(
    settings: Settings, *, customer_id: str, price_id: str, organization_id: uuid.UUID
) -> str:
    import stripe

    key = _require_key(settings)
    base = settings.web_base_url.rstrip("/")

    def _create() -> Any:
        return stripe.checkout.Session.create(
            api_key=key,
            mode="subscription",
            customer=customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            client_reference_id=str(organization_id),
            success_url=f"{base}/app/settings?billing=success",
            cancel_url=f"{base}/app/settings?billing=cancelled",
            allow_promotion_codes=True,
        )

    session = await asyncio.to_thread(_create)
    return str(session["url"])


async def create_portal_url(settings: Settings, *, customer_id: str) -> str:
    import stripe

    key = _require_key(settings)
    base = settings.web_base_url.rstrip("/")

    def _create() -> Any:
        return stripe.billing_portal.Session.create(
            api_key=key, customer=customer_id, return_url=f"{base}/app/settings"
        )

    session = await asyncio.to_thread(_create)
    return str(session["url"])


def construct_event(settings: Settings, payload: bytes, signature: str) -> dict[str, Any]:
    """Verify the webhook signature and parse the event. Raises ValueError on
    a bad payload/signature (route maps it to 400)."""
    import stripe

    if settings.stripe_webhook_secret is None:
        raise ValueError("STRIPE_WEBHOOK_SECRET is not configured")
    try:
        event = stripe.Webhook.construct_event(
            payload, signature, settings.stripe_webhook_secret.get_secret_value()
        )
    except Exception as exc:  # noqa: BLE001 - bad signature/payload alike -> 400
        raise ValueError("Invalid webhook payload or signature") from exc
    return dict(event)
