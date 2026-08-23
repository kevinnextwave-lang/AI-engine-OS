"""Why Competitors Win: gather facts from the response/citation graph, run the
pure analyzers, persist `competitive_insights`.

Everything compared here is observed data: parsed responses, their citations
(with `citation_entities` attribution), source-domain classifications, claims
and the brand's own crawled structured data. Competitor websites are NOT
crawled; the entity-clarity analyzer therefore only reports brand-side gaps as
potential contributing factors.
"""

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.competitive.metrics import BRAND, compute_all
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.insights import ANALYSIS_VERSION
from app.insights.analyzers import (
    MIN_RESPONSES,
    BrandProfile,
    CompetitorFacts,
    EntitySignals,
    Insight,
    analyze_competitor,
)
from app.models.competitor import Competitor
from app.models.crawl import WebsitePage
from app.models.entities import Entity, EntityLink, SchemaIssue
from app.models.insights import CompetitiveInsight
from app.models.intelligence import ResponseCitation, ResponseClaim
from app.models.project import Project
from app.models.prompts import AiResponse, PromptRun, PromptRunStatus
from app.models.sources import CitationEntity, CitationEntityType, SourceDomain
from app.sources.normalize import normalize_hostname
from app.visibility.observations import load_observations

log = get_logger(__name__)

DEFAULT_WINDOW_DAYS = 90

# Cited-URL path patterns → content category. Conservative on purpose.
PAGE_CATEGORIES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "comparison",
        re.compile(r"(?:^|[/-])(?:vs|versus|compare|comparison|alternatives?)(?:$|[/-])"),
    ),
    ("faq", re.compile(r"faq|help|support|docs|documentation|questions")),
    ("use_case", re.compile(r"use-?cases?|customers?|case-stud|success|stories")),
    ("educational", re.compile(r"guide|how-to|howto|learn|tutorial|academy|blog|resources")),
    ("product", re.compile(r"product|pricing|features?|plans|integrations?")),
)
_SPECIFIC = re.compile(r"\d")


def categorize_url(url: str | None) -> str | None:
    if not url:
        return None
    path = url.lower()
    for name, pattern in PAGE_CATEGORIES:
        if pattern.search(path):
            return name
    return None


@dataclass
class InsightAnalysisResult:
    project_id: uuid.UUID
    window_days: int
    eligible_responses: int
    competitors_analyzed: int
    insights_written: int
    insights_removed: int
    analyzed_at: datetime
    note: str


