"""Controlled tool registry: the ONLY way agents read project data.

Security model:
* every tool is a fixed, parameterized query bound to one project — an agent
  can never reach another tenant's rows, construct SQL, or touch the session;
* inputs are validated against each tool's pydantic schema;
* outputs are capped (limits clamped server-side) and reduced to plain dicts;
* free-text fields that originate outside the platform (page content, AI
  response text, anchor text…) are marked untrusted by the callers that render
  prompts (see prompting.py);
* every call is logged (structlog) and recorded on the toolbox for the run's
  evidence trail.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.competitor import Competitor
from app.models.content_gaps import ContentGap
from app.models.crawl import WebsitePage
from app.models.entities import Entity
from app.models.gaps import CitationGap
from app.models.intelligence import ResponseCitation
from app.models.project import Project
from app.models.prompts import AiResponse, Prompt, PromptRun, PromptRunStatus
from app.models.sources import SourceDomain

log = get_logger(__name__)

MAX_LIMIT = 50
TEXT_CAP = 4000  # characters of untrusted free text per item


class ToolError(Exception):
    """Invalid tool name or arguments. Never carries another tenant's data."""


class _Empty(BaseModel):
    pass


class _Paged(BaseModel):
    limit: int = Field(default=20, ge=1, le=MAX_LIMIT)
    offset: int = Field(default=0, ge=0, le=10_000)


class _PageArg(BaseModel):
    page_id: uuid.UUID


class _ChangeInput(BaseModel):
    location: str = Field(min_length=1, max_length=200)
    current_text: str = Field(max_length=2000)
    proposed_text: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=3, max_length=1000)
    evidence: dict[str, Any] = Field(default_factory=dict)
    confidence: str = Field(default="low", pattern="^(high|medium|low)$")


class _ReviewInput(BaseModel):
    page_id: uuid.UUID
    score: float = Field(ge=0, le=100)
    findings: list[dict[str, Any]] = Field(default_factory=list, max_length=40)
    recommendations: list[dict[str, Any]] = Field(default_factory=list, max_length=40)
    proposed_changes: list[dict[str, Any]] = Field(default_factory=list, max_length=40)
    confidence: str = Field(default="low", pattern="^(high|medium|low)$")
    analysis_version: str = Field(default="content-optimization/v1", max_length=40)

    @classmethod
    def _validate_changes(cls, changes: list[dict[str, Any]]) -> None:
        for c in changes:
            _ChangeInput(**c)

    def model_post_init(self, __context: Any) -> None:
        self._validate_changes(self.proposed_changes)


class _BriefInput(BaseModel):
    """Schema for the framework's only write tool. Everything is validated and
    the row is always project-scoped; status starts 'draft' and an existing
    brief's review status is never touched by a re-save."""

    source_key: str = Field(min_length=3, max_length=200)
    title: str = Field(min_length=3, max_length=300)
    content_type: str
    objective: str = Field(min_length=3, max_length=4000)
    search_intent: str = Field(default="", max_length=4000)
    audience: str = Field(default="", max_length=2000)
    differentiation: str = Field(default="", max_length=4000)
    target_prompt_ids: list[uuid.UUID] = Field(default_factory=list, max_length=25)
    competitor_ids: list[uuid.UUID] = Field(default_factory=list, max_length=25)
    outline: dict[str, Any] = Field(default_factory=dict)
    information_requirements: list[str] = Field(default_factory=list, max_length=30)
    evidence_requirements: dict[str, Any] = Field(default_factory=dict)
    citation_opportunities: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    entity_requirements: list[str] = Field(default_factory=list, max_length=20)
    internal_link_recommendations: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    confidence: str = Field(default="low", pattern="^(high|medium|low)$")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    params: type[BaseModel]
    handler: Callable[["ToolBox", Any], Awaitable[Any]]

    @property
    def schema(self) -> dict[str, Any]:
        return self.params.model_json_schema()


