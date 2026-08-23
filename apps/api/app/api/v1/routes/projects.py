"""Project onboarding endpoints.

Authorization chain on every route:
    authenticated user -> organization membership -> project belongs to organization

- Collection routes (`/projects`) resolve the organization from the caller's
  memberships. A supplied organization_id is only a selector; it is validated
  against membership and never trusted on its own.
- Item routes (`/projects/{project_id}`) derive the organization from the
  project row via `require_project_access`; non-members see 404.
- Legacy org-scoped collection (`/organizations/{organization_id}/projects`)
  is kept for clients that already use it.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    CurrentUser,
    DBSession,
    ProjectAccess,
    require_permission,
    require_project_access,
)
from app.core.errors import NotFoundError, PermissionDeniedError, ValidationAppError
from app.core.permissions import Permission, role_has
from app.models.membership import Membership
from app.repositories.organizations import MembershipRepository, OrganizationRepository
from app.schemas.common import MessageResponse
from app.schemas.projects import (
    DomainCreateRequest,
    DomainResponse,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)
from app.services.projects import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])
org_router = APIRouter(prefix="/organizations/{organization_id}/projects", tags=["projects"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Authenticated but role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
}


def _project_response(project: object) -> ProjectResponse:
    resp = ProjectResponse.model_validate(project)
    domains = getattr(project, "domains", None) or []
    primary = next((d for d in domains if d.is_primary), None)
    resp.primary_domain = DomainResponse.model_validate(primary) if primary else None
    return resp


async def _resolve_membership_for_create(
    session: DBSession, user: CurrentUser, organization_id: uuid.UUID | None
) -> Membership:
    """Pick the organization a new project belongs to, always via membership."""
    memberships = await MembershipRepository(session).list_for_user(user.id)
    if organization_id is not None:
        membership = next((m for m in memberships if m.organization_id == organization_id), None)
        if membership is None:
            raise NotFoundError("Organization not found")
    elif len(memberships) == 1:
        membership = memberships[0]
    elif not memberships:
        raise NotFoundError("You do not belong to any organization")
    else:
        raise ValidationAppError(
            "organization_id is required because you belong to multiple organizations",
            details=[{"loc": ["body", "organization_id"], "msg": "field required"}],
        )
    if not role_has(membership.role, Permission.PROJECTS_MANAGE):
        raise PermissionDeniedError()
    return membership


# -- /projects collection ---------------------------------------------------


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List projects",
    description="Projects in every organization you belong to. Filter with `organization_id`.",
    responses=_ERRORS,
)
async def list_projects(
    user: CurrentUser,
    session: DBSession,
    organization_id: Annotated[
        uuid.UUID | None, Query(description="Restrict to one of your organizations")
    ] = None,
) -> ProjectListResponse:
    memberships = await MembershipRepository(session).list_for_user(user.id)
    org_ids = [m.organization_id for m in memberships if role_has(m.role, Permission.PROJECTS_READ)]
    if organization_id is not None:
        if organization_id not in org_ids:
            raise NotFoundError("Organization not found")
        org_ids = [organization_id]
    # Skip organizations that are soft-deleted.
    orgs = OrganizationRepository(session)
    live_ids = [oid for oid in org_ids if await orgs.get_by_id(oid) is not None]
    projects = await ProjectService(session).list_for_organizations(live_ids)
    items = [_project_response(p) for p in projects]
    return ProjectListResponse(items=items, total=len(items))


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
    description=(
        "Creates a project and registers `website_url` as its primary domain. "
        "Requires the member role or higher."
    ),
    responses={**_ERRORS, 422: {"description": "Validation error (e.g. invalid URL)"}},
)
async def create_project(
    body: ProjectCreateRequest, user: CurrentUser, session: DBSession
) -> ProjectResponse:
    membership = await _resolve_membership_for_create(session, user, body.organization_id)
    project = await ProjectService(session).create(
        organization_id=membership.organization_id,
        name=body.name,
        website_url=body.website_url,
        description=body.description,
        industry=body.industry,
        country=body.country,
    )
    return _project_response(project)


# -- legacy org-scoped collection --------------------------------------------


@org_router.get("", response_model=list[ProjectResponse], responses=_ERRORS, deprecated=True)
async def list_projects_in_organization(
    membership: Annotated[Membership, Depends(require_permission(Permission.PROJECTS_READ))],
    session: DBSession,
) -> list[ProjectResponse]:
    projects = await ProjectService(session).list_for_organization(membership.organization_id)
    return [_project_response(p) for p in projects]


@org_router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
    deprecated=True,
)
async def create_project_in_organization(
    body: ProjectCreateRequest,
    membership: Annotated[Membership, Depends(require_permission(Permission.PROJECTS_MANAGE))],
    session: DBSession,
) -> ProjectResponse:
    project = await ProjectService(session).create(
        organization_id=membership.organization_id,  # path org, never the body
        name=body.name,
        website_url=body.website_url,
        description=body.description,
        industry=body.industry,
        country=body.country,
    )
    return _project_response(project)


# -- /projects/{project_id} --------------------------------------------------


@router.get(
    "/{project_id}", response_model=ProjectResponse, summary="Get a project", responses=_ERRORS
)
async def get_project(
    access: Annotated[ProjectAccess, Depends(require_project_access(Permission.PROJECTS_READ))],
) -> ProjectResponse:
    return _project_response(access.project)


@router.patch(
    "/{project_id}", response_model=ProjectResponse, summary="Update a project", responses=_ERRORS
)
async def update_project(
    body: ProjectUpdateRequest,
    access: Annotated[ProjectAccess, Depends(require_project_access(Permission.PROJECTS_MANAGE))],
    session: DBSession,
) -> ProjectResponse:
    project = await ProjectService(session).update(
        access.project, **body.model_dump(exclude_unset=True)
    )
    return _project_response(project)


@router.delete(
    "/{project_id}",
    response_model=MessageResponse,
    summary="Delete a project",
    description="Deletes the project with its domains and competitors. Requires admin or owner.",
    responses=_ERRORS,
)
async def delete_project(
    access: Annotated[ProjectAccess, Depends(require_project_access(Permission.PROJECTS_DELETE))],
    session: DBSession,
) -> MessageResponse:
    await ProjectService(session).delete(access.project)
    return MessageResponse(message="Project deleted")


# -- domains -----------------------------------------------------------------


@router.get(
    "/{project_id}/domains",
    response_model=list[DomainResponse],
    summary="List a project's domains",
    responses=_ERRORS,
)
async def list_domains(
    access: Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))],
    session: DBSession,
) -> list[DomainResponse]:
    domains = await ProjectService(session).list_domains(access.project)
    return [DomainResponse.model_validate(d) for d in domains]


@router.post(
    "/{project_id}/domains",
    response_model=DomainResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a domain",
    description=(
        "URL is normalized and the hostname extracted. A project has at most one primary domain."
    ),
    responses={**_ERRORS, 409: {"description": "Duplicate hostname or primary already set"}},
)
async def add_domain(
    body: DomainCreateRequest,
    access: Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_MANAGE))],
    session: DBSession,
) -> DomainResponse:
    domain = await ProjectService(session).add_domain(
        access.project, url=body.url, is_primary=body.is_primary
    )
    return DomainResponse.model_validate(domain)
