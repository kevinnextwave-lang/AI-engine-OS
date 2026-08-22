"""Authentication service.

Responsibilities: registration, login, refresh-token rotation with reuse
detection, logout. Route handlers only translate HTTP <-> service calls.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, InvalidCredentialsError, InvalidTokenError
from app.core.logging import get_logger
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
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.refresh_tokens import RefreshTokenRepository
from app.repositories.users import UserRepository
from app.services.organizations import OrganizationService

log = get_logger(__name__)

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

    async def register(
        self,
        *,
        email: str,
        password: str,
        first_name: str | None,
        last_name: str | None,
        organization_name: str,
        client: ClientInfo,
    ) -> AuthResult:
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
        await OrganizationService(self._session).create_with_owner(
            name=organization_name, owner_id=user.id
        )
        user.last_login_at = utcnow()
        log.info("user_registered", user_id=str(user.id))
        return await self._issue_tokens(user, client)

    async def login(self, *, email: str, password: str, client: ClientInfo) -> AuthResult:
        user = await self._users.get_by_email(email)
        if user is None:
            verify_password(password, _DUMMY_HASH)
            raise InvalidCredentialsError()
        if not verify_password(password, user.password_hash) or not user.is_active:
            log.info("login_failed", user_id=str(user.id))
            raise InvalidCredentialsError()
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        user.last_login_at = utcnow()
        log.info("login_succeeded", user_id=str(user.id))
        return await self._issue_tokens(user, client)

    async def refresh(self, *, refresh_token: str, client: ClientInfo) -> AuthResult:
        now = utcnow()
        record = await self._tokens.get_by_hash(hash_token(refresh_token))
        if record is None:
            raise InvalidTokenError()

        if record.is_revoked:
            # Reuse of a rotated token => likely theft. Kill the whole family.
            log.warning(
                "refresh_token_reuse_detected",
                user_id=str(record.user_id),
                family_id=str(record.family_id),
            )
            await self._tokens.revoke_family(record.family_id, now)
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
        return result

    async def logout(self, *, refresh_token: str | None) -> None:
        if not refresh_token:
            return
        record = await self._tokens.get_by_hash(hash_token(refresh_token))
        if record is not None and not record.is_revoked:
            await self._tokens.revoke_family(record.family_id, utcnow())

    async def logout_everywhere(self, *, user_id: uuid.UUID) -> None:
        await self._tokens.revoke_all_for_user(user_id, utcnow())