@dataclass
class ToolCall:
    tool: str
    params: dict[str, Any]
    items: int


def _clip(value: str | None, cap: int = TEXT_CAP) -> str | None:
    if value is None:
        return None
    return value if len(value) <= cap else value[:cap] + "…[truncated]"


class ToolBox:
    """Tools bound to one session + one project. Handed to agents via context."""

    def __init__(self, session: AsyncSession, project: Project) -> None:
        self._session = session
        self._project = project
        self.usage: list[ToolCall] = []
        # Set by the orchestrator so write tools can record provenance.
        self.agent_run_id: uuid.UUID | None = None

    @property
    def project_id(self) -> uuid.UUID:
        return self._project.id

    def available(self) -> list[dict[str, Any]]:
        return [
            {"name": s.name, "description": s.description, "schema": s.schema}
            for s in TOOLS.values()
        ]

    async def call(self, name: str, **params: Any) -> Any:
        spec = TOOLS.get(name)
        if spec is None:
            raise ToolError(f"Unknown tool '{name}'")
        try:
            validated = spec.params(**params)
        except ValidationError as exc:
            raise ToolError(
                f"Invalid arguments for tool '{name}': {exc.error_count()} errors"
            ) from exc
        result = await spec.handler(self, validated)
        items = len(result) if isinstance(result, list) else 1
        self.usage.append(
            ToolCall(tool=name, params=validated.model_dump(mode="json"), items=items)
        )
        log.info(
            "agent_tool_call",
            tool=name,
            project_id=str(self._project.id),
            items=items,
        )
        return result


# --- handlers (fixed queries, project-scoped, capped) -----------------------------------


async def _get_project(box: ToolBox, _: _Empty) -> dict[str, Any]:
    from app.models.domain import Domain

    p = box._project
    hosts = (
        await box._session.scalars(select(Domain.hostname).where(Domain.project_id == p.id))
    ).all()
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description,
        "industry": p.industry,
        "domains": list(hosts)[:10],
    }


async def _get_pages(box: ToolBox, params: _Paged) -> list[dict[str, Any]]:
    rows = (
        await box._session.scalars(
            select(WebsitePage)
            .where(WebsitePage.project_id == box.project_id, WebsitePage.http_status < 400)
            .order_by(WebsitePage.last_crawled_at.desc())
            .limit(params.limit)
            .offset(params.offset)
        )
    ).all()
    return [
        {
            "id": str(r.id),
            "url": r.url,
            "title": _clip(r.title, 300),
            "meta_description": _clip(r.meta_description, 500),
            "word_count": r.word_count,
        }
        for r in rows
    ]


async def _get_page(box: ToolBox, params: _PageArg) -> dict[str, Any]:
    row = (
        await box._session.scalars(
            select(WebsitePage).where(
                WebsitePage.id == params.page_id, WebsitePage.project_id == box.project_id
            )
        )
    ).one_or_none()
    if row is None:
        raise ToolError("Page not found in this project")
    return {
        "id": str(row.id),
        "url": row.url,
        "title": _clip(row.title, 300),
        "meta_description": _clip(row.meta_description, 500),
        "word_count": row.word_count,
        "language": row.language,
        "http_status": row.http_status,
    }


async def _get_competitors(box: ToolBox, params: _Paged) -> list[dict[str, Any]]:
    rows = (
        await box._session.scalars(
            select(Competitor)
            .where(Competitor.project_id == box.project_id)
            .order_by(Competitor.created_at)
            .limit(params.limit)
            .offset(params.offset)
        )
    ).all()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "domain": r.hostname,
            "status": r.status,
            "source": r.source,
        }
        for r in rows
    ]


async def _get_prompts(box: ToolBox, params: _Paged) -> list[dict[str, Any]]:
    rows = (
        await box._session.scalars(
            select(Prompt)
            .where(Prompt.project_id == box.project_id)
            .order_by(Prompt.created_at)
            .limit(params.limit)
            .offset(params.offset)
        )
    ).all()
    return [
        {
            "id": str(r.id),
            "text": _clip(r.text, 500),
            "category": r.category.value,
            "funnel_stage": r.funnel_stage.value,
        }
        for r in rows
    ]


