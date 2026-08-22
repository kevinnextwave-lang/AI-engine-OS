"""Read models for entity intelligence + on-demand (re)analysis dispatch."""

import uuid
from collections import Counter
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.entities.extraction import KNOWN_TYPES
from app.models.crawl import WebsitePage
from app.models.entities import Entity, EntityScope
from app.repositories.entities import EntityRepository
from app.schemas.entities import (
    EntityConsistencyResponse,
    EntityLinkResponse,
    EntityListResponse,
    EntityObservationResponse,
    EntityResponse,
    PageSchemaResponse,
    ProjectSchemaResponse,
    ProjectSchemaSummary,
    SchemaBlockResponse,
    SchemaIssueResponse,
)

log = get_logger(__name__)

Dispatcher = Callable[[uuid.UUID], None]


class EntityService:
    def __init__(self, session: AsyncSession, dispatcher: Dispatcher) -> None:
        self._session = session
        self._dispatch = dispatcher
        self._repo = EntityRepository(session)

    def request_analysis(self, project_id: uuid.UUID) -> None:
        self._dispatch(project_id)
        log.info("entity_analysis_requested", project_id=str(project_id))

    async def _page_urls(self, page_ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
        ids = [p for p in page_ids if p is not None]
        if not ids:
            return {}
        rows = await self._session.execute(
            select(WebsitePage.id, WebsitePage.normalized_url).where(WebsitePage.id.in_(ids))
        )
        return {pid: url for pid, url in rows.all()}

    async def _to_responses(self, entities: list[Entity]) -> list[EntityResponse]:
        links = await self._repo.links_for_entities([e.id for e in entities])
        urls = await self._page_urls({e.page_id for e in entities})
        out: list[EntityResponse] = []
        for e in entities:
            item = EntityResponse.model_validate(e)
            item.page_url = urls.get(e.page_id) if e.page_id else None
            item.links = [EntityLinkResponse.model_validate(ln) for ln in links.get(e.id, [])]
            out.append(item)
        return out

    async def list_entities(
        self,
        project_id: uuid.UUID,
        *,
        entity_type: str | None,
        scope: EntityScope | None,
        known_only: bool,
        limit: int,
        offset: int,
    ) -> EntityListResponse:
        rows, total = await self._repo.list_for_project(
            project_id,
            entity_type=entity_type,
            scope=scope,
            known_only=known_only,
            limit=limit,
            offset=offset,
        )
        org = await self._repo.project_organization(project_id)
        org_resp = (await self._to_responses([org]))[0] if org else None
        return EntityListResponse(
            items=await self._to_responses(rows),
            total=total,
            limit=limit,
            offset=offset,
            organization=org_resp,
            analyzed_at=await self._repo.analyzed_at(project_id),
        )

    async def project_schema(self, project_id: uuid.UUID) -> ProjectSchemaResponse:
        blocks = await self._repo.blocks_for_project(project_id)
        pages_total = await self._session.scalar(
            select(func.count())
            .select_from(WebsitePage)
            .where(WebsitePage.project_id == project_id, WebsitePage.http_status == 200)
        )
        pages_with = {b.page_id for b in blocks}
        formats = Counter(b.format.value for b in blocks)
        type_pages: dict[str, set[uuid.UUID]] = {}
        for b in blocks:
            for t in b.schema_types:
                type_pages.setdefault(t, set()).add(b.page_id)
        schema_types = {t: len(p) for t, p in sorted(type_pages.items())}
        issues = await self._repo.issues(project_id)
        urls = await self._page_urls({i.page_id for i in issues})
        issue_items = []
        for i in issues:
            item = SchemaIssueResponse.model_validate(i)
            item.page_url = urls.get(i.page_id)
            issue_items.append(item)
        present = sorted(t for t in KNOWN_TYPES if t in schema_types)
        summary = ProjectSchemaSummary(
            pages_crawled=int(pages_total or 0),
            pages_with_structured_data=len(pages_with),
            pages_without_structured_data=max(0, int(pages_total or 0) - len(pages_with)),
            blocks_total=len(blocks),
            blocks_invalid=sum(1 for b in blocks if not b.is_valid),
            formats=dict(formats),
            schema_types=schema_types,
            entity_types=await self._repo.type_counts(project_id),
            known_types_present=present,
            known_types_absent=sorted(KNOWN_TYPES - set(present)),
            issues_by_code=dict(Counter(i.code for i in issues)),
        )
        return ProjectSchemaResponse(
            summary=summary,
            issues=issue_items,
            analyzed_at=await self._repo.analyzed_at(project_id),
        )

    async def page_schema(self, page: WebsitePage) -> PageSchemaResponse:
        blocks = await self._repo.blocks_for_page(page.id)
        issues = await self._repo.issues(page.project_id, page_id=page.id)
        entities, _ = await self._repo.list_for_project(
            page.project_id, page_id=page.id, limit=1000
        )
        entity_items = await self._to_responses(entities)
        by_block_issues: dict[uuid.UUID | None, list[SchemaIssueResponse]] = {}
        for i in issues:
            issue_item = SchemaIssueResponse.model_validate(i)
            issue_item.page_url = page.normalized_url
            by_block_issues.setdefault(i.structured_data_id, []).append(issue_item)
        by_block_entities: dict[uuid.UUID | None, list[EntityResponse]] = {}
        for e, entity_item in zip(entities, entity_items, strict=True):
            by_block_entities.setdefault(e.structured_data_id, []).append(entity_item)
        return PageSchemaResponse(
            page_id=page.id,
            url=page.normalized_url,
            blocks=[
                SchemaBlockResponse(
                    id=b.id,
                    format=b.format,
                    position=b.position,
                    schema_types=b.schema_types,
                    is_valid=b.is_valid,
                    error=b.error,
                    payload=b.payload,
                    issues=by_block_issues.get(b.id, []),
                    entities=by_block_entities.get(b.id, []),
                )
                for b in blocks
            ],
            analyzed_at=await self._repo.analyzed_at(page.project_id),
        )

    async def consistency(self, project_id: uuid.UUID) -> EntityConsistencyResponse:
        observations = await self._repo.observations(project_id)
        compared = await self._session.scalar(
            select(func.count())
            .select_from(Entity)
            .where(
                Entity.project_id == project_id,
                Entity.scope == EntityScope.PAGE,
                Entity.fingerprint.is_not(None),
            )
        )
        analyzed: datetime | None = await self._repo.analyzed_at(project_id)
        return EntityConsistencyResponse(
            items=[EntityObservationResponse.model_validate(o) for o in observations],
            total=len(observations),
            entities_compared=int(compared or 0),
            analyzed_at=analyzed,
        )
