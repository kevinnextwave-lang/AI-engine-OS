from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentMembership, CurrentUser, DBSession, require_role
from app.models.membership import Membership, MembershipRole
from app.schemas.organizations import (
    MemberResponse,
    OrganizationCreateRequest,
    OrganizationResponse,
    OrganizationWithRoleResponse,
)
from app.services.organizations import OrganizationService

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationWithRoleResponse])
async def list_my_organizations(
    user: CurrentUser, session: DBSession
) -> list[OrganizationWithRoleResponse]:
    return await OrganizationService(session).list_for_user(user.id)


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    body: OrganizationCreateRequest, user: CurrentUser, session: DBSession
) -> OrganizationResponse:
    org = await OrganizationService(session).create_with_owner(name=body.name, owner_id=user.id)
    return OrganizationResponse.model_validate(org)


@router.get("/{organization_id}", response_model=OrganizationWithRoleResponse)
async def get_organization(membership: CurrentMembership) -> OrganizationWithRoleResponse:
    org = membership.organization
    return OrganizationWithRoleResponse(
        id=org.id, name=org.name, slug=org.slug, created_at=org.created_at, role=membership.role
    )


@router.get("/{organization_id}/members", response_model=list[MemberResponse])
async def list_members(
    membership: Annotated[Membership, Depends(require_role(MembershipRole.MEMBER))],
    session: DBSession,
) -> list[MemberResponse]:
    return await OrganizationService(session).list_members(membership.organization_id)
