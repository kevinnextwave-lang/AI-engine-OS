"""Self-serve account deletion and owner-only organization deletion."""

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.membership import Membership, MembershipRole
from tests.conftest import auth_header
from tests.test_authz import PASSWORD, org_id_for, signup


async def _member_of(
    session: AsyncSession, client: AsyncClient, org: str, role: MembershipRole
) -> tuple[dict, dict[str, str]]:  # type: ignore[type-arg]
    """A real signed-up user (own solo org) added to `org` with `role`."""
    other = await signup(client, org="Their Own Co")
    session.add(
        Membership(
            organization_id=uuid.UUID(org),
            user_id=uuid.UUID(other["user"]["id"]),
            role=role,
        )
    )
    await session.commit()
    return other, auth_header(other["access_token"])


async def test_delete_account_solo_owner_deletes_org_too(client: AsyncClient) -> None:
    created = await signup(client, org="Solo Co")
    h = auth_header(created["access_token"])

    wrong = await client.request(
        "DELETE", "/api/v1/auth/me", json={"password": "not-the-password"}, headers=h
    )
    assert wrong.status_code == 422

    ok = await client.request("DELETE", "/api/v1/auth/me", json={"password": PASSWORD}, headers=h)
    assert ok.status_code == 200, ok.text

    # The account is gone: the still-valid access token no longer resolves,
    # and logging in again fails.
    assert (await client.get("/api/v1/auth/me", headers=h)).status_code == 401
    login = await client.post(
        "/api/v1/auth/login", json={"email": created["user"]["email"], "password": PASSWORD}
    )
    assert login.status_code == 401


async def test_delete_account_blocked_for_sole_owner_with_members(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await signup(client, org="Team Co")
    h = auth_header(owner["access_token"])
    org = await org_id_for(client, owner["access_token"])
    _, mh = await _member_of(db_session, client, org, MembershipRole.MEMBER)

    blocked = await client.request(
        "DELETE", "/api/v1/auth/me", json={"password": PASSWORD}, headers=h
    )
    assert blocked.status_code == 422 and "only owner" in blocked.text

    # The member owns only their solo org; their own deletion goes through
    # (solo org soft-deleted, membership in Team Co cascades away).
    ok = await client.request("DELETE", "/api/v1/auth/me", json={"password": PASSWORD}, headers=mh)
    assert ok.status_code == 200, ok.text

    # With the last other member gone, the owner can now delete too.
    now_ok = await client.request(
        "DELETE", "/api/v1/auth/me", json={"password": PASSWORD}, headers=h
    )
    assert now_ok.status_code == 200, now_ok.text


async def test_org_delete_is_owner_only_and_soft(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner = await signup(client, org="Deletable Co")
    h = auth_header(owner["access_token"])
    org = await org_id_for(client, owner["access_token"])
    _, mh = await _member_of(db_session, client, org, MembershipRole.ADMIN)

    assert (await client.delete(f"/api/v1/organizations/{org}", headers=mh)).status_code == 403

    ok = await client.delete(f"/api/v1/organizations/{org}", headers=h)
    assert ok.status_code == 200, ok.text
    # Soft-deleted orgs vanish from every scoped surface (deps 404 them).
    assert (await client.get(f"/api/v1/organizations/{org}", headers=h)).status_code == 404
