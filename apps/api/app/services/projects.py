"""Project service. organization_id always comes from an authorized dependency."""

import secrets
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.project import Project, ProjectStatus
from app.repositories.projects import ProjectRepository
from app.services.organizations import slugify


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectRepository(session)

    async def _unique_slug(self, organization_id: uuid.UUID, name: str) -> str:
        base = slugify(name)
        slug = base
        while await self._projects.slug_exists(organization_id, slug):
            slug = f"{base}-{secrets.token_hex(2)}"
        return slug

    async def create(
        self,
        *,
        organization_id: uuid.UUID,
        name: str,
        description: str | None = None,
        industry: str | None = None,
        country: str | None = None,
    ) -> Project:
        project = Project(
            organization_id=organization_id,
            name=name.strip(),
            slug=await self._unique_slug(organization_id, name),
            description=description,
            industry=industry,
            country=country.upper() if country else None,
        )
        return await self._projects.add(project)

    async def list_for_organization(self, organization_id: uuid.UUID) -> list[Project]:
        return await self._projects.list_for_organization(organization_id)

    async def update(
        self,
        project: Project,
        *,
        name: str | None = None,
        description: str | None = None,
        industry: str | None = None,
        country: str | None = None,
        status: ProjectStatus | None = None,
    ) -> Project:
        if name is not None:
            project.name = name.strip()
        if description is not None:
            project.description = description
        if industry is not None:
            project.industry = industry
        if country is not None:
            project.country = country.upper()
        if status is not None:
            project.status = status
        await self._session.flush()
        await self._session.refresh(project)  # pick up DB-side updated_at
        return project

    async def delete(self, project: Project) -> None:
        if project is None:  # pragma: no cover - defensive
            raise NotFoundError("Project not found")
        await self._session.delete(project)
        await self._session.flush()
