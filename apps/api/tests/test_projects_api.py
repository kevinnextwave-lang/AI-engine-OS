"""Milestone 1D — project onboarding: CRUD, validation, domains, competitors,
unauthorized, cross-tenant, role permissions."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.core.urls import InvalidURLError, normalize_website_url
from app.models import MembershipRole
from tests.conftest import auth_header
from tests.test_authz import add_member, org_id_for, signup


async def create_project(client: AsyncClient, headers: dict[str, str], **overrides: object) -> dict:  # type: ignore[type-arg]
    body: dict[str, object] = {"name": "Acme Brand", "website_url": "https://www.acme.com"}
    body.update(overrides)
    resp = await client.post("/api/v1/projects", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


# --- URL normalization ------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "url", "host"),
    [
        ("acme.com", "https://acme.com", "acme.com"),
        ("https://WWW.Acme.com/", "https://www.acme.com", "www.acme.com"),
        ("http://acme.com:80/pricing/", "http://acme.com/pricing/", "acme.com"),
        ("https://acme.com:8443/a?b=1#frag", "https://acme.com:8443/a?b=1", "acme.com"),
        ("  acme.co.uk  ", "https://acme.co.uk", "acme.co.uk"),
        ("https://münchen.de", "https://xn--mnchen-3ya.de", "xn--mnchen-3ya.de"),
    ],
)
def test_normalize_website_url(raw: str, url: str, host: str) -> None:
    result = normalize_website_url(raw)
    assert (result.url, result.hostname) == (url, host)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not a url",
        "ftp://acme.com",
        "http://localhost",
        "http://127.0.0.1",
        "acme",
        "https://user:pw@acme.com",
        "https://-bad-.com",
        "https://acme.123",
    ],
)
def test_invalid_urls_rejected(raw: str) -> None:
    with pytest.raises(InvalidURLError):
        normalize_website_url(raw)


# --- CRUD ---------------------------------------------------------------------


async def test_create_project_registers_primary_domain(client: AsyncClient) -> None:
    data = await signup(client, org="Acme")
    h = auth_header(data["access_token"])
    project = await create_project(
        client, h, website_url="Acme.com/", industry="SaaS", country="us", description="d"
    )
    assert project["slug"] == "acme-brand"
    assert project["country"] == "US"
    assert project["status"] == "active"
    assert project["primary_domain"]["hostname"] == "acme.com"
    assert project["primary_domain"]["url"] == "https://acme.com"
    assert project["primary_domain"]["is_primary"] is True

    domains = (await client.get(f"/api/v1/projects/{project['id']}/domains", headers=h)).json()
    assert [d["hostname"] for d in domains] == ["acme.com"]


async def test_list_get_update_delete(client: AsyncClient) -> None:
    data = await signup(client, org="Acme")
    h = auth_header(data["access_token"])
    p1 = await create_project(client, h, name="First", website_url="first.com")
    p2 = await create_project(client, h, name="Second", website_url="second.com")

    listed = (await client.get("/api/v1/projects", headers=h)).json()
    assert listed["total"] == 2
    assert {p["id"] for p in listed["items"]} == {p1["id"], p2["id"]}

    got = await client.get(f"/api/v1/projects/{p1['id']}", headers=h)
    assert got.status_code == 200 and got.json()["name"] == "First"

    upd = await client.patch(
        f"/api/v1/projects/{p1['id']}",
        json={"name": "Renamed", "status": "paused", "country": "de"},
        headers=h,
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "Renamed"
    assert upd.json()["status"] == "paused"
    assert upd.json()["country"] == "DE"
    assert upd.json()["slug"] == "first"  # slug is stable
    assert upd.json()["primary_domain"]["hostname"] == "first.com"

    assert (await client.delete(f"/api/v1/projects/{p1['id']}", headers=h)).status_code == 200
    assert (await client.get(f"/api/v1/projects/{p1['id']}", headers=h)).status_code == 404
    assert (await client.get("/api/v1/projects", headers=h)).json()["total"] == 1


async def test_list_filter_by_organization_and_multi_org_create(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    data = await signup(client, org="Primary Org")
    h = auth_header(data["access_token"])
    org1 = await org_id_for(client, data["access_token"])
    org2 = (
        await client.post("/api/v1/organizations", json={"name": "Second Org"}, headers=h)
    ).json()["id"]

    # Two orgs -> organization_id becomes required with a useful error.
    resp = await client.post(
        "/api/v1/projects", json={"name": "Ambiguous", "website_url": "amb.io"}, headers=h
    )
    assert resp.status_code == 422
    assert "organization_id" in resp.json()["error"]["message"]
    assert resp.json()["error"]["details"][0]["loc"] == ["body", "organization_id"]

    a = await create_project(client, h, name="In One", website_url="one.io", organization_id=org1)
    b = await create_project(client, h, name="In Two", website_url="two.io", organization_id=org2)
    assert a["organization_id"] == org1 and b["organization_id"] == org2

    all_projects = (await client.get("/api/v1/projects", headers=h)).json()
    assert all_projects["total"] == 2
    only_two = (
        await client.get("/api/v1/projects", params={"organization_id": org2}, headers=h)
    ).json()
    assert [p["id"] for p in only_two["items"]] == [b["id"]]

    # Filtering by an org you don't belong to -> 404
    assert (
        await client.get("/api/v1/projects", params={"organization_id": uuid.uuid4()}, headers=h)
    ).status_code == 404


# --- validation ------------------------------------------------------------------


async def test_project_validation_errors_are_useful(client: AsyncClient) -> None:
    data = await signup(client)
    h = auth_header(data["access_token"])

    resp = await client.post("/api/v1/projects", json={"name": "No URL"}, headers=h)
    assert resp.status_code == 422
    locs = [d["loc"] for d in resp.json()["error"]["details"]]
    assert ["body", "website_url"] in locs

    resp = await client.post(
        "/api/v1/projects", json={"name": "Bad", "website_url": "not a url"}, headers=h
    )
    assert resp.status_code == 422
    detail = next(d for d in resp.json()["error"]["details"] if d["loc"] == ["body", "website_url"])
    assert "whitespace" in detail["msg"].lower()

    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Bad", "website_url": "acme.com", "country": "USA"},
        headers=h,
    )
    assert resp.status_code == 422
    detail = next(d for d in resp.json()["error"]["details"] if d["loc"] == ["body", "country"])
    assert "alpha-2" in detail["msg"]

    resp = await client.post(
        "/api/v1/projects", json={"name": "X", "website_url": "x.com"}, headers=h
    )
    assert resp.status_code == 422  # name too short


# --- domains ------------------------------------------------------------------------


async def test_domains_add_list_and_duplicates(client: AsyncClient) -> None:
    data = await signup(client)
    h = auth_header(data["access_token"])
    project = await create_project(client, h, website_url="acme.com")
    pid = project["id"]

    added = await client.post(
        f"/api/v1/projects/{pid}/domains", json={"url": "https://Shop.Acme.com/"}, headers=h
    )
    assert added.status_code == 201
    assert added.json()["hostname"] == "shop.acme.com"
    assert added.json()["is_primary"] is False
    assert added.json()["verified"] is False

    # Same hostname again (different casing/path) -> 409
    dup = await client.post(
        f"/api/v1/projects/{pid}/domains", json={"url": "http://SHOP.acme.com/x"}, headers=h
    )
    assert dup.status_code == 409
    assert "already part of this project" in dup.json()["error"]["message"]

    # Second primary -> 409
    second_primary = await client.post(
        f"/api/v1/projects/{pid}/domains",
        json={"url": "https://acme.io", "is_primary": True},
        headers=h,
    )
    assert second_primary.status_code == 409
    assert "primary" in second_primary.json()["error"]["message"]

    # Invalid URL -> 422 with field-level message
    bad = await client.post(
        f"/api/v1/projects/{pid}/domains", json={"url": "ftp://x.com"}, headers=h
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["details"][0]["loc"] == ["body", "url"]

    listed = (await client.get(f"/api/v1/projects/{pid}/domains", headers=h)).json()
    assert [(d["hostname"], d["is_primary"]) for d in listed] == [
        ("acme.com", True),
        ("shop.acme.com", False),
    ]


# --- competitors ----------------------------------------------------------------------


async def test_competitor_management(client: AsyncClient) -> None:
    data = await signup(client)
    h = auth_header(data["access_token"])
    pid = (await create_project(client, h, website_url="acme.com"))["id"]

    c = await client.post(
        f"/api/v1/projects/{pid}/competitors",
        json={"name": "  Rival Inc ", "website_url": "Rival.io/about"},
        headers=h,
    )
    assert c.status_code == 201
    body = c.json()
    assert body["name"] == "Rival Inc"
    assert body["website_url"] == "https://rival.io/about"
    assert body["hostname"] == "rival.io"

    dup = await client.post(
        f"/api/v1/projects/{pid}/competitors",
        json={"name": "Rival again", "website_url": "https://rival.io"},
        headers=h,
    )
    assert dup.status_code == 409

    own = await client.post(
        f"/api/v1/projects/{pid}/competitors",
        json={"name": "Me", "website_url": "https://acme.com"},
        headers=h,
    )
    assert own.status_code == 409
    assert "own domains" in own.json()["error"]["message"]

    invalid = await client.post(
        f"/api/v1/projects/{pid}/competitors",
        json={"name": "", "website_url": "nope"},
        headers=h,
    )
    assert invalid.status_code == 422
    assert {d["loc"][1] for d in invalid.json()["error"]["details"]} == {"name", "website_url"}

    listed = (await client.get(f"/api/v1/projects/{pid}/competitors", headers=h)).json()
    assert [x["hostname"] for x in listed] == ["rival.io"]

    gone = await client.delete(f"/api/v1/projects/{pid}/competitors/{body['id']}", headers=h)
    assert gone.status_code == 200
    assert (await client.get(f"/api/v1/projects/{pid}/competitors", headers=h)).json() == []
    assert (
        await client.delete(f"/api/v1/projects/{pid}/competitors/{body['id']}", headers=h)
    ).status_code == 404


# --- unauthorized / cross-tenant --------------------------------------------------------


async def test_unauthenticated_requests_rejected(client: AsyncClient) -> None:
    pid = uuid.uuid4()
    for method, path in [
        ("GET", "/api/v1/projects"),
        ("POST", "/api/v1/projects"),
        ("GET", f"/api/v1/projects/{pid}"),
        ("PATCH", f"/api/v1/projects/{pid}"),
        ("DELETE", f"/api/v1/projects/{pid}"),
        ("GET", f"/api/v1/projects/{pid}/domains"),
        ("POST", f"/api/v1/projects/{pid}/domains"),
        ("GET", f"/api/v1/projects/{pid}/competitors"),
        ("POST", f"/api/v1/projects/{pid}/competitors"),
        ("DELETE", f"/api/v1/projects/{pid}/competitors/{uuid.uuid4()}"),
    ]:
        resp = await client.request(method, path, json={})
        assert resp.status_code == 401, (method, path)
        assert resp.json()["error"]["code"] == "unauthenticated"


async def test_cross_tenant_access_is_blocked(client: AsyncClient) -> None:
    a = await signup(client, org="Org A")
    b = await signup(client, org="Org B")
    ha, hb = auth_header(a["access_token"]), auth_header(b["access_token"])
    org_a = await org_id_for(client, a["access_token"])
    pid = (await create_project(client, ha, website_url="a-corp.com"))["id"]
    cid = (
        await client.post(
            f"/api/v1/projects/{pid}/competitors",
            json={"name": "R", "website_url": "r.com"},
            headers=ha,
        )
    ).json()["id"]

    # B cannot see A's project in any list
    assert (await client.get("/api/v1/projects", headers=hb)).json()["total"] == 0
    # B cannot create into A's org, even by naming it
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Intruder", "website_url": "i.com", "organization_id": org_a},
        headers=hb,
    )
    assert resp.status_code == 404
    # Every item route is 404 for B (never 403 — no existence leak)
    for method, path, body in [
        ("GET", f"/api/v1/projects/{pid}", None),
        ("PATCH", f"/api/v1/projects/{pid}", {"name": "Pwned"}),
        ("DELETE", f"/api/v1/projects/{pid}", None),
        ("GET", f"/api/v1/projects/{pid}/domains", None),
        ("POST", f"/api/v1/projects/{pid}/domains", {"url": "evil.com"}),
        ("GET", f"/api/v1/projects/{pid}/competitors", None),
        ("POST", f"/api/v1/projects/{pid}/competitors", {"name": "E", "website_url": "e.com"}),
        ("DELETE", f"/api/v1/projects/{pid}/competitors/{cid}", None),
    ]:
        resp = await client.request(method, path, json=body, headers=hb)
        assert resp.status_code == 404, (method, path)

    # A's data is untouched
    assert (await client.get(f"/api/v1/projects/{pid}", headers=ha)).json()["name"] == "Acme Brand"
    assert len((await client.get(f"/api/v1/projects/{pid}/competitors", headers=ha)).json()) == 1


# --- role permissions ---------------------------------------------------------------------


async def test_role_permissions_on_projects(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await signup(client, org="Perm Co")
    org = await org_id_for(client, owner["access_token"])
    h = {
        role: auth_header(
            create_access_token(
                await add_member(
                    db_session, org, f"{role.value}-{uuid.uuid4().hex[:6]}@x.com", role
                )
            )
        )
        for role in (MembershipRole.ADMIN, MembershipRole.MEMBER, MembershipRole.VIEWER)
    }
    h[MembershipRole.OWNER] = auth_header(owner["access_token"])
    pid = (await create_project(client, h[MembershipRole.OWNER], website_url="perm.co"))["id"]

    # Viewer: read yes, write no
    v = h[MembershipRole.VIEWER]
    assert (await client.get("/api/v1/projects", headers=v)).json()["total"] == 1
    assert (await client.get(f"/api/v1/projects/{pid}/domains", headers=v)).status_code == 200
    assert (await client.get(f"/api/v1/projects/{pid}/competitors", headers=v)).status_code == 200
    assert (
        await client.post(
            "/api/v1/projects", json={"name": "No", "website_url": "no.io"}, headers=v
        )
    ).status_code == 403
    assert (
        await client.post(f"/api/v1/projects/{pid}/domains", json={"url": "v.io"}, headers=v)
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/projects/{pid}/competitors",
            json={"name": "V", "website_url": "v.io"},
            headers=v,
        )
    ).status_code == 403
    assert (await client.delete(f"/api/v1/projects/{pid}", headers=v)).status_code == 403

    # Member: manage data yes, delete project no
    m = h[MembershipRole.MEMBER]
    assert (
        await client.post(f"/api/v1/projects/{pid}/domains", json={"url": "m.perm.co"}, headers=m)
    ).status_code == 201
    comp = await client.post(
        f"/api/v1/projects/{pid}/competitors", json={"name": "M", "website_url": "m.io"}, headers=m
    )
    assert comp.status_code == 201
    assert (
        await client.delete(f"/api/v1/projects/{pid}/competitors/{comp.json()['id']}", headers=m)
    ).status_code == 200
    assert (await client.delete(f"/api/v1/projects/{pid}", headers=m)).status_code == 403

    # Admin and owner can delete
    extra = (
        await create_project(client, h[MembershipRole.ADMIN], name="Temp", website_url="t.co")
    )["id"]
    assert (
        await client.delete(f"/api/v1/projects/{extra}", headers=h[MembershipRole.ADMIN])
    ).status_code == 200
    assert (
        await client.delete(f"/api/v1/projects/{pid}", headers=h[MembershipRole.OWNER])
    ).status_code == 200


# --- OpenAPI ---------------------------------------------------------------------


async def test_openapi_documents_onboarding_endpoints(client: AsyncClient) -> None:
    spec = (await client.get("/openapi.json")).json()
    paths = spec["paths"]
    for path, methods in {
        "/api/v1/projects": {"get", "post"},
        "/api/v1/projects/{project_id}": {"get", "patch", "delete"},
        "/api/v1/projects/{project_id}/domains": {"get", "post"},
        "/api/v1/projects/{project_id}/competitors": {"get", "post"},
        "/api/v1/projects/{project_id}/competitors/{competitor_id}": {"delete"},
    }.items():
        assert methods <= set(paths[path]), path
    post = paths["/api/v1/projects"]["post"]
    assert post["summary"] == "Create a project"
    assert {"401", "403", "404", "422"} <= set(post["responses"])
    schema = spec["components"]["schemas"]["ProjectCreateRequest"]
    assert set(schema["required"]) == {"name", "website_url"}
