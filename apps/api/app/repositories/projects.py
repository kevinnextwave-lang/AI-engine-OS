import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.competitor import Competitor
from app.models.domain import Domain
from app.models.project import Project


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        stmt = (
            select(Project).options(selectinload(Project.domains)).where(Project.id == project_id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def slug_exists(self, organization_id: uuid.UUID, slug: str) -> bool:
        stmt = select(Project.id).where(
            Project.organization_id == organization_id, Project.slug == slug
        )
        return (await self._session.scalar(stmt)) is not None

    async def list_for_organizations(self, organization_ids: Sequence[uuid.UUID]) -> list[Project]:
        if not organization_ids:
            return []
        stmt = (
            select(Project)
            .options(selectinload(Project.domains))
            .where(Project.organization_id.in_(list(organization_ids)))
            .order_by(Project.created_at.desc())
        )
        return list((await self._session.scalars(stmt)).all())

    async def list_for_organization(self, organization_id: uuid.UUID) -> list[Project]:
        return await self.list_for_organizations([organization_id])

    async def add(self, project: Project) -> Project:
        self._session.add(project)
        await self._session.flush()
        return project


class DomainRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_project(self, project_id: uuid.UUID) -> list[Domain]:
        stmt = (
            select(Domain)
            .where(Domain.project_id == project_id)
            .order_by(Domain.is_primary.desc(), Domain.created_at)
        )
        return list((await self._session.scalars(stmt)).all())

    async def get_by_hostname(self, project_id: uuid.UUID, hostname: str) -> Domain | None:
        stmt = select(Domain).where(Domain.project_id == project_id, Domain.hostname == hostname)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_primary(self, project_id: uuid.UUID) -> Domain | None:
        stmt = select(Domain).where(Domain.project_id == project_id, Domain.is_primary.is_(True))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add(self, domain: Domain) -> Domain:
        self._session.add(domain)
        await self._session.flush()
        return domain


class CompetitorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_project(self, project_id: uuid.UUID) -> list[Competitor]:
        stmt = (
            select(Competitor)
            .where(Competitor.project_id == project_id)
            .order_by(Competitor.created_at)
        )
        return list((await self._session.scalars(stmt)).all())

    async def get_in_project(
        self, project_id: uuid.UUID, competitor_id: uuid.UUID
    ) -> Competitor | None:
        stmt = select(Competitor).where(
            Competitor.id == competitor_id, Competitor.project_id == project_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_hostname(self, project_id: uuid.UUID, hostname: str) -> Competitor | None:
        stmt = select(Competitor).where(
            Competitor.project_id == project_id, Competitor.hostname == hostname
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add(self, competitor: Competitor) -> Competitor:
        self._session.add(competitor)
        await self._session.flush()
        return competitor

    async def delete(self, competitor: Competitor) -> None:
        await self._session.delete(competitor)
        await self._session.flush()
