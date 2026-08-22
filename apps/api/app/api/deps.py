"""FastAPI dependencies: DB session, current user, tenant scoping, RBAC, rate limits.

Tenant rule: organization_id is NEVER read from a request body. It comes from
the URL path (validated against the caller's memberships) or is derived from
the requested resource (e.g. a project's organization). A caller who is not a
member sees 404, so other tenants' existence is not leaked (IDOR protection).
"""

import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
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
from app.core.permissions import Permission, role_has
from app.core.rate_limit import InMemoryRateLimiter, RateLimiter, RedisRateLimiter
from app.core.security import decode_access_token
from app.db.session import get_db_session
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization, OrganizationStatus
from app.models.project import Project
from app.models.user import User
from app.repositories.organizations import MembershipRepository
from app.repositories.projects import ProjectRepository
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


# -- Organization scoping -------------------------------------------------


def _org_is_usable(org: Organization) -> bool:
    return org.deleted_at is None and org.status != OrganizationStatus.DELETED


async def get_current_membership(
    session: DBSession,
    user: CurrentUser,
    organization_id: Annotated[uuid.UUID, Path()],
) -> Membership:
    """Membership of the caller in the organization named in the URL path."""
    membership = await MembershipRepository(session).get(organization_id, user.id)
    if membership is None or not _org_is_usable(membership.organization):
        raise NotFoundError("Organization not found")
    return membership


CurrentMembership = Annotated[Membership, Depends(get_current_membership)]


async def get_current_organization(membership: CurrentMembership) -> Organization:
    """The organization from the URL path, guaranteed to include the caller."""
    return membership.organization


CurrentOrganization = Annotated[Organization, Depends(get_current_organization)]


def require_role(minimum: MembershipRole) -> Callable[..., Coroutine[Any, Any, Membership]]:
    """Require at least `minimum` role in the path organization."""

    async def _dependency(membership: CurrentMembership) -> Membership:
        if not membership.has_at_least(minimum):
            raise PermissionDeniedError()
        return membership

    return _dependency


def require_permission(
    permission: Permission,
) -> Callable[..., Coroutine[Any, Any, Membership]]:
    """Require a specific permission (see core/permissions.py) in the path organization."""

    async def _dependency(membership: CurrentMembership) -> Membership:
        if not role_has(membership.role, permission):
            raise PermissionDeniedError()
        return membership

    return _dependency


# -- Project scoping ------------------------------------------------------


@dataclass(frozen=True)
class ProjectAccess:
    project: Project
    membership: Membership

    @property
    def organization(self) -> Organization:
        return self.membership.organization


async def get_project_access(
    session: DBSession,
    user: CurrentUser,
    project_id: Annotated[uuid.UUID, Path()],
) -> ProjectAccess:
    """Resolve a project from the URL and the caller's membership in its organization.

    The organization is derived from the project row — never from the request.
    """
    project = await ProjectRepository(session).get_by_id(project_id)
    if project is None:
        raise NotFoundError("Project not found")
    membership = await MembershipRepository(session).get(project.organization_id, user.id)
    if membership is None or not _org_is_usable(membership.organization):
        raise NotFoundError("Project not found")
    return ProjectAccess(project=project, membership=membership)


CurrentProjectAccess = Annotated[ProjectAccess, Depends(get_project_access)]


def require_project_access(
    permission: Permission = Permission.PROJECTS_READ,
) -> Callable[..., Coroutine[Any, Any, ProjectAccess]]:
    """Require membership in the project's organization plus the given permission."""

    async def _dependency(access: CurrentProjectAccess) -> ProjectAccess:
        if not role_has(access.membership.role, permission):
            raise PermissionDeniedError()
        return access

    return _dependency
