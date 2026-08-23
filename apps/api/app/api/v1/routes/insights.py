"""Why Competitors Win (Milestone 5D): evidence-backed, non-causal insights.

Project-scoped list/analyze use `require_project_access`; the competitor-scoped
list derives the project from the competitor row (non-members 404). DATA_READ
for reads, DATA_MANAGE to analyze.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import DBSession, ProjectAccess, require_project_access
from app.api.v1.routes.competitors import CompetitorAccess
from app.api.v1.routes.prompts import _require
from app.core.permissions import Permission
from app.insights.analyzers import CAUTION
from app.insights.engine import CompetitiveInsightEngine
from app.models.insights import CompetitiveInsight, InsightConfidence, InsightImpact, InsightType
from app.schemas.insights import (
    InsightAnalyzeRequest,
    InsightAnalyzeResponse,
    InsightListResponse,
    InsightView,
)

project_router = APIRouter(prefix="/projects/{project_id}/competitive-insights", tags=["insights"])
router = APIRouter(prefix="/competitors/{competitor_id}/insights", tags=["insights"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
}
ReadAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))]
ManageAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_MANAGE))]

_IMPACT_ORDER = {"high": 0, "medium": 1, "low": 2}


def _listing(rows: list[CompetitiveInsight], limit: int, offset: int) -> InsightListResponse:
    rows.sort(key=lambda r: (_IMPACT_ORDER.get(r.impact, 3), -r.strength, r.title))
    total = len(rows)
    page = rows[offset : offset + limit]
    return InsightListResponse(
        items=[InsightView.model_validate(r) for r in page],
        total=total,
        limit=limit,
        offset=offset,
        analyzed_at=max((r.analyzed_at for r in rows), default=None),
        note=CAUTION,
    )


@project_router.get(
    "",
    response_model=InsightListResponse,
    summary="Competitive insights for a project (observed patterns, not causation)",
    responses=_ERRORS,
)
async def list_insights(
    access: ReadAccess,
    session: DBSession,
    insight_type: Annotated[InsightType | None, Query()] = None,
    impact: Annotated[InsightImpact | None, Query()] = None,
    confidence: Annotated[InsightConfidence | None, Query()] = None,
    competitor_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InsightListResponse:
    stmt = select(CompetitiveInsight).where(CompetitiveInsight.project_id == access.project.id)
    if insight_type is not None:
        stmt = stmt.where(CompetitiveInsight.insight_type == insight_type.value)
    if impact is not None:
        stmt = stmt.where(CompetitiveInsight.impact == impact.value)
    if confidence is not None:
        stmt = stmt.where(CompetitiveInsight.confidence == confidence.value)
    if competitor_id is not None:
        stmt = stmt.where(CompetitiveInsight.competitor_id == competitor_id)
    rows = list((await session.scalars(stmt)).all())
    return _listing(rows, limit, offset)


@project_router.post(
    "/analyze",
    response_model=InsightAnalyzeResponse,
    summary="Re-analyze competitive insights from the response/citation graph",
    responses=_ERRORS,
)
async def analyze_insights(
    access: ManageAccess, session: DBSession, body: InsightAnalyzeRequest | None = None
) -> InsightAnalyzeResponse:
    body = body or InsightAnalyzeRequest()
    result = await CompetitiveInsightEngine(session).analyze(
        access.project.id, window_days=body.window_days
    )
    await session.commit()
    return InsightAnalyzeResponse(**result.__dict__)


@router.get(
    "",
    response_model=InsightListResponse,
    summary="Insights about one competitor",
    responses=_ERRORS,
)
async def competitor_insights(
    competitor_access: CompetitorAccess,
    session: DBSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InsightListResponse:
    competitor, access = competitor_access
    _require(access, Permission.DATA_READ)
    rows = list(
        (
            await session.scalars(
                select(CompetitiveInsight).where(
                    CompetitiveInsight.competitor_id == competitor.id,
                    CompetitiveInsight.project_id == competitor.project_id,
                )
            )
        ).all()
    )
    return _listing(rows, limit, offset)
