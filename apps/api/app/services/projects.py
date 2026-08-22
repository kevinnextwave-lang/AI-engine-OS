"""Project onboarding: projects, their domains and competitors.

organization_id always arrives from an authorized dependency (membership
validated), never from an unchecked request value.
"""

import secrets
import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.competitors.service import CompetitorInput, CompetitorService
from app.core.errors import ConflictError, NotFoundError
from app.core.urls import normalize_website_url
from app.models.competitor import Competitor
from app.models.domain import Domain
from app.models.project import Project, ProjectStatus
from app.repositories.projects import CompetitorRepository, DomainRepository, ProjectRepository
from app.services.organizations import slugify


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectRepository(session)
        self._domains = DomainRepository(session)
        self._competitors = CompetitorRepository(session)

    # -- projects ----------------------------------------------------------

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
        website_url: str,
        description: str | None = None,
        industry: str | None = None,
        country: str | None = None,
    ) -> Project:
        """Create a project and its primary domain from the website URL."""
        normalized = normalize_website_url(website_url)
        project = Project(
            organization_id=organization_id,
            name=name.strip(),
            slug=await self._unique_slug(organization_id, name),
            description=description,
            industry=industry,
            country=country.upper() if country else None,
        )
        await self._projects.add(project)
        await self._domains.add(
            Domain(
                project_id=project.id,
                url=normalized.url,
                hostname=normalized.hostname,
                is_primary=True,
            )
        )
        return await self.reload(project.id)

    async def reload(self, project_id: uuid.UUID) -> Project:
        project = await self._projects.get_by_id(project_id)
        if project is None:  # pragma: no cover - defensive
            raise NotFoundError("Project not found")
        return project

    async def list_for_organizations(self, organization_ids: Sequence[uuid.UUID]) -> list[Project]:
        return await self._projects.list_for_organizations(organization_ids)

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
        return await self.reload(project.id)

    async def delete(self, project: Project) -> None:
        await self._session.delete(project)
        await self._session.flush()

    # -- domains -----------------------------------------------------------

    async def list_domains(self, project: Project) -> list[Domain]:
        return await self._domains.list_for_project(project.id)

    async def add_domain(self, project: Project, *, url: str, is_primary: bool = False) -> Domain:
        normalized = normalize_website_url(url)
        if await self._domains.get_by_hostname(project.id, normalized.hostname):
            raise ConflictError(f"Domain {normalized.hostname} is already part of this project")
        if is_primary and await self._domains.get_primary(project.id):
            raise ConflictError(
                "This project already has a primary domain; remove or demote it first"
            )
        return await self._domains.add(
            Domain(
                project_id=project.id,
                url=normalized.url,
                hostname=normalized.hostname,
                is_primary=is_primary,
            )
        )

    # -- competitors (5A: see app.competitors.service) ----------------------

    async def list_competitors(self, project: Project) -> list[Competitor]:
        return await CompetitorService(self._session).list_for_project(project.id)

    async def add_competitor(self, project: Project, *, name: str, website_url: str) -> Competitor:
        return await CompetitorService(self._session).create(
            project.id, CompetitorInput(name=name, website_url=website_url)
        )

    async def remove_competitor(self, project: Project, competitor_id: uuid.UUID) -> None:
        svc = CompetitorService(self._session)
        await svc.delete(await svc.get_in_project(project.id, competitor_id))
