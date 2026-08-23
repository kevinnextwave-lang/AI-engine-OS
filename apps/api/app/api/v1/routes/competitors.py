"""Competitor configuration (Milestone 5A).

Project-scoped list/create use `require_project_access`; competitor-scoped
routes derive the project from the competitor row and check membership
(non-members 404). DATA_READ for reads, DATA_MANAGE for every write.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.deps import (
    CurrentUser,
    DBSession,
    ProjectAccess,
    get_project_access,
    require_project_access,
)
from app.api.v1.routes.prompts import _require
from app.competitors.service import CompetitorInput, CompetitorService
from app.core.errors import NotFoundError
from app.core.permissions import Permission
from app.models.competitor import Competitor, CompetitorStatus
from app.schemas.common import MessageResponse
from app.schemas.competitors import (
    AliasCreateRequest,
    CompetitorAliasView,
    CompetitorCreateRequest,
    CompetitorDomainView,
    CompetitorProductView,
    CompetitorResponse,
    CompetitorUpdateRequest,
    DomainCreateRequest,
    ProductCreateRequest,
    ProductUpdateRequest,
)

project_router = APIRouter(prefix="/projects/{project_id}/competitors", tags=["competitors"])
router = APIRouter(prefix="/competitors/{competitor_id}", tags=["competitors"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
    409: {"description": "Duplicate competitor, alias, domain or product"},
}
ReadAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))]
ManageAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_MANAGE))]


@project_router.get(
    "", response_model=list[CompetitorResponse], summary="List competitors", responses=_ERRORS
)
async def list_competitors(
    access: ReadAccess,
    session: DBSession,
    status_filter: Annotated[CompetitorStatus | None, Query(alias="status")] = None,
) -> list[CompetitorResponse]:
    rows = await CompetitorService(session).list_for_project(
        access.project.id, status=status_filter
    )
    return [CompetitorResponse.model_validate(c) for c in rows]


@project_router.post(
    "",
    response_model=CompetitorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a competitor",
    responses=_ERRORS,
)
async def add_competitor(
    body: CompetitorCreateRequest, access: ManageAccess, session: DBSession
) -> CompetitorResponse:
    competitor = await CompetitorService(session).create(
        access.project.id,
        CompetitorInput(
            name=body.name,
            website_url=body.website_url,
            description=body.description,
            source=body.source,
            status=body.status,
            confidence=body.confidence,
            aliases=body.aliases,
        ),
    )
    await session.commit()
    return CompetitorResponse.model_validate(
        await CompetitorService(session).get_in_project(access.project.id, competitor.id)
    )


@project_router.delete(
    "/{competitor_id}",
    response_model=MessageResponse,
    summary="Remove a competitor (legacy path; same as DELETE /competitors/{id})",
    responses=_ERRORS,
)
async def remove_competitor_legacy(
    competitor_id: uuid.UUID, access: ManageAccess, session: DBSession
) -> MessageResponse:
    svc = CompetitorService(session)
    await svc.delete(await svc.get_in_project(access.project.id, competitor_id))
    await session.commit()
    return MessageResponse(message="Competitor removed")


async def get_competitor_access(
    session: DBSession, user: CurrentUser, competitor_id: Annotated[uuid.UUID, Path()]
) -> tuple[Competitor, ProjectAccess]:
    competitor = await CompetitorService(session).get(competitor_id)
    if competitor is None:
        raise NotFoundError("Competitor not found")
    access = await get_project_access(session, user, competitor.project_id)
    return competitor, access


CompetitorAccess = Annotated[tuple[Competitor, ProjectAccess], Depends(get_competitor_access)]


async def _fresh(session: DBSession, competitor: Competitor) -> CompetitorResponse:
    return CompetitorResponse.model_validate(
        await CompetitorService(session).get_in_project(competitor.project_id, competitor.id)
    )


@router.get("", response_model=CompetitorResponse, summary="Get a competitor", responses=_ERRORS)
async def get_competitor(competitor_access: CompetitorAccess) -> CompetitorResponse:
    competitor, access = competitor_access
    _require(access, Permission.DATA_READ)
    return CompetitorResponse.model_validate(competitor)


@router.patch(
    "", response_model=CompetitorResponse, summary="Update a competitor", responses=_ERRORS
)
async def update_competitor(
    competitor_access: CompetitorAccess, body: CompetitorUpdateRequest, session: DBSession
) -> CompetitorResponse:
    competitor, access = competitor_access
    _require(access, Permission.DATA_MANAGE)
    fields = body.model_fields_set
    await CompetitorService(session).update(
        competitor,
        name=body.name,
        website_url=body.website_url,
        description=body.description,
        clear_description="description" in fields and body.description is None,
        status=body.status,
        confidence=body.confidence,
    )
    await session.commit()
    return await _fresh(session, competitor)


@router.delete("", response_model=MessageResponse, summary="Delete a competitor", responses=_ERRORS)
async def delete_competitor(
    competitor_access: CompetitorAccess, session: DBSession
) -> MessageResponse:
    competitor, access = competitor_access
    _require(access, Permission.DATA_MANAGE)
    await CompetitorService(session).delete(competitor)
    await session.commit()
    return MessageResponse(message="Competitor removed")


# -- aliases ----------------------------------------------------------------------


@router.post(
    "/aliases",
    response_model=CompetitorAliasView,
    status_code=201,
    summary="Add an alias",
    responses=_ERRORS,
)
async def add_alias(
    competitor_access: CompetitorAccess, body: AliasCreateRequest, session: DBSession
) -> CompetitorAliasView:
    competitor, access = competitor_access
    _require(access, Permission.DATA_MANAGE)
    row = await CompetitorService(session).add_alias(competitor, body.alias)
    await session.commit()
    await session.refresh(row)
    return CompetitorAliasView.model_validate(row)


@router.delete(
    "/aliases/{alias_id}",
    response_model=MessageResponse,
    summary="Remove an alias",
    responses=_ERRORS,
)
async def remove_alias(
    competitor_access: CompetitorAccess, alias_id: uuid.UUID, session: DBSession
) -> MessageResponse:
    competitor, access = competitor_access
    _require(access, Permission.DATA_MANAGE)
    await CompetitorService(session).remove_alias(competitor, alias_id)
    await session.commit()
    return MessageResponse(message="Alias removed")


# -- domains ----------------------------------------------------------------------


@router.post(
    "/domains",
    response_model=CompetitorDomainView,
    status_code=201,
    summary="Add a domain",
    responses=_ERRORS,
)
async def add_domain(
    competitor_access: CompetitorAccess, body: DomainCreateRequest, session: DBSession
) -> CompetitorDomainView:
    competitor, access = competitor_access
    _require(access, Permission.DATA_MANAGE)
    row = await CompetitorService(session).add_domain(
        competitor, body.domain, domain_type=body.domain_type, is_primary=body.is_primary
    )
    await session.commit()
    await session.refresh(row)
    return CompetitorDomainView.model_validate(row)


@router.delete(
    "/domains/{domain_id}",
    response_model=MessageResponse,
    summary="Remove a domain",
    responses=_ERRORS,
)
async def remove_domain(
    competitor_access: CompetitorAccess, domain_id: uuid.UUID, session: DBSession
) -> MessageResponse:
    competitor, access = competitor_access
    _require(access, Permission.DATA_MANAGE)
    await CompetitorService(session).remove_domain(competitor, domain_id)
    await session.commit()
    return MessageResponse(message="Domain removed")


# -- products ---------------------------------------------------------------------


@router.post(
    "/products",
    response_model=CompetitorProductView,
    status_code=201,
    summary="Add a product",
    responses=_ERRORS,
)
async def add_product(
    competitor_access: CompetitorAccess, body: ProductCreateRequest, session: DBSession
) -> CompetitorProductView:
    competitor, access = competitor_access
    _require(access, Permission.DATA_MANAGE)
    row = await CompetitorService(session).add_product(
        competitor, name=body.name, description=body.description, url=body.url
    )
    await session.commit()
    await session.refresh(row)
    return CompetitorProductView.model_validate(row)


@router.patch(
    "/products/{product_id}",
    response_model=CompetitorProductView,
    summary="Update a product",
    responses=_ERRORS,
)
async def update_product(
    competitor_access: CompetitorAccess,
    product_id: uuid.UUID,
    body: ProductUpdateRequest,
    session: DBSession,
) -> CompetitorProductView:
    competitor, access = competitor_access
    _require(access, Permission.DATA_MANAGE)
    row = await CompetitorService(session).update_product(
        competitor, product_id, name=body.name, description=body.description, url=body.url
    )
    await session.commit()
    await session.refresh(row)
    return CompetitorProductView.model_validate(row)


@router.delete(
    "/products/{product_id}",
    response_model=MessageResponse,
    summary="Remove a product",
    responses=_ERRORS,
)
async def remove_product(
    competitor_access: CompetitorAccess, product_id: uuid.UUID, session: DBSession
) -> MessageResponse:
    competitor, access = competitor_access
    _require(access, Permission.DATA_MANAGE)
    await CompetitorService(session).remove_product(competitor, product_id)
    await session.commit()
    return MessageResponse(message="Product removed")