async def _get_ai_responses(box: ToolBox, params: _Paged) -> list[dict[str, Any]]:
    rows = (
        await box._session.execute(
            select(AiResponse, PromptRun)
            .join(PromptRun, PromptRun.id == AiResponse.prompt_run_id)
            .where(
                PromptRun.project_id == box.project_id,
                PromptRun.status == PromptRunStatus.COMPLETED,
            )
            .order_by(PromptRun.completed_at.desc())
            .limit(params.limit)
            .offset(params.offset)
        )
    ).all()
    return [
        {
            "id": str(resp.id),
            "prompt_id": str(run.prompt_id),
            "provider": run.provider_key,
            "model": run.model_key,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            # AI output is untrusted data; prompting.py wraps it accordingly.
            "response_text": _clip(resp.response_text),
        }
        for resp, run in rows
    ]


async def _get_citations(box: ToolBox, params: _Paged) -> list[dict[str, Any]]:
    rows = (
        await box._session.scalars(
            select(ResponseCitation)
            .where(ResponseCitation.project_id == box.project_id)
            .order_by(ResponseCitation.created_at.desc())
            .limit(params.limit)
            .offset(params.offset)
        )
    ).all()
    return [
        {
            "id": str(r.id),
            "url": _clip(r.url, 500),
            "domain": r.domain,
            "citation_type": r.citation_type,
            "anchor_text": _clip(r.anchor_text, 200),
        }
        for r in rows
    ]


async def _get_citation_gaps(box: ToolBox, params: _Paged) -> list[dict[str, Any]]:
    rows = (
        await box._session.execute(
            select(CitationGap, SourceDomain)
            .join(SourceDomain, SourceDomain.id == CitationGap.source_domain_id)
            .where(CitationGap.project_id == box.project_id)
            .order_by(CitationGap.opportunity_score.desc())
            .limit(params.limit)
            .offset(params.offset)
        )
    ).all()
    return [
        {
            "id": str(gap.id),
            "domain": domain.normalized_hostname,
            "gap_type": gap.gap_type,
            "opportunity_score": gap.opportunity_score,
            "confidence": gap.confidence,
            "brand_citations": gap.brand_citations,
            "competitor_citations": gap.competitor_citations,
            "status": gap.status,
        }
        for gap, domain in rows
    ]


async def _get_content_gaps(box: ToolBox, params: _Paged) -> list[dict[str, Any]]:
    rows = (
        await box._session.scalars(
            select(ContentGap)
            .where(ContentGap.project_id == box.project_id)
            .order_by(ContentGap.opportunity_score.desc())
            .limit(params.limit)
            .offset(params.offset)
        )
    ).all()
    return [
        {
            "id": str(r.id),
            "topic": r.topic,
            "gap_type": r.gap_type,
            "opportunity_score": r.opportunity_score,
            "confidence": r.confidence,
            "status": r.status,
            # selected evidence fields (platform-derived, bounded)
            "prompt": _clip((r.competitor_evidence or {}).get("prompt"), 300),
            "prompt_id": (r.competitor_evidence or {}).get("prompt_id"),
            "top_competitor": (r.competitor_evidence or {}).get("top_competitor"),
            "top_competitor_rate": (r.competitor_evidence or {}).get("top_competitor_rate"),
            "brand_mention_rate": (r.competitor_evidence or {}).get("brand_mention_rate"),
            "providers": (r.competitor_evidence or {}).get("providers") or [],
            "research_domains": (r.competitor_evidence or {}).get("research_domains") or [],
        }
        for r in rows
    ]


