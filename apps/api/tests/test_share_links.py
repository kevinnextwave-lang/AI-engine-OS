"""Share links: creation/list/revoke RBAC, single-exposure tokens, and the
public report endpoint's uniform 404 behavior."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models import MembershipRole
from app.models.organization import Organization, OrganizationStatus
from tests.conftest import auth_header
from tests.test_authz import add_member, org_id_for, signup
from tests.test_projects_api import create_project

pytestmark = pytest.mark.anyio


async def _setup(client: AsyncClient) -> tuple[dict[str, str], str, str]:
    owner = await signup(client, org="Share Co")
    h = auth_header(owner["access_token"])
    org = await org_id_for(client, owner["access_token"])
    pid = (await create_project(client, h, name="Brand", website_url="https://brand.example"))["id"]
    return h, org, pid


async def test_create_list_revoke_roundtrip(client: AsyncClient) -> None:
    h, _org, pid = await _setup(client)
    r = await client.post(
        f"/api/v1/projects/{pid}/share-links", json={"label": "Client X"}, headers=h
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["token"]
    assert created["url_path"] == f"/r/{created['token']}"
    assert created["label"] == "Client X"

    listed = (await client.get(f"/api/v1/projects/{pid}/share-links", headers=h)).json()
    assert len(listed) == 1
    # The raw token is shown once, at creation, and never again.
    assert "token" not in listed[0] and "token_hash" not in listed[0]

    r = await client.delete(f"/api/v1/share-links/{created['id']}", headers=h)
    assert r.status_code == 200
    assert r.json()["revoked_at"] is not None


async def test_public_report_serves_and_dies_with_the_link(client: AsyncClient) -> None:
    h, _org, pid = await _setup(client)
    created = (await client.post(f"/api/v1/projects/{pid}/share-links", json={}, headers=h)).json()
    token = created["token"]

    r = await client.get(f"/api/v1/public/reports/{token}")  # no auth header
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["project_name"] == "Brand"
    assert report["window"] == "30d"
    assert "overview" in report and "engines" in report and "series" in report
    # Results, not methodology: no prompt texts anywhere in the payload.
    assert "prompts" not in report

    # Access is stamped (visible to the owning team).
    listed = (await client.get(f"/api/v1/projects/{pid}/share-links", headers=h)).json()
    assert listed[0]["last_accessed_at"] is not None

    await client.delete(f"/api/v1/share-links/{created['id']}", headers=h)
    assert (await client.get(f"/api/v1/public/reports/{token}")).status_code == 404


async def test_public_report_unknown_token_404(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/public/reports/not-a-real-token")).status_code == 404


async def test_public_report_dead_org_404(client: AsyncClient, db_session: AsyncSession) -> None:
    h, org, pid = await _setup(client)
    token = (await client.post(f"/api/v1/projects/{pid}/share-links", json={}, headers=h)).json()[
        "token"
    ]
    assert (await client.get(f"/api/v1/public/reports/{token}")).status_code == 200
    await db_session.execute(
        update(Organization)
        .where(Organization.id == uuid.UUID(org))
        .values(status=OrganizationStatus.SUSPENDED)
    )
    await db_session.flush()
    assert (await client.get(f"/api/v1/public/reports/{token}")).status_code == 404


async def test_share_link_rbac_and_tenancy(client: AsyncClient, db_session: AsyncSession) -> None:
    h, org, pid = await _setup(client)
    created = (await client.post(f"/api/v1/projects/{pid}/share-links", json={}, headers=h)).json()

    viewer_id = await add_member(
        db_session, org, f"viewer-{uuid.uuid4().hex[:6]}@share.example", MembershipRole.VIEWER
    )
    vh = auth_header(create_access_token(viewer_id))
    assert (await client.get(f"/api/v1/projects/{pid}/share-links", headers=vh)).status_code == 200
    assert (
        await client.post(f"/api/v1/projects/{pid}/share-links", json={}, headers=vh)
    ).status_code == 403
    assert (
        await client.delete(f"/api/v1/share-links/{created['id']}", headers=vh)
    ).status_code == 403

    outsider = await signup(client, org="Other Co")
    oh = auth_header(outsider["access_token"])
    assert (await client.get(f"/api/v1/projects/{pid}/share-links", headers=oh)).status_code == 404
    assert (
        await client.delete(f"/api/v1/share-links/{created['id']}", headers=oh)
    ).status_code == 404
