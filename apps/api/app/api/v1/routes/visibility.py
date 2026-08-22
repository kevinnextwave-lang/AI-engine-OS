"""AI Visibility Score: computed on demand from parsed prompt-run observations.

Read-only; DATA_READ on the project's organization. The methodology is
documented in docs/ai-visibility-score.md and echoed in every response's
`method` and `data_quality` fields.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import DBSession, ProjectAccess, require_project_access
from app.core.permissions import Permission
from app.schemas.visibility import (
    VisibilityByEngine,
    VisibilityByPrompt,
    VisibilityCompetitors,
    VisibilityOverview,
    VisibilityTrends,
    Window,
)
from app.visibility.engine import DEFAULT_WINDOW, VisibilityEngine

router = APIRouter(prefix="/projects/{project_id}/visibility", tags=["visibility"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Project not found, or not a member of its organization"},
}

ReadAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))]
WindowParam = Annotated[
    Window, Query(description="Scoring window; the previous period has the same length")
]


@router.get(
    "",
    response_model=VisibilityOverview,
    summary="AI Visibility Score for the current window vs the previous period",
    responses=_ERRORS,
)
async def get_visibility(
    access: ReadAccess, session: DBSession, window: WindowParam = DEFAULT_WINDOW
) -> Any:
    return await VisibilityEngine(session).overview(access.project.id, window)


@router.get(
    "/trends",
    response_model=VisibilityTrends,
    summary="7/30/90-day comparisons and a weekly series over 90 days",
    responses=_ERRORS,
)
async def get_visibility_trends(access: ReadAccess, session: DBSession) -> Any:
    return await VisibilityEngine(session).trends(access.project.id)


@router.get(
    "/by-engine",
    response_model=VisibilityByEngine,
    summary="Score breakdown by AI provider and model",
    responses=_ERRORS,
)
async def get_visibility_by_engine(
    access: ReadAccess, session: DBSession, window: WindowParam = DEFAULT_WINDOW
) -> Any:
    return await VisibilityEngine(session).by_engine(access.project.id, window)


@router.get(
    "/by-prompt",
    response_model=VisibilityByPrompt,
    summary="Score breakdown by prompt, category and funnel stage",
    responses=_ERRORS,
)
async def get_visibility_by_prompt(
    access: ReadAccess, session: DBSession, window: WindowParam = DEFAULT_WINDOW
) -> Any:
    return await VisibilityEngine(session).by_prompt(access.project.id, window)


@router.get(
    "/competitors",
    response_model=VisibilityCompetitors,
    summary="Brand vs configured competitors: mentions, share of voice, sentiment",
    responses=_ERRORS,
)
async def get_visibility_competitors(
    access: ReadAccess, session: DBSession, window: WindowParam = DEFAULT_WINDOW
) -> Any:
    return await VisibilityEngine(session).competitors(access.project.id, window)
