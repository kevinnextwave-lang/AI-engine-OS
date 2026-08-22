"""Parse AI responses into observations; reprocess with newer parser versions.

`parse_and_store` replaces every observation row for the response and stamps
`ai_responses.parser_version`/`parsed_at`/`parse_summary`. The `ai_responses`
row itself is never duplicated.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.intelligence import PARSER_VERSION
from app.intelligence.context import ParseContext, brand_from
from app.intelligence.interpreter import Interpreter
from app.intelligence.pipeline import parse_response
from app.intelligence.schema import ParsedResponse
from app.models.intelligence import BrandMention, CompetitorMention, ResponseCitation, ResponseClaim
from app.models.project import Project
from app.models.prompts import AiResponse, PromptRun
from app.repositories.projects import CompetitorRepository, DomainRepository
from app.sources.service import SourceIntelligenceService

log = get_logger(__name__)


class ResponseIntelligenceService:
    def __init__(self, session: AsyncSession, interpreter: Interpreter | None = None) -> None:
        self._session = session
        self._interpreter = interpreter

    async def build_context(self, project: Project) -> ParseContext:
        domains = await DomainRepository(self._session).list_for_project(project.id)
        primary = next((d for d in domains if d.is_primary), domains[0] if domains else None)
        competitors = await CompetitorRepository(self._session).list_for_project(project.id)
        return ParseContext(
            project_id=project.id,
            brand=brand_from(project.name, primary.url if primary else None),
            competitors=[brand_from(c.name, c.website_url, c.id) for c in competitors],
            brand_domains=tuple(d.hostname for d in domains),
        )

    async def parse_and_store(
        self, response: AiResponse, *, force: bool = False
    ) -> ParsedResponse | None:
        """Parse (or reparse) one response. Skips when already parsed by the
        current parser version unless `force`."""
        if response.parser_version == PARSER_VERSION and not force:
            return None
        run = await self._session.get(PromptRun, response.prompt_run_id)
        if run is None:
            return None
        project = await self._session.get(Project, run.project_id)
        if project is None:
            return None
        ctx = await self.build_context(project)
        parsed = await parse_response(response.response_text, ctx, self._interpreter)
        await self._replace_rows(response, project.id, parsed, ctx)
        await self._session.flush()
        # Citation Intelligence (4A): link new citations into the source graph.
        sources = SourceIntelligenceService(self._session)
        await sources.resolve_for_response(response.id, project.id)
        await sources.aggregate_project_sources(project.id)
        response.parser_version = parsed.parser_version
        response.parsed_at = datetime.now(UTC)
        response.parse_summary = summary_of(parsed)
        run.visibility = visibility_of(parsed)
        await self._session.flush()
        log.info(
            "ai_response_parsed",
            ai_response_id=str(response.id),
            parser_version=parsed.parser_version,
            brand_mentioned=parsed.position_signals.brand_mentioned,
            competitor_mentions=len(parsed.competitor_mentions),
            citations=len(parsed.citations),
            stage2_used=parsed.stage2_used,
            stage2_error=parsed.stage2_error,
        )
        return parsed

    async def reprocess_batch(self, batch_id: uuid.UUID, *, force: bool = True) -> int:
        """Re-parse every response of a batch with the current parser version."""
        responses = (
            await self._session.scalars(
                select(AiResponse)
                .join(PromptRun, PromptRun.id == AiResponse.prompt_run_id)
                .where(PromptRun.batch_id == batch_id)
            )
        ).all()
        count = 0
        for response in responses:
            if await self.parse_and_store(response, force=force) is not None:
                count += 1
        await self._session.commit()
        return count

    async def _replace_rows(
        self, response: AiResponse, project_id: uuid.UUID, parsed: ParsedResponse, ctx: ParseContext
    ) -> None:
        for model in (BrandMention, CompetitorMention, ResponseClaim, ResponseCitation):
            await self._session.execute(delete(model).where(model.ai_response_id == response.id))
        competitor_ids: dict[str, uuid.UUID | None] = {
            c.name: c.competitor_id for c in ctx.competitors
        }
        v = parsed.parser_version
        self._session.add_all(
            BrandMention(
                ai_response_id=response.id,
                project_id=project_id,
                brand_name=m.brand_name,
                mention_text=m.mention_text,
                position=m.position,
                sentiment=m.sentiment.value,
                recommendation_strength=m.recommendation_strength.value,
                context=m.context,
                source=m.source,
                parser_version=v,
            )
            for m in parsed.mentions
        )
        self._session.add_all(
            CompetitorMention(
                ai_response_id=response.id,
                project_id=project_id,
                competitor_id=competitor_ids.get(m.brand_name),
                competitor_name=m.brand_name,
                mention_text=m.mention_text,
                position=m.position,
                sentiment=m.sentiment.value,
                recommendation_strength=m.recommendation_strength.value,
                context=m.context,
                source=m.source,
                parser_version=v,
            )
            for m in parsed.competitor_mentions
        )
        self._session.add_all(
            ResponseClaim(
                ai_response_id=response.id,
                project_id=project_id,
                subject=c.subject,
                predicate=c.predicate,
                object=c.object,
                confidence=c.confidence,
                context=c.context,
                parser_version=v,
            )
            for c in parsed.claims
        )
        self._session.add_all(
            ResponseCitation(
                ai_response_id=response.id,
                project_id=project_id,
                url=c.url,
                domain=c.domain,
                anchor_text=c.anchor_text,
                citation_position=c.citation_position,
                citation_type=c.citation_type.value,
                parser_version=v,
            )
            for c in parsed.citations
        )


def summary_of(parsed: ParsedResponse) -> dict[str, Any]:
    ps = parsed.position_signals
    return {
        "parser_version": parsed.parser_version,
        "brand_mentioned": ps.brand_mentioned,
        "brand_position": ps.brand_position,
        "sentiment": parsed.sentiment.value,
        "recommendation_strength": _strongest(parsed),
        "competitors_mentioned": ps.competitors_mentioned,
        "recommendations": [r.model_dump(mode="json") for r in parsed.recommendations],
        "counts": {
            "mentions": len(parsed.mentions),
            "competitor_mentions": len(parsed.competitor_mentions),
            "claims": len(parsed.claims),
            "citations": len(parsed.citations),
        },
        "answer_is_list": ps.answer_is_list,
        "ordered_list": ps.ordered_list,
        "list_items": ps.list_items,
        "first_mentioned_brand": ps.first_mentioned_brand,
        "stage2_used": parsed.stage2_used,
        "stage2_error": parsed.stage2_error,
    }


def _strongest(parsed: ParsedResponse) -> str | None:
    order = ["unknown", "none", "weak", "moderate", "strong"]
    values = [m.recommendation_strength.value for m in parsed.mentions]
    return max(values, key=order.index) if values else None


def visibility_of(parsed: ParsedResponse) -> dict[str, Any]:
    """Compact per-run visibility stored on prompt_runs.visibility (used by the prompt table)."""
    ps = parsed.position_signals
    return {
        "brand_mentioned": ps.brand_mentioned,
        "position": ps.brand_position,
        "sentiment": parsed.sentiment.value,
        "competitors_mentioned": ps.competitors_mentioned,
        "parser_version": parsed.parser_version,
    }
