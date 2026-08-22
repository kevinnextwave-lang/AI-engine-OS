"""One row per parsed, completed prompt run — the unit the metrics aggregate over."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intelligence import BrandMention, CompetitorMention, ResponseCitation
from app.models.prompts import AiResponse, Prompt, PromptRun, PromptRunStatus
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

    observations: list[ResponseObservation] = []
    for run, response, prompt in rows:
        if run.completed_at is None:
            continue
        bm = mentions.get(response.id, [])
        positions = [m.position for m in bm if m.position is not None]
        cited = any(_cites_brand(c.domain, c.url, domains) for c in citations.get(response.id, []))
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
            )
        )
    return ObservationSet(observations, competitor_names, domains)


def _cites_brand(domain: str | None, url: str | None, brand_domains: list[str]) -> bool:
    host = (domain or "").lower().removeprefix("www.")
    if not host and url:
        from urllib.parse import urlsplit

        host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
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