class CompetitiveInsightEngine:
    def __init__(self, session: AsyncSession, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or datetime.now(UTC)

    async def analyze(
        self, project_id: uuid.UUID, *, window_days: int = DEFAULT_WINDOW_DAYS
    ) -> InsightAnalysisResult:
        project = await self._session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        start = self._now - timedelta(days=window_days)
        data = await load_observations(self._session, project_id, start=start, end=self._now)
        obs = data.observations
        competitors = (
            await self._session.scalars(
                select(Competitor).where(Competitor.project_id == project_id)
            )
        ).all()
        rows = {r.name: r for r in compute_all(obs, data.competitor_names)}
        citation_signals = await self._citation_signals(project_id, data.brand_domains, start)
        claim_signals = await self._claim_signals(project_id, project.name, competitors, start)
        brand_profile = await self._brand_profile(project_id)

        written = removed = 0
        for competitor in competitors:
            facts = self._facts(
                project,
                competitor,
                rows,
                citation_signals,
                claim_signals,
                obs_count=len(obs),
                prompt_total=len({o.prompt_id for o in obs}),
                window_days=window_days,
                brand_profile=brand_profile,
            )
            insights = analyze_competitor(facts)
            w, r = await self._persist(project_id, competitor.id, insights)
            written += w
            removed += r
        await self._session.flush()
        note = (
            "Insights describe observed patterns and potential contributing factors, "
            "never causation."
        )
        if len(obs) < MIN_RESPONSES:
            note = (
                f"Fewer than {MIN_RESPONSES} eligible responses in the window — "
                "no insights are produced from this little evidence. " + note
            )
        log.info(
            "competitive_insights_analyzed",
            project_id=str(project_id),
            eligible_responses=len(obs),
            competitors=len(competitors),
            written=written,
            removed=removed,
        )
        return InsightAnalysisResult(
            project_id=project_id,
            window_days=window_days,
            eligible_responses=len(obs),
            competitors_analyzed=len(competitors),
            insights_written=written,
            insights_removed=removed,
            analyzed_at=self._now,
            note=note,
        )

    # -- fact gathering ----------------------------------------------------------------

    def _facts(
        self,
        project: Project,
        competitor: Competitor,
        rows: dict[str, Any],
        citation_signals: dict[str, EntitySignals],
        claim_signals: dict[str, tuple[int, int, list[str]]],
        *,
        obs_count: int,
        prompt_total: int,
        window_days: int,
        brand_profile: BrandProfile,
    ) -> CompetitorFacts:
        def signals(key: str, display: str) -> EntitySignals:
            sig = citation_signals.get(key, EntitySignals(name=display))
            sig.name = display
            metrics = rows.get(key if key == BRAND else display)
            if metrics is not None:
                sig.responses_mentioning = metrics.mentions
                sig.mention_share = metrics.mention_share
                sig.recommendation_share = metrics.recommendation_share
                sig.average_position = metrics.average_position
                sig.sentiment_score = metrics.sentiment_score
                sig.prompt_coverage = metrics.prompts_appearing
            claims, specific, examples = claim_signals.get(key, (0, 0, []))
            sig.claims = claims
            sig.claims_with_specifics = specific
            sig.claim_examples = examples
            return sig

        brand_metrics = rows.get(BRAND)
        comp_metrics = rows.get(competitor.name)
        gap = (
            comp_metrics.score - brand_metrics.score
            if brand_metrics is not None
            and comp_metrics is not None
            and brand_metrics.score is not None
            and comp_metrics.score is not None
            else None
        )
        return CompetitorFacts(
            competitor_name=competitor.name,
            sample_size=obs_count,
            total_prompts=prompt_total,
            window_days=window_days,
            brand=signals(BRAND, project.name),
            competitor=signals(competitor.name, competitor.name),
            brand_profile=brand_profile,
            visibility_gap=round(gap, 1) if gap is not None else None,
        )

    async def _citation_signals(
        self, project_id: uuid.UUID, brand_domains: list[str], start: datetime
    ) -> dict[str, EntitySignals]:
        """Citation footprint per entity key (BRAND or competitor name) from the
        window's citations, their `citation_entities` rows and the cited hosts."""
        rows = (
            await self._session.execute(
                select(ResponseCitation)
                .join(AiResponse, AiResponse.id == ResponseCitation.ai_response_id)
                .join(PromptRun, PromptRun.id == AiResponse.prompt_run_id)
                .where(
                    PromptRun.project_id == project_id,
                    PromptRun.status == PromptRunStatus.COMPLETED,
                    PromptRun.completed_at >= start,
                    AiResponse.parser_version.is_not(None),
                )
            )
        ).scalars()
        citations = list(rows)
        entity_rows: dict[uuid.UUID, list[CitationEntity]] = {}
        if citations:
            for ce in (
                await self._session.scalars(
                    select(CitationEntity).where(
                        CitationEntity.citation_id.in_([c.id for c in citations])
                    )
                )
            ).all():
                entity_rows.setdefault(ce.citation_id, []).append(ce)
        hosts = {h for c in citations if (h := _host_of(c)) is not None}
        domain_types: dict[str, tuple[str, bool]] = {}
        if hosts:
            for d in (
                await self._session.scalars(
                    select(SourceDomain).where(SourceDomain.normalized_hostname.in_(hosts))
                )
            ).all():
                domain_types[d.normalized_hostname] = (d.domain_type, d.is_authority)

        comp_names = {}
        for ce_list in entity_rows.values():
            for ce in ce_list:
                if ce.entity_type == CitationEntityType.COMPETITOR.value:
                    comp_names[ce.entity_name] = ce.entity_name

        out: dict[str, EntitySignals] = {}

        def sig(key: str) -> EntitySignals:
            return out.setdefault(key, EntitySignals(name=key))

        brand_hosts = set(brand_domains)
        for c in citations:
            host = _host_of(c)
            keys: set[str] = set()
            for ce in entity_rows.get(c.id, []):
                if ce.entity_type == CitationEntityType.PROJECT.value:
                    keys.add(BRAND)
                elif ce.entity_type == CitationEntityType.COMPETITOR.value:
                    keys.add(ce.entity_name)
            if host and any(host == d or host.endswith("." + d) for d in brand_hosts if d):
                keys.add(BRAND)
            if not keys:
                continue
            dtype, authority = domain_types.get(host or "", ("unknown", False))
            category = categorize_url(c.url)
            for key in keys:
                s = sig(key)
                s.citations += 1
                if host:
                    s.citing_domains.add(host)
                    s.domains_by_type.setdefault(dtype, set()).add(host)
                    if authority:
                        s.authority_domains.add(host)
                    if dtype == "research":
                        s.research_domains.add(host)
                        s.research_citations += 1
                if category and c.url:
                    s.cited_pages.setdefault(category, set()).add(c.url)
        return out

    async def _claim_signals(
        self,
        project_id: uuid.UUID,
        brand_name: str,
        competitors: Sequence[Competitor],
        start: datetime,
    ) -> dict[str, tuple[int, int, list[str]]]:
        """(claims, claims with specifics, examples) per entity key from window claims."""
        claims = (
            await self._session.scalars(
                select(ResponseClaim)
                .join(AiResponse, AiResponse.id == ResponseClaim.ai_response_id)
                .join(PromptRun, PromptRun.id == AiResponse.prompt_run_id)
                .where(
                    PromptRun.project_id == project_id,
                    PromptRun.status == PromptRunStatus.COMPLETED,
                    PromptRun.completed_at >= start,
                )
            )
        ).all()
        keys = [(BRAND, brand_name.lower())] + [(c.name, c.name.lower()) for c in competitors]
        out: dict[str, tuple[int, int, list[str]]] = {}
        for key, needle in keys:
            total = specific = 0
            examples: list[str] = []
            for claim in claims:
                if needle not in claim.subject.lower():
                    continue
                total += 1
                if _SPECIFIC.search(claim.object) or _SPECIFIC.search(claim.context):
                    specific += 1
                    if len(examples) < 5:
                        examples.append(f"{claim.subject} {claim.predicate} {claim.object}"[:200])
            out[key] = (total, specific, examples)
        return out

    async def _brand_profile(self, project_id: uuid.UUID) -> BrandProfile:
        profile = BrandProfile()
        profile.pages_crawled = len(
            (
                await self._session.scalars(
                    select(WebsitePage.id).where(WebsitePage.project_id == project_id)
                )
            ).all()
        )
        entities = (
            await self._session.scalars(select(Entity).where(Entity.project_id == project_id))
        ).all()
        for e in entities:
            etype = (e.entity_type or "").lower()
            if etype in ("organization", "brand", "corporation", "localbusiness"):
                profile.has_organization_schema = True
                if e.name:
                    profile.organization_names.add(e.name.strip())
                if e.description:
                    profile.has_description = True
                profile.sameas_links += len(e.same_as or [])
            if etype in ("product", "softwareapplication", "service"):
                profile.product_schema_count += 1
        profile.sameas_links += len(
            (
                await self._session.scalars(
                    select(EntityLink.id).where(EntityLink.project_id == project_id)
                )
            ).all()
        )
        profile.schema_issues = len(
            (
                await self._session.scalars(
                    select(SchemaIssue.id).where(SchemaIssue.project_id == project_id)
                )
            ).all()
        )
        return profile

    # -- persistence -------------------------------------------------------------------

    async def _persist(
        self, project_id: uuid.UUID, competitor_id: uuid.UUID, insights: list[Insight]
    ) -> tuple[int, int]:
        existing = {
            row.insight_type: row
            for row in (
                await self._session.scalars(
                    select(CompetitiveInsight).where(
                        CompetitiveInsight.project_id == project_id,
                        CompetitiveInsight.competitor_id == competitor_id,
                    )
                )
            ).all()
        }
        produced = {i.insight_type.value for i in insights}
        stale = [t for t in existing if t not in produced]
        if stale:
            await self._session.execute(
                delete(CompetitiveInsight).where(
                    CompetitiveInsight.project_id == project_id,
                    CompetitiveInsight.competitor_id == competitor_id,
                    CompetitiveInsight.insight_type.in_(stale),
                )
            )
        for insight in insights:
            row = existing.get(insight.insight_type.value)
            if row is None:
                row = CompetitiveInsight(
                    project_id=project_id,
                    competitor_id=competitor_id,
                    insight_type=insight.insight_type.value,
                )
                self._session.add(row)
            row.title = insight.title
            row.description = insight.description
            row.evidence = insight.evidence
            row.confidence = insight.confidence.value
            row.impact = insight.impact.value
            row.strength = round(insight.strength, 1)
            row.analysis_version = ANALYSIS_VERSION
            row.window_days = insight.evidence.get("window_days", DEFAULT_WINDOW_DAYS)
            row.analyzed_at = self._now
        return len(insights), len(stale)


def _host_of(citation: ResponseCitation) -> str | None:
    if citation.domain:
        try:
            return normalize_hostname(citation.domain)
        except ValueError:
            return None
    if citation.url:
        from urllib.parse import urlsplit

        try:
            return normalize_hostname(urlsplit(citation.url).hostname)
        except ValueError:
            return None
    return None
