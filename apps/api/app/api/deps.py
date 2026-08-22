"""FastAPI dependencies: DB session, current user, tenant scoping, rate limits.

Tenant rule: organization_id comes ONLY from the URL path and is validated
against the caller's memberships. The client can never pick an org it does
not belong to (IDOR protection).
"""

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

import jwt
from fastapi import Depends, Path, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import (
    AuthenticationError,
    InvalidTokenError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
)
from app.core.rate_limit import InMemoryRateLimiter, RateLimiter, RedisRateLimiter
from app.core.security import decode_access_token
from app.db.session import get_db_session
from app.models.membership import Membership, MembershipRole
from app.models.user import User
from app.repositories.organizations import MembershipRepository
from app.repositories.users import UserRepository

_bearer = HTTPBearer(auto_error=False)

DBSession = Annotated[AsyncSession, Depends(get_db_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


# -- Redis / rate limiting ------------------------------------------------

_memory_limiter = InMemoryRateLimiter()


def get_redis(request: Request) -> Redis | None:
    redis: Redis | None = getattr(request.app.state, "redis", None)
    return redis


def get_rate_limiter(redis: Annotated[Redis | None, Depends(get_redis)]) -> RateLimiter:
    if redis is None:
        return _memory_limiter
    return RedisRateLimiter(redis)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(
    scope: str, *, per_minute: int | None = None
) -> Callable[..., Coroutine[Any, Any, None]]:
    """Build a dependency that rate-limits by client IP for the given scope."""

    async def _dependency(
        request: Request,
        limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
        settings: SettingsDep,
    ) -> None:
        limit = per_minute or settings.rate_limit_default_per_minute
        if not await limiter.hit(f"{scope}:{client_ip(request)}", limit, 60):
            raise RateLimitedError()

    return _dependency


# -- Authentication -------------------------------------------------------


async def get_current_user(
    session: DBSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError()
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise InvalidTokenError() from exc

    user = await UserRepository(session).get_by_id(user_id)
    if user is None or not user.is_active:
        raise InvalidTokenError()
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


# -- Tenant scoping -------------------------------------------------------


async def get_current_membership(
    session: DBSession,
    user: CurrentUser,
    organization_id: Annotated[uuid.UUID, Path()],
) -> Membership:
    membership = await MembershipRepository(session).get(organization_id, user.id)
    if membership is None or membership.organization.deleted_at is not None:
        # 404, not 403: don't reveal whether the org exists.
        raise NotFoundError("Organization not found")
    return membership


CurrentMembership = Annotated[Membership, Depends(get_current_membership)]


def require_role(minimum: MembershipRole) -> Callable[..., Coroutine[Any, Any, Membership]]:
    async def _dependency(membership: CurrentMembership) -> Membership:
        if not membership.has_at_least(minimum):
            raise PermissionDeniedError()
        return membership

    return _dependency
