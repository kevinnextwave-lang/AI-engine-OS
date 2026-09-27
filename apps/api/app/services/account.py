"""Account flows built on single-use emailed tokens: password reset and
email verification.

Anti-enumeration: request_password_reset behaves identically whether or not
the email exists (the route always answers 202). Failures to DELIVER the
email are logged, never surfaced — surfacing them would leak existence.

Single-use: completing a flow stamps used_at; validation rejects used and
expired tokens. Completing a password reset also revokes every refresh
token the user has (a reset after suspected theft must end stolen sessions).
"""

import asyncio
import secrets
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.email import EmailMessage, EmailSender, get_email_sender
from app.core.errors import ValidationAppError
from app.core.logging import get_logger
from app.core.passwords import validate_password
from app.core.security import hash_password, hash_token, utcnow, verify_password
from app.models.account_token import AccountToken, AccountTokenPurpose
from app.models.auth_audit_log import AuthEvent
from app.models.membership import MembershipRole
from app.models.organization import OrganizationStatus
from app.models.user import User
from app.repositories.organizations import MembershipRepository
from app.repositories.refresh_tokens import RefreshTokenRepository
from app.repositories.users import UserRepository
from app.services.audit import AuthAuditService
from app.services.auth import ClientInfo

log = get_logger("services.account")

_INVALID_LINK = "This link is invalid, has expired, or was already used."