async def _get_entity_data(box: ToolBox, params: _Paged) -> list[dict[str, Any]]:
    rows = (
        await box._session.scalars(
            select(Entity)
            .where(Entity.project_id == box.project_id)
            .order_by(Entity.created_at)
            .limit(params.limit)
            .offset(params.offset)
        )
    ).all()
    return [
        {
            "id": str(r.id),
            "entity_type": r.entity_type,
            "name": _clip(r.name, 300),
            "description": _clip(r.description, 500),
            "same_as": (r.same_as or [])[:10],
        }
        for r in rows
    ]


async def _get_competitive_visibility(box: ToolBox, _: _Empty) -> dict[str, Any]:
    """Brand vs configured competitors (5C): compact entities + advantages."""
    from app.competitive.engine import CompetitiveVisibilityEngine

    overview = await CompetitiveVisibilityEngine(box._session).overview(box.project_id)
    return {
        "window": overview.get("window"),
        "entities": [
            {
                "name": e["name"],
                "is_brand": e["is_brand"],
                "score": e["score"],
                "mention_share": e["mention_share"],
                "recommendation_share": e["recommendation_share"],
                "citation_share": e["citation_share"],
                "prompt_coverage": e["prompt_coverage"],
                "sufficiency": e["sufficiency"],
            }
            for e in overview.get("entities", [])
        ],
        "advantages": [
            {
                "competitor": a["competitor"],
                "advantage": a["advantage"],
                "material": a["material"],
                "where_they_win": a["where_they_win"],
            }
            for a in overview.get("advantages", [])
        ],
        "data_quality": {
            "sample_size": overview.get("data_quality", {}).get("sample_size"),
            "confidence": overview.get("data_quality", {}).get("confidence"),
        },
    }


async def _get_competitive_insights(box: ToolBox, params: _Paged) -> list[dict[str, Any]]:
    from app.models.insights import CompetitiveInsight

    rows = (
        await box._session.scalars(
            select(CompetitiveInsight)
            .where(CompetitiveInsight.project_id == box.project_id)
            .order_by(CompetitiveInsight.strength.desc())
            .limit(params.limit)
            .offset(params.offset)
        )
    ).all()
    return [
        {
            "id": str(r.id),
            "competitor_id": str(r.competitor_id),
            "insight_type": r.insight_type,
            "title": _clip(r.title, 300),
            "confidence": r.confidence,
            "impact": r.impact,
        }
        for r in rows
    ]


async def _get_competitor_candidates(box: ToolBox, params: _Paged) -> list[dict[str, Any]]:
    from app.models.competitor_candidates import CompetitorCandidate

    rows = (
        await box._session.scalars(
            select(CompetitorCandidate)
            .where(CompetitorCandidate.project_id == box.project_id)
            .order_by(CompetitorCandidate.confidence.desc())
            .limit(params.limit)
            .offset(params.offset)
        )
    ).all()
    return [
        {
            "id": str(r.id),
            "name": r.name,
            "domain": r.domain,
            "confidence": r.confidence,
            "confidence_label": r.confidence_label,
            "status": r.status,
            "responses": (r.evidence or {}).get("responses"),
        }
        for r in rows
    ]


async def _get_page_content(box: ToolBox, params: _PageArg) -> dict[str, Any]:
    """One page's analyzable content: latest crawled text (UNTRUSTED), headings,
    structured-data types and page-scoped entities. Project-scoped."""
    from app.models.crawl import PageVersion
    from app.models.entities import Entity
    from app.models.page_intelligence import PageHeading, PageStructuredData

    page = (
        await box._session.scalars(
            select(WebsitePage).where(
                WebsitePage.id == params.page_id, WebsitePage.project_id == box.project_id
            )
        )
    ).one_or_none()
    if page is None:
        raise ToolError("Page not found in this project")
    version = (
        await box._session.scalars(
            select(PageVersion)
            .where(PageVersion.page_id == page.id)
            .order_by(PageVersion.crawled_at.desc())
            .limit(1)
        )
    ).one_or_none()
    headings = (
        await box._session.scalars(
            select(PageHeading)
            .where(PageHeading.page_id == page.id)
            .order_by(PageHeading.position)
            .limit(50)
        )
    ).all()
    blocks = (
        await box._session.scalars(
            select(PageStructuredData).where(PageStructuredData.page_id == page.id).limit(20)
        )
    ).all()
    entities = (
        await box._session.scalars(select(Entity).where(Entity.page_id == page.id).limit(20))
    ).all()
    return {
        "id": str(page.id),
        "url": page.url,
        "title": _clip(page.title, 300),
        "meta_description": _clip(page.meta_description, 500),
        "word_count": page.word_count,
        "language": page.language,
        # page text is untrusted content from the web
        "extracted_text": _clip(version.extracted_text if version else None, 8000),
        "headings": [{"level": h.level, "text": _clip(h.text, 200)} for h in headings],
        "schema_types": sorted({t for b in blocks for t in (b.schema_types or [])}),
        "entities": [{"entity_type": e.entity_type, "name": _clip(e.name, 200)} for e in entities],
    }


