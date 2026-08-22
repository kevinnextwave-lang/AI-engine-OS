import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Entity, EntityLink, EntityObservation, EntityScope, SchemaIssue
from app.models.page_intelligence import PageStructuredData


class EntityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        entity_type: str | None = None,
        scope: EntityScope | None = None,
        page_id: uuid.UUID | None = None,
        known_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Entity], int]:
        base = select(Entity).where(Entity.project_id == project_id)
        if entity_type is not None:
            base = base.where(Entity.entity_type == entity_type)
        if scope is not None:
            base = base.where(Entity.scope == scope)
        if page_id is not None:
            base = base.where(Entity.page_id == page_id)
        if known_only:
            base = base.where(Entity.is_known_type.is_(True))
        total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self._session.scalars(
            base.order_by(
                Entity.scope.desc(),  # project-level first
                Entity.entity_type,
                Entity.name,
                Entity.page_id,
                Entity.json_path,
            )
            .limit(limit)
            .offset(offset)
        )
        return list(rows.all()), int(total or 0)

    async def links_for_entities(
        self, entity_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[EntityLink]]:
        if not entity_ids:
            return {}
        rows = await self._session.scalars(
            select(EntityLink).where(EntityLink.entity_id.in_(entity_ids)).order_by(EntityLink.url)
        )
        out: dict[uuid.UUID, list[EntityLink]] = {}
        for link in rows.all():
            out.setdefault(link.entity_id, []).append(link)
        return out

    async def project_organization(self, project_id: uuid.UUID) -> Entity | None:
        return (
            await self._session.scalars(
                select(Entity).where(
                    Entity.project_id == project_id, Entity.scope == EntityScope.PROJECT
                )
            )
        ).first()

    async def type_counts(self, project_id: uuid.UUID) -> dict[str, int]:
        rows = await self._session.execute(
            select(Entity.entity_type, func.count())
            .where(Entity.project_id == project_id, Entity.scope == EntityScope.PAGE)
            .group_by(Entity.entity_type)
        )
        return {t: int(c) for t, c in rows.all()}

    async def observations(self, project_id: uuid.UUID) -> list[EntityObservation]:
        rows = await self._session.scalars(
            select(EntityObservation)
            .where(EntityObservation.project_id == project_id)
            .order_by(EntityObservation.code, EntityObservation.entity_name)
        )
        return list(rows.all())

    async def issues(
        self, project_id: uuid.UUID, *, page_id: uuid.UUID | None = None
    ) -> list[SchemaIssue]:
        stmt = select(SchemaIssue).where(SchemaIssue.project_id == project_id)
        if page_id is not None:
            stmt = stmt.where(SchemaIssue.page_id == page_id)
        rows = await self._session.scalars(
            stmt.order_by(SchemaIssue.page_id, SchemaIssue.block_position, SchemaIssue.json_path)
        )
        return list(rows.all())

    async def blocks_for_project(self, project_id: uuid.UUID) -> list[PageStructuredData]:
        rows = await self._session.scalars(
            select(PageStructuredData).where(PageStructuredData.project_id == project_id)
        )
        return list(rows.all())

    async def blocks_for_page(self, page_id: uuid.UUID) -> list[PageStructuredData]:
        rows = await self._session.scalars(
            select(PageStructuredData)
            .where(PageStructuredData.page_id == page_id)
            .order_by(PageStructuredData.position)
        )
        return list(rows.all())

    async def analyzed_at(self, project_id: uuid.UUID) -> datetime | None:
        value: datetime | None = await self._session.scalar(
            select(func.max(Entity.created_at)).where(Entity.project_id == project_id)
        )
        return value
