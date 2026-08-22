import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        return await self._session.get(Project, project_id)

    async def get_in_organization(
        self, organization_id: uuid.UUID, project_id: uuid.UUID
    ) -> Project | None:
        stmt = select(Project).where(
            Project.id == project_id, Project.organization_id == organization_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def slug_exists(self, organization_id: uuid.UUID, slug: str) -> bool:
        stmt = select(Project.id).where(
            Project.organization_id == organization_id, Project.slug == slug
        )
        return (await self._session.scalar(stmt)) is not None

    async def list_for_organization(self, organization_id: uuid.UUID) -> list[Project]:
        stmt = (
            select(Project)
            .where(Project.organization_id == organization_id)
            .order_by(Project.created_at.desc())
        )
        return list((await self._session.scalars(stmt)).all())

    async def add(self, project: Project) -> Project:
        self._session.add(project)
        await self._session.flush()
        return project
