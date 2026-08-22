"""Projects.

Collection routes live under the organization (path organization_id is
validated against membership). Item routes take only project_id; the
organization is derived from the project row via require_project_access.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import DBSession, ProjectAccess, require_permission, require_project_access
from app.core.permissions import Permission
from app.models.membership import Membership
from app.schemas.common import MessageResponse
from app.schemas.projects import ProjectCreateRequest, ProjectResponse, ProjectUpdateRequest
from app.services.projects import ProjectService

org_router = APIRouter(prefix="/organizations/{organization_id}/projects", tags=["projects"])
router = APIRouter(prefix="/projects", tags=["projects"])


@org_router.get("", response_model=list[ProjectResponse])
async def list_projects(
    membership: Annotated[Membership, Depends(require_permission(Permission.PROJECTS_READ))],
    session: DBSession,
) -> list[ProjectResponse]:
    projects = await ProjectService(session).list_for_organization(membership.organization_id)
    return [ProjectResponse.model_validate(p) for p in projects]


@org_router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreateRequest,
    membership: Annotated[Membership, Depends(require_permission(Permission.PROJECTS_MANAGE))],
    session: DBSession,
) -> ProjectResponse:
    project = await ProjectService(session).create(
        organization_id=membership.organization_id,  # from the authorized membership, not the body
        name=body.name,
        description=body.description,
        industry=body.industry,
        country=body.country,
    )
    return ProjectResponse.model_validate(project)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    access: Annotated[ProjectAccess, Depends(require_project_access(Permission.PROJECTS_READ))],
) -> ProjectResponse:
    return ProjectResponse.model_validate(access.project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    body: ProjectUpdateRequest,
    access: Annotated[ProjectAccess, Depends(require_project_access(Permission.PROJECTS_MANAGE))],
    session: DBSession,
) -> ProjectResponse:
    project = await ProjectService(session).update(
        access.project, **body.model_dump(exclude_unset=True)
    )
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}", response_model=MessageResponse)
async def delete_project(
    access: Annotated[ProjectAccess, Depends(require_project_access(Permission.PROJECTS_DELETE))],
    session: DBSession,
) -> MessageResponse:
    await ProjectService(session).delete(access.project)
    return MessageResponse(message="Project deleted")
