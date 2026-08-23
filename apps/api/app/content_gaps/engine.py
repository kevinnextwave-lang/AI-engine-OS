"""Competitive Content Gap Engine: per prompt-topic, compare competitor
visibility in AI responses with the customer's crawled site coverage and
persist `content_gaps`. Re-analysis upserts by (project, topic, type); review
status and note survive; stale `new` rows whose evidence vanished are removed.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.competitive.metrics import BRAND, entity_view
from app.content_gaps import ANALYSIS_VERSION
from app.content_gaps.topics import (
    MIN_TOPIC_RESPONSES,
    PageMatch,
    TopicFacts,
    classify,
    confidence_for,
    match_page,
    normalize_topic,
    score,
    topic_keywords,
    topic_label,
)
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.models.content_gaps import ContentGap, GapStatus
from app.models.crawl import WebsitePage
from app.models.intelligence import ResponseCitation
from app.models.project import Project
from app.models.prompts import AiResponse, PromptRun, PromptRunStatus
from app.models.sources import CitationEntity, CitationEntityType, SourceDomain
from app.sources.normalize import normalize_hostname
from app.visibility.observations import ObservationSet, ResponseObservation, load_observations

log = get_logger(__name__)

DEFAULT_WINDOW_DAYS = 90


@dataclass
class ContentGapAnalysisResult:
    project_id: uuid.UUID
    window_days: int
    eligible_responses: int
    topics_analyzed: int
    pages_considered: int
    gaps_written: int
    gaps_removed: int
    analyzed_at: datetime
    note: str


class ContentGapEngine:
    def __init__(self, session: AsyncSession, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or datetime.now(UTC)

    async def analyze(
        self, project_id: uuid.UUID, *, window_days: int = DEFAULT_WINDOW_DAYS
    ) -> ContentGapAnalysisResult:
        project = await self._session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        start = self._now - timedelta(days=window_days)
        data = await load_observations(self._session, project_id, start=start, end=self._now)
        pages = (
            await self._session.scalars(
                select(WebsitePage).where(
                    WebsitePage.project_id == project_id,
                    WebsitePage.http_status < 400,
                    WebsitePage.is_duplicate_of_id.is_(None),
                )
            )
        ).all()
        research_by_response = await self._research_citations(project_id, start)

        topics = self._topic_facts(data, pages, research_by_response)
        written = removed = 0
        seen_keys: set[tuple[str, str]] = set()
        for facts in topics:
            gap_types = classify(facts)
            for gap_type in gap_types:
                key = (normalize_topic(topic_label(facts.prompt_text)), gap_type.value)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                await self._upsert(project_id, facts, gap_type.value, window_days)
                written += 1
        removed = await self._remove_stale(project_id, seen_keys)
        await self._session.flush()
        log.info(
            "content_gaps_analyzed",
            project_id=str(project_id),
            eligible_responses=len(data.observations),
            topics=len(topics),
            pages=len(pages),
            written=written,
            removed=removed,
        )
        return ContentGapAnalysisResult(
            project_id=project_id,
            window_days=window_days,
            eligible_responses=len(data.observations),
            topics_analyzed=len(topics),
            pages_considered=len(pages),
            gaps_written=written,
            gaps_removed=removed,
            analyzed_at=self._now,
            note=(
                "Gaps compare competitor visibility in AI responses with crawled site "
                "coverage. Topics with fewer than "
                f"{MIN_TOPIC_RESPONSES} responses, or without a clear competitor lead, "
                "produce no gap."
            ),
        )

    # -- facts -------------------------------------------------------------------------

    def _topic_facts(
        self,
        data: ObservationSet,
        pages: Any,
        research_by_response: dict[uuid.UUID, dict[str, Any]],
    ) -> list[TopicFacts]:
        by_prompt: dict[uuid.UUID, list[ResponseObservation]] = {}
        for o in data.observations:
            by_prompt.setdefault(o.prompt_id, []).append(o)
        out: list[TopicFacts] = []
        for pid, obs in by_prompt.items():
            first = obs[0]
            keywords = topic_keywords(first.prompt_text)
            matches: list[PageMatch] = []
            for page in pages:
                m = match_page(
                    keywords, page.url, page.title, page.meta_description, page.word_count
                )
                if m is not None:
                    matches.append(m)
            comp_mentions: dict[str, int] = {}
            for name in data.competitor_names:
                n = sum(1 for o in obs if entity_view(o, name).mentioned)
                if n:
                    comp_mentions[name] = n
            research: set[str] = set()
            comp_research: set[str] = set()
            citations = 0
            for o in obs:
                info = research_by_response.get(o.response_id)
                if info:
                    citations += info["citations"]
                    research |= info["research_domains"]
                    comp_research |= info["competitor_research_domains"]
            out.append(
                TopicFacts(
                    prompt_id=str(pid),
                    prompt_text=first.prompt_text,
                    category=first.category,
                    funnel_stage=first.funnel_stage,
                    responses=len(obs),
                    brand_mentions=sum(1 for o in obs if entity_view(o, BRAND).mentioned),
                    competitor_mentions=comp_mentions,
                    providers=sorted({o.provider_key for o in obs}),
                    research_domains=sorted(research),
                    competitor_research_domains=sorted(comp_research),
                    brand_cited=sum(1 for o in obs if o.brand_cited),
                    citations=citations,
                    matches=matches,
                )
            )
        return out

    async def _research_citations(
        self, project_id: uuid.UUID, start: datetime
    ) -> dict[uuid.UUID, dict[str, Any]]:
        """Per response: citation count, research-type cited domains, and which of
        those citations relate to competitors (`citation_entities`)."""
        rows = (
            await self._session.execute(
                select(ResponseCitation, AiResponse.id)
                .join(AiResponse, AiResponse.id == ResponseCitation.ai_response_id)
                .join(PromptRun, PromptRun.id == AiResponse.prompt_run_id)
                .where(
                    PromptRun.project_id == project_id,
                    PromptRun.status == PromptRunStatus.COMPLETED,
                    PromptRun.completed_at >= start,
                    AiResponse.parser_version.is_not(None),
                )
            )
        ).all()
        citations = [c for c, _ in rows]
        hosts = {h for c in citations if (h := _host_of(c)) is not None}
        research_hosts: set[str] = set()
        if hosts:
            for d in (
                await self._session.scalars(
                    select(SourceDomain).where(
                        SourceDomain.normalized_hostname.in_(hosts),
                        SourceDomain.domain_type == "research",
                    )
                )
            ).all():
                research_hosts.add(d.normalized_hostname)
        competitor_citation_ids: set[uuid.UUID] = set()
        if citations:
            for ce in (
                await self._session.scalars(
                    select(CitationEntity).where(
                        CitationEntity.citation_id.in_([c.id for c in citations]),
                        CitationEntity.entity_type == CitationEntityType.COMPETITOR.value,
                    )
                )
            ).all():
                competitor_citation_ids.add(ce.citation_id)
        out: dict[uuid.UUID, dict[str, Any]] = {}
        for c, response_id in rows:
            info = out.setdefault(
                response_id,
                {"citations": 0, "research_domains": set(), "competitor_research_domains": set()},
            )
            info["citations"] += 1
            host = _host_of(c)
            if host in research_hosts:
                info["research_domains"].add(host)
                if c.id in competitor_citation_ids:
                    info["competitor_research_domains"].add(host)
        return out

    # -- persistence -------------------------------------------------------------------

    async def _upsert(
        self, project_id: uuid.UUID, facts: TopicFacts, gap_type: str, window_days: int
    ) -> None:
        label = topic_label(facts.prompt_text)
        normalized = normalize_topic(label)
        scored = score(facts)
        top = facts.top_competitor
        competitor_evidence = {
            "prompt": facts.prompt_text,
            "prompt_id": facts.prompt_id,
            "responses": facts.responses,
            "providers": facts.providers,
            "brand_mentions": facts.brand_mentions,
            "brand_mention_rate": round(facts.brand_rate, 1),
            "competitor_mentions": facts.competitor_mentions,
            "top_competitor": top[0] if top else None,
            "top_competitor_rate": round(facts.competitor_rate, 1),
            "citations": facts.citations,
            "research_domains": facts.research_domains,
            "competitor_research_domains": facts.competitor_research_domains,
            "competitor_visibility": _band(facts.competitor_rate),
        }
        customer_coverage = {
            "pages_matched": len(facts.matches),
            "coverage_strength": scored["coverage_strength"],
            "coverage": _band(100.0 * scored["coverage_strength"]),
            "brand_cited_responses": facts.brand_cited,
            "pages": [
                {
                    "url": m.url,
                    "title": m.title,
                    "word_count": m.word_count,
                    "substantial": m.substantial,
                    "matched_keywords": m.matched_keywords,
                    "categories": sorted(m.categories),
                }
                for m in facts.matches[:10]
            ],
        }
        row = (
            await self._session.scalars(
                select(ContentGap).where(
                    ContentGap.project_id == project_id,
                    ContentGap.normalized_topic == normalized,
                    ContentGap.gap_type == gap_type,
                )
            )
        ).one_or_none()
        if row is None:
            row = ContentGap(
                project_id=project_id,
                normalized_topic=normalized,
                gap_type=gap_type,
            )
            self._session.add(row)
        row.prompt_id = uuid.UUID(facts.prompt_id)
        row.topic = label
        row.competitor_evidence = competitor_evidence
        row.customer_coverage = customer_coverage
        row.opportunity_score = scored["score"]
        row.confidence = confidence_for(facts.responses).value
        row.analysis_version = ANALYSIS_VERSION
        row.window_days = window_days
        row.analyzed_at = self._now
        # scoring transparency
        row.competitor_evidence["scoring"] = {
            "components": scored["components"],
            "weights": scored["weights"],
        }

    async def _remove_stale(self, project_id: uuid.UUID, seen_keys: set[tuple[str, str]]) -> int:
        rows = (
            await self._session.scalars(
                select(ContentGap).where(
                    ContentGap.project_id == project_id,
                    ContentGap.status == GapStatus.NEW.value,
                )
            )
        ).all()
        stale = [r.id for r in rows if (r.normalized_topic, r.gap_type) not in seen_keys]
        if stale:
            await self._session.execute(delete(ContentGap).where(ContentGap.id.in_(stale)))
        return len(stale)


def _band(rate: float) -> str:
    if rate >= 60:
        return "high"
    if rate >= 30:
        return "medium"
    return "low"


def _host_of(citation: ResponseCitation) -> str | None:
    if citation.domain:
        return normalize_hostname(citation.domain)
    if citation.url:
        from urllib.parse import urlsplit

        return normalize_hostname(urlsplit(citation.url).hostname)
    return None
