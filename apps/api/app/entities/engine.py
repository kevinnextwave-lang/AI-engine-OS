"""Rebuilds a project's entity intelligence from stored structured data."""

import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.entities.consistency import find_inconsistencies
from app.entities.extraction import extract_entities
from app.entities.organization import PageInfo, build_project_organization, page_role
from app.entities.same_as import classify, is_authoritative
from app.entities.validation import validate_block
from app.models.crawl import WebsitePage
from app.models.entities import Entity, EntityLink, EntityObservation, EntityScope, SchemaIssue
from app.models.page_intelligence import PageContentMetrics, PageStructuredData
from app.models.project import Project
from app.repositories.projects import DomainRepository

log = get_logger("entities.engine")


@dataclass
class AnalysisResult:
    entities: int
    links: int
    issues: int
    observations: int
    organization_entity_id: uuid.UUID | None


async def run_entity_analysis(session: AsyncSession, project_id: uuid.UUID) -> AnalysisResult:
    project = await session.get(Project, project_id)
    if project is None:
        raise ValueError("project not found")
    domains = await DomainRepository(session).list_for_project(project_id)
    primary = next((d for d in domains if d.is_primary), domains[0] if domains else None)
    root_host = (primary.hostname if primary else "").lower()
    if root_host.startswith("www."):
        root_host = root_host[4:]

    pages = list(
        (
            await session.scalars(select(WebsitePage).where(WebsitePage.project_id == project_id))
        ).all()
    )
    page_by_id = {p.id: p for p in pages}
    blocks = list(
        (
            await session.scalars(
                select(PageStructuredData)
                .where(PageStructuredData.project_id == project_id)
                .order_by(PageStructuredData.page_id, PageStructuredData.position)
            )
        ).all()
    )

    # Derived rows are rebuilt from scratch on every run.
    for model in (EntityObservation, SchemaIssue, EntityLink, Entity):
        await session.execute(delete(model).where(model.project_id == project_id))

    entities: list[Entity] = []
    links: list[EntityLink] = []
    issues: list[SchemaIssue] = []
    for block in blocks:
        if block.page_id not in page_by_id:
            continue
        for issue in validate_block(block.format, block.payload, block.is_valid, block.error):
            issues.append(
                SchemaIssue(
                    project_id=project_id,
                    page_id=block.page_id,
                    structured_data_id=block.id,
                    format=block.format,
                    code=issue.code,
                    severity=issue.severity,
                    message=issue.message,
                    json_path=issue.path,
                    block_position=block.position,
                )
            )
        if not block.is_valid or block.payload is None:
            continue
        for ex in extract_entities(block.payload):
            entity = Entity(
                project_id=project_id,
                page_id=block.page_id,
                structured_data_id=block.id,
                scope=EntityScope.PAGE,
                source_format=block.format,
                entity_type=ex.entity_type,
                extra_types=ex.extra_types,
                name=ex.name[:500] if ex.name else None,
                description=ex.description,
                url=ex.url[:2048] if ex.url else None,
                same_as=ex.same_as,
                identifier=ex.identifier,
                properties=ex.properties,
                json_path=ex.json_path[:500],
                fingerprint=ex.fingerprint[:700] if ex.fingerprint else None,
                is_known_type=ex.is_known_type,
            )
            entities.append(entity)
    session.add_all(entities)
    session.add_all(issues)
    await session.flush()
    for entity in entities:
        links.extend(_links_for(entity))

    # Project-level organization.
    page_info: dict[Any, PageInfo] = {}
    roles: dict[Any, str | None] = {}
    for p in pages:
        if p.http_status != 200:
            continue
        path = urlsplit(p.normalized_url).path or "/"
        host = (urlsplit(p.normalized_url).hostname or "").lower().removeprefix("www.")
        is_root = path in ("", "/") and host == root_host
        page_info[p.id] = PageInfo(id=p.id, url=p.normalized_url, path=path)
        roles[p.id] = page_role(path, is_root)
    role_page_ids = [pid for pid, r in roles.items() if r is not None]
    if role_page_ids:
        for m in (
            await session.scalars(
                select(PageContentMetrics).where(PageContentMetrics.page_id.in_(role_page_ids))
            )
        ).all():
            page_info[m.page_id].clean_text = m.clean_text
    org_fields = build_project_organization(
        entities, page_info, roles, project_name=project.name, root_host=root_host
    )
    org_id: uuid.UUID | None = None
    if org_fields is not None:
        org = Entity(
            project_id=project_id,
            page_id=None,
            structured_data_id=None,
            scope=EntityScope.PROJECT,
            source_format=None,
            is_known_type=True,
            json_path="",
            **org_fields,
        )
        session.add(org)
        await session.flush()
        org_id = org.id
        links.extend(_links_for(org))
    session.add_all(links)

    page_urls = {p.id: p.normalized_url for p in pages}
    observations = [
        EntityObservation(
            project_id=project_id,
            code=o.code,
            severity=o.severity,
            title=o.title,
            description=o.description,
            entity_type=o.entity_type,
            entity_name=o.entity_name[:500] if o.entity_name else None,
            evidence=o.evidence,
        )
        for o in find_inconsistencies(entities, page_urls)
    ]
    session.add_all(observations)
    await session.commit()
    result = AnalysisResult(
        entities=len(entities) + (1 if org_id else 0),
        links=len(links),
        issues=len(issues),
        observations=len(observations),
        organization_entity_id=org_id,
    )
    log.info(
        "entity_analysis_completed",
        project_id=str(project_id),
        entities=result.entities,
        issues=result.issues,
        observations=result.observations,
        types=dict(Counter(e.entity_type for e in entities).most_common(10)),
    )
    return result


def _links_for(entity: Entity) -> list[EntityLink]:
    out: list[EntityLink] = []
    for url in dict.fromkeys(entity.same_as):
        if not url.startswith(("http://", "https://")):
            continue
        platform = classify(url)
        out.append(
            EntityLink(
                entity_id=entity.id,
                project_id=entity.project_id,
                url=url[:2048],
                platform=platform,
                is_authoritative=is_authoritative(platform),
            )
        )
    return out
