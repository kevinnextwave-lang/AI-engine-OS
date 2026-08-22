"""Adversarial probes written during the production-readiness review.

Each test encodes a hypothesis about a possible hole. A failing test here
is a finding, not a regression.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models import MembershipRole, Organization, OrganizationStatus
from tests.conftest import auth_header
from tests.test_authz import add_member, org_id_for, signup
from tests.test_projects_api import create_project


async def _two_tenants(client: AsyncClient) -> tuple[dict, dict, str, str, str]:  # type: ignore[type-arg]
    a = await signup(client, org="Org A")
    b = await signup(client, org="Org B")
    org_a = await org_id_for(client, a["access_token"])
    org_b = await org_id_for(client, b["access_token"])
    pid_a = (await create_project(client, auth_header(a["access_token"]), website_url="a.com"))[
        "id"
    ]
    return a, b, org_a, org_b, pid_a


async def test_legacy_org_route_cannot_be_used_to_reach_other_tenant(client: AsyncClient) -> None:
    """B uses their OWN org id in the path but A's project id elsewhere."""
    a, b, org_a, org_b, pid_a = await _two_tenants(client)
    hb = auth_header(b["access_token"])
    listed = (await client.get(f"/api/v1/organizations/{org_b}/projects", headers=hb)).json()
    assert all(p["id"] != pid_a for p in listed)
    # B's competitor id vs A's project id, and vice versa
    pid_b = (await create_project(client, hb, website_url="b.com"))["id"]
    cid_b = (
        await client.post(
            f"/api/v1/projects/{pid_b}/competitors",
            json={"name": "X", "website_url": "x.com"},
            headers=hb,
        )
    ).json()["id"]
    assert (
        await client.delete(f"/api/v1/projects/{pid_a}/competitors/{cid_b}", headers=hb)
    ).status_code == 404


async def test_viewer_cannot_create_project_via_body_selector(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await signup(client, org="Org A")
    org = await org_id_for(client, owner["access_token"])
    uid = await add_member(
        db_session, org, f"v-{uuid.uuid4().hex[:6]}@x.com", MembershipRole.VIEWER
    )
    hv = auth_header(create_access_token(uid))
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Nope", "website_url": "nope.io", "organization_id": org},
        headers=hv,
    )
    assert resp.status_code == 403


@pytest.mark.xfail(strict=True, reason="Review finding H2: suspended status not enforced")
async def test_suspended_organization_is_blocked(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """HYPOTHESIS: status=suspended is not enforced anywhere."""
    a = await signup(client, org="Org A")
    org = await org_id_for(client, a["access_token"])
    h = auth_header(a["access_token"])
    pid = (await create_project(client, h, website_url="a.com"))["id"]
    await db_session.execute(
        update(Organization)
        .where(Organization.id == uuid.UUID(org))
        .values(status=OrganizationStatus.SUSPENDED)
    )
    await db_session.flush()
    assert (await client.get(f"/api/v1/organizations/{org}", headers=h)).status_code in (403, 404)
    assert (await client.get(f"/api/v1/projects/{pid}", headers=h)).status_code in (403, 404)
    assert (
        await client.post(
            "/api/v1/projects", json={"name": "More", "website_url": "m.io"}, headers=h
        )
    ).status_code in (403, 404)


async def test_access_token_survives_logout_all(client: AsyncClient) -> None:
    """HYPOTHESIS: logout-all revokes refresh tokens only; access token still valid."""
    a = await signup(client)
    h = auth_header(a["access_token"])
    await client.post("/api/v1/auth/logout-all", headers=h)
    resp = await client.get("/api/v1/auth/me", headers=h)
    # Document current behaviour: stateless JWT remains valid until expiry.
    assert resp.status_code == 200


async def test_rate_limit_bypass_via_x_forwarded_for(client: AsyncClient) -> None:
    """HYPOTHESIS: the limiter trusts X-Forwarded-For from any client."""
    codes = []
    for i in range(12):
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": f"z{i}@example.com", "password": "x" * 12},
            headers={"X-Forwarded-For": f"10.0.0.{i}"},
        )
        codes.append(r.status_code)
    # Review finding H1: the limiter is spoofable today, so all 12 are 401.
    # Once fixed this assertion must flip to `429 in codes`.
    assert 429 not in codes


@pytest.mark.xfail(strict=True, reason="Review finding M4: deleted users listed as members")
async def test_deleted_user_membership_not_listed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await signup(client, org="Org A")
    org = await org_id_for(client, owner["access_token"])
    uid = await add_member(
        db_session, org, f"d-{uuid.uuid4().hex[:6]}@x.com", MembershipRole.MEMBER
    )
    from app.core.security import utcnow
    from app.models import User

    await db_session.execute(update(User).where(User.id == uid).values(deleted_at=utcnow()))
    await db_session.flush()
    # Deleted user cannot authenticate
    assert (
        await client.get("/api/v1/auth/me", headers=auth_header(create_access_token(uid)))
    ).status_code == 401
    # HYPOTHESIS: but still appears in the member list
    members = (
        await client.get(
            f"/api/v1/organizations/{org}/members", headers=auth_header(owner["access_token"])
        )
    ).json()
    assert all(m["user_id"] != str(uid) for m in members)


async def test_org_settings_of_other_tenant_unreachable(client: AsyncClient) -> None:
    a, b, org_a, org_b, _ = await _two_tenants(client)
    hb = auth_header(b["access_token"])
    for path in (f"/api/v1/organizations/{org_a}", f"/api/v1/organizations/{org_a}/members"):
        assert (await client.get(path, headers=hb)).status_code == 404
    # Enumerating orgs via the list endpoint never shows A
    mine = (await client.get("/api/v1/organizations", headers=hb)).json()
    assert [o["id"] for o in mine] == [org_b]


async def test_soft_deleted_org_projects_not_listed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.core.security import utcnow

    a = await signup(client, org="Org A")
    org = await org_id_for(client, a["access_token"])
    h = auth_header(a["access_token"])
    pid = (await create_project(client, h, website_url="a.com"))["id"]
    await db_session.execute(
        update(Organization).where(Organization.id == uuid.UUID(org)).values(deleted_at=utcnow())
    )
    await db_session.flush()
    assert (await client.get("/api/v1/projects", headers=h)).json()["total"] == 0
    assert (await client.get(f"/api/v1/projects/{pid}", headers=h)).status_code == 404
    assert (await client.get("/api/v1/organizations", headers=h)).json() == []
    rows = (await db_session.scalars(select(Organization))).all()
    assert rows
