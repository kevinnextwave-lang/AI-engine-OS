"""Organization service — tenant creation and membership queries."""

import re
import secrets
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.repositories.organizations import MembershipRepository, OrganizationRepository
from app.schemas.organizations import MemberResponse, OrganizationWithRoleResponse

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.lower()).strip("-")
    return slug[:80] or "org"


class OrganizationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._orgs = OrganizationRepository(session)
        self._memberships = MembershipRepository(session)

    async def _unique_slug(self, name: str) -> str:
        base = slugify(name)
        slug = base
        while await self._orgs.slug_exists(slug):
            slug = f"{base}-{secrets.token_hex(3)}"
        return slug

    async def create_with_owner(self, *, name: str, owner_id: uuid.UUID) -> Organization:
        org = Organization(name=name.strip(), slug=await self._unique_slug(name))
        await self._orgs.add(org)
        await self._memberships.add(
            Membership(organization_id=org.id, user_id=owner_id, role=MembershipRole.OWNER)
        )
        return org

    async def list_for_user(self, user_id: uuid.UUID) -> list[OrganizationWithRoleResponse]:
        rows = await self._orgs.list_for_user(user_id)
        return [
            OrganizationWithRoleResponse(
                id=org.id, name=org.name, slug=org.slug, created_at=org.created_at, role=m.role
            )
            for org, m in rows
        ]

    async def list_members(self, org_id: uuid.UUID) -> list[MemberResponse]:
        memberships = await self._memberships.list_for_organization(org_id)
        return [
            MemberResponse(
                user_id=m.user_id,
                email=m.user.email,
                full_name=m.user.full_name,
                role=m.role,
                joined_at=m.created_at,
            )
            for m in memberships
        ]
