"""Plan limits, billing routes, and the Stripe webhook lifecycle.

Stripe itself is stubbed at the app.billing.stripe_client seam — these tests
verify OUR behavior: enforcement, persistence, and the suspend/recover path.
"""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_settings as deps_get_settings
from app.billing import stripe_client
from app.core.config import Settings, get_settings
from app.models import CrawlJob, CrawlStatus, CrawlType, Organization, OrganizationPlan
from app.models.organization import OrganizationStatus
from app.models.seo import SeoAudit
from tests.conftest import auth_header
from tests.test_authz import org_id_for, signup
from tests.test_projects_api import create_project


def billing_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "stripe_secret_key": "sk_test_123",
        "stripe_webhook_secret": "whsec_123",
        "stripe_price_starter": "price_starter_1",
        "stripe_price_growth": "price_growth_1",
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


async def test_free_plan_project_limit(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await signup(client, org="Limit Co")
    h = auth_header(owner["access_token"])
    org = await org_id_for(client, owner["access_token"])

    first = await create_project(client, h, name="One", website_url="one.com")
    assert first["id"]
    # FREE includes exactly one project.
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Two", "website_url": "https://two.com", "organization_id": org},
        headers=h,
    )
    assert resp.status_code == 422 and "Free plan includes 1 project" in resp.text

    # Upgrading the plan lifts the cap.
    await db_session.execute(
        update(Organization)
        .where(Organization.id == uuid.UUID(org))
        .values(plan=OrganizationPlan.STARTER)
    )
    await db_session.flush()
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Two", "website_url": "https://two.com", "organization_id": org},
        headers=h,
    )
    assert resp.status_code == 201, resp.text