async def _save_content_review(box: ToolBox, params: "_ReviewInput") -> dict[str, Any]:
    """Upsert one content optimization review for a page of THIS project.

    Validated write: the page must belong to the project; inserts start
    'draft'; re-saves replace the analysis but keep the review's status and
    carry over decisions for changes whose (location, current_text) are
    unchanged. The original page is NEVER modified here or anywhere else."""
    import hashlib

    from app.models.content_reviews import ContentOptimizationReview, ReviewStatus

    page = (
        await box._session.scalars(
            select(WebsitePage.id).where(
                WebsitePage.id == params.page_id, WebsitePage.project_id == box.project_id
            )
        )
    ).one_or_none()
    if page is None:
        raise ToolError("Page not found in this project")

    def change_key(c: dict[str, Any]) -> str:
        raw = f"{c.get('location')}|{c.get('current_text')}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    changes = []
    seen_ids: set[str] = set()
    for c in params.proposed_changes:
        cid = change_key(c)
        if cid in seen_ids:
            continue  # identical (location, current_text) proposals collapse to one
        seen_ids.add(cid)
        changes.append(
            {
                "change_id": cid,
                "location": c["location"],
                "current_text": c["current_text"],
                "proposed_text": c["proposed_text"],
                "reason": c["reason"],
                "evidence": c.get("evidence") or {},
                "confidence": c.get("confidence", "low"),
                "decision": "pending",
                "decided_text": None,
            }
        )
    row = (
        await box._session.scalars(
            select(ContentOptimizationReview).where(
                ContentOptimizationReview.project_id == box.project_id,
                ContentOptimizationReview.page_id == params.page_id,
            )
        )
    ).one_or_none()
    created = row is None
    if row is None:
        row = ContentOptimizationReview(
            project_id=box.project_id,
            page_id=params.page_id,
            status=ReviewStatus.DRAFT.value,
        )
        box._session.add(row)
    else:
        previous = {c["change_id"]: c for c in (row.proposed_changes or [])}
        for c in changes:
            old = previous.get(c["change_id"])
            if old is not None:
                c["decision"] = old.get("decision", "pending")
                c["decided_text"] = old.get("decided_text")
    row.agent_run_id = box.agent_run_id
    row.score = params.score
    row.findings = params.findings
    row.recommendations = params.recommendations
    row.proposed_changes = changes
    row.confidence = params.confidence
    row.analysis_version = params.analysis_version
    from datetime import UTC, datetime

    row.analyzed_at = datetime.now(UTC)
    await box._session.flush()
    return {
        "id": str(row.id),
        "created": created,
        "status": row.status,
        "changes": len(changes),
    }


