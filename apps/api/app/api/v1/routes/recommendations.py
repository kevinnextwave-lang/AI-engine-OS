"""Recommendations: generated from Citation Intelligence, reviewed by humans.

Project routes use `require_project_access`; per-recommendation routes derive
the project from the row (non-members 404). DATA_READ for reads, DATA_MANAGE
for generate and every status change. No route performs any external action.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, select

from app.api.deps import (
    CurrentUser,
    DBSession,
    ProjectAccess,
    get_project_access,
    require_project_access,
)
from app.api.v1.routes.prompts import _require
from app.core.errors import NotFoundError
from app.core.permissions import Permission
from app.models.recommendations import (
    TRANSITIONS,
    Recommendation,
    RecommendationPriority,
    RecommendationStatus,
    RecommendationType,
)
from app.recommendations import GENERATOR_VERSION
from app.recommendations.engine import RecommendationEngine
from app.recommendations.service import transition
from app.schemas.recommendations import (
    GenerateResponse,
    RecommendationListResponse,
    RecommendationSummary,
    RecommendationUpdateRequest,
    RecommendationView,
    ReviewRequest,
)

project_router = APIRouter(
    prefix="/projects/{project_id}/recommendations", tags=["recommendations"]
)
rec_router = APIRouter(prefix="/recommendations/{recommendation_id}", tags=["recommendations"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
}
ReadAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))]
ManageAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_MANAGE))]

PRIORITY_ORDER = {p.value: i for i, p in enumerate(RecommendationPriority)}


def _view(rec: Recommendation) -> RecommendationView:
    return RecommendationView(
        id=rec.id,
        project_id=rec.project_id,
        recommendation_type=RecommendationType(rec.recommendation_type),
        title=rec.title,
        description=rec.description,
        explanation=rec.explanation,
        evidence=rec.evidence,
        priority=RecommendationPriority(rec.priority),
        opportunity_score=rec.opportunity_score,
        confidence=rec.confidence,
        status=RecommendationStatus(rec.status),
        note=rec.note,
        citation_gap_id=rec.citation_gap_id,
        source_key=rec.source_key,
        generator_version=rec.generator_version,
        generated_at=rec.generated_at,
        reviewed_at=rec.reviewed_at,
        reviewed_by_user_id=rec.reviewed_by_user_id,
        allowed_transitions=sorted(
            TRANSITIONS[RecommendationStatus(rec.status)], key=lambda s: s.value
        ),
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


async def _generated_at(session: DBSession, project_id: uuid.UUID):  # type: ignore[no-untyped-def]
    return await session.scalar(
        select(func.max(Recommendation.generated_at)).where(Recommendation.project_id == project_id)
    )


@project_router.get(
    "", response_model=RecommendationListResponse, summary="List recommendations", responses=_ERRORS
)
async def list_recommendations(
    access: ReadAccess,
    session: DBSession,
    status: Annotated[RecommendationStatus | None, Query()] = None,
    priority: Annotated[RecommendationPriority | None, Query()] = None,
    recommendation_type: Annotated[RecommendationType | None, Query(alias="type")] = None,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RecommendationListResponse:
    base = select(Recommendation).where(Recommendation.project_id == access.project.id)
    if status:
        base = base.where(Recommendation.status == status.value)
    if priority:
        base = base.where(Recommendation.priority == priority.value)
    if recommendation_type:
        base = base.where(Recommendation.recommendation_type == recommendation_type.value)
    if min_score is not None:
        base = base.where(Recommendation.opportunity_score >= min_score)
    total = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (await session.scalars(base)).all()
    rows = sorted(
        rows, key=lambda r: (PRIORITY_ORDER.get(r.priority, 9), -r.opportunity_score, r.title)
    )[offset : offset + limit]
    return RecommendationListResponse(
        items=[_view(r) for r in rows],
        total=int(total),
        limit=limit,
        offset=offset,
        generated_at=await _generated_at(session, access.project.id),
    )


@project_router.get(
    "/summary",
    response_model=RecommendationSummary,
    summary="Counts by status, priority, type",
    responses=_ERRORS,
)
async def recommendation_summary(access: ReadAccess, session: DBSession) -> RecommendationSummary:
    rows = (
        await session.scalars(
            select(Recommendation).where(Recommendation.project_id == access.project.id)
        )
    ).all()
    by: dict[str, dict[str, int]] = {"status": {}, "priority": {}, "type": {}}
    for r in rows:
        for k, v in (
            ("status", r.status),
            ("priority", r.priority),
            ("type", r.recommendation_type),
        ):
            by[k][v] = by[k].get(v, 0) + 1
    awaiting = by["status"].get("new", 0) + by["status"].get("reviewing", 0)
    return RecommendationSummary(
        project_id=access.project.id,
        total=len(rows),
        by_status=by["status"],
        by_priority=by["priority"],
        by_type=by["type"],
        awaiting_review=awaiting,
        generated_at=await _generated_at(session, access.project.id),
        generator_version=GENERATOR_VERSION,
        note=(
            "Recommendations are generated from observed citation gaps and require human review; "
            "nothing is executed automatically."
        ),
    )


@project_router.post(
    "/generate",
    response_model=GenerateResponse,
    summary="(Re)generate recommendations from the project's citation gaps",
    description="Run the citation-gap analysis first. Existing review statuses are kept.",
    responses=_ERRORS,
)
async def generate_recommendations(access: ManageAccess, session: DBSession) -> GenerateResponse:
    result = await RecommendationEngine(session).generate(access.project.id)
    await session.commit()
    return GenerateResponse(**result.__dict__)


async def get_recommendation_access(
    session: DBSession, user: CurrentUser, recommendation_id: Annotated[uuid.UUID, Path()]
) -> tuple[Recommendation, ProjectAccess]:
    rec = await session.get(Recommendation, recommendation_id)
    if rec is None:
        raise NotFoundError("Recommendation not found")
    access = await get_project_access(session, user, rec.project_id)
    return rec, access


RecAccess = Annotated[tuple[Recommendation, ProjectAccess], Depends(get_recommendation_access)]


@rec_router.get(
    "", response_model=RecommendationView, summary="Get a recommendation", responses=_ERRORS
)
async def get_recommendation(rec_access: RecAccess) -> RecommendationView:
    rec, access = rec_access
    _require(access, Permission.DATA_READ)
    return _view(rec)


async def _review(
    rec_access: RecAccess,
    session: DBSession,
    user: CurrentUser,
    to: RecommendationStatus,
    note: str | None,
) -> RecommendationView:
    rec, access = rec_access
    _require(access, Permission.DATA_MANAGE)
    transition(rec, to, user_id=user.id, note=note)
    await session.commit()
    await session.refresh(rec)
    return _view(rec)


@rec_router.post(
    "/approve",
    response_model=RecommendationView,
    summary="Approve (human decision; no action is taken automatically)",
    responses={**_ERRORS, 409: {"description": "Transition not allowed from the current status"}},
)
async def approve_recommendation(
    rec_access: RecAccess, session: DBSession, user: CurrentUser, body: ReviewRequest | None = None
) -> RecommendationView:
    return await _review(
        rec_access, session, user, RecommendationStatus.APPROVED, body.note if body else None
    )


@rec_router.post(
    "/dismiss",
    response_model=RecommendationView,
    summary="Dismiss",
    responses={**_ERRORS, 409: {"description": "Transition not allowed from the current status"}},
)
async def dismiss_recommendation(
    rec_access: RecAccess, session: DBSession, user: CurrentUser, body: ReviewRequest | None = None
) -> RecommendationView:
    return await _review(
        rec_access, session, user, RecommendationStatus.DISMISSED, body.note if body else None
    )


@rec_router.post(
    "/start",
    response_model=RecommendationView,
    summary="Mark an approved recommendation as in progress",
    responses={**_ERRORS, 409: {"description": "Transition not allowed from the current status"}},
)
async def start_recommendation(
    rec_access: RecAccess, session: DBSession, user: CurrentUser, body: ReviewRequest | None = None
) -> RecommendationView:
    return await _review(
        rec_access, session, user, RecommendationStatus.IN_PROGRESS, body.note if body else None
    )


@rec_router.patch(
    "",
    response_model=RecommendationView,
    summary="Other reviewer transitions (reviewing, completed, reopen) or a note",
    responses={**_ERRORS, 409: {"description": "Transition not allowed from the current status"}},
)
async def update_recommendation(
    rec_access: RecAccess, session: DBSession, user: CurrentUser, body: RecommendationUpdateRequest
) -> RecommendationView:
    rec, access = rec_access
    _require(access, Permission.DATA_MANAGE)
    if body.status is not None and body.status.value != rec.status:
        transition(rec, body.status, user_id=user.id, note=body.note)
    elif "note" in body.model_fields_set:
        rec.note = (body.note or "").strip() or None
    await session.commit()
    await session.refresh(rec)
    return _view(rec)
