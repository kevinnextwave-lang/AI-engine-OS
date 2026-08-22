import uuid

from httpx import AsyncClient

from tests.conftest import auth_header, register, unique_email

REFRESH_COOKIE = "asg_refresh_token"


async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_register_returns_tokens_and_sets_cookie(client: AsyncClient) -> None:
    email = unique_email()
    data = await register(client, email)
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == email
    assert "password" not in data["user"]
    assert REFRESH_COOKIE in client.cookies

    me = await client.get("/api/v1/auth/me", headers=auth_header(data["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == email


async def test_register_creates_owner_membership(client: AsyncClient) -> None:
    data = await register(client, org="My Brand Co")
    resp = await client.get("/api/v1/organizations", headers=auth_header(data["access_token"]))
    assert resp.status_code == 200
    orgs = resp.json()
    assert len(orgs) == 1
    assert orgs[0]["name"] == "My Brand Co"
    assert orgs[0]["slug"].startswith("my-brand-co")
    assert orgs[0]["role"] == "owner"


async def test_register_duplicate_email_conflicts(client: AsyncClient) -> None:
    email = unique_email()
    await register(client, email)
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email.upper(),
            "password": "CorrectHorseBattery1",
            "organization_name": "Xyz",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


async def test_register_rejects_weak_password(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": unique_email(), "password": "short", "organization_name": "Xyz"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_login_success_and_failure(client: AsyncClient) -> None:
    email = unique_email()
    await register(client, email)

    ok = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "CorrectHorseBattery1"}
    )
    assert ok.status_code == 200
    assert ok.json()["access_token"]

    bad = await client.post("/api/v1/auth/login", json={"email": email, "password": "nope-nope"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "invalid_credentials"

    unknown = await client.post(
        "/api/v1/auth/login", json={"email": unique_email(), "password": "nope-nope"}
    )
    assert unknown.status_code == 401
    # Same error shape for unknown user vs wrong password (no user enumeration).
    assert unknown.json() == bad.json()


async def test_protected_route_requires_token(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    resp = await client.get("/api/v1/auth/me", headers=auth_header("garbage"))
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_token"


async def test_refresh_rotates_and_old_token_is_rejected(client: AsyncClient) -> None:
    await register(client)
    first_cookie = client.cookies[REFRESH_COOKIE]

    r1 = await client.post("/api/v1/auth/refresh")
    assert r1.status_code == 200
    second_cookie = client.cookies[REFRESH_COOKIE]
    assert second_cookie != first_cookie

    # Replay the old (rotated) token: must fail AND revoke the family.
    client.cookies.set(REFRESH_COOKIE, first_cookie, path="/api/v1/auth")
    replay = await client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401

    # The newer token in the same family is now dead too (theft detection).
    client.cookies.set(REFRESH_COOKIE, second_cookie, path="/api/v1/auth")
    after = await client.post("/api/v1/auth/refresh")
    assert after.status_code == 401


async def test_refresh_without_cookie_fails(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


async def test_logout_revokes_refresh_token(client: AsyncClient) -> None:
    await register(client)
    cookie = client.cookies[REFRESH_COOKIE]
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 200
    client.cookies.set(REFRESH_COOKIE, cookie, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_logout_all_revokes_every_session(client: AsyncClient) -> None:
    email = unique_email()
    data = await register(client, email)
    c1 = client.cookies[REFRESH_COOKIE]
    await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "CorrectHorseBattery1"}
    )
    c2 = client.cookies[REFRESH_COOKIE]
    assert c1 != c2

    resp = await client.post("/api/v1/auth/logout-all", headers=auth_header(data["access_token"]))
    assert resp.status_code == 200
    for c in (c1, c2):
        client.cookies.set(REFRESH_COOKIE, c, path="/api/v1/auth")
        assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_auth_rate_limit(client: AsyncClient) -> None:
    email = unique_email()
    statuses = []
    for _ in range(12):
        r = await client.post("/api/v1/auth/login", json={"email": email, "password": "x" * 10})
        statuses.append(r.status_code)
    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429
    assert r.json()["error"]["code"] == "rate_limited"


async def test_organization_idor_is_blocked(client: AsyncClient) -> None:
    """User B must not be able to read or list members of User A's organization."""
    a = await register(client, org="Org A")
    a_orgs = (
        await client.get("/api/v1/organizations", headers=auth_header(a["access_token"]))
    ).json()
    org_a_id = a_orgs[0]["id"]

    b = await register(client, org="Org B")
    hb = auth_header(b["access_token"])

    # A's org looks nonexistent to B (404, not 403 — no existence leak).
    assert (await client.get(f"/api/v1/organizations/{org_a_id}", headers=hb)).status_code == 404
    assert (
        await client.get(f"/api/v1/organizations/{org_a_id}/members", headers=hb)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/organizations/{uuid.uuid4()}/members", headers=hb)
    ).status_code == 404

    # A can read its own org and members.
    ha = auth_header(a["access_token"])
    org = await client.get(f"/api/v1/organizations/{org_a_id}", headers=ha)
    assert org.status_code == 200 and org.json()["role"] == "owner"
    members = await client.get(f"/api/v1/organizations/{org_a_id}/members", headers=ha)
    assert members.status_code == 200
    assert [m["role"] for m in members.json()] == ["owner"]


async def test_create_additional_organization(client: AsyncClient) -> None:
    data = await register(client, org="First")
    h = auth_header(data["access_token"])
    resp = await client.post("/api/v1/organizations", json={"name": "Second"}, headers=h)
    assert resp.status_code == 201
    orgs = (await client.get("/api/v1/organizations", headers=h)).json()
    assert sorted(o["name"] for o in orgs) == ["First", "Second"]
    assert all(o["role"] == "owner" for o in orgs)


async def test_unknown_route_error_shape(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