class AccountService:
    def __init__(self, session: AsyncSession, sender: EmailSender | None = None) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._audit = AuthAuditService(session)
        self._settings = get_settings()
        self._sender = sender or get_email_sender(self._settings)

    # -- token plumbing ----------------------------------------------------

    async def _issue(self, user_id: uuid.UUID, purpose: AccountTokenPurpose, ttl: timedelta) -> str:
        raw = secrets.token_urlsafe(48)
        self._session.add(
            AccountToken(
                user_id=user_id,
                purpose=purpose.value,
                token_hash=hash_token(raw),
                expires_at=utcnow() + ttl,
            )
        )
        await self._session.flush()
        return raw

    async def _get_valid(self, raw: str, purpose: AccountTokenPurpose) -> AccountToken:
        """Load a fresh (unused, unexpired) token or raise. Callers stamp
        used_at themselves once their own validation passed, so e.g. a weak
        replacement password doesn't burn the reset link."""
        record = (
            await self._session.scalars(
                select(AccountToken).where(
                    AccountToken.token_hash == hash_token(raw),
                    AccountToken.purpose == purpose.value,
                )
            )
        ).first()
        if record is None or record.used_at is not None or record.expires_at <= utcnow():
            raise ValidationAppError(_INVALID_LINK)
        return record

    def _link(self, path: str, token: str) -> str:
        return f"{self._settings.web_base_url.rstrip('/')}{path}?token={token}"

    # -- password reset ----------------------------------------------------

    async def request_password_reset(self, *, email: str, client: ClientInfo) -> None:
        email = email.lower().strip()
        user = await self._users.get_by_email(email)
        if user is None or not user.is_active:
            # Same outward behaviour as success; nothing to audit against a user.
            return
        ttl = timedelta(minutes=self._settings.password_reset_token_expire_minutes)
        raw = await self._issue(user.id, AccountTokenPurpose.PASSWORD_RESET, ttl)
        await self._audit.record(
            AuthEvent.PASSWORD_RESET_REQUESTED,
            user_id=user.id,
            email=email,
            ip_address=client.ip_address,
            user_agent=client.user_agent,
        )
        minutes = self._settings.password_reset_token_expire_minutes
        message = EmailMessage(
            to=email,
            subject="Reset your password",
            text=(
                "Someone (hopefully you) requested a password reset for your "
                "AI Search Growth OS account.\n\n"
                f"Reset it here (link valid for {minutes} minutes, single use):\n"
                f"{self._link('/reset-password', raw)}\n\n"
                "If you didn't request this, you can ignore this email — your "
                "password is unchanged."
            ),
        )
        try:
            await self._sender.send(message)
        except Exception:  # noqa: BLE001 - never leak delivery state to the caller
            log.exception("password_reset_email_failed", user_id=str(user.id))

    async def reset_password(self, *, token: str, new_password: str, client: ClientInfo) -> None:
        record = await self._get_valid(token, AccountTokenPurpose.PASSWORD_RESET)
        user = await self._users.get_by_id(record.user_id)
        if user is None or not user.is_active:
            raise ValidationAppError(_INVALID_LINK)
        problems = validate_password(new_password, email=user.email)
        if problems:
            # Policy failure must not burn the single-use link.
            raise ValidationAppError("; ".join(problems))
        record.used_at = utcnow()
        user.password_hash = await asyncio.to_thread(hash_password, new_password)
        # A reset must end every existing session: that is the point when the
        # reason for the reset is a stolen credential.
        await RefreshTokenRepository(self._session).revoke_all_for_user(user.id, utcnow())
        await self._audit.record(
            AuthEvent.PASSWORD_RESET_COMPLETED,
            user_id=user.id,
            email=user.email,
            ip_address=client.ip_address,
            user_agent=client.user_agent,
        )

    # -- account deletion ----------------------------------------------------

    async def delete_account(self, *, user: User, password: str, client: ClientInfo) -> None:
        """Self-serve deletion. The password confirms intent (a stolen access
        token alone must not be able to destroy the account).

        Organizations: one where this user is the only member is soft-deleted
        with the account. One with OTHER members where this user is the only
        owner blocks deletion — ownership must be transferred (or the org
        deleted) first, otherwise the org would be orphaned. Orgs with another
        owner simply lose this membership (FK cascade).
        """
        if not await asyncio.to_thread(verify_password, password, user.password_hash):
            raise ValidationAppError("Password is incorrect.")

        memberships_repo = MembershipRepository(self._session)
        for membership in await memberships_repo.list_for_user(user.id):
            org = membership.organization
            if org.deleted_at is not None or org.status == OrganizationStatus.DELETED:
                continue
            members = await memberships_repo.list_for_organization(org.id)
            others = [m for m in members if m.user_id != user.id]
            if not others:
                org.status = OrganizationStatus.DELETED
                org.deleted_at = utcnow()
                continue
            if membership.role == MembershipRole.OWNER and not any(
                m.role == MembershipRole.OWNER for m in others
            ):
                raise ValidationAppError(
                    f"You are the only owner of '{org.name}', which still has other members. "
                    "Transfer ownership or remove the members first."
                )
        log.info("account_deleted", user_id=str(user.id), email=user.email)
        # Hard delete: memberships, refresh tokens and account tokens cascade;
        # authorship columns are SET NULL; the auth audit trail keeps its rows
        # with user_id nulled (events remain for investigation).
        await self._session.delete(user)

    # -- email verification --------------------------------------------------

    async def send_verification(self, user: User) -> None:
        """Best-effort: callers like signup must never fail on mail delivery."""
        if user.email_verified:
            return
        ttl = timedelta(hours=self._settings.email_verification_token_expire_hours)
        raw = await self._issue(user.id, AccountTokenPurpose.EMAIL_VERIFY, ttl)
        hours = self._settings.email_verification_token_expire_hours
        message = EmailMessage(
            to=user.email,
            subject="Verify your email address",
            text=(
                "Welcome to AI Search Growth OS!\n\n"
                f"Please confirm this email address (link valid for {hours} hours):\n"
                f"{self._link('/verify-email', raw)}\n\n"
                "If you didn't create this account, you can ignore this email."
            ),
        )
        try:
            await self._sender.send(message)
        except Exception:  # noqa: BLE001
            log.exception("verification_email_failed", user_id=str(user.id))

    async def verify_email(self, *, token: str, client: ClientInfo) -> User:
        record = await self._get_valid(token, AccountTokenPurpose.EMAIL_VERIFY)
        user = await self._users.get_by_id(record.user_id)
        if user is None or not user.is_active:
            raise ValidationAppError(_INVALID_LINK)
        record.used_at = utcnow()
        user.email_verified = True
        await self._audit.record(
            AuthEvent.EMAIL_VERIFIED,
            user_id=user.id,
            email=user.email,
            ip_address=client.ip_address,
            user_agent=client.user_agent,
        )
        return user
