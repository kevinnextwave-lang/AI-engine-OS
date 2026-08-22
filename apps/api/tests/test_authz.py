"""Milestone 1C — authentication and authorization.

Covers: signup (valid, duplicate email, invalid password), login (valid,
invalid), expired access token, refresh rotation, revoked refresh token,
organization isolation, RBAC matrix, IDOR attempts, audit logging.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.passwords import validate_password
from app.core.security import create_access_token
from app.models import AuthAuditLog, AuthEvent, Membership, MembershipRole, User
from tests.conftest import auth_header, unique_email

REFRESH_COOKIE = "asg_refresh_token"
PASSWORD = "CorrectHorseBattery1"


async def signup(client: AsyncClient, email: str | None = None, org: str = "Acme") -> dict:  # type: ignore[type-arg]
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": email or unique_email(),
            "password": PASSWORD,
            "first_name": "Test",
            "last_name": "User",
            "organization_name": org,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


async def org_id_for(client: AsyncClient, token: str) -> str:
    orgs = (await client.get("/api/v1/organizations", headers=auth_header(token))).json()
    return str(orgs[0]["id"])


async def add_member(
    session: AsyncSession, org_id: str, email: str, role: MembershipRole
) -> uuid.UUID:
    """Create a user directly in the DB and attach them to an org with a role."""
    user = User(email=email, password_hash="x", first_name="M", last_name="Ember")
    session.add(user)
    await session.flush()
    session.add(Membership(organization_id=uuid.UUID(org_id), user_id=user.id, role=role))
    await session.flush()
    return user.id


# --- signup ---------------------------------------------------------------


async def test_valid_signup_creates_user_org_and_owner_membership(client: AsyncClient) -> None:
    email = unique_email()
    data = await signup(client, email, org="Signup Co")
    assert data["user"]["email"] == email
    assert data["user"]["full_name"] == "Test User"
    assert data["access_token"] and data["expires_in"] > 0
    assert REFRESH_COOKIE in client.cookies

    orgs = (
        await client.get("/api/v1/organizations", headers=auth_header(data["access_token"]))
    ).json()
    assert [(o["name"], o["role"]) for o in orgs] == [("Signup Co", "owner")]


async def test_signup_duplicate_email_is_conflict(client: AsyncClient) -> None:
    email = unique_email()
    await signup(client, email)
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": email.upper(), "password": PASSWORD, "organization_name": "Other"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "conflict"


async def test_signup_invalid_email_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": "not-an-email", "password": PASSWORD, "organization_name": "Acme"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


async def test_signup_invalid_passwords_rejected(client: AsyncClient) -> None:
    email = unique_email()
    for bad in [
        "short1!",
        "onlyletterslong",
        "12345678901",
        "aaaaaaaaaaaa",
        email.split("@")[0] + "zz1",
    ]:
        resp = await client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": bad, "organization_name": "Acme"},
        )
        assert resp.status_code == 422, bad
        assert resp.json()["error"]["code"] == "validation_error"


def test_password_policy_rules() -> None:
    assert validate_password("CorrectHorseBattery1") == []
    assert validate_password("short1!")
    assert validate_password("lettersonlyhere")
    assert validate_password("12345678901")
    assert validate_password("Password1!", email="x@y.com")  # common
    assert validate_password("jane.doe.secret1", email="jane.doe@example.com")


async def test_password_is_stored_hashed(client: AsyncClient, db_session: AsyncSession) -> None:
    email = unique_email()
    await signup(client, email)
    user = await db_session.scalar(select(User).where(User.email == email))
    assert user is not None
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash


# --- login ----------------------------------------------------------------


async def test_valid_login(client: AsyncClient) -> None:
    email = unique_email()
    await signup(client, email)
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200
    me = await client.get("/api/v1/auth/me", headers=auth_header(resp.json()["access_token"]))
    assert me.status_code == 200 and me.json()["email"] == email


async def test_invalid_login_is_safe_and_uniform(client: AsyncClient) -> None:
    email = unique_email()
    await signup(client, email)
    wrong = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "nope-nope-1"}
    )
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": unique_email(), "password": "nope-nope-1"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert "password" not in wrong.text.lower() or "invalid email or password" in wrong.text.lower()


async def test_login_is_rate_limited(client: AsyncClient) -> None:
    codes = [
        (
            await client.post(
                "/api/v1/auth/login", json={"email": unique_email(), "password": "x" * 12}
            )
        ).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [401] * 10 and codes[10] == 429


# --- tokens ---------------------------------------------------------------


async def test_expired_access_token_rejected(client: AsyncClient) -> None:
    data = await signup(client)
    expired = create_access_token(uuid.UUID(data["user"]["id"]), expires_minutes=-1)
    resp = await client.get("/api/v1/auth/me", headers=auth_header(expired))
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_token"
    assert resp.headers.get("www-authenticate") == "Bearer"


async def test_refresh_rotates_tokens(client: AsyncClient) -> None:
    data = await signup(client)
    first = client.cookies[REFRESH_COOKIE]
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200
    assert resp.json()["access_token"] != data["access_token"]
    assert client.cookies[REFRESH_COOKIE] != first


async def test_revoked_refresh_token_rejected_and_family_killed(client: AsyncClient) -> None:
    await signup(client)
    old = client.cookies[REFRESH_COOKIE]
    await client.post("/api/v1/auth/refresh")
    new = client.cookies[REFRESH_COOKIE]

    client.cookies.set(REFRESH_COOKIE, old, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401  # replay
    client.cookies.set(REFRESH_COOKIE, new, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401  # family revoked


async def test_logout_revokes_refresh_token(client: AsyncClient) -> None:
    await signup(client)
    cookie = client.cookies[REFRESH_COOKIE]
    assert (await client.post("/api/v1/auth/logout")).status_code == 200
    client.cookies.set(REFRESH_COOKIE, cookie, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_refresh_cookie_is_httponly_and_path_scoped(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": unique_email(), "password": PASSWORD, "organization_name": "Cookie Co"},
    )
    cookie = resp.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Path=/api/v1/auth" in cookie and "SameSite=lax" in cookie


# --- organization isolation / IDOR -----------------------------------------


async def test_organization_isolation(client: AsyncClient) -> None:
    a = await signup(client, org="Org A")
    b = await signup(client, org="Org B")
    org_a = await org_id_for(client, a["access_token"])
    hb = auth_header(b["access_token"])

    for path in (
        f"/api/v1/organizations/{org_a}",
        f"/api/v1/organizations/{org_a}/members",
        f"/api/v1/organizations/{org_a}/projects",
    ):
        assert (await client.get(path, headers=hb)).status_code == 404, path
    assert (
        await client.post(
            f"/api/v1/organizations/{org_a}/projects",
            json={"name": "Xy", "website_url": "x.com"},
            headers=hb,
        )
    ).status_code == 404


async def test_idor_on_project_ids(client: AsyncClient) -> None:
    a = await signup(client, org="Org A")
    b = await signup(client, org="Org B")
    org_a = await org_id_for(client, a["access_token"])
    ha, hb = auth_header(a["access_token"]), auth_header(b["access_token"])

    created = await client.post(
        f"/api/v1/organizations/{org_a}/projects",
        json={"name": "Secret Site", "website_url": "secret.example"},
        headers=ha,
    )
    assert created.status_code == 201
    pid = created.json()["id"]

    assert (await client.get(f"/api/v1/projects/{pid}", headers=ha)).status_code == 200
    # B guessing A's project id: 404, never 403 (no existence leak)
    assert (await client.get(f"/api/v1/projects/{pid}", headers=hb)).status_code == 404
    assert (
        await client.patch(f"/api/v1/projects/{pid}", json={"name": "Pwned"}, headers=hb)
    ).status_code == 404
    assert (await client.delete(f"/api/v1/projects/{pid}", headers=hb)).status_code == 404
    assert (await client.get(f"/api/v1/projects/{uuid.uuid4()}", headers=hb)).status_code == 404
    # Unchanged
    assert (await client.get(f"/api/v1/projects/{pid}", headers=ha)).json()["name"] == "Secret Site"


async def test_organization_id_in_body_is_ignored(client: AsyncClient) -> None:
    """A client cannot redirect a create into another tenant by sending organization_id."""
    a = await signup(client, org="Org A")
    b = await signup(client, org="Org B")
    org_a = await org_id_for(client, a["access_token"])
    org_b = await org_id_for(client, b["access_token"])

    resp = await client.post(
        f"/api/v1/organizations/{org_b}/projects",
        json={"name": "Sneaky", "website_url": "sneaky.io", "organization_id": org_a},
        headers=auth_header(b["access_token"]),
    )
    assert resp.status_code == 201
    assert resp.json()["organization_id"] == org_b


# --- RBAC -----------------------------------------------------------------


async def test_rbac_matrix(client: AsyncClient, db_session: AsyncSession) -> None:
    owner = await signup(client, org="RBAC Co")
    org = await org_id_for(client, owner["access_token"])

    tokens = {}
    for role in (MembershipRole.ADMIN, MembershipRole.MEMBER, MembershipRole.VIEWER):
        uid = await add_member(
            db_session, org, f"{role.value}-{uuid.uuid4().hex[:6]}@example.com", role
        )
        tokens[role] = auth_header(create_access_token(uid))
    tokens[MembershipRole.OWNER] = auth_header(owner["access_token"])

    # Everyone can read members and projects.
    for role, h in tokens.items():
        assert (
            await client.get(f"/api/v1/organizations/{org}/members", headers=h)
        ).status_code == 200, role
        assert (
            await client.get(f"/api/v1/organizations/{org}/projects", headers=h)
        ).status_code == 200, role

    # Viewer is read-only.
    r = await client.post(
        f"/api/v1/organizations/{org}/projects",
        json={"name": "Nope", "website_url": "nope.io"},
        headers=tokens[MembershipRole.VIEWER],
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"

    # Member / admin / owner can create and update projects.
    created = {}
    for role in (MembershipRole.MEMBER, MembershipRole.ADMIN, MembershipRole.OWNER):
        r = await client.post(
            f"/api/v1/organizations/{org}/projects",
            json={"name": f"P-{role.value}", "website_url": f"{role.value}.example.com"},
            headers=tokens[role],
        )
        assert r.status_code == 201, role
        created[role] = r.json()["id"]
        r = await client.patch(
            f"/api/v1/projects/{created[role]}", json={"description": "ok"}, headers=tokens[role]
        )
        assert r.status_code == 200, role

    # Viewer cannot update.
    r = await client.patch(
        f"/api/v1/projects/{created[MembershipRole.MEMBER]}",
        json={"description": "x"},
        headers=tokens[MembershipRole.VIEWER],
    )
    assert r.status_code == 403

    # Delete requires admin+: member denied, admin allowed, owner allowed.
    assert (
        await client.delete(
            f"/api/v1/projects/{created[MembershipRole.MEMBER]}",
            headers=tokens[MembershipRole.MEMBER],
        )
    ).status_code == 403
    assert (
        await client.delete(
            f"/api/v1/projects/{created[MembershipRole.MEMBER]}",
            headers=tokens[MembershipRole.ADMIN],
        )
    ).status_code == 200
    assert (
        await client.delete(
            f"/api/v1/projects/{created[MembershipRole.ADMIN]}",
            headers=tokens[MembershipRole.OWNER],
        )
    ).status_code == 200


def test_permission_matrix_shape() -> None:
    from app.core.permissions import Permission, role_has

    assert role_has(MembershipRole.OWNER, Permission.BILLING_MANAGE)
    assert role_has(MembershipRole.OWNER, Permission.ORG_TRANSFER_OWNERSHIP)
    assert not role_has(MembershipRole.ADMIN, Permission.BILLING_MANAGE)
    assert not role_has(MembershipRole.ADMIN, Permission.ORG_TRANSFER_OWNERSHIP)
    assert role_has(MembershipRole.ADMIN, Permission.MEMBERS_MANAGE)
    assert role_has(MembershipRole.ADMIN, Permission.ORG_MANAGE)
    assert role_has(MembershipRole.MEMBER, Permission.PROJECTS_MANAGE)
    assert role_has(MembershipRole.MEMBER, Permission.DATA_MANAGE)
    assert not role_has(MembershipRole.MEMBER, Permission.MEMBERS_MANAGE)
    assert not role_has(MembershipRole.MEMBER, Permission.ORG_MANAGE)
    assert not role_has(MembershipRole.MEMBER, Permission.BILLING_MANAGE)
    assert role_has(MembershipRole.VIEWER, Permission.PROJECTS_READ)
    assert not role_has(MembershipRole.VIEWER, Permission.PROJECTS_MANAGE)
    assert not role_has(MembershipRole.VIEWER, Permission.DATA_MANAGE)


# --- audit logging ----------------------------------------------------------


async def test_auth_events_are_audited(client: AsyncClient, db_session: AsyncSession) -> None:
    email = unique_email()
    data = await signup(client, email)
    await client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-pass-1"})
    await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    old = client.cookies[REFRESH_COOKIE]
    await client.post("/api/v1/auth/refresh")
    client.cookies.set(REFRESH_COOKIE, old, path="/api/v1/auth")
    await client.post("/api/v1/auth/refresh")  # reuse
    await client.post("/api/v1/auth/logout-all", headers=auth_header(data["access_token"]))

    uid = uuid.UUID(data["user"]["id"])
    rows = (
        await db_session.scalars(
            select(AuthAuditLog)
            .where(AuthAuditLog.user_id == uid)
            .order_by(AuthAuditLog.created_at)
        )
    ).all()
    events = [r.event for r in rows]
    assert events[0] == AuthEvent.SIGNUP
    assert AuthEvent.LOGIN_FAILED in events
    assert AuthEvent.LOGIN_SUCCEEDED in events
    assert AuthEvent.TOKEN_REFRESHED in events
    assert AuthEvent.REFRESH_REUSE_DETECTED in events
    assert events[-1] == AuthEvent.LOGOUT_ALL
    assert all(r.ip_address for r in rows)
    # Nothing secret in the audit trail.
    blob = str([r.details for r in rows])
    assert PASSWORD not in blob and data["access_token"] not in blob
