"""Recommendation Engine: citation gaps (+ citation evidence) → reviewable recommendations.

Generation is idempotent: each recommendation has a stable `source_key`; a
re-run updates evidence/priority in place and keeps the human review status.
Recommendations still `new` whose basis disappeared are removed. Nothing is
ever executed — the output is a list for a person to approve, dismiss or start.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Integer, cast, delete, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.gaps import CitationGap, GapConfidence, GapType
from app.models.intelligence import ResponseCitation
from app.models.prompts import AiResponse, Prompt, PromptRun, PromptRunStatus
from app.models.recommendations import (
    Recommendation,
    RecommendationStatus,
    RecommendationType,
)
from app.models.sources import CitationEntity, CitationRelationship, SourceDomain
from app.recommendations import GENERATOR_VERSION
from app.recommendations.rules import (
    COMMERCIAL_CATEGORIES,
    COMMERCIAL_STAGES,
    GapFacts,
    ResearchFacts,
    citation_description,
    citation_explanation,
    citation_title,
    competitor_gap,
    is_recommendable,
    priority_for,
    research_confidence,
    research_explanation,
    research_is_warranted,
)

log = get_logger(__name__)

RESEARCH_PATH_HINTS = ("/research", "/report", "/study", "/whitepaper", "/survey", "/paper")


@dataclass
class GenerationResult:
    project_id: uuid.UUID
    generated: int
    removed: int
    skipped_insufficient: int
    research_considered: bool
    research_reasons: list[str]
    generated_at: datetime


class RecommendationEngine:
    def __init__(self, session: AsyncSession, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or datetime.now(UTC)

    async def generate(self, project_id: uuid.UUID) -> GenerationResult:
        gaps = (
            await self._session.scalars(
                select(CitationGap).where(CitationGap.project_id == project_id)
            )
        ).all()
        window_days = int((gaps[0].evidence.get("window_days") if gaps else None) or 90)
        commercial = await self._commercial_prompts_by_domain(project_id, window_days)

        domains = {
            d.id: d
            for d in (
                await self._session.scalars(
                    select(SourceDomain).where(
                        SourceDomain.id.in_([g.source_domain_id for g in gaps] or [uuid.uuid4()])
                    )
                )
            ).all()
        }
        keep: set[str] = set()
        generated = 0
        skipped = 0
        for gap in gaps:
            inputs = gap.evidence.get("inputs", {}) or {}
            domain = domains.get(gap.source_domain_id)
            if domain is None:
                continue
            facts = GapFacts(
                domain=domain.normalized_hostname,
                display_name=domain.display_name,
                source_type=str(inputs.get("domain_type", "unknown")),
                gap_type=GapType(gap.gap_type),
                opportunity_score=gap.opportunity_score,
                confidence=GapConfidence(gap.confidence),
                brand_citations=gap.brand_citations,
                competitor_citations=gap.competitor_citations,
                competitors=dict(gap.competitors),
                relevant_responses=gap.relevant_response_count,
                eligible_responses=int(inputs.get("eligible_responses", 0)),
                prompts_citing=int(inputs.get("prompts_citing", 0)),
                total_prompts=int(inputs.get("total_prompts", 0)),
                source_relevance=float(inputs.get("source_relevance", 0.0)),
                commercial_prompts=commercial.get(gap.source_domain_id, 0),
                top_pages=list(gap.evidence.get("top_pages", []) or []),
                window_days=window_days,
            )
            if not is_recommendable(facts):
                if facts.confidence is GapConfidence.INSUFFICIENT:
                    skipped += 1
                continue
            key = f"citation:gap:{facts.domain}"
            priority, pscore = priority_for(facts)
            await self._upsert(
                project_id,
                key,
                rec_type=RecommendationType.CITATION,
                citation_gap_id=gap.id,
                title=citation_title(facts),
                description=citation_description(facts),
                explanation=citation_explanation(facts),
                evidence={
                    "relevant_prompt_count": facts.prompts_citing,
                    "total_prompts": facts.total_prompts,
                    "competitor_citation_count": facts.competitor_citations,
                    "brand_citation_count": facts.brand_citations,
                    "competitors": facts.competitors,
                    "relevant_responses": facts.relevant_responses,
                    "eligible_responses": facts.eligible_responses,
                    "source_relevance": facts.source_relevance,
                    "source_type": facts.source_type,
                    "gap_type": facts.gap_type.value,
                    "confidence": facts.confidence.value,
                    "competitor_gap": round(
                        competitor_gap(facts.brand_citations, facts.competitor_citations), 3
                    ),
                    "business_relevance": round(facts.commercial_prompts / facts.prompts_citing, 3)
                    if facts.prompts_citing
                    else 0.0,
                    "commercial_prompts": facts.commercial_prompts,
                    "priority_score": pscore,
                    "top_pages": facts.top_pages,
                    "window_days": window_days,
                    "citation_gap_id": str(gap.id),
                },
                priority=priority.value,
                opportunity_score=gap.opportunity_score,
                confidence=facts.confidence.value,
            )
            keep.add(key)
            generated += 1

        research = await self._research_facts(project_id, window_days)
        warranted, reasons = research_is_warranted(research)
        if warranted:
            confidence = research_confidence(research)
            # Priority from the strength of the evidence (capped by confidence in priority_for).
            share = (
                research.commercial_prompts / research.prompts_citing
                if research.prompts_citing
                else 0
            )
            score = min(
                100.0,
                20.0 * min(5, research.competitor_research_citations) * (0.6 + 0.4 * share),
            )
            facts_for_priority = GapFacts(
                domain="research",
                display_name="research",
                source_type="research",
                gap_type=GapType.BRAND_ABSENT,
                opportunity_score=score,
                confidence=confidence,
                brand_citations=research.brand_research_citations,
                competitor_citations=research.competitor_research_citations,
                competitors=research.competitors,
                relevant_responses=research.research_responses,
                eligible_responses=research.eligible_responses,
                prompts_citing=research.prompts_citing,
                total_prompts=research.prompts_citing,
                source_relevance=85.0,
                commercial_prompts=research.commercial_prompts,
            )
            priority, pscore = priority_for(facts_for_priority)
            key = "content:original-research"
            await self._upsert(
                project_id,
                key,
                rec_type=RecommendationType.CONTENT,
                citation_gap_id=None,
                title="Create original research",
                description=(
                    "Competitors are cited from research, reports and studies in relevant AI "
                    "answers while the brand is not. Original, verifiable research on the topics "
                    "these prompts ask about could give AI engines evidence that mentions you."
                ),
                explanation=research_explanation(research, confidence),
                evidence={
                    "competitor_research_citations": research.competitor_research_citations,
                    "brand_research_citations": research.brand_research_citations,
                    "research_responses": research.research_responses,
                    "research_sources": research.research_sources,
                    "competitors": research.competitors,
                    "commercial_prompts": research.commercial_prompts,
                    "prompts_citing": research.prompts_citing,
                    "eligible_responses": research.eligible_responses,
                    "conditions": {
                        "competitors_cited_for_research": True,
                        "brand_content_gap": True,
                        "commercially_relevant": True,
                    },
                    "confidence": confidence.value,
                    "priority_score": pscore,
                    "window_days": window_days,
                },
                priority=priority.value,
                opportunity_score=round(score, 1),
                confidence=confidence.value,
            )
            keep.add(key)
            generated += 1

        removed = await self._prune(project_id, keep)
        await self._session.flush()
        log.info(
            "recommendations_generated",
            project_id=str(project_id),
            generated=generated,
            removed=removed,
            skipped_insufficient=skipped,
            research=warranted,
        )
        return GenerationResult(
            project_id, generated, removed, skipped, warranted, reasons, self._now
        )

    # -- evidence queries ------------------------------------------------------------------

    def _eligible(self, project_id: uuid.UUID, window_days: int) -> Any:
        start = self._now - timedelta(days=window_days)
        return (
            select(
                AiResponse.id.label("response_id"),
                PromptRun.prompt_id.label("prompt_id"),
            )
            .join(PromptRun, PromptRun.id == AiResponse.prompt_run_id)
            .where(
                PromptRun.project_id == project_id,
                PromptRun.status == PromptRunStatus.COMPLETED,
                AiResponse.parser_version.is_not(None),
                PromptRun.completed_at >= start,
                PromptRun.completed_at < self._now,
            )
            .subquery("eligible")
        )

    @staticmethod
    def _is_commercial() -> Any:
        return or_(
            Prompt.category.in_(list(COMMERCIAL_CATEGORIES)),
            Prompt.funnel_stage.in_(list(COMMERCIAL_STAGES)),
        )

    async def _commercial_prompts_by_domain(
        self, project_id: uuid.UUID, window_days: int
    ) -> dict[uuid.UUID, int]:
        """Distinct commercial prompts whose responses cite each source domain."""
        eligible = self._eligible(project_id, window_days)
        rows = (
            await self._session.execute(
                select(
                    ResponseCitation.source_domain_id,
                    func.count(distinct(eligible.c.prompt_id)),
                )
                .join(eligible, eligible.c.response_id == ResponseCitation.ai_response_id)
                .join(Prompt, Prompt.id == eligible.c.prompt_id)
                .where(
                    ResponseCitation.project_id == project_id,
                    ResponseCitation.source_domain_id.is_not(None),
                    self._is_commercial(),
                )
                .group_by(ResponseCitation.source_domain_id)
            )
        ).all()
        return {d: int(n) for d, n in rows}

    async def _research_facts(self, project_id: uuid.UUID, window_days: int) -> ResearchFacts:
        """Citations to research-type sources (domain type `research`, or a
        research-looking path) with brand/competitor relationships."""
        eligible = self._eligible(project_id, window_days)
        path_hint = or_(*[ResponseCitation.url.ilike(f"%{h}%") for h in RESEARCH_PATH_HINTS])
        research = (
            select(
                ResponseCitation.id.label("cid"),
                ResponseCitation.source_domain_id.label("domain_id"),
                eligible.c.response_id,
                eligible.c.prompt_id,
            )
            .join(eligible, eligible.c.response_id == ResponseCitation.ai_response_id)
            .join(SourceDomain, SourceDomain.id == ResponseCitation.source_domain_id)
            .where(
                ResponseCitation.project_id == project_id,
                or_(SourceDomain.domain_type == "research", path_hint),
            )
            .subquery("research")
        )
        rel = (
            select(
                CitationEntity.citation_id.label("cid"),
                CitationEntity.entity_name,
                CitationEntity.relationship,
            )
            .where(CitationEntity.project_id == project_id)
            .subquery("rel")
        )
        totals = (
            await self._session.execute(
                select(
                    func.count(distinct(research.c.response_id)),
                    func.count(distinct(research.c.prompt_id)),
                    func.coalesce(
                        func.sum(
                            cast(rel.c.relationship == CitationRelationship.BRAND.value, Integer)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(
                            cast(
                                rel.c.relationship == CitationRelationship.COMPETITOR.value,
                                Integer,
                            )
                        ),
                        0,
                    ),
                )
                .select_from(research)
                .outerjoin(rel, rel.c.cid == research.c.cid)
            )
        ).one()
        comp_rows = (
            await self._session.execute(
                select(rel.c.entity_name, func.count())
                .join(research, research.c.cid == rel.c.cid)
                .where(rel.c.relationship == CitationRelationship.COMPETITOR.value)
                .group_by(rel.c.entity_name)
            )
        ).all()
        src_rows = (
            await self._session.execute(
                select(SourceDomain.normalized_hostname, func.count())
                .join(research, research.c.domain_id == SourceDomain.id)
                .group_by(SourceDomain.normalized_hostname)
                .order_by(func.count().desc())
                .limit(5)
            )
        ).all()
        commercial = (
            await self._session.scalar(
                select(func.count(distinct(research.c.prompt_id)))
                .select_from(research)
                .join(Prompt, Prompt.id == research.c.prompt_id)
                .where(self._is_commercial())
            )
            or 0
        )
        eligible_total = await self._session.scalar(select(func.count()).select_from(eligible)) or 0
        return ResearchFacts(
            competitor_research_citations=int(totals[3]),
            brand_research_citations=int(totals[2]),
            research_responses=int(totals[0]),
            research_sources=[{"domain": d, "citations": int(n)} for d, n in src_rows],
            commercial_prompts=int(commercial),
            prompts_citing=int(totals[1]),
            competitors={name: int(n) for name, n in comp_rows},
            eligible_responses=int(eligible_total),
            window_days=window_days,
        )

    # -- persistence ---------------------------------------------------------------------------

    async def _upsert(
        self,
        project_id: uuid.UUID,
        source_key: str,
        *,
        rec_type: RecommendationType,
        citation_gap_id: uuid.UUID | None,
        title: str,
        description: str,
        explanation: dict[str, str],
        evidence: dict[str, Any],
        priority: str,
        opportunity_score: float,
        confidence: str,
    ) -> Recommendation:
        rec = (
            await self._session.scalars(
                select(Recommendation).where(
                    Recommendation.project_id == project_id,
                    Recommendation.source_key == source_key,
                )
            )
        ).first()
        if rec is None:
            rec = Recommendation(
                project_id=project_id,
                source_key=source_key,
                recommendation_type=rec_type.value,
                generator_version=GENERATOR_VERSION,
                generated_at=self._now,
            )
            self._session.add(rec)
        rec.recommendation_type = rec_type.value
        rec.citation_gap_id = citation_gap_id
        rec.title = title
        rec.description = description
        rec.explanation = explanation
        rec.evidence = evidence
        rec.priority = priority
        rec.opportunity_score = opportunity_score
        rec.confidence = confidence
        rec.generator_version = GENERATOR_VERSION
        rec.generated_at = self._now
        return rec

    async def _prune(self, project_id: uuid.UUID, keep: set[str]) -> int:
        stmt = delete(Recommendation).where(
            Recommendation.project_id == project_id,
            Recommendation.status == RecommendationStatus.NEW.value,
        )
        if keep:
            stmt = stmt.where(Recommendation.source_key.not_in(keep))
        result = await self._session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)
