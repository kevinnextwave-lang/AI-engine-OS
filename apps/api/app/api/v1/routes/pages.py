"""Website page intelligence endpoints.

Page routes resolve the page row first, then the caller's membership in the
page's project organization (`get_project_access`); foreign or unknown pages
are 404. Everything is read-only and requires `data:read`.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, select

from app.api.deps import (
    CurrentUser,
    DBSession,
    ProjectAccess,
    get_project_access,
    require_project_access,
)
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.permissions import Permission, role_has
from app.models.crawl import WebsitePage
from app.models.page_intelligence import LinkStatus, LinkType
from app.repositories.page_intelligence import PageIntelligenceRepository
from app.schemas.pages import (
    ContentMetricsResponse,
    HeadingResponse,
    ImageResponse,
    LinkListResponse,
    LinkResponse,
    MetadataResponse,
    PageDetailResponse,
    PageListResponse,
    PageSummary,
)

project_router = APIRouter(prefix="/projects/{project_id}/pages", tags=["pages"])
router = APIRouter(prefix="/pages", tags=["pages"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
}


async def get_page_access(
    session: DBSession, user: CurrentUser, page_id: Annotated[uuid.UUID, Path()]
) -> tuple[WebsitePage, ProjectAccess]:
    page = await session.get(WebsitePage, page_id)
    if page is None:
        raise NotFoundError("Page not found")
    access = await get_project_access(session, user, page.project_id)
    if not role_has(access.membership.role, Permission.DATA_READ):
        raise PermissionDeniedError()
    return page, access


PageAccess = Annotated[tuple[WebsitePage, ProjectAccess], Depends(get_page_access)]


def _summary(page: WebsitePage, pathname: str | None = None) -> PageSummary:
    item = PageSummary.model_validate(page)
    item.pathname = pathname
    return item


@project_router.get(
    "",
    response_model=PageListResponse,
    summary="List crawled pages for a project",
    description=(
        "Latest known version of every crawled page. "
        "Filter by status, language, or a URL substring."
    ),
    responses=_ERRORS,
)
async def list_pages(
    access: Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))],
    session: DBSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    http_status: Annotated[int | None, Query(ge=100, le=599)] = None,
    language: Annotated[str | None, Query(max_length=35)] = None,
    q: Annotated[str | None, Query(max_length=200, description="URL contains")] = None,
    duplicates: Annotated[
        bool | None, Query(description="true: only duplicates; false: only canonical")
    ] = None,
) -> PageListResponse:
    base = select(WebsitePage).where(WebsitePage.project_id == access.project.id)
    if http_status is not None:
        base = base.where(WebsitePage.http_status == http_status)
    if language:
        base = base.where(WebsitePage.language == language)
    if q:
        base = base.where(WebsitePage.normalized_url.ilike(f"%{q}%"))
    if duplicates is True:
        base = base.where(WebsitePage.is_duplicate_of_id.is_not(None))
    elif duplicates is False:
        base = base.where(WebsitePage.is_duplicate_of_id.is_(None))
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = (
        await session.scalars(base.order_by(WebsitePage.normalized_url).limit(limit).offset(offset))
    ).all()
    return PageListResponse(
        items=[_summary(p) for p in rows], total=int(total or 0), limit=limit, offset=offset
    )


@router.get(
    "/{page_id}",
    response_model=PageDetailResponse,
    summary="Get a page with its intelligence",
    responses=_ERRORS,
)
async def get_page(page_access: PageAccess, session: DBSession) -> PageDetailResponse:
    page, _ = page_access
    repo = PageIntelligenceRepository(session)
    meta = await repo.metadata_for_page(page.id)
    metrics = await repo.metrics_for_page(page.id)
    headings = await repo.headings_for_page(page.id)
    images = await repo.images_for_page(page.id)
    detail = PageDetailResponse(
        **_summary(page, meta.pathname if meta else None).model_dump(),
        html_hash=page.html_hash,
        content_hash=page.content_hash,
        metadata=MetadataResponse.model_validate(meta) if meta else None,
        content=ContentMetricsResponse.model_validate(metrics) if metrics else None,
        headings=[HeadingResponse.model_validate(h) for h in headings],
        images=[ImageResponse.model_validate(i) for i in images],
        link_counts={
            "total": metrics.link_count if metrics else 0,
            "internal": metrics.internal_link_count if metrics else 0,
            "external": metrics.external_link_count if metrics else 0,
        },
        clean_text=metrics.clean_text if metrics else None,
    )
    return detail


@router.get(
    "/{page_id}/headings",
    response_model=list[HeadingResponse],
    summary="Heading structure in document order",
    responses=_ERRORS,
)
async def get_page_headings(page_access: PageAccess, session: DBSession) -> list[HeadingResponse]:
    page, _ = page_access
    rows = await PageIntelligenceRepository(session).headings_for_page(page.id)
    return [HeadingResponse.model_validate(h) for h in rows]


@router.get(
    "/{page_id}/links",
    response_model=LinkListResponse,
    summary="Links found on a page",
    description="Filter by `type` (internal/external) and `status` (ok/broken/unknown/invalid).",
    responses=_ERRORS,
)
async def get_page_links(
    page_access: PageAccess,
    session: DBSession,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    link_type: Annotated[LinkType | None, Query(alias="type")] = None,
    status: Annotated[LinkStatus | None, Query()] = None,
) -> LinkListResponse:
    page, _ = page_access
    rows, total = await PageIntelligenceRepository(session).links_for_page(
        page.id, link_type=link_type, status=status, limit=limit, offset=offset
    )
    return LinkListResponse(
        items=[LinkResponse.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
