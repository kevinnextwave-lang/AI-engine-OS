import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.membership import Membership
from app.models.organization import Organization


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, org_id: uuid.UUID) -> Organization | None:
        stmt = select(Organization).where(
            Organization.id == org_id, Organization.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Organization | None:
        stmt = select(Organization).where(
            Organization.slug == slug, Organization.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def slug_exists(self, slug: str) -> bool:
        stmt = select(Organization.id).where(Organization.slug == slug)
        return (await self._session.scalar(stmt)) is not None

    async def add(self, organization: Organization) -> Organization:
        self._session.add(organization)
        await self._session.flush()
        return organization

    async def list_for_user(self, user_id: uuid.UUID) -> list[tuple[Organization, Membership]]:
        stmt = (
            select(Organization, Membership)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Membership.user_id == user_id, Organization.deleted_at.is_(None))
            .order_by(Organization.created_at)
        )
        result = await self._session.execute(stmt)
        return [(org, membership) for org, membership in result.all()]


class MembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, org_id: uuid.UUID, user_id: uuid.UUID) -> Membership | None:
        stmt = (
            select(Membership)
            .options(selectinload(Membership.organization))
            .where(Membership.organization_id == org_id, Membership.user_id == user_id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[Membership]:
        stmt = (
            select(Membership)
            .options(selectinload(Membership.organization))
            .where(Membership.user_id == user_id)
            .order_by(Membership.created_at)
        )
        return list((await self._session.scalars(stmt)).all())

    async def list_for_organization(self, org_id: uuid.UUID) -> list[Membership]:
        stmt = (
            select(Membership)
            .options(selectinload(Membership.user))
            .where(Membership.organization_id == org_id)
            .order_by(Membership.created_at)
        )
        return list((await self._session.scalars(stmt)).all())

    async def add(self, membership: Membership) -> Membership:
        self._session.add(membership)
        await self._session.flush()
        return membership
