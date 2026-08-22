"""Structured data and entity intelligence endpoints.

Authorization: project routes use `require_project_access`; the page route
derives the project from the page row (`get_page_access`). DATA_READ for all
reads, DATA_MANAGE to trigger a re-analysis.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DBSession, ProjectAccess, require_project_access
from app.api.v1.routes.pages import PageAccess
from app.core.permissions import Permission
from app.models.entities import EntityScope
from app.schemas.entities import (
    EntityAnalysisStartResponse,
    EntityConsistencyResponse,
    EntityListResponse,
    PageSchemaResponse,
    ProjectSchemaResponse,
)
from app.services.entities import Dispatcher, EntityService
from app.workers.tasks import dispatch_entity_analysis

project_router = APIRouter(prefix="/projects/{project_id}", tags=["entities"])
page_router = APIRouter(prefix="/pages/{page_id}", tags=["entities"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
}


def get_entity_dispatcher() -> Dispatcher:
    return dispatch_entity_analysis


DispatcherDep = Annotated[Dispatcher, Depends(get_entity_dispatcher)]
ReadAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))]


@project_router.get(
    "/entities",
    response_model=EntityListResponse,
    summary="List entities extracted from structured data",
    description=(
        "Entities found in JSON-LD, Microdata and RDFa across crawled pages, plus the "
        "consolidated project organization. Filter by `type` (schema.org type name) and "
        "`scope` (`page` | `project`)."
    ),
    responses=_ERRORS,
)
async def list_entities(
    access: ReadAccess,
    session: DBSession,
    dispatcher: DispatcherDep,
    entity_type: Annotated[str | None, Query(alias="type", max_length=120)] = None,
    scope: Annotated[EntityScope | None, Query()] = None,
    known_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EntityListResponse:
    return await EntityService(session, dispatcher).list_entities(
        access.project.id,
        entity_type=entity_type,
        scope=scope,
        known_only=known_only,
        limit=limit,
        offset=offset,
    )


@project_router.get(
    "/schema",
    response_model=ProjectSchemaResponse,
    summary="Structured data summary and validation issues for a project",
    responses=_ERRORS,
)
async def project_schema(
    access: ReadAccess, session: DBSession, dispatcher: DispatcherDep
) -> ProjectSchemaResponse:
    return await EntityService(session, dispatcher).project_schema(access.project.id)


@project_router.get(
    "/entity-consistency",
    response_model=EntityConsistencyResponse,
    summary="Cross-page entity inconsistencies and duplicates",
    responses=_ERRORS,
)
async def entity_consistency(
    access: ReadAccess, session: DBSession, dispatcher: DispatcherDep
) -> EntityConsistencyResponse:
    return await EntityService(session, dispatcher).consistency(access.project.id)


@project_router.post(
    "/entity-analysis",
    response_model=EntityAnalysisStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run entity analysis",
    description=(
        "Rebuilds entities, schema issues and consistency observations from the stored "
        "crawl data. Runs automatically after every crawl; use this after manual changes."
    ),
    responses=_ERRORS,
)
async def start_entity_analysis(
    access: Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_MANAGE))],
    session: DBSession,
    dispatcher: DispatcherDep,
) -> EntityAnalysisStartResponse:
    EntityService(session, dispatcher).request_analysis(access.project.id)
    return EntityAnalysisStartResponse(project_id=access.project.id, queued=True)


@page_router.get(
    "/schema",
    response_model=PageSchemaResponse,
    summary="Structured data blocks of a page with validation and entities",
    responses=_ERRORS,
)
async def page_schema(
    page_access: PageAccess, session: DBSession, dispatcher: DispatcherDep
) -> PageSchemaResponse:
    page, _ = page_access
    return await EntityService(session, dispatcher).page_schema(page)
