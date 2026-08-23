"""One row per parsed, completed prompt run — the unit the metrics aggregate over."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.competitor import CompetitorDomain
from app.models.intelligence import BrandMention, CompetitorMention, ResponseCitation
from app.models.prompts import AiResponse, Prompt, PromptRun, PromptRunStatus
from app.models.sources import CitationEntity, CitationEntityType
from app.repositories.projects import CompetitorRepository, DomainRepository

STRENGTH_RANK = {"unknown": 0, "none": 1, "weak": 2, "moderate": 3, "strong": 4}


@dataclass
class CompetitorObservation:
    name: str
    competitor_id: uuid.UUID | None
    position: int | None
    sentiment: str
    strength: str


@dataclass
class ResponseObservation:
    run_id: uuid.UUID
    response_id: uuid.UUID
    prompt_id: uuid.UUID
    prompt_text: str
    category: str
    funnel_stage: str
    provider_key: str
    model_key: str
    completed_at: datetime
    parser_version: str | None
    brand_mentioned: bool
    brand_position: int | None
    brand_sentiment: str  # aggregate over the response's brand mentions
    brand_strength: str  # strongest recommendation strength
    brand_cited: bool
    competitors: list[CompetitorObservation] = field(default_factory=list)
    # Citations in this response that reference the brand / each configured competitor
    # (own-site hosts, or citation_entities rows written by source intelligence).
    brand_citations: int = 0
    competitor_citations: dict[str, int] = field(default_factory=dict)

    @property
    def recommended(self) -> bool:
        """Positively recommended: moderate/strong strength and not negative sentiment."""
        return (
            self.brand_mentioned
            and self.brand_strength in ("moderate", "strong")
            and self.brand_sentiment != "negative"
        )


@dataclass
class ObservationSet:
    observations: list[ResponseObservation]
    competitor_names: list[str]  # configured competitors (even if never mentioned)
    brand_domains: list[str]


def _aggregate_sentiment(values: list[str]) -> str:
    kinds = {v for v in values if v != "unknown"}
    if not kinds:
        return "unknown"
    if "mixed" in kinds or {"positive", "negative"} <= kinds:
        return "mixed"
    if "negative" in kinds:
        return "negative"
    if "positive" in kinds:
        return "positive"
    return "neutral"


async def load_observations(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    start: datetime | None,
    end: datetime | None,
) -> ObservationSet:
    domains = [
        d.hostname.lower().removeprefix("www.")
        for d in await DomainRepository(session).list_for_project(project_id)
    ]
    competitors = await CompetitorRepository(session).list_for_project(project_id)
    competitor_names = [c.name for c in competitors]
    competitor_hosts: dict[str, str] = {}  # normalised host → competitor name
    name_by_id: dict[uuid.UUID, str] = {}
    for comp in competitors:
        name_by_id[comp.id] = comp.name
        host_key = comp.normalized_domain or comp.hostname.lower().removeprefix("www.")
        competitor_hosts[host_key] = comp.name
    if competitors:
        for cd in (
            await session.scalars(
                select(CompetitorDomain).where(CompetitorDomain.competitor_id.in_(list(name_by_id)))
            )
        ).all():
            competitor_hosts.setdefault(cd.domain, name_by_id[cd.competitor_id])

    stmt = (
        select(PromptRun, AiResponse, Prompt)
        .join(AiResponse, AiResponse.prompt_run_id == PromptRun.id)
        .join(Prompt, Prompt.id == PromptRun.prompt_id)
        .where(
            PromptRun.project_id == project_id,
            PromptRun.status == PromptRunStatus.COMPLETED,
            AiResponse.parser_version.is_not(None),
        )
    )
    if start is not None:
        stmt = stmt.where(PromptRun.completed_at >= start)
    if end is not None:
        stmt = stmt.where(PromptRun.completed_at < end)
    rows = (await session.execute(stmt.order_by(PromptRun.completed_at))).all()
    if not rows:
        return ObservationSet([], competitor_names, domains)

    response_ids = [r.id for _, r, _ in rows]
    mentions: dict[uuid.UUID, list[BrandMention]] = {}
    for bm_row in (
        await session.scalars(
            select(BrandMention).where(BrandMention.ai_response_id.in_(response_ids))
        )
    ).all():
        mentions.setdefault(bm_row.ai_response_id, []).append(bm_row)
    comp_mentions: dict[uuid.UUID, list[CompetitorMention]] = {}
    for cm_row in (
        await session.scalars(
            select(CompetitorMention).where(CompetitorMention.ai_response_id.in_(response_ids))
        )
    ).all():
        comp_mentions.setdefault(cm_row.ai_response_id, []).append(cm_row)
    citations: dict[uuid.UUID, list[ResponseCitation]] = {}
    for c in (
        await session.scalars(
            select(ResponseCitation).where(ResponseCitation.ai_response_id.in_(response_ids))
        )
    ).all():
        citations.setdefault(c.ai_response_id, []).append(c)
    citation_ids = [c.id for rows_ in citations.values() for c in rows_]
    entity_rows: dict[uuid.UUID, list[CitationEntity]] = {}
    if citation_ids:
        for ce in (
            await session.scalars(
                select(CitationEntity).where(CitationEntity.citation_id.in_(citation_ids))
            )
        ).all():
            entity_rows.setdefault(ce.citation_id, []).append(ce)

    observations: list[ResponseObservation] = []
    for run, response, prompt in rows:
        if run.completed_at is None:
            continue
        bm = mentions.get(response.id, [])
        positions = [m.position for m in bm if m.position is not None]
        brand_citations = 0
        competitor_citations: dict[str, int] = {}
        for c in citations.get(response.id, []):
            related = _citation_entities(
                c, entity_rows.get(c.id, []), domains, competitor_hosts, name_by_id
            )
            if related["brand"]:
                brand_citations += 1
            for cname in related["competitors"]:
                competitor_citations[cname] = competitor_citations.get(cname, 0) + 1
        cited = brand_citations > 0
        comps: dict[str, CompetitorObservation] = {}
        for cm in comp_mentions.get(response.id, []):
            existing = comps.get(cm.competitor_name)
            if existing is None:
                comps[cm.competitor_name] = CompetitorObservation(
                    cm.competitor_name,
                    cm.competitor_id,
                    cm.position,
                    cm.sentiment,
                    cm.recommendation_strength,
                )
            else:
                if cm.position is not None and (
                    existing.position is None or cm.position < existing.position
                ):
                    existing.position = cm.position
                if STRENGTH_RANK[cm.recommendation_strength] > STRENGTH_RANK[existing.strength]:
                    existing.strength = cm.recommendation_strength
                existing.sentiment = _aggregate_sentiment([existing.sentiment, cm.sentiment])
        observations.append(
            ResponseObservation(
                run_id=run.id,
                response_id=response.id,
                prompt_id=prompt.id,
                prompt_text=prompt.text,
                category=prompt.category.value,
                funnel_stage=prompt.funnel_stage.value,
                provider_key=run.provider_key or "unknown",
                model_key=run.model_key or "unknown",
                completed_at=run.completed_at,
                parser_version=response.parser_version,
                brand_mentioned=bool(bm),
                brand_position=min(positions) if positions else None,
                brand_sentiment=_aggregate_sentiment([m.sentiment for m in bm]),
                brand_strength=max(
                    (m.recommendation_strength for m in bm),
                    key=lambda s: STRENGTH_RANK[s],
                    default="unknown",
                ),
                brand_cited=cited,
                competitors=list(comps.values()),
                brand_citations=brand_citations,
                competitor_citations=competitor_citations,
            )
        )
    return ObservationSet(observations, competitor_names, domains)


def _citation_host(domain: str | None, url: str | None) -> str:
    host = (domain or "").lower().removeprefix("www.")
    if not host and url:
        from urllib.parse import urlsplit

        host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    return host


def _citation_entities(
    citation: ResponseCitation,
    entities: list[CitationEntity],
    brand_domains: list[str],
    competitor_hosts: dict[str, str],
    name_by_id: dict[uuid.UUID, str],
) -> dict[str, Any]:
    """Which entities a citation references: the brand when the host is a project
    domain, a competitor when the host is one of its domains, plus any
    citation_entities rows (slug / anchor matches from source intelligence)."""
    brand = _cites_brand(citation.domain, citation.url, brand_domains)
    names: set[str] = set()
    host = _citation_host(citation.domain, citation.url)
    if host:
        for h, cname in competitor_hosts.items():
            if h and (host == h or host.endswith("." + h)):
                names.add(cname)
    for ce in entities:
        if ce.entity_type == CitationEntityType.PROJECT.value:
            brand = True
        elif ce.entity_type == CitationEntityType.COMPETITOR.value and ce.entity_id in name_by_id:
            names.add(name_by_id[ce.entity_id])
    return {"brand": brand, "competitors": names}


def _cites_brand(domain: str | None, url: str | None, brand_domains: list[str]) -> bool:
    host = _citation_host(domain, url)
    return any(host == d or host.endswith("." + d) for d in brand_domains if d) if host else False


def as_dict(o: ResponseObservation) -> dict[str, Any]:
    return {
        "run_id": str(o.run_id),
        "provider": o.provider_key,
        "model": o.model_key,
        "brand_mentioned": o.brand_mentioned,
        "position": o.brand_position,
        "sentiment": o.brand_sentiment,
        "strength": o.brand_strength,
        "cited": o.brand_cited,
    }
