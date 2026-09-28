"""Share links: authed management + the public, unauthenticated report.

The public route is the only unauthenticated data endpoint in the API, so it
is deliberately blunt: IP rate-limited, one constant 404 for every kind of
miss, and a payload that carries results (scores, engines, trend) but never
methodology (prompt texts) or tenant identifiers.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, status

from app.api.deps import (
    CurrentProjectAccess,
    CurrentUser,
    DBSession,
    ProjectAccess,
    get_project_access,
    rate_limit,
)
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.logging import get_logger
from app.core.permissions import Permission, role_has
from app.models.share_link import ProjectShareLink
from app.schemas.share_links import (
    PublicReportResponse,
    ShareLinkCreatedResponse,
    ShareLinkCreateRequest,
    ShareLinkResponse,
)
from app.services.share_links import ShareLinkService, build_public_report

log = get_logger("routes.share_links")

project_router = APIRouter(prefix="/projects/{project_id}/share-links", tags=["share-links"])
link_router = APIRouter(prefix="/share-links", tags=["share-links"])
public_router = APIRouter(prefix="/public", tags=["share-links"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
}


def _require(access: ProjectAccess, permission: Permission) -> None:
    if not role_has(access.membership.role, permission):
        raise PermissionDeniedError()


def _url_path(token: str) -> str:
    return f"/r/{token}"


@project_router.get(
    "",
    response_model=list[ShareLinkResponse],
    summary="List a project's share links",
    responses=_ERRORS,
)
async def list_share_links(
    access: CurrentProjectAccess, session: DBSession
) -> list[ShareLinkResponse]:
    _require(access, Permission.DATA_READ)
    links = await ShareLinkService(session).list_for_project(access.project.id)
    return [ShareLinkResponse.model_validate(link) for link in links]


@project_router.post(
    "",
    response_model=ShareLinkCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a share link",
    description=(
        "Returns the raw token exactly once — only its keyed hash is stored. "
        "The public report lives at /r/{token} on the web app."
    ),
    responses=_ERRORS,
)
async def create_share_link(
    body: ShareLinkCreateRequest,
    access: CurrentProjectAccess,
    user: CurrentUser,
    session: DBSession,
) -> ShareLinkCreatedResponse:
    _require(access, Permission.DATA_MANAGE)
    link, raw = await ShareLinkService(session).create(
        access.project, label=body.label, user_id=user.id
    )
    await session.commit()
    await session.refresh(link)
    log.info("share_link_created", project_id=str(access.project.id), share_link_id=str(link.id))
    base = ShareLinkResponse.model_validate(link)
    return ShareLinkCreatedResponse(**base.model_dump(), token=raw, url_path=_url_path(raw))


async def get_link_access(
    session: DBSession, user: CurrentUser, link_id: Annotated[uuid.UUID, Path()]
) -> tuple[ProjectShareLink, ProjectAccess]:
    link = await ShareLinkService(session).get(link_id)
    if link is None:
        raise NotFoundError("Share link not found")
    access = await get_project_access(session, user, link.project_id)
    return link, access


@link_router.delete(
    "/{link_id}",
    response_model=ShareLinkResponse,
    summary="Revoke a share link",
    description="The URL stops working immediately. The row is kept for auditability.",
    responses=_ERRORS,
)
async def revoke_share_link(
    link_access: Annotated[tuple[ProjectShareLink, ProjectAccess], Depends(get_link_access)],
    session: DBSession,
) -> ShareLinkResponse:
    link, access = link_access
    _require(access, Permission.DATA_MANAGE)
    updated = await ShareLinkService(session).revoke(link)
    await session.commit()
    log.info("share_link_revoked", share_link_id=str(link.id))
    return ShareLinkResponse.model_validate(updated)


@public_router.get(
    "/reports/{token}",
    response_model=PublicReportResponse,
    dependencies=[Depends(rate_limit("public-report", per_minute=30))],
    summary="Public read-only visibility report",
    description="No authentication. Unknown, revoked, or unusable links are all a plain 404.",
    responses={404: {"description": "Unknown or revoked link"}, 429: {"description": "Slow down"}},
)
async def public_report(token: str, session: DBSession) -> PublicReportResponse:
    resolved = await ShareLinkService(session).resolve(token)
    if resolved is None:
        raise NotFoundError("Report not found")
    link, project = resolved
    payload = await build_public_report(session, project)
    # Best-effort access stamp; never worth failing the request over.
    link.last_accessed_at = datetime.now(UTC)
    return PublicReportResponse(**payload)
