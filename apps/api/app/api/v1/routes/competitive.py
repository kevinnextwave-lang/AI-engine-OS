"""Competitive AI Visibility (Milestone 5C): brand vs configured competitors.

Read-only; DATA_READ on the project's organization; non-members get 404.
Methodology in docs/competitive-visibility.md, echoed in every payload's
`method`, `weights`, `note` and `data_quality`.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import DBSession, ProjectAccess, require_project_access
from app.competitive.engine import CompetitiveVisibilityEngine
from app.core.permissions import Permission
from app.schemas.competitive import (
    CompetitiveEngines,
    CompetitiveOverview,
    CompetitivePrompts,
    CompetitiveTrends,
)
from app.schemas.visibility import Window
from app.visibility.engine import DEFAULT_WINDOW

router = APIRouter(prefix="/projects/{project_id}/competitive-visibility", tags=["competitive"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Project not found, or not a member of its organization"},
}
ReadAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))]
WindowParam = Annotated[Window, Query(description="Window; previous period has the same length")]


@router.get(
    "",
    response_model=CompetitiveOverview,
    summary="Brand vs competitors: shares, positions, citations, sentiment, score, advantages",
    responses=_ERRORS,
)
async def get_competitive(
    access: ReadAccess, session: DBSession, window: WindowParam = DEFAULT_WINDOW
) -> Any:
    return await CompetitiveVisibilityEngine(session).overview(access.project.id, window)


@router.get(
    "/trends",
    response_model=CompetitiveTrends,
    summary="7/30/90-day comparisons per entity and a weekly series over 90 days",
    responses=_ERRORS,
)
async def get_competitive_trends(access: ReadAccess, session: DBSession) -> Any:
    return await CompetitiveVisibilityEngine(session).trends(access.project.id)


@router.get(
    "/prompts",
    response_model=CompetitivePrompts,
    summary="Per-prompt comparison of the brand and each competitor",
    responses=_ERRORS,
)
async def get_competitive_prompts(
    access: ReadAccess, session: DBSession, window: WindowParam = DEFAULT_WINDOW
) -> Any:
    return await CompetitiveVisibilityEngine(session).prompts(access.project.id, window)


@router.get(
    "/engines",
    response_model=CompetitiveEngines,
    summary="Brand vs competitors per AI provider",
    responses=_ERRORS,
)
async def get_competitive_engines(
    access: ReadAccess, session: DBSession, window: WindowParam = DEFAULT_WINDOW
) -> Any:
    return await CompetitiveVisibilityEngine(session).engines(access.project.id, window)
