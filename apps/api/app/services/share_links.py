"""Share links: create/list/revoke, and resolving a public token to a report.

The public payload is deliberately narrower than the app: overview, per-engine
breakdown, and the trend series — never per-prompt texts (a prompt set is
competitive strategy; a share link is for showing results, not methodology).
"""

import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_token
from app.models.organization import Organization, OrganizationStatus
from app.models.project import Project, ProjectStatus
from app.models.share_link import ProjectShareLink
from app.visibility.engine import VisibilityEngine

PUBLIC_WINDOW = "30d"


class ShareLinkService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_project(self, project_id: uuid.UUID) -> list[ProjectShareLink]:
        rows = (
            await self._session.scalars(
                select(ProjectShareLink)
                .where(ProjectShareLink.project_id == project_id)
                .order_by(ProjectShareLink.created_at.desc())
            )
        ).all()
        return list(rows)

    async def create(
        self, project: Project, *, label: str | None, user_id: uuid.UUID | None
    ) -> tuple[ProjectShareLink, str]:
        """Returns (row, raw_token). The raw token is shown exactly once."""
        raw = secrets.token_urlsafe(32)
        link = ProjectShareLink(
            project_id=project.id,
            created_by_user_id=user_id,
            token_hash=hash_token(raw),
            label=(label or None),
        )
        self._session.add(link)
        await self._session.flush()
        return link, raw

    async def get(self, link_id: uuid.UUID) -> ProjectShareLink | None:
        return await self._session.get(ProjectShareLink, link_id)

    async def revoke(self, link: ProjectShareLink) -> ProjectShareLink:
        if link.revoked_at is None:
            link.revoked_at = datetime.now(UTC)
            await self._session.flush()
        return link

    async def resolve(self, raw_token: str) -> tuple[ProjectShareLink, Project] | None:
        """Active link + servable project, or None. Constant shape on every
        miss (unknown, revoked, archived project, unusable org) — a public
        endpoint must not explain which part failed."""
        link = await self._session.scalar(
            select(ProjectShareLink).where(ProjectShareLink.token_hash == hash_token(raw_token))
        )
        if link is None or link.revoked_at is not None:
            return None
        project = await self._session.get(Project, link.project_id)
        if project is None or project.status != ProjectStatus.ACTIVE:
            return None
        org = await self._session.get(Organization, project.organization_id)
        if org is None or org.deleted_at is not None or org.status != OrganizationStatus.ACTIVE:
            return None
        return link, project


async def build_public_report(
    session: AsyncSession, project: Project, *, now: datetime | None = None
) -> dict[str, Any]:
    engine = VisibilityEngine(session, now=now)
    overview = await engine.overview(project.id, PUBLIC_WINDOW)
    by_engine = await engine.by_engine(project.id, PUBLIC_WINDOW)
    trends = await engine.trends(project.id)
    return {
        "project_name": project.name,
        "window": PUBLIC_WINDOW,
        "generated_at": overview["generated_at"],
        "overview": overview,
        "engines": by_engine["providers"],
        "series": trends["series"],
    }
