"""Team management: invitations, member removal, role changes.

Path organization scoping runs through the same membership dependencies as
everything else; the ownership rules live in TeamService.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path
from pydantic import EmailStr, Field

from app.api.deps import (
    CurrentMembership,
    CurrentUser,
    DBSession,
    require_permission,
    user_rate_limit,
)
from app.core.permissions import Permission
from app.models.membership import Membership, MembershipRole
from app.schemas.common import APIModel, MessageResponse
from app.schemas.organizations import MemberResponse
from app.services.organizations import OrganizationService
from app.services.team import TeamService

router = APIRouter(prefix="/organizations/{organization_id}", tags=["team"])
accept_router = APIRouter(prefix="/invites", tags=["team"])

_MANAGE = Annotated[Membership, Depends(require_permission(Permission.MEMBERS_MANAGE))]


class InviteCreateRequest(APIModel):
    email: EmailStr
    # OWNER is refused by the service with a clear message.
    role: MembershipRole = MembershipRole.MEMBER


class InviteResponse(APIModel):
    id: uuid.UUID
    email: EmailStr
    role: MembershipRole
    expires_at: datetime
    created_at: datetime


class AcceptInviteRequest(APIModel):
    token: str = Field(min_length=16, max_length=256)


class MemberRoleUpdateRequest(APIModel):
    role: MembershipRole


@router.post(
    "/invites",
    response_model=InviteResponse,
    status_code=201,
    dependencies=[Depends(user_rate_limit("team:invite", per_minute=10))],
)
async def create_invite(
    body: InviteCreateRequest,
    membership: _MANAGE,
    user: CurrentUser,
    session: DBSession,
) -> InviteResponse:
    invite = await TeamService(session).create_invite(
        membership.organization, email=body.email, role=body.role, invited_by=user
    )
    return InviteResponse.model_validate(invite)


@router.get("/invites", response_model=list[InviteResponse])
async def list_invites(membership: _MANAGE, session: DBSession) -> list[InviteResponse]:
    rows = await TeamService(session).list_pending(membership.organization_id)
    return [InviteResponse.model_validate(r) for r in rows]


@router.delete("/invites/{invite_id}", response_model=MessageResponse)
async def revoke_invite(
    invite_id: Annotated[uuid.UUID, Path()],
    membership: _MANAGE,
    session: DBSession,
) -> MessageResponse:
    await TeamService(session).revoke_invite(membership.organization_id, invite_id)
    return MessageResponse(message="Invitation revoked.")


@router.delete("/members/{user_id}", response_model=MessageResponse)
async def remove_member(
    user_id: Annotated[uuid.UUID, Path()],
    membership: CurrentMembership,
    user: CurrentUser,
    session: DBSession,
) -> MessageResponse:
    """Managers remove anyone (owners only by owners; never the last owner).
    Anyone may remove THEMSELVES (leave the organization) without the
    members:manage permission."""
    if user_id != user.id and not membership.has_at_least(MembershipRole.ADMIN):
        # Same 403 the permission dependency would give a non-manager.
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError()
    await TeamService(session).remove_member(membership, user_id)
    message = "You have left the organization." if user_id == user.id else "Member removed."
    return MessageResponse(message=message)


@router.patch("/members/{user_id}", response_model=MemberResponse)
async def change_member_role(
    user_id: Annotated[uuid.UUID, Path()],
    body: MemberRoleUpdateRequest,
    membership: _MANAGE,
    session: DBSession,
) -> MemberResponse:
    await TeamService(session).change_role(membership, user_id, body.role)
    members = await OrganizationService(session).list_members(membership.organization_id)
    return next(m for m in members if m.user_id == user_id)


@accept_router.post("/accept", response_model=MessageResponse)
async def accept_invite(
    body: AcceptInviteRequest, user: CurrentUser, session: DBSession
) -> MessageResponse:
    membership = await TeamService(session).accept_invite(user, token=body.token)
    return MessageResponse(message=f"You've joined the organization as {membership.role.value}.")
