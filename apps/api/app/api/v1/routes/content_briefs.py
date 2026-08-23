"""Content briefs (Milestone 6C).

Project-scoped list uses `require_project_access`; brief-scoped routes derive
the project from the row (non-members 404). DATA_READ for reads, DATA_MANAGE
for updates. Briefs are created by the content-strategy agent, not here.
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
from app.core.errors import NotFoundError
from app.core.permissions import Permission
from app.models.content_briefs import ContentBrief, ContentBriefStatus, ContentType
from app.schemas.content_briefs import (
    ContentBriefListResponse,
    ContentBriefUpdateRequest,
    ContentBriefView,
)

project_router = APIRouter(prefix="/projects/{project_id}/content-briefs", tags=["content-briefs"])
brief_router = APIRouter(prefix="/content-briefs/{brief_id}", tags=["content-briefs"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
}
ReadAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))]


@project_router.get(
    "",
    response_model=ContentBriefListResponse,
    summary="Content briefs for a project",
    responses=_ERRORS,
)
async def list_content_briefs(
    access: ReadAccess,
    session: DBSession,
    status: Annotated[ContentBriefStatus | None, Query()] = None,
    content_type: Annotated[ContentType | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ContentBriefListResponse:
    stmt = select(ContentBrief).where(ContentBrief.project_id == access.project.id)
    if status is not None:
        stmt = stmt.where(ContentBrief.status == status.value)
    if content_type is not None:
        stmt = stmt.where(ContentBrief.content_type == content_type.value)
    rows = list((await session.scalars(stmt.order_by(ContentBrief.created_at.desc()))).all())
    page = rows[offset : offset + limit]
    return ContentBriefListResponse(
        items=[ContentBriefView.model_validate(r) for r in page],
        total=len(rows),
        limit=limit,
        offset=offset,
    )


async def get_brief_access(
    session: DBSession, user: CurrentUser, brief_id: Annotated[uuid.UUID, Path()]
) -> tuple[ContentBrief, ProjectAccess]:
    brief = await session.get(ContentBrief, brief_id)
    if brief is None:
        raise NotFoundError("Content brief not found")
    access = await get_project_access(session, user, brief.project_id)
    return brief, access


BriefAccess = Annotated[tuple[ContentBrief, ProjectAccess], Depends(get_brief_access)]


@brief_router.get(
    "", response_model=ContentBriefView, summary="Get a content brief", responses=_ERRORS
)
async def get_content_brief(brief_access: BriefAccess) -> ContentBriefView:
    brief, access = brief_access
    _require(access, Permission.DATA_READ)
    return ContentBriefView.model_validate(brief)


@brief_router.patch(
    "",
    response_model=ContentBriefView,
    summary="Update a brief's status (or light edits)",
    responses=_ERRORS,
)
async def update_content_brief(
    brief_access: BriefAccess, body: ContentBriefUpdateRequest, session: DBSession
) -> ContentBriefView:
    brief, access = brief_access
    _require(access, Permission.DATA_MANAGE)
    if body.status is not None:
        brief.status = body.status.value
    if body.title is not None:
        brief.title = body.title
    if body.audience is not None:
        brief.audience = body.audience
    await session.commit()
    await session.refresh(brief)
    return ContentBriefView.model_validate(brief)