async def test_free_plan_monthly_audit_quota(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await signup(client, org="Audit Co")
    h = auth_header(owner["access_token"])
    pid = uuid.UUID((await create_project(client, h, website_url="audits.com"))["id"])

    job = CrawlJob(
        project_id=pid,
        root_url="https://audits.com/",
        crawl_type=CrawlType.FULL,
        max_pages=10,
        max_depth=2,
        status=CrawlStatus.COMPLETED,
    )
    db_session.add(job)
    await db_session.flush()
    for _ in range(4):  # FREE quota
        db_session.add(SeoAudit(project_id=pid, crawl_job_id=job.id))
    await db_session.flush()

    resp = await client.post(f"/api/v1/projects/{pid}/seo-audits", json={}, headers=h)
    assert resp.status_code == 429, resp.text
    assert "audits" in resp.text and "Free" in resp.text


async def test_billing_summary_shape(client: AsyncClient) -> None:
    owner = await signup(client, org="Summary Co")
    h = auth_header(owner["access_token"])
    org = await org_id_for(client, owner["access_token"])
    resp = await client.get(f"/api/v1/organizations/{org}/billing", headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["plan"] == "free" and body["plan_label"] == "Free"
    assert body["billing_enabled"] is False and body["has_subscription"] is False
    assert body["limits"]["projects_per_org"] == 1
    assert body["ai_spend_today_usd"] == 0
    assert body["can_manage"] is True


async def test_checkout_creates_customer_and_returns_url(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await signup(client, org="Checkout Co")
    h = auth_header(owner["access_token"])
    org = await org_id_for(client, owner["access_token"])

    app = client._transport.app  # type: ignore[attr-defined]
    settings = billing_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[deps_get_settings] = lambda: settings

    async def fake_ensure_customer(_s: Settings, o: Organization, email: str) -> str:
        o.stripe_customer_id = "cus_test_1"
        return "cus_test_1"

    async def fake_checkout(
        _s: Settings, *, customer_id: str, price_id: str, organization_id: uuid.UUID
    ) -> str:
        assert customer_id == "cus_test_1" and price_id == "price_starter_1"
        return "https://checkout.stripe.com/test-session"

    monkeypatch.setattr(stripe_client, "ensure_customer", fake_ensure_customer)
    monkeypatch.setattr(stripe_client, "create_checkout_url", fake_checkout)

    resp = await client.post(
        f"/api/v1/organizations/{org}/billing/checkout", json={"plan": "starter"}, headers=h
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["url"].startswith("https://checkout.stripe.com/")

    refreshed = await db_session.get(Organization, uuid.UUID(org))
    assert refreshed is not None and refreshed.stripe_customer_id == "cus_test_1"


def _event(kind: str, obj: dict[str, Any]) -> dict[str, Any]:
    return {"type": kind, "data": {"object": obj}}


async def test_webhook_lifecycle_suspend_and_recover(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = await signup(client, org="Lifecycle Co")
    h = auth_header(owner["access_token"])
    org = await org_id_for(client, owner["access_token"])
    pid = (await create_project(client, h, website_url="lc.com"))["id"]

    app = client._transport.app  # type: ignore[attr-defined]
    settings = billing_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[deps_get_settings] = lambda: settings

    events: list[dict[str, Any]] = []
    monkeypatch.setattr(stripe_client, "construct_event", lambda _s, _p, _sig: events.pop(0))

    async def post_event(ev: dict[str, Any]) -> None:
        events.append(ev)
        r = await client.post(
            "/api/v1/billing/webhook", content=b"{}", headers={"stripe-signature": "t"}
        )
        assert r.status_code == 200, r.text

    def sub(status: str, price: str = "price_starter_1") -> dict[str, Any]:
        return {
            "id": "sub_1",
            "customer": "cus_lc_1",
            "status": status,
            "items": {"data": [{"price": {"id": price}}]},
        }

    # 1. Checkout completes: customer + subscription linked to the org.
    await post_event(
        _event(
            "checkout.session.completed",
            {"client_reference_id": org, "customer": "cus_lc_1", "subscription": "sub_1"},
        )
    )
    # 2. Subscription active on the starter price: plan upgrades.
    await post_event(_event("customer.subscription.updated", sub("active")))
    o = await db_session.get(Organization, uuid.UUID(org))
    assert o is not None
    await db_session.refresh(o)
    assert o.plan is OrganizationPlan.STARTER and o.status is OrganizationStatus.ACTIVE

    # 3. Payments fail terminally: billing hold.
    await post_event(_event("customer.subscription.updated", sub("unpaid")))
    await db_session.refresh(o)
    assert o.status is OrganizationStatus.SUSPENDED
    # Everything 404s while suspended — except billing, the recovery path.
    assert (await client.get(f"/api/v1/projects/{pid}", headers=h)).status_code == 404
    assert (await client.get(f"/api/v1/organizations/{org}/billing", headers=h)).status_code == 200

    # 4. Payment fixed: service restored, plan intact.
    await post_event(_event("customer.subscription.updated", sub("active")))
    await db_session.refresh(o)
    assert o.status is OrganizationStatus.ACTIVE and o.plan is OrganizationPlan.STARTER
    assert (await client.get(f"/api/v1/projects/{pid}", headers=h)).status_code == 200

    # 5. Cancellation: back to Free, still serving.
    await post_event(
        _event("customer.subscription.deleted", {"customer": "cus_lc_1", "id": "sub_1"})
    )
    await db_session.refresh(o)
    assert o.plan is OrganizationPlan.FREE and o.status is OrganizationStatus.ACTIVE
    assert o.stripe_subscription_id is None


async def test_webhook_rejects_bad_signature(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = client._transport.app  # type: ignore[attr-defined]
    settings = billing_settings()
    app.dependency_overrides[get_settings] = lambda: settings

    def boom(_s: Settings, _p: bytes, _sig: str) -> dict[str, Any]:
        raise ValueError("Invalid webhook payload or signature")

    monkeypatch.setattr(stripe_client, "construct_event", boom)
    r = await client.post(
        "/api/v1/billing/webhook", content=b"{}", headers={"stripe-signature": "bad"}
    )
    assert r.status_code == 422


async def test_checkout_forbidden_for_non_owner(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await signup(client, org="Perm Co")
    org = await org_id_for(client, owner["access_token"])
    from app.models.membership import Membership, MembershipRole

    other = await signup(client, org="Elsewhere")
    db_session.add(
        Membership(
            organization_id=uuid.UUID(org),
            user_id=uuid.UUID(other["user"]["id"]),
            role=MembershipRole.ADMIN,
        )
    )
    await db_session.commit()
    resp = await client.post(
        f"/api/v1/organizations/{org}/billing/checkout",
        json={"plan": "starter"},
        headers=auth_header(other["access_token"]),
    )
    assert resp.status_code == 403