async def _save_content_brief(box: ToolBox, params: _BriefInput) -> dict[str, Any]:
    """Upsert one content brief for THIS project (unique per source_key).

    The framework's only write tool: inserts start as 'draft'; re-saves update
    the brief's content but never its status, prompt/competitor ids are
    verified to belong to the project, and nothing else is writable."""
    from app.models.competitor import Competitor
    from app.models.content_briefs import ContentBrief, ContentBriefStatus, ContentType

    if params.content_type not in {t.value for t in ContentType}:
        raise ToolError(f"Unknown content_type '{params.content_type}'")
    if params.target_prompt_ids:
        valid_prompts = set(
            (
                await box._session.scalars(
                    select(Prompt.id).where(
                        Prompt.project_id == box.project_id,
                        Prompt.id.in_(params.target_prompt_ids),
                    )
                )
            ).all()
        )
        if valid_prompts != set(params.target_prompt_ids):
            raise ToolError("target_prompt_ids must all belong to this project")
    if params.competitor_ids:
        valid_comps = set(
            (
                await box._session.scalars(
                    select(Competitor.id).where(
                        Competitor.project_id == box.project_id,
                        Competitor.id.in_(params.competitor_ids),
                    )
                )
            ).all()
        )
        if valid_comps != set(params.competitor_ids):
            raise ToolError("competitor_ids must all belong to this project")
    row = (
        await box._session.scalars(
            select(ContentBrief).where(
                ContentBrief.project_id == box.project_id,
                ContentBrief.source_key == params.source_key,
            )
        )
    ).one_or_none()
    created = row is None
    if row is None:
        row = ContentBrief(
            project_id=box.project_id,
            source_key=params.source_key,
            status=ContentBriefStatus.DRAFT.value,
        )
        box._session.add(row)
    row.agent_run_id = box.agent_run_id
    row.title = params.title
    row.content_type = params.content_type
    row.objective = params.objective
    row.search_intent = params.search_intent
    row.audience = params.audience
    row.differentiation = params.differentiation
    row.target_prompt_ids = [str(i) for i in params.target_prompt_ids]
    row.competitor_ids = [str(i) for i in params.competitor_ids]
    row.outline = params.outline
    row.information_requirements = list(params.information_requirements)
    row.evidence_requirements = params.evidence_requirements
    row.citation_opportunities = params.citation_opportunities
    row.entity_requirements = list(params.entity_requirements)
    row.internal_link_recommendations = params.internal_link_recommendations
    row.confidence = params.confidence
    await box._session.flush()
    return {"id": str(row.id), "created": created, "status": row.status}


async def _get_seo_audit(box: ToolBox, _: _Empty) -> dict[str, Any]:
    """Latest completed technical SEO audit (score + issue counts), if any."""
    from app.models.seo import AuditStatus, SeoAudit

    audit = (
        await box._session.scalars(
            select(SeoAudit)
            .where(
                SeoAudit.project_id == box.project_id,
                SeoAudit.status == AuditStatus.COMPLETED,
            )
            .order_by(SeoAudit.completed_at.desc())
            .limit(1)
        )
    ).one_or_none()
    if audit is None:
        return {"available": False}
    summary = audit.summary or {}
    return {
        "available": True,
        "audit_id": str(audit.id),
        "health_score": audit.health_score,
        "pages_analyzed": audit.pages_analyzed,
        "by_severity": summary.get("by_severity", {}),
        "completed_at": audit.completed_at.isoformat() if audit.completed_at else None,
    }


async def _get_claims(box: ToolBox, params: _Paged) -> list[dict[str, Any]]:
    """Recent extracted claims (subject/predicate/object are untrusted AI output)."""
    from app.models.intelligence import ResponseClaim

    rows = (
        await box._session.scalars(
            select(ResponseClaim)
            .where(ResponseClaim.project_id == box.project_id)
            .order_by(ResponseClaim.created_at.desc())
            .limit(params.limit)
            .offset(params.offset)
        )
    ).all()
    return [
        {
            "id": str(r.id),
            "subject": _clip(r.subject, 200),
            "predicate": _clip(r.predicate, 100),
            "object": _clip(r.object, 300),
            "confidence": r.confidence,
        }
        for r in rows
    ]


