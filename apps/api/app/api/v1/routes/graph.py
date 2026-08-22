"""AI Search Graph (Milestone 4D): bounded, project-scoped graph queries.

All routes derive the project from the path (`require_project_access`,
DATA_READ); non-members get 404. Every response is limited/paginated and
filtered by a time window — the whole graph is never returned.
"""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import DBSession, ProjectAccess, require_project_access
from app.core.errors import ValidationAppError
from app.core.permissions import Permission
from app.graph import GRAPH_VERSION
from app.graph.queries import DEFAULT_LIMIT, MAX_LIMIT, GraphQueryService, SourceView, Window
from app.schemas.graph import (
    GraphClaimsResponse,
    GraphCompetitorsResponse,
    GraphOverview,
    GraphPromptsResponse,
    GraphSourcesResponse,
)

router = APIRouter(prefix="/projects/{project_id}/graph", tags=["graph"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Project not found, or not a member of its organization"},
}

ReadAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))]
StartParam = Annotated[datetime | None, Query(description="Window start (default: 90 days ago)")]
EndParam = Annotated[datetime | None, Query(description="Window end (default: now)")]
LimitParam = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
OffsetParam = Annotated[int, Query(ge=0)]


def window_from(start: datetime | None, end: datetime | None) -> Window:
    default = Window.default()
    s = start or default.start
    e = end or default.end
    if s.tzinfo is None:
        s = s.replace(tzinfo=UTC)
    if e.tzinfo is None:
        e = e.replace(tzinfo=UTC)
    if s >= e:
        raise ValidationAppError("start must be before end")
    return Window(s, e)


def _window(w: Window) -> dict[str, datetime]:
    return {"start": w.start, "end": w.end}


@router.get(
    "/overview",
    response_model=GraphOverview,
    summary="Bounded subgraph: project, brand, competitors, top prompts, top sources, top claims",
    responses=_ERRORS,
)
async def graph_overview(
    access: ReadAccess,
    session: DBSession,
    start: StartParam = None,
    end: EndParam = None,
    top_sources: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    top_prompts: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    top_claims: Annotated[int, Query(ge=0, le=MAX_LIMIT)] = 10,
) -> Any:
    return await GraphQueryService(session).overview(
        access.project.id,
        window_from(start, end),
        top_sources=top_sources,
        top_prompts=top_prompts,
        top_claims=top_claims,
    )


@router.get(
    "/sources",
    response_model=GraphSourcesResponse,
    summary="Sources: most cited (top), competitor-associated, gap, or rising",
    responses=_ERRORS,
)
async def graph_sources(
    access: ReadAccess,
    session: DBSession,
    view: Annotated[SourceView, Query()] = "top",
    source_type: Annotated[str | None, Query()] = None,
    start: StartParam = None,
    end: EndParam = None,
    limit: LimitParam = DEFAULT_LIMIT,
    offset: OffsetParam = 0,
) -> Any:
    w = window_from(start, end)
    items, total = await GraphQueryService(session).sources(
        access.project.id, w, view=view, source_type=source_type, limit=limit, offset=offset
    )
    return {
        "version": GRAPH_VERSION,
        "project_id": access.project.id,
        "window": _window(w),
        "view": view,
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/competitors",
    response_model=GraphCompetitorsResponse,
    summary="Brand and competitors: mentions, citations, co-mentions, top sources",
    responses=_ERRORS,
)
async def graph_competitors(
    access: ReadAccess,
    session: DBSession,
    start: StartParam = None,
    end: EndParam = None,
    limit: LimitParam = DEFAULT_LIMIT,
    offset: OffsetParam = 0,
) -> Any:
    w = window_from(start, end)
    items, edges, total = await GraphQueryService(session).competitors(
        access.project.id, w, limit=limit, offset=offset
    )
    return {
        "version": GRAPH_VERSION,
        "project_id": access.project.id,
        "window": _window(w),
        "items": items,
        "edges": edges,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/prompts",
    response_model=GraphPromptsResponse,
    summary="Prompts ranked by competitor citations they produce",
    responses=_ERRORS,
)
async def graph_prompts(
    access: ReadAccess,
    session: DBSession,
    start: StartParam = None,
    end: EndParam = None,
    limit: LimitParam = DEFAULT_LIMIT,
    offset: OffsetParam = 0,
) -> Any:
    w = window_from(start, end)
    items, total = await GraphQueryService(session).prompts(
        access.project.id, w, limit=limit, offset=offset
    )
    return {
        "version": GRAPH_VERSION,
        "project_id": access.project.id,
        "window": _window(w),
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/claims",
    response_model=GraphClaimsResponse,
    summary="Repeated claims, grouped, with brand/competitor association",
    responses=_ERRORS,
)
async def graph_claims(
    access: ReadAccess,
    session: DBSession,
    associated_with: Annotated[Literal["brand", "competitor", "other"] | None, Query()] = None,
    min_occurrences: Annotated[int, Query(ge=1, le=1000)] = 2,
    start: StartParam = None,
    end: EndParam = None,
    limit: LimitParam = DEFAULT_LIMIT,
    offset: OffsetParam = 0,
) -> Any:
    w = window_from(start, end)
    items, total = await GraphQueryService(session).claims(
        access.project.id,
        w,
        associated_with=associated_with,
        min_occurrences=min_occurrences,
        limit=limit,
        offset=offset,
    )
    return {
        "version": GRAPH_VERSION,
        "project_id": access.project.id,
        "window": _window(w),
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
