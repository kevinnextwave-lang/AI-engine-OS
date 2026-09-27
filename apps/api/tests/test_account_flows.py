"""Password reset and email verification: emailed single-use tokens, session
revocation on reset, anti-enumeration, and expiry."""

import re
import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.account as account_module
from app.core.email import EmailMessage, EmailSender
from app.core.security import hash_token, utcnow
from app.models.account_token import AccountToken, AccountTokenPurpose
from tests.conftest import auth_header
from tests.test_authz import PASSWORD, signup, unique_email

NEW_PASSWORD = "Tr1ple-correct-horse-battery!"


class RecordingSender(EmailSender):
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> RecordingSender:
    rec = RecordingSender()
    monkeypatch.setattr(account_module, "get_email_sender", lambda settings=None: rec)
    return rec


def _token_from(message: EmailMessage) -> str:
    m = re.search(r"token=([A-Za-z0-9_-]+)", message.text)
    assert m, message.text
    return m.group(1)


async def test_password_reset_flow(client: AsyncClient, outbox: RecordingSender) -> None:
    email = unique_email()
    await signup(client, email=email)
    outbox.sent.clear()  # drop the signup verification email

    resp = await client.post("/api/v1/auth/forgot-password", json={"email": email})
    assert resp.status_code == 202
    assert len(outbox.sent) == 1 and outbox.sent[0].to == email
    token = _token_from(outbox.sent[0])

    resp = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": NEW_PASSWORD}
    )
    assert resp.status_code == 200, resp.text

    # Old password no longer works; the new one does.
    old = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert old.status_code == 401
    new = await client.post("/api/v1/auth/login", json={"email": email, "password": NEW_PASSWORD})
    assert new.status_code == 200, new.text

    # Single use: replaying the link fails.
    replay = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": NEW_PASSWORD + "x"}
    )
    assert replay.status_code == 422


async def test_forgot_password_does_not_reveal_account_existence(
    client: AsyncClient, outbox: RecordingSender
) -> None:
    known = unique_email()
    await signup(client, email=known)
    outbox.sent.clear()

    r_known = await client.post("/api/v1/auth/forgot-password", json={"email": known})
    r_unknown = await client.post("/api/v1/auth/forgot-password", json={"email": unique_email()})
    assert r_known.status_code == r_unknown.status_code == 202
    assert r_known.json() == r_unknown.json()
    # Only the real account got an email; the response never says so.
    assert len(outbox.sent) == 1


async def test_reset_rejects_weak_password(client: AsyncClient, outbox: RecordingSender) -> None:
    email = unique_email()
    await signup(client, email=email)
    outbox.sent.clear()
    await client.post("/api/v1/auth/forgot-password", json={"email": email})
    token = _token_from(outbox.sent[0])
    resp = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": "aaaaaaaaaaaa"}
    )
    assert resp.status_code == 422
    # A policy failure must not burn the single-use link: retrying the SAME
    # token with a strong password succeeds.
    ok = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": NEW_PASSWORD}
    )
    assert ok.status_code == 200, ok.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": NEW_PASSWORD})
    assert login.status_code == 200


async def test_email_verification_flow(client: AsyncClient, outbox: RecordingSender) -> None:
    email = unique_email()
    created = await signup(client, email=email)
    h = auth_header(created["access_token"])
    assert created["user"]["email_verified"] is False

    # Signup sent the verification email.
    assert len(outbox.sent) == 1 and "verify-email" in outbox.sent[0].text
    token = _token_from(outbox.sent[0])

    resp = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert resp.status_code == 200, resp.text
    me = (await client.get("/api/v1/auth/me", headers=h)).json()
    assert me["email_verified"] is True

    # Replay fails; resend after verification sends nothing new.
    assert (
        await client.post("/api/v1/auth/verify-email", json={"token": token})
    ).status_code == 422
    outbox.sent.clear()
    resend = await client.post("/api/v1/auth/resend-verification", headers=h)
    assert resend.status_code == 202 and outbox.sent == []


async def test_expired_token_is_rejected(
    client: AsyncClient, outbox: RecordingSender, db_session: AsyncSession
) -> None:
    email = unique_email()
    created = await signup(client, email=email)
    raw = "expired-token-" + uuid.uuid4().hex
    db_session.add(
        AccountToken(
            user_id=uuid.UUID(created["user"]["id"]),
            purpose=AccountTokenPurpose.PASSWORD_RESET.value,
            token_hash=hash_token(raw),
            expires_at=utcnow() - timedelta(minutes=1),
        )
    )
    await db_session.commit()
    resp = await client.post(
        "/api/v1/auth/reset-password", json={"token": raw, "password": NEW_PASSWORD}
    )
    assert resp.status_code == 422
