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
    )
}