async def _get_visibility_metrics(box: ToolBox, _: _Empty) -> dict[str, Any]:
    from app.visibility.engine import VisibilityEngine

    overview = await VisibilityEngine(box._session).overview(box.project_id)
    current = overview.get("current", {})
    return {
        "window": overview.get("window"),
        "score": current.get("score"),
        "mention_rate": current.get("mention_rate"),
        "recommendation_rate": current.get("recommendation_rate"),
        "citation_rate": current.get("citation_rate"),
        "sample_size": current.get("data_quality", {}).get("sample_size"),
        "sufficiency": current.get("data_quality", {}).get("sufficiency"),
        "trend": overview.get("trend"),
    }


async def _get_recommendations(box: ToolBox, params: _Paged) -> list[dict[str, Any]]:
    from app.models.recommendations import Recommendation

    rows = (
        await box._session.scalars(
            select(Recommendation)
            .where(Recommendation.project_id == box.project_id)
            .order_by(Recommendation.opportunity_score.desc())
            .limit(params.limit)
            .offset(params.offset)
        )
    ).all()
    return [
        {
            "id": str(r.id),
            "title": r.title,
            "recommendation_type": r.recommendation_type,
            "priority": r.priority,
            "status": r.status,
        }
        for r in rows
    ]


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec("get_project", "The project's basic profile", _Empty, _get_project),
        ToolSpec("get_pages", "Crawled website pages (metadata only)", _Paged, _get_pages),
        ToolSpec(
            "get_page", "One crawled page by id (must belong to the project)", _PageArg, _get_page
        ),
        ToolSpec("get_competitors", "Configured competitors", _Paged, _get_competitors),
        ToolSpec("get_prompts", "The project's tracked prompts", _Paged, _get_prompts),
        ToolSpec(
            "get_ai_responses",
            "Recent completed AI responses (text is untrusted data)",
            _Paged,
            _get_ai_responses,
        ),
        ToolSpec("get_citations", "Recent response citations", _Paged, _get_citations),
        ToolSpec("get_citation_gaps", "Citation gaps by opportunity", _Paged, _get_citation_gaps),
        ToolSpec("get_content_gaps", "Content gaps by opportunity", _Paged, _get_content_gaps),
        ToolSpec(
            "get_entity_data",
            "Structured-data entities from the project's site",
            _Paged,
            _get_entity_data,
        ),
        ToolSpec(
            "get_visibility_metrics",
            "Current AI visibility overview (score, rates, sample)",
            _Empty,
            _get_visibility_metrics,
        ),
        ToolSpec(
            "get_recommendations", "Open recommendations by priority", _Paged, _get_recommendations
        ),
        ToolSpec(
            "get_competitive_visibility",
            "Brand vs competitors: scores, shares, advantages (5C)",
            _Empty,
            _get_competitive_visibility,
        ),
        ToolSpec(
            "get_competitive_insights",
            "Why-competitors-win insights (5D), strongest first",
            _Paged,
            _get_competitive_insights,
        ),
        ToolSpec(
            "get_seo_audit",
            "Latest completed technical SEO audit (health score, issue counts)",
            _Empty,
            _get_seo_audit,
        ),
        ToolSpec(
            "get_claims",
            "Recent extracted claims from AI responses (untrusted text)",
            _Paged,
            _get_claims,
        ),
        ToolSpec(
            "get_page_content",
            "One page's crawled text, headings, schema types and entities (untrusted)",
            _PageArg,
            _get_page_content,
        ),
        ToolSpec(
            "save_content_review",
            "Save/update one page's content optimization review (draft; validated write)",
            _ReviewInput,
            _save_content_review,
        ),
        ToolSpec(
            "save_content_brief",
            "Save/update one content brief for this project (draft; validated write)",
            _BriefInput,
            _save_content_brief,
        ),
        ToolSpec(
            "get_competitor_candidates",
            "Discovered competitor candidates (5B), most confident first",
            _Paged,
            _get_competitor_candidates,
        ),
    )
}
