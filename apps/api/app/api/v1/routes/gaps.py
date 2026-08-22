"""Citation gaps: where competitors get cited and the brand does not.

Project-scoped list/summary/analyze use `require_project_access`; per-gap
routes derive the project from the row (non-members 404). DATA_READ for reads,
DATA_MANAGE for analyze and status updates.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

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
from app.gaps import ANALYSIS_VERSION
from app.gaps.engine import DEFAULT_WINDOW_DAYS, CitationGapEngine
from app.gaps.scoring import priority_for
from app.models.gaps import CitationGap, GapConfidence, GapStatus, GapType
from app.models.sources import SourceDomain
from app.schemas.gaps import (
    AnalyzeResponse,
    CitationGapListResponse,
    CitationGapSummary,
    CitationGapUpdateRequest,
    CitationGapView,
    GapSufficiency,
)

project_router = APIRouter(prefix="/projects/{project_id}/citation-gaps", tags=["citation-gaps"])
gap_router = APIRouter(prefix="/citation-gaps/{gap_id}", tags=["citation-gaps"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
}

ReadAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))]
ManageAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_MANAGE))]


def _view(gap: CitationGap, domain: SourceDomain) -> CitationGapView:
    return CitationGapView(
        id=gap.id,
        project_id=gap.project_id,
        source_domain_id=gap.source_domain_id,
        source_page_id=gap.source_page_id,
        domain=domain.normalized_hostname,
        display_name=domain.display_name,
        source_type=domain.domain_type,
        gap_type=GapType(gap.gap_type),
        priority=priority_for(gap.opportunity_score),
        brand_citations=gap.brand_citations,
        competitor_citations=gap.competitor_citations,
        competitors=gap.competitors,
        relevant_response_count=gap.relevant_response_count,
        opportunity_score=gap.opportunity_score,
        confidence=GapConfidence(gap.confidence),
        explanation=gap.explanation,
        status=GapStatus(gap.status),
        note=gap.note,
        evidence=gap.evidence,
        analysis_version=gap.analysis_version,
        analyzed_at=gap.analyzed_at,
        created_at=gap.created_at,
        updated_at=gap.updated_at,
    )


async def _analyzed_at(session: DBSession, project_id: uuid.UUID):  # type: ignore[no-untyped-def]
    return await session.scalar(
        select(func.max(CitationGap.analyzed_at)).where(CitationGap.project_id == project_id)
    )


@project_router.get(
    "",
    response_model=CitationGapListResponse,
    summary="List a project's citation gaps",
    responses=_ERRORS,
)
async def list_gaps(
    access: ReadAccess,
    session: DBSession,
    source_type: Annotated[str | None, Query()] = None,
    gap_type: Annotated[GapType | None, Query()] = None,
    status: Annotated[GapStatus | None, Query()] = None,
    confidence: Annotated[GapConfidence | None, Query()] = None,
    competitor: Annotated[
        str | None, Query(description="Only sources where this competitor is cited")
    ] = None,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    max_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CitationGapListResponse:
    d = aliased(SourceDomain)
    base = (
        select(CitationGap, d)
        .join(d, d.id == CitationGap.source_domain_id)
        .where(CitationGap.project_id == access.project.id)
    )
    if source_type:
        base = base.where(d.domain_type == source_type)
    if gap_type:
        base = base.where(CitationGap.gap_type == gap_type.value)
    if status:
        base = base.where(CitationGap.status == status.value)
    if confidence:
        base = base.where(CitationGap.confidence == confidence.value)
    if competitor:
        base = base.where(CitationGap.competitors.has_key(competitor))
    if min_score is not None:
        base = base.where(CitationGap.opportunity_score >= min_score)
    if max_score is not None:
        base = base.where(CitationGap.opportunity_score <= max_score)
    total = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (
        await session.execute(
            base.order_by(CitationGap.opportunity_score.desc(), d.normalized_hostname)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return CitationGapListResponse(
        items=[_view(g, dom) for g, dom in rows],
        total=int(total),
        limit=limit,
        offset=offset,
        analyzed_at=await _analyzed_at(session, access.project.id),
    )


@project_router.get(
    "/summary",
    response_model=CitationGapSummary,
    summary="Counts, top opportunities and data sufficiency for a project's gaps",
    responses=_ERRORS,
)
async def gap_summary(access: ReadAccess, session: DBSession) -> CitationGapSummary:
    pid = access.project.id
    rows = (
        await session.execute(
            select(CitationGap, SourceDomain)
            .join(SourceDomain, SourceDomain.id == CitationGap.source_domain_id)
            .where(CitationGap.project_id == pid)
            .order_by(CitationGap.opportunity_score.desc())
        )
    ).all()
    by: dict[str, dict[str, int]] = {
        k: {} for k in ("gap_type", "status", "confidence", "source_type", "priority")
    }
    ahead: dict[str, int] = {}
    actionable = 0
    open_statuses = {
        GapStatus.NEW.value,
        GapStatus.REVIEWING.value,
        GapStatus.ACCEPTED.value,
        GapStatus.IN_PROGRESS.value,
    }
    for gap, dom in rows:
        for key, value in (
            ("gap_type", gap.gap_type),
            ("status", gap.status),
            ("confidence", gap.confidence),
            ("source_type", dom.domain_type),
            ("priority", priority_for(gap.opportunity_score)),
        ):
            by[key][value] = by[key].get(value, 0) + 1
        if (
            gap.status in open_statuses
            and gap.confidence != GapConfidence.INSUFFICIENT.value
            and gap.opportunity_score >= 40
        ):
            actionable += 1
        if gap.brand_citations == 0:
            for name in gap.competitors:
                ahead[name] = ahead.get(name, 0) + 1
    first = rows[0][0] if rows else None
    inputs = (first.evidence.get("inputs", {}) if first else {}) or {}
    eligible = int(inputs.get("eligible_responses", 0))
    prompts = int(inputs.get("total_prompts", 0))
    window = int((first.evidence.get("window_days") if first else None) or DEFAULT_WINDOW_DAYS)
    sufficient = eligible >= 5 and len(rows) > 0
    return CitationGapSummary(
        project_id=pid,
        analyzed_at=await _analyzed_at(session, pid),
        analysis_version=ANALYSIS_VERSION,
        total=len(rows),
        by_gap_type=by["gap_type"],
        by_status=by["status"],
        by_confidence=by["confidence"],
        by_source_type=by["source_type"],
        by_priority=by["priority"],
        actionable=actionable,
        top_opportunities=[
            _view(g, dom)
            for g, dom in rows
            if g.status in open_statuses and g.confidence != GapConfidence.INSUFFICIENT.value
        ][:5],
        competitors_ahead=dict(sorted(ahead.items(), key=lambda kv: -kv[1])),
        data=GapSufficiency(
            eligible_responses=eligible,
            relevant_prompts=prompts,
            sources_observed=len(rows),
            window_days=window,
            sufficient=sufficient,
            note=(
                "Gaps are computed from parsed AI responses in the analysis window; "
                "confidence reflects sample size per source."
                if sufficient
                else "Not enough parsed AI responses yet to identify citation gaps; "
                "run a prompt set and analyse again."
            ),
        ),
        method=ANALYSIS_VERSION,
    )


@project_router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    summary="(Re)compute a project's citation gaps from its stored citations",
    responses=_ERRORS,
)
async def analyze_gaps(
    access: ManageAccess,
    session: DBSession,
    window_days: Annotated[int, Query(ge=7, le=365)] = DEFAULT_WINDOW_DAYS,
) -> AnalyzeResponse:
    result = await CitationGapEngine(session).analyze(access.project.id, window_days=window_days)
    await session.commit()
    return AnalyzeResponse(**result.__dict__)


async def get_gap_access(
    session: DBSession, user: CurrentUser, gap_id: Annotated[uuid.UUID, Path()]
) -> tuple[CitationGap, SourceDomain, ProjectAccess]:
    row = (
        await session.execute(
            select(CitationGap, SourceDomain)
            .join(SourceDomain, SourceDomain.id == CitationGap.source_domain_id)
            .where(CitationGap.id == gap_id)
        )
    ).first()
    if row is None:
        raise NotFoundError("Citation gap not found")
    gap, domain = row
    access = await get_project_access(session, user, gap.project_id)
    return gap, domain, access


GapAccess = Annotated[tuple[CitationGap, SourceDomain, ProjectAccess], Depends(get_gap_access)]


@gap_router.get("", response_model=CitationGapView, summary="Get a citation gap", responses=_ERRORS)
async def get_gap(gap_access: GapAccess) -> CitationGapView:
    gap, domain, access = gap_access
    _require(access, Permission.DATA_READ)
    return _view(gap, domain)


@gap_router.patch(
    "",
    response_model=CitationGapView,
    summary="Update a gap's status or note",
    responses=_ERRORS,
)
async def update_gap(
    gap_access: GapAccess, body: CitationGapUpdateRequest, session: DBSession
) -> CitationGapView:
    gap, domain, access = gap_access
    _require(access, Permission.DATA_MANAGE)
    if body.status is not None:
        gap.status = body.status.value
    if "note" in body.model_fields_set:
        gap.note = body.note
    await session.commit()
    await session.refresh(gap)
    return _view(gap, domain)
