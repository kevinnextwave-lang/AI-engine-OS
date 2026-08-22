"""Response intelligence: read parsed observations, reprocess with the current parser."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, ProjectAccess, get_project_access
from app.api.v1.routes.execution import BatchAccess
from app.api.v1.routes.prompts import _require
from app.core.errors import NotFoundError
from app.core.permissions import Permission
from app.intelligence import PARSER_VERSION
from app.models.intelligence import BrandMention, CompetitorMention, ResponseCitation, ResponseClaim
from app.models.prompts import AiResponse, PromptRun
from app.repositories.execution import PromptRunRepository
from app.schemas.intelligence import (
    CitationView,
    ClaimView,
    CompetitorMentionView,
    MentionView,
    ReprocessResponse,
    ResponseIntelligenceView,
)
from app.services.intelligence import ResponseIntelligenceService

run_router = APIRouter(prefix="/prompt-runs/{run_id}", tags=["intelligence"])
batch_router = APIRouter(prefix="/prompt-run-batches/{batch_id}", tags=["intelligence"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
}


async def get_run_access(
    session: DBSession, user: CurrentUser, run_id: Annotated[uuid.UUID, Path()]
) -> tuple[PromptRun, ProjectAccess]:
    run = await PromptRunRepository(session).get(run_id)
    if run is None:
        raise NotFoundError("Prompt run not found")
    access = await get_project_access(session, user, run.project_id)
    return run, access


RunAccess = Annotated[tuple[PromptRun, ProjectAccess], Depends(get_run_access)]


async def _response_for(session: DBSession, run: PromptRun) -> AiResponse:
    response = (
        await session.scalars(select(AiResponse).where(AiResponse.prompt_run_id == run.id))
    ).first()
    if response is None:
        raise NotFoundError("No AI response recorded for this run")
    return response


async def _view(
    session: DBSession, run: PromptRun, response: AiResponse
) -> ResponseIntelligenceView:
    rid = response.id
    mentions = (
        await session.scalars(
            select(BrandMention)
            .where(BrandMention.ai_response_id == rid)
            .order_by(BrandMention.position.nulls_last(), BrandMention.created_at)
        )
    ).all()
    competitors = (
        await session.scalars(
            select(CompetitorMention)
            .where(CompetitorMention.ai_response_id == rid)
            .order_by(CompetitorMention.position.nulls_last(), CompetitorMention.created_at)
        )
    ).all()
    claims = (
        await session.scalars(
            select(ResponseClaim)
            .where(ResponseClaim.ai_response_id == rid)
            .order_by(ResponseClaim.created_at)
        )
    ).all()
    citations = (
        await session.scalars(
            select(ResponseCitation)
            .where(ResponseCitation.ai_response_id == rid)
            .order_by(ResponseCitation.citation_position.nulls_last(), ResponseCitation.created_at)
        )
    ).all()
    return ResponseIntelligenceView(
        prompt_run_id=run.id,
        ai_response_id=rid,
        parser_version=response.parser_version,
        parsed_at=response.parsed_at,
        summary=response.parse_summary,
        mentions=[MentionView.model_validate(m) for m in mentions],
        competitor_mentions=[CompetitorMentionView.model_validate(m) for m in competitors],
        claims=[ClaimView.model_validate(c) for c in claims],
        citations=[CitationView.model_validate(c) for c in citations],
    )


@run_router.get(
    "/intelligence",
    response_model=ResponseIntelligenceView,
    summary="Parsed observations for a prompt run",
    responses=_ERRORS,
)
async def get_run_intelligence(
    run_access: RunAccess, session: DBSession
) -> ResponseIntelligenceView:
    run, access = run_access
    _require(access, Permission.DATA_READ)
    return await _view(session, run, await _response_for(session, run))


@run_router.post(
    "/reprocess",
    response_model=ResponseIntelligenceView,
    summary="Re-parse a run's response with the current parser version",
    description="Replaces the run's observations; the stored AI response is kept as-is.",
    responses=_ERRORS,
)
async def reprocess_run(run_access: RunAccess, session: DBSession) -> ResponseIntelligenceView:
    run, access = run_access
    _require(access, Permission.DATA_MANAGE)
    response = await _response_for(session, run)
    await ResponseIntelligenceService(session).parse_and_store(response, force=True)
    await session.commit()
    return await _view(session, run, response)


@batch_router.post(
    "/reprocess",
    response_model=ReprocessResponse,
    summary="Re-parse every response in a batch",
    responses=_ERRORS,
)
async def reprocess_batch(batch_access: BatchAccess, session: DBSession) -> ReprocessResponse:
    batch, access = batch_access
    _require(access, Permission.DATA_MANAGE)
    count = await ResponseIntelligenceService(session).reprocess_batch(batch.id)
    return ReprocessResponse(reprocessed=count, parser_version=PARSER_VERSION)
