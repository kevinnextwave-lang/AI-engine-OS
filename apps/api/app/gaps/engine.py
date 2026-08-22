"""Citation Gap Engine: observe → compare → persist.

For one project and window:
  1. eligible responses = completed, parsed prompt runs in the window;
  2. per cited source domain: relevant responses, prompts, citation counts,
     brand / competitor citations (from `citation_entities`), per-competitor
     counts, first/last cited, first-/second-half split;
  3. Source Relevance Score (4B) from the domain's global citation history;
  4. gap type, Citation Opportunity Score, confidence, explanation;
  5. upsert `citation_gaps` (status and note survive re-analysis; rows still
     `new` whose source vanished from the window are removed).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Integer, and_, cast, delete, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.gaps import ANALYSIS_VERSION
from app.gaps.scoring import (
    SourceStats,
    classify_gap,
    confidence_for,
    explain,
    opportunity,
)
from app.models.gaps import CitationGap, GapStatus
from app.models.intelligence import ResponseCitation
from app.models.prompts import AiResponse, PromptRun, PromptRunStatus
from app.models.sources import CitationEntity, CitationRelationship, SourceDomain, SourcePage
from app.sources.relevance import RelevanceInputs, source_relevance

log = get_logger(__name__)

DEFAULT_WINDOW_DAYS = 90


@dataclass
class AnalysisResult:
    project_id: uuid.UUID
    window_days: int
    eligible_responses: int
    total_prompts: int
    sources_observed: int
    gaps_written: int
    gaps_removed: int
    analyzed_at: datetime


class CitationGapEngine:
    def __init__(self, session: AsyncSession, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or datetime.now(UTC)

    async def analyze(
        self, project_id: uuid.UUID, *, window_days: int = DEFAULT_WINDOW_DAYS
    ) -> AnalysisResult:
        start = self._now - timedelta(days=window_days)
        mid = self._now - timedelta(days=window_days / 2)

        eligible = (
            select(
                PromptRun.id.label("run_id"),
                AiResponse.id.label("response_id"),
                PromptRun.prompt_id,
            )
            .join(AiResponse, AiResponse.prompt_run_id == PromptRun.id)
            .where(
                PromptRun.project_id == project_id,
                PromptRun.status == PromptRunStatus.COMPLETED,
                AiResponse.parser_version.is_not(None),
                PromptRun.completed_at >= start,
                PromptRun.completed_at < self._now,
            )
        ).subquery()
        eligible_responses = (
            await self._session.scalar(select(func.count()).select_from(eligible)) or 0
        )
        total_prompts = (
            await self._session.scalar(select(func.count(distinct(eligible.c.prompt_id)))) or 0
        )

        # relationship flags per citation (a citation may relate to several entities)
        rel = (
            select(
                CitationEntity.citation_id.label("cid"),
                func.bool_or(CitationEntity.relationship == CitationRelationship.BRAND.value).label(
                    "is_brand"
                ),
                func.bool_or(
                    CitationEntity.relationship == CitationRelationship.COMPETITOR.value
                ).label("is_competitor"),
            )
            .where(CitationEntity.project_id == project_id)
            .group_by(CitationEntity.citation_id)
            .subquery()
        )
        cites = (
            select(
                ResponseCitation.id.label("cid"),
                ResponseCitation.source_domain_id.label("domain_id"),
                ResponseCitation.source_page_id.label("page_id"),
                ResponseCitation.created_at.label("cited_at"),
                eligible.c.response_id,
                eligible.c.prompt_id,
                func.coalesce(rel.c.is_brand, False).label("is_brand"),
                func.coalesce(rel.c.is_competitor, False).label("is_competitor"),
            )
            .join(eligible, eligible.c.response_id == ResponseCitation.ai_response_id)
            .outerjoin(rel, rel.c.cid == ResponseCitation.id)
            .where(
                ResponseCitation.project_id == project_id,
                ResponseCitation.source_domain_id.is_not(None),
            )
        ).subquery()

        per_domain = (
            await self._session.execute(
                select(
                    cites.c.domain_id,
                    func.count().label("citations"),
                    func.count(distinct(cites.c.response_id)).label("relevant"),
                    func.count(distinct(cites.c.prompt_id)).label("prompts"),
                    func.sum(cast(cites.c.is_brand, Integer)).label("brand"),
                    func.sum(cast(cites.c.is_competitor, Integer)).label("competitor"),
                    func.min(cites.c.cited_at).label("first"),
                    func.max(cites.c.cited_at).label("last"),
                    func.sum(cast(cites.c.cited_at < mid, Integer)).label("first_half"),
                    func.sum(cast(cites.c.cited_at >= mid, Integer)).label("second_half"),
                ).group_by(cites.c.domain_id)
            )
        ).all()
        domain_ids = [r.domain_id for r in per_domain]
        if not domain_ids:
            removed = await self._prune(project_id, keep=set())
            await self._session.flush()
            return AnalysisResult(
                project_id,
                window_days,
                int(eligible_responses),
                int(total_prompts),
                0,
                0,
                removed,
                self._now,
            )

        # per competitor, per domain
        comp_rows = (
            await self._session.execute(
                select(cites.c.domain_id, CitationEntity.entity_name, func.count())
                .join(CitationEntity, CitationEntity.citation_id == cites.c.cid)
                .where(CitationEntity.relationship == CitationRelationship.COMPETITOR.value)
                .group_by(cites.c.domain_id, CitationEntity.entity_name)
            )
        ).all()
        competitors: dict[uuid.UUID, dict[str, int]] = {}
        for domain_id, name, n in comp_rows:
            competitors.setdefault(domain_id, {})[name] = int(n)

        # top pages per domain (for the evidence)
        page_rows = (
            await self._session.execute(
                select(cites.c.domain_id, SourcePage.url, func.count().label("n"))
                .join(SourcePage, SourcePage.id == cites.c.page_id)
                .group_by(cites.c.domain_id, SourcePage.url)
                .order_by(func.count().desc())
            )
        ).all()
        top_pages: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for domain_id, url, n in page_rows:
            bucket = top_pages.setdefault(domain_id, [])
            if len(bucket) < 5:
                bucket.append({"url": url, "citations": int(n)})

        domains = {
            d.id: d
            for d in (
                await self._session.scalars(
                    select(SourceDomain).where(SourceDomain.id.in_(domain_ids))
                )
            ).all()
        }
        relevance = await self._relevance(domain_ids, domains)

        written = 0
        keep: set[uuid.UUID] = set()
        for r in per_domain:
            domain = domains[r.domain_id]
            stats = SourceStats(
                domain=domain.normalized_hostname,
                domain_type=domain.domain_type,
                source_relevance=relevance[r.domain_id]["score"],
                eligible_responses=int(eligible_responses),
                total_prompts=int(total_prompts),
                relevant_responses=int(r.relevant),
                prompts_citing=int(r.prompts),
                citations=int(r.citations),
                brand_citations=int(r.brand or 0),
                competitor_citations=int(r.competitor or 0),
                competitors=competitors.get(r.domain_id, {}),
                first_cited_at=r.first,
                last_cited_at=r.last,
                citations_first_half=int(r.first_half or 0),
                citations_second_half=int(r.second_half or 0),
                now=self._now,
                window_days=window_days,
            )
            gap_type = classify_gap(stats)
            confidence = confidence_for(stats)
            score = opportunity(stats, gap_type)
            await self._upsert(
                project_id,
                r.domain_id,
                gap_type=gap_type.value,
                stats=stats,
                confidence=confidence.value,
                score=score,
                explanation=explain(stats, gap_type, confidence),
                evidence={
                    **score,
                    "window_days": window_days,
                    "source_relevance": relevance[r.domain_id],
                    "top_pages": top_pages.get(r.domain_id, []),
                    "citations_first_half": stats.citations_first_half,
                    "citations_second_half": stats.citations_second_half,
                },
            )
            keep.add(r.domain_id)
            written += 1
        removed = await self._prune(project_id, keep=keep)
        await self._session.flush()
        log.info(
            "citation_gaps_analyzed",
            project_id=str(project_id),
            eligible_responses=int(eligible_responses),
            sources=len(domain_ids),
            written=written,
            removed=removed,
        )
        return AnalysisResult(
            project_id,
            window_days,
            int(eligible_responses),
            int(total_prompts),
            len(domain_ids),
            written,
            removed,
            self._now,
        )

    async def _relevance(
        self, domain_ids: list[uuid.UUID], domains: dict[uuid.UUID, SourceDomain]
    ) -> dict[uuid.UUID, dict[str, Any]]:
        """Global (cross-project, counts only) relevance inputs per domain."""
        rows = (
            await self._session.execute(
                select(
                    ResponseCitation.source_domain_id,
                    func.count(),
                    func.count(distinct(ResponseCitation.project_id)),
                    func.count(distinct(func.date_trunc("week", ResponseCitation.created_at))),
                )
                .where(ResponseCitation.source_domain_id.in_(domain_ids))
                .group_by(ResponseCitation.source_domain_id)
            )
        ).all()
        out: dict[uuid.UUID, dict[str, Any]] = {}
        for domain_id, n, projects, weeks in rows:
            d = domains[domain_id]
            weeks_since = max(1, (self._now - d.first_seen_at).days // 7 + 1)
            out[domain_id] = source_relevance(
                RelevanceInputs(
                    citation_count=int(n),
                    projects_observed=int(projects),
                    weeks_with_citations=int(weeks),
                    weeks_since_first_seen=weeks_since,
                    domain_type=d.domain_type,
                    is_authority=d.is_authority,
                )
            )
        return out

    async def _upsert(
        self,
        project_id: uuid.UUID,
        domain_id: uuid.UUID,
        *,
        gap_type: str,
        stats: SourceStats,
        confidence: str,
        score: dict[str, Any],
        explanation: str,
        evidence: dict[str, Any],
    ) -> None:
        gap = (
            await self._session.scalars(
                select(CitationGap).where(
                    and_(
                        CitationGap.project_id == project_id,
                        CitationGap.source_domain_id == domain_id,
                        CitationGap.source_page_id.is_(None),
                    )
                )
            )
        ).first()
        if gap is None:
            gap = CitationGap(
                project_id=project_id, source_domain_id=domain_id, analysis_version=ANALYSIS_VERSION
            )
            self._session.add(gap)
        gap.gap_type = gap_type
        gap.brand_citations = stats.brand_citations
        gap.competitor_citations = stats.competitor_citations
        gap.relevant_response_count = stats.relevant_responses
        gap.opportunity_score = float(score["score"])
        gap.confidence = confidence
        gap.explanation = explanation
        gap.competitors = dict(stats.competitors)
        gap.evidence = evidence
        gap.analysis_version = ANALYSIS_VERSION
        gap.analyzed_at = self._now

    async def _prune(self, project_id: uuid.UUID, *, keep: set[uuid.UUID]) -> int:
        stmt = delete(CitationGap).where(
            CitationGap.project_id == project_id,
            CitationGap.status == GapStatus.NEW.value,
        )
        if keep:
            stmt = stmt.where(CitationGap.source_domain_id.not_in(keep))
        result = await self._session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)
