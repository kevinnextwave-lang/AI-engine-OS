"""Team management: invite lifecycle, email matching, ownership guardrails."""

import re

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.team as team_module
from app.core.email import EmailMessage, EmailSender
from tests.conftest import auth_header
from tests.test_authz import org_id_for, signup, unique_email


class RecordingSender(EmailSender):
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> RecordingSender:
    rec = RecordingSender()
    monkeypatch.setattr(team_module, "get_email_sender", lambda settings=None: rec)
    return rec


def _token(message: EmailMessage) -> str:
    m = re.search(r"token=([A-Za-z0-9_-]+)", message.text)
    assert m, message.text
    return m.group(1)


async def _org(client: AsyncClient) -> tuple[dict[str, str], str]:
    owner = await signup(client, org="Team Co")
    return auth_header(owner["access_token"]), await org_id_for(client, owner["access_token"])


async def test_invite_accept_flow(client: AsyncClient, outbox: RecordingSender) -> None:
    h, org = await _org(client)
    invited_email = unique_email()

    r = await client.post(
        f"/api/v1/organizations/{org}/invites",
        json={"email": invited_email, "role": "member"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert len(outbox.sent) == 1 and outbox.sent[0].to == invited_email
    token = _token(outbox.sent[0])

    # Pending list shows it; the wrong account cannot accept it.
    listed = (await client.get(f"/api/v1/organizations/{org}/invites", headers=h)).json()
    assert [i["email"] for i in listed] == [invited_email]

    stranger = await signup(client, email=unique_email(), org="Stranger Co")
    wrong = await client.post(
        "/api/v1/invites/accept",
        json={"token": token},
        headers=auth_header(stranger["access_token"]),
    )
    assert wrong.status_code == 422 and invited_email in wrong.text

    # The invited address signs up and accepts.
    invitee = await signup(client, email=invited_email, org="Their Own Co")
    hi = auth_header(invitee["access_token"])
    ok = await client.post("/api/v1/invites/accept", json={"token": token}, headers=hi)
    assert ok.status_code == 200 and "member" in ok.text

    members = (await client.get(f"/api/v1/organizations/{org}/members", headers=h)).json()
    assert any(m["email"] == invited_email and m["role"] == "member" for m in members)
    # Single use: a replay of the consumed link is refused.
    assert (
        await client.post("/api/v1/invites/accept", json={"token": token}, headers=hi)
    ).status_code == 422
    listed = (await client.get(f"/api/v1/organizations/{org}/invites", headers=h)).json()
    assert listed == []


async def test_invite_guardrails(client: AsyncClient, outbox: RecordingSender) -> None:
    h, org = await _org(client)
    # No owner invites.
    r = await client.post(
        f"/api/v1/organizations/{org}/invites",
        json={"email": unique_email(), "role": "owner"},
        headers=h,
    )
    assert r.status_code == 422 and "ownership" in r.text
    # Re-inviting the same email kills the earlier link.
    email = unique_email()
    for _ in range(2):
        assert (
            await client.post(
                f"/api/v1/organizations/{org}/invites",
                json={"email": email, "role": "viewer"},
                headers=h,
            )
        ).status_code == 201
    first_token, second_token = _token(outbox.sent[-2]), _token(outbox.sent[-1])
    invitee = await signup(client, email=email, org="X Co")
    hi = auth_header(invitee["access_token"])
    assert (
        await client.post("/api/v1/invites/accept", json={"token": first_token}, headers=hi)
    ).status_code == 422
    assert (
        await client.post("/api/v1/invites/accept", json={"token": second_token}, headers=hi)
    ).status_code == 200
    # Members (no members:manage) cannot invite; outsiders get 404.
    member_h = hi  # viewer in this org now — viewer lacks members:manage
    r = await client.post(
        f"/api/v1/organizations/{org}/invites",
        json={"email": unique_email(), "role": "member"},
        headers=member_h,
    )
    assert r.status_code == 403
    outsider = await signup(client, org="Out Co")
    r = await client.post(
        f"/api/v1/organizations/{org}/invites",
        json={"email": unique_email(), "role": "member"},
        headers=auth_header(outsider["access_token"]),
    )
    assert r.status_code == 404


async def test_revoke_invite(client: AsyncClient, outbox: RecordingSender) -> None:
    h, org = await _org(client)
    email = unique_email()
    created = await client.post(
        f"/api/v1/organizations/{org}/invites",
        json={"email": email, "role": "member"},
        headers=h,
    )
    invite_id = created.json()["id"]
    token = _token(outbox.sent[0])
    assert (
        await client.delete(f"/api/v1/organizations/{org}/invites/{invite_id}", headers=h)
    ).status_code == 200
    invitee = await signup(client, email=email, org="Y Co")
    assert (
        await client.post(
            "/api/v1/invites/accept",
            json={"token": token},
            headers=auth_header(invitee["access_token"]),
        )
    ).status_code == 422


async def _join_as(
    client: AsyncClient,
    outbox: RecordingSender,
    owner_h: dict[str, str],
    org: str,
    role: str,
) -> tuple[dict, dict[str, str]]:
    email = unique_email()
    await client.post(
        f"/api/v1/organizations/{org}/invites",
        json={"email": email, "role": role},
        headers=owner_h,
    )
    token = _token(outbox.sent[-1])
    account = await signup(client, email=email, org="Own Co")
    h = auth_header(account["access_token"])
    assert (
        await client.post("/api/v1/invites/accept", json={"token": token}, headers=h)
    ).status_code == 200
    return account, h


async def test_member_removal_and_roles(
    client: AsyncClient, outbox: RecordingSender, db_session: AsyncSession
) -> None:
    h, org = await _org(client)
    admin, admin_h = await _join_as(client, outbox, h, org, "admin")
    member, member_h = await _join_as(client, outbox, h, org, "member")

    owner_id = None
    members = (await client.get(f"/api/v1/organizations/{org}/members", headers=h)).json()
    owner_id = next(m["user_id"] for m in members if m["role"] == "owner")

    # A member cannot remove others, but can leave.
    assert (
        await client.delete(
            f"/api/v1/organizations/{org}/members/{admin['user']['id']}", headers=member_h
        )
    ).status_code == 403
    assert (
        await client.delete(
            f"/api/v1/organizations/{org}/members/{member['user']['id']}", headers=member_h
        )
    ).status_code == 200

    # An admin cannot touch the owner (remove or promote/demote).
    assert (
        await client.delete(f"/api/v1/organizations/{org}/members/{owner_id}", headers=admin_h)
    ).status_code == 403
    assert (
        await client.patch(
            f"/api/v1/organizations/{org}/members/{owner_id}",
            json={"role": "member"},
            headers=admin_h,
        )
    ).status_code == 403
    assert (
        await client.patch(
            f"/api/v1/organizations/{org}/members/{admin['user']['id']}",
            json={"role": "owner"},
            headers=admin_h,
        )
    ).status_code == 403

    # The last owner cannot leave or be demoted.
    assert (
        await client.delete(f"/api/v1/organizations/{org}/members/{owner_id}", headers=h)
    ).status_code == 422
    assert (
        await client.patch(
            f"/api/v1/organizations/{org}/members/{owner_id}",
            json={"role": "admin"},
            headers=h,
        )
    ).status_code == 422

    # Owner promotes the admin to owner; then the original owner may leave.
    promoted = await client.patch(
        f"/api/v1/organizations/{org}/members/{admin['user']['id']}",
        json={"role": "owner"},
        headers=h,
    )
    assert promoted.status_code == 200 and promoted.json()["role"] == "owner"
    assert (
        await client.delete(f"/api/v1/organizations/{org}/members/{owner_id}", headers=h)
    ).status_code == 200
    members = (await client.get(f"/api/v1/organizations/{org}/members", headers=admin_h)).json()
    assert [m["role"] for m in members] == ["owner"]
