"""Competitive content gaps (Milestone 5E).

Project-scoped list/analyze use `require_project_access`; gap-scoped routes
derive the project from the row (non-members 404). DATA_READ for reads,
DATA_MANAGE to analyze or update.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import select

from app.api.deps import (
    CurrentUser,
    DBSession,
    ProjectAccess,
    get_project_access,
    require_project_access,
)
from app.api.v1.routes.prompts import _require
from app.content_gaps.engine import ContentGapEngine
from app.core.errors import NotFoundError
from app.core.permissions import Permission
from app.models.content_gaps import ContentGap, ContentGapType
from app.models.gaps import GapStatus
from app.schemas.content_gaps import (
    ContentGapAnalyzeRequest,
    ContentGapAnalyzeResponse,
    ContentGapListResponse,
    ContentGapUpdateRequest,
    ContentGapView,
)

project_router = APIRouter(prefix="/projects/{project_id}/content-gaps", tags=["content-gaps"])
gap_router = APIRouter(prefix="/content-gaps/{gap_id}", tags=["content-gaps"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
}
ReadAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))]
ManageAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_MANAGE))]

NOTE = (
    "Content gaps are observed differences between competitor visibility in AI responses "
    "and the crawled website's coverage; review before acting on them."
)


@project_router.get(
    "",
    response_model=ContentGapListResponse,
    summary="Content gaps: topics where competitors are visible and site coverage is weak",
    responses=_ERRORS,
)
async def list_content_gaps(
    access: ReadAccess,
    session: DBSession,
    gap_type: Annotated[ContentGapType | None, Query()] = None,
    status: Annotated[GapStatus | None, Query()] = None,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ContentGapListResponse:
    stmt = select(ContentGap).where(ContentGap.project_id == access.project.id)
    if gap_type is not None:
        stmt = stmt.where(ContentGap.gap_type == gap_type.value)
    if status is not None:
        stmt = stmt.where(ContentGap.status == status.value)
    if min_score is not None:
        stmt = stmt.where(ContentGap.opportunity_score >= min_score)
    rows = list((await session.scalars(stmt)).all())
    rows.sort(key=lambda r: (-r.opportunity_score, r.topic, r.gap_type))
    page = rows[offset : offset + limit]
    return ContentGapListResponse(
        items=[ContentGapView.model_validate(r) for r in page],
        total=len(rows),
        limit=limit,
        offset=offset,
        analyzed_at=max((r.analyzed_at for r in rows), default=None),
        note=NOTE,
    )


@project_router.post(
    "/analyze",
    response_model=ContentGapAnalyzeResponse,
    summary="Re-analyze content gaps from responses, citations and crawled pages",
    responses=_ERRORS,
)
async def analyze_content_gaps(
    access: ManageAccess, session: DBSession, body: ContentGapAnalyzeRequest | None = None
) -> ContentGapAnalyzeResponse:
    body = body or ContentGapAnalyzeRequest()
    result = await ContentGapEngine(session).analyze(
        access.project.id, window_days=body.window_days
    )
    await session.commit()
    return ContentGapAnalyzeResponse(**result.__dict__)


async def get_content_gap_access(
    session: DBSession, user: CurrentUser, gap_id: Annotated[uuid.UUID, Path()]
) -> tuple[ContentGap, ProjectAccess]:
    gap = (await session.scalars(select(ContentGap).where(ContentGap.id == gap_id))).one_or_none()
    if gap is None:
        raise NotFoundError("Content gap not found")
    access = await get_project_access(session, user, gap.project_id)
    return gap, access


ContentGapAccess = Annotated[tuple[ContentGap, ProjectAccess], Depends(get_content_gap_access)]


@gap_router.get("", response_model=ContentGapView, summary="Get a content gap", responses=_ERRORS)
async def get_content_gap(gap_access: ContentGapAccess) -> ContentGapView:
    gap, access = gap_access
    _require(access, Permission.DATA_READ)
    return ContentGapView.model_validate(gap)


@gap_router.patch(
    "",
    response_model=ContentGapView,
    summary="Update a content gap's status or note",
    responses=_ERRORS,
)
async def update_content_gap(
    gap_access: ContentGapAccess, body: ContentGapUpdateRequest, session: DBSession
) -> ContentGapView:
    gap, access = gap_access
    _require(access, Permission.DATA_MANAGE)
    if body.status is not None:
        gap.status = body.status.value
    if "note" in body.model_fields_set:
        gap.note = body.note
    await session.commit()
    await session.refresh(gap)
    return ContentGapView.model_validate(gap)
