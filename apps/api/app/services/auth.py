"""Authentication service.

Responsibilities: signup, login, refresh-token rotation with reuse detection,
logout, and the audit trail for all of them. Route handlers only translate
HTTP <-> service calls.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, InvalidCredentialsError, InvalidTokenError
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    refresh_token_expiry,
    utcnow,
    verify_password,
)
from app.models.auth_audit_log import AuthEvent
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.refresh_tokens import RefreshTokenRepository
from app.repositories.users import UserRepository
from app.services.audit import AuthAuditService
from app.services.organizations import OrganizationService

# Verifying against a real hash on unknown-user logins keeps timing uniform.
_DUMMY_HASH = hash_password("dummy-password-for-timing-equalization")


@dataclass(frozen=True)
class ClientInfo:
    user_agent: str | None = None
    ip_address: str | None = None


@dataclass(frozen=True)
class AuthResult:
    user: User
    access_token: str
    refresh_token: str
    expires_in: int


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._tokens = RefreshTokenRepository(session)
        self._audit = AuthAuditService(session)
        self._settings = get_settings()

    # -- helpers ---------------------------------------------------------

    async def _issue_tokens(
        self, user: User, client: ClientInfo, family_id: uuid.UUID | None = None
    ) -> AuthResult:
        raw_refresh = generate_refresh_token()
        record = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            family_id=family_id or uuid.uuid4(),
            expires_at=refresh_token_expiry(),
            user_agent=(client.user_agent or "")[:512] or None,
            ip_address=(client.ip_address or "")[:64] or None,
        )
        await self._tokens.add(record)
        return AuthResult(
            user=user,
            access_token=create_access_token(user.id),
            refresh_token=raw_refresh,
            expires_in=self._settings.access_token_expire_minutes * 60,
        )

    # -- use cases -------------------------------------------------------

    async def signup(
        self,
        *,
        email: str,
        password: str,
        first_name: str | None,
        last_name: str | None,
        organization_name: str,
        client: ClientInfo,
    ) -> AuthResult:
        """Create user + organization + owner membership and start a session."""
        email = email.lower().strip()
        if await self._users.get_by_email(email):
            raise ConflictError("An account with this email already exists")

        user = User(
            email=email,
            password_hash=hash_password(password),
            first_name=(first_name or "").strip() or None,
            last_name=(last_name or "").strip() or None,
        )
        await self._users.add(user)
        org = await OrganizationService(self._session).create_with_owner(
            name=organization_name, owner_id=user.id
        )
        user.last_login_at = utcnow()
        await self._audit.record(
            AuthEvent.SIGNUP,
            user_id=user.id,
            email=email,
            ip_address=client.ip_address,
            user_agent=client.user_agent,
            details={"organization_id": str(org.id)},
        )
        return await self._issue_tokens(user, client)

    # Kept for callers written against the Milestone 1 name.
    register = signup

    async def login(self, *, email: str, password: str, client: ClientInfo) -> AuthResult:
        email = email.lower().strip()
        user = await self._users.get_by_email(email)
        if user is None:
            verify_password(password, _DUMMY_HASH)
            await self._audit.record(
                AuthEvent.LOGIN_FAILED,
                email=email,
                ip_address=client.ip_address,
                user_agent=client.user_agent,
                details={"reason": "unknown_email"},
            )
            raise InvalidCredentialsError()
        if not verify_password(password, user.password_hash) or not user.is_active:
            await self._audit.record(
                AuthEvent.LOGIN_FAILED,
                user_id=user.id,
                email=email,
                ip_address=client.ip_address,
                user_agent=client.user_agent,
                details={"reason": "inactive" if not user.is_active else "bad_password"},
            )
            raise InvalidCredentialsError()
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        user.last_login_at = utcnow()
        await self._audit.record(
            AuthEvent.LOGIN_SUCCEEDED,
            user_id=user.id,
            email=email,
            ip_address=client.ip_address,
            user_agent=client.user_agent,
        )
        return await self._issue_tokens(user, client)

    async def refresh(self, *, refresh_token: str, client: ClientInfo) -> AuthResult:
        now = utcnow()
        record = (
            await self._tokens.get_by_hash(hash_token(refresh_token)) if refresh_token else None
        )
        if record is None:
            raise InvalidTokenError()

        if record.is_revoked:
            # Reuse of a rotated token => likely theft. Kill the whole family.
            await self._tokens.revoke_family(record.family_id, now)
            await self._audit.record(
                AuthEvent.REFRESH_REUSE_DETECTED,
                user_id=record.user_id,
                ip_address=client.ip_address,
                user_agent=client.user_agent,
                details={"family_id": str(record.family_id)},
            )
            raise InvalidTokenError()

        if record.expires_at <= now:
            record.revoked_at = now
            raise InvalidTokenError()

        user = await self._users.get_by_id(record.user_id)
        if user is None or not user.is_active:
            await self._tokens.revoke_family(record.family_id, now)
            raise InvalidTokenError()

        result = await self._issue_tokens(user, client, family_id=record.family_id)
        new_record = await self._tokens.get_by_hash(hash_token(result.refresh_token))
        record.revoked_at = now
        record.replaced_by_id = new_record.id if new_record else None
        await self._audit.record(
            AuthEvent.TOKEN_REFRESHED,
            user_id=user.id,
            ip_address=client.ip_address,
            user_agent=client.user_agent,
            details={"family_id": str(record.family_id)},
        )
        return result

    async def logout(self, *, refresh_token: str | None, client: ClientInfo) -> None:
        if not refresh_token:
            return
        record = await self._tokens.get_by_hash(hash_token(refresh_token))
        if record is not None and not record.is_revoked:
            await self._tokens.revoke_family(record.family_id, utcnow())
            await self._audit.record(
                AuthEvent.LOGOUT,
                user_id=record.user_id,
                ip_address=client.ip_address,
                user_agent=client.user_agent,
                details={"family_id": str(record.family_id)},
            )

    async def logout_everywhere(self, *, user_id: uuid.UUID, client: ClientInfo) -> None:
        await self._tokens.revoke_all_for_user(user_id, utcnow())
        await self._audit.record(
            AuthEvent.LOGOUT_ALL,
            user_id=user_id,
            ip_address=client.ip_address,
            user_agent=client.user_agent,
        )
