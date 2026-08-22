"""Resolve citations into the source graph and aggregate per project.

Flow for one citation:
  1. normalise its URL / domain → upsert `source_domains` (by normalized
     hostname) and, when a URL exists, `source_pages` (by normalized URL);
  2. link `citations.source_domain_id` / `source_page_id`;
  3. write a `citation_entities` row only when the evidence is clear: the cited
     host is one of the project's domains (brand) or a configured competitor's
     host (competitor). Anything else gets no relationship row.

`aggregate_project_sources` rebuilds a project's `project_sources` from its
citations (idempotent), so counts can always be regenerated.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Integer, cast, delete, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.core.logging import get_logger
from app.models.competitor import Competitor
from app.models.domain import Domain
from app.models.intelligence import ResponseCitation
from app.models.project import Project
from app.models.sources import (
    CitationEntity,
    CitationEntityType,
    CitationRelationship,
    ProjectSource,
    SourceDomain,
    SourcePage,
)
from app.sources.classify import Classification, PageSignals, classify
from app.sources.normalize import (
    classify_domain,
    display_name_for,
    host_matches,
    normalize_hostname,
    normalize_url,
)

log = get_logger(__name__)

# Confidence of a brand/competitor relationship derived from the cited host.
EXACT_HOST_CONFIDENCE = 0.95
SUBDOMAIN_CONFIDENCE = 0.8


@dataclass
class ProjectHosts:
    project_id: uuid.UUID
    brand_name: str
    brand_hosts: set[str] = field(default_factory=set)
    competitor_hosts: dict[str, Competitor] = field(default_factory=dict)  # host → competitor

    @property
    def company_hosts(self) -> frozenset[str]:
        return frozenset(self.brand_hosts) | frozenset(self.competitor_hosts)


@dataclass
class ResolveResult:
    resolved: int = 0
    skipped: int = 0  # no usable host
    domains_created: int = 0
    pages_created: int = 0
    relationships: int = 0


class SourceIntelligenceService:
    def __init__(self, session: AsyncSession, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or datetime.now(UTC)
        self._hosts_cache: dict[uuid.UUID, ProjectHosts] = {}
        self._company_cache: frozenset[str] | None = None

    # -- context -------------------------------------------------------------------

    async def project_hosts(self, project_id: uuid.UUID) -> ProjectHosts | None:
        cached = self._hosts_cache.get(project_id)
        if cached is not None:
            return cached
        project = await self._session.get(Project, project_id)
        if project is None:
            return None
        domains = (
            await self._session.scalars(select(Domain).where(Domain.project_id == project_id))
        ).all()
        competitors = (
            await self._session.scalars(
                select(Competitor).where(Competitor.project_id == project_id)
            )
        ).all()
        hosts = ProjectHosts(project_id=project_id, brand_name=project.name)
        for d in domains:
            h = normalize_hostname(d.hostname)
            if h:
                hosts.brand_hosts.add(h)
        for c in competitors:
            h = normalize_hostname(c.hostname)
            if h and h not in hosts.brand_hosts:
                hosts.competitor_hosts[h] = c
        self._hosts_cache[project_id] = hosts
        return hosts

    # -- source upserts --------------------------------------------------------------

    async def upsert_domain(
        self, hostname: str, *, seen_at: datetime, company_hosts: frozenset[str] = frozenset()
    ) -> tuple[SourceDomain, bool]:
        """Get-or-create by normalized hostname; concurrency-safe via ON CONFLICT.
        `domain_type` is only set on insert and never downgraded to unknown."""
        normalized = normalize_hostname(hostname)
        if normalized is None:
            raise ValueError(f"not a hostname: {hostname!r}")
        stmt: Any = (
            pg_insert(SourceDomain)
            .values(
                id=uuid.uuid4(),
                hostname=hostname.strip().lower().rstrip("."),
                normalized_hostname=normalized,
                display_name=display_name_for(normalized),
                domain_type=classify_domain(normalized, company_hosts=company_hosts).value,
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            )
            .on_conflict_do_update(
                constraint="uq_source_domains_normalized_hostname",
                set_={
                    "first_seen_at": func.least(SourceDomain.first_seen_at, seen_at),
                    "last_seen_at": func.greatest(SourceDomain.last_seen_at, seen_at),
                },
            )
            .returning(SourceDomain.id, literal_column("(xmax = 0)"))
        )
        row = (await self._session.execute(stmt)).one()
        domain = await self._session.get(SourceDomain, row[0], populate_existing=True)
        if domain is None:  # pragma: no cover - the row was just upserted
            raise RuntimeError("source domain vanished after upsert")
        created = bool(row[1])
        if created or domain.domain_type == "unknown":
            # Cheap hostname-only pass on first sight / while still unknown; the
            # full signal-based pass (pages, titles, metadata) is `classify_domain_record`.
            await self.classify_domain_record(domain, company_hosts=company_hosts)
        return domain, created

    async def upsert_page(
        self, domain: SourceDomain, url: str, *, seen_at: datetime
    ) -> tuple[SourcePage, bool] | None:
        normalized = normalize_url(url)
        if normalized is None:
            return None
        stmt: Any = (
            pg_insert(SourcePage)
            .values(
                id=uuid.uuid4(),
                source_domain_id=domain.id,
                url=url.strip()[:2048],
                normalized_url=normalized[:2048],
                first_seen_at=seen_at,
                last_seen_at=seen_at,
            )
            .on_conflict_do_update(
                constraint="uq_source_pages_normalized_url",
                set_={
                    "first_seen_at": func.least(SourcePage.first_seen_at, seen_at),
                    "last_seen_at": func.greatest(SourcePage.last_seen_at, seen_at),
                },
            )
            .returning(SourcePage.id, literal_column("(xmax = 0)"))
        )
        row = (await self._session.execute(stmt)).one()
        page = await self._session.get(SourcePage, row[0], populate_existing=True)
        if page is None:  # pragma: no cover - the row was just upserted
            raise RuntimeError("source page vanished after upsert")
        return page, bool(row[1])

    # -- classification (4B) ---------------------------------------------------------------

    async def classify_domain_record(
        self,
        domain: SourceDomain,
        *,
        company_hosts: frozenset[str] = frozenset(),
        page_limit: int = 50,
    ) -> Classification:
        """Run the signal-based classifier over the domain and a sample of its
        cited pages, and store the result. A known type is never replaced by
        `unknown` (absence of evidence is not evidence of change), but a more
        confident result always wins."""
        from app.core.config import get_settings
        from app.sources.registry import get_registry

        pages = (
            await self._session.scalars(
                select(SourcePage)
                .where(SourcePage.source_domain_id == domain.id)
                .order_by(SourcePage.last_seen_at.desc())
                .limit(page_limit)
            )
        ).all()
        result = classify(
            domain.normalized_hostname,
            registry=get_registry(),
            pages=[PageSignals(p.url, p.title, p.metadata_ or {}) for p in pages],
            company_hosts=company_hosts,
            threshold=get_settings().source_classification_threshold,
        )
        if result.domain_type.value != "unknown" or domain.domain_type == "unknown":
            previous = domain.classification_confidence or 0.0
            if result.domain_type.value != domain.domain_type or result.confidence >= previous:
                domain.domain_type = result.domain_type.value
                domain.classification_confidence = (
                    result.confidence if result.domain_type.value != "unknown" else None
                )
        domain.classification = result.as_dict()
        domain.is_authority = result.authority
        domain.classified_at = self._now
        return result

    async def reclassify(self, *, batch_size: int = 500) -> int:
        """Re-run classification for every known domain (after a registry change)."""
        count = 0
        last_id: uuid.UUID | None = None
        while True:
            stmt = select(SourceDomain).order_by(SourceDomain.id).limit(batch_size)
            if last_id is not None:
                stmt = stmt.where(SourceDomain.id > last_id)
            batch = (await self._session.scalars(stmt)).all()
            if not batch:
                break
            for d in batch:
                await self.classify_domain_record(d, company_hosts=await self._all_company_hosts())
                count += 1
            last_id = batch[-1].id
            await self._session.commit()
            if len(batch) < batch_size:
                break
        return count

    async def _all_company_hosts(self) -> frozenset[str]:
        """Every project's own and competitor hosts — evidence that a domain is a company site."""
        if self._company_cache is None:
            hosts = set()
            for (h,) in (await self._session.execute(select(Domain.hostname))).all():
                n = normalize_hostname(h)
                if n:
                    hosts.add(n)
            for (h,) in (await self._session.execute(select(Competitor.hostname))).all():
                n = normalize_hostname(h)
                if n:
                    hosts.add(n)
            self._company_cache = frozenset(hosts)
        return self._company_cache

    # -- citation resolution -----------------------------------------------------------

    async def resolve_citation(
        self, citation: ResponseCitation, hosts: ProjectHosts, *, stats: ResolveResult | None = None
    ) -> bool:
        """Link one citation to its domain/page and record a clear relationship.
        Returns False when the citation has no usable host."""
        stats = stats or ResolveResult()
        host = normalize_hostname(citation.domain) or (
            normalize_hostname(normalize_url(citation.url)) if citation.url else None
        )
        if host is None:
            stats.skipped += 1
            return False
        seen_at = citation.created_at or self._now
        domain, d_created = await self.upsert_domain(
            citation.domain or host, seen_at=seen_at, company_hosts=hosts.company_hosts
        )
        stats.domains_created += int(d_created)
        citation.source_domain_id = domain.id
        citation.source_page_id = None
        if citation.url:
            upserted = await self.upsert_page(domain, citation.url, seen_at=seen_at)
            if upserted is not None:
                page, p_created = upserted
                stats.pages_created += int(p_created)
                citation.source_page_id = page.id

        await self._session.execute(
            delete(CitationEntity).where(CitationEntity.citation_id == citation.id)
        )
        rel = self._relationship_for(host, hosts)
        if rel is not None:
            self._session.add(
                CitationEntity(citation_id=citation.id, project_id=hosts.project_id, **rel)
            )
            stats.relationships += 1
        stats.resolved += 1
        return True

    @staticmethod
    def _relationship_for(host: str, hosts: ProjectHosts) -> dict[str, object] | None:
        brand = host_matches(host, hosts.brand_hosts)
        if brand is not None:
            return {
                "entity_type": CitationEntityType.PROJECT.value,
                "entity_id": hosts.project_id,
                "entity_name": hosts.brand_name,
                "relationship": CitationRelationship.BRAND.value,
                "confidence": EXACT_HOST_CONFIDENCE if host == brand else SUBDOMAIN_CONFIDENCE,
            }
        comp_host = host_matches(host, set(hosts.competitor_hosts))
        if comp_host is not None:
            competitor = hosts.competitor_hosts[comp_host]
            return {
                "entity_type": CitationEntityType.COMPETITOR.value,
                "entity_id": competitor.id,
                "entity_name": competitor.name,
                "relationship": CitationRelationship.COMPETITOR.value,
                "confidence": EXACT_HOST_CONFIDENCE if host == comp_host else SUBDOMAIN_CONFIDENCE,
            }
        return None  # uncertain: no relationship row

    async def resolve_for_response(
        self, ai_response_id: uuid.UUID, project_id: uuid.UUID
    ) -> ResolveResult:
        """Resolve every citation of one response (called right after parsing)."""
        stats = ResolveResult()
        hosts = await self.project_hosts(project_id)
        if hosts is None:
            return stats
        citations = (
            await self._session.scalars(
                select(ResponseCitation).where(ResponseCitation.ai_response_id == ai_response_id)
            )
        ).all()
        for c in citations:
            await self.resolve_citation(c, hosts, stats=stats)
        await self._session.flush()
        return stats

    # -- aggregation -------------------------------------------------------------------

    async def aggregate_project_sources(self, project_id: uuid.UUID) -> int:
        """Rebuild `project_sources` for one project from its resolved citations.
        One row per cited domain (page NULL) plus one per cited page."""
        rel_sub = (
            select(
                CitationEntity.citation_id.label("cid"),
                func.max(
                    cast(CitationEntity.relationship == CitationRelationship.BRAND.value, Integer)
                ).label("is_brand"),
                func.max(
                    cast(
                        CitationEntity.relationship == CitationRelationship.COMPETITOR.value,
                        Integer,
                    )
                ).label("is_competitor"),
            )
            .where(CitationEntity.project_id == project_id)
            .group_by(CitationEntity.citation_id)
            .subquery()
        )
        base = (
            select(
                ResponseCitation.source_domain_id,
                ResponseCitation.source_page_id,
                ResponseCitation.created_at,
                func.coalesce(rel_sub.c.is_brand, 0).label("is_brand"),
                func.coalesce(rel_sub.c.is_competitor, 0).label("is_competitor"),
            )
            .outerjoin(rel_sub, rel_sub.c.cid == ResponseCitation.id)
            .where(
                ResponseCitation.project_id == project_id,
                ResponseCitation.source_domain_id.is_not(None),
            )
        ).subquery()

        def grouped(with_page: bool) -> Select[Any]:
            page_col = (
                base.c.source_page_id
                if with_page
                else cast(literal_column("NULL"), base.c.source_page_id.type)
            )
            stmt = select(
                base.c.source_domain_id,
                page_col.label("source_page_id"),
                func.count().label("citation_count"),
                func.sum(base.c.is_brand).label("brand_citation_count"),
                func.sum(base.c.is_competitor).label("competitor_citation_count"),
                func.min(base.c.created_at).label("first_cited_at"),
                func.max(base.c.created_at).label("last_cited_at"),
            ).group_by(base.c.source_domain_id)
            if with_page:
                stmt = stmt.where(base.c.source_page_id.is_not(None)).group_by(
                    base.c.source_page_id
                )
            return stmt

        rows = [
            *(await self._session.execute(grouped(False))).all(),
            *(await self._session.execute(grouped(True))).all(),
        ]
        await self._session.execute(
            delete(ProjectSource).where(ProjectSource.project_id == project_id)
        )
        if rows:
            self._session.add_all(
                ProjectSource(
                    project_id=project_id,
                    source_domain_id=r.source_domain_id,
                    source_page_id=r.source_page_id,
                    citation_count=int(r.citation_count),
                    brand_citation_count=int(r.brand_citation_count or 0),
                    competitor_citation_count=int(r.competitor_citation_count or 0),
                    first_cited_at=r.first_cited_at,
                    last_cited_at=r.last_cited_at,
                )
                for r in rows
            )
        await self._session.flush()
        return len(rows)

    # -- backfill ------------------------------------------------------------------------

    async def backfill(
        self,
        *,
        project_id: uuid.UUID | None = None,
        force: bool = False,
        batch_size: int = 500,
    ) -> ResolveResult:
        """Resolve historical citations (all projects, or one) without re-running
        any AI query, then rebuild the affected projects' aggregates. Commits per
        batch so a large backfill can be resumed; `force` re-resolves citations
        that already have a source (e.g. after a normalisation change)."""
        stats = ResolveResult()
        touched: set[uuid.UUID] = set()
        last_id: uuid.UUID | None = None
        while True:
            stmt = select(ResponseCitation).order_by(ResponseCitation.id).limit(batch_size)
            if project_id is not None:
                stmt = stmt.where(ResponseCitation.project_id == project_id)
            if not force:
                stmt = stmt.where(ResponseCitation.source_domain_id.is_(None))
            if last_id is not None:
                stmt = stmt.where(ResponseCitation.id > last_id)
            batch = (await self._session.scalars(stmt)).all()
            if not batch:
                break
            for c in batch:
                hosts = await self.project_hosts(c.project_id)
                if hosts is None:
                    stats.skipped += 1
                    continue
                if await self.resolve_citation(c, hosts, stats=stats):
                    touched.add(c.project_id)
            last_id = batch[-1].id
            await self._session.commit()
            if len(batch) < batch_size:
                break
        for pid in touched if project_id is None else ({project_id} if touched else set()):
            await self.aggregate_project_sources(pid)
        await self._session.commit()
        log.info(
            "source_backfill_done",
            project_id=str(project_id) if project_id else None,
            resolved=stats.resolved,
            skipped=stats.skipped,
            domains_created=stats.domains_created,
            pages_created=stats.pages_created,
            relationships=stats.relationships,
            projects=len(touched),
        )
        return stats
