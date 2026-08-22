"""Competitor discovery candidates (5B). Candidates are only ever promoted to
competitors by a person calling /accept. DATA_MANAGE for discover/accept/reject."""

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
from app.api.v1.routes.execution import RegistryDep
from app.api.v1.routes.prompts import _require
from app.core.errors import NotFoundError
from app.core.permissions import Permission
from app.discovery.service import CompetitorDiscoveryService
from app.models.competitor_candidates import CandidateSource, CandidateStatus, CompetitorCandidate
from app.schemas.competitors import CompetitorResponse
from app.schemas.discovery import (
    AcceptRequest,
    CandidateListResponse,
    CandidateView,
    DiscoverRequest,
    DiscoverResponse,
)

project_router = APIRouter(
    prefix="/projects/{project_id}/competitor-candidates", tags=["competitor-discovery"]
)
router = APIRouter(prefix="/competitor-candidates/{candidate_id}", tags=["competitor-discovery"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
}
ReadAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))]
ManageAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_MANAGE))]


@project_router.get(
    "", response_model=CandidateListResponse, summary="List discovery candidates", responses=_ERRORS
)
async def list_candidates(
    access: ReadAccess,
    session: DBSession,
    status: Annotated[CandidateStatus | None, Query()] = None,
    source: Annotated[CandidateSource | None, Query()] = None,
    min_confidence: Annotated[float | None, Query(ge=0, le=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CandidateListResponse:
    base = select(CompetitorCandidate).where(CompetitorCandidate.project_id == access.project.id)
    if status:
        base = base.where(CompetitorCandidate.status == status.value)
    if source:
        base = base.where(CompetitorCandidate.source == source.value)
    if min_confidence is not None:
        base = base.where(CompetitorCandidate.confidence >= min_confidence)
    total = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (
        await session.scalars(
            base.order_by(CompetitorCandidate.confidence.desc(), CompetitorCandidate.name)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    discovered_at = await session.scalar(
        select(func.max(CompetitorCandidate.discovered_at)).where(
            CompetitorCandidate.project_id == access.project.id
        )
    )
    return CandidateListResponse(
        items=[CandidateView.model_validate(r, from_attributes=True) for r in rows],
        total=int(total),
        limit=limit,
        offset=offset,
        discovered_at=discovered_at,
    )


@project_router.post(
    "/discover",
    response_model=DiscoverResponse,
    summary="Run competitor discovery (deterministic + AI-assisted)",
    description=(
        "Scans stored AI responses, website entities and, when a provider is configured, asks the "
        "AI provider for candidates. Nothing is added as a competitor; review the candidates."
    ),
    responses=_ERRORS,
)
async def discover(
    access: ManageAccess,
    session: DBSession,
    registry: RegistryDep,
    body: DiscoverRequest | None = None,
) -> DiscoverResponse:
    body = body or DiscoverRequest()
    result = await CompetitorDiscoveryService(session, registry).discover(
        access.project.id, window_days=body.window_days, use_ai=body.use_ai
    )
    await session.commit()
    return DiscoverResponse(
        **result.__dict__,
        note="Candidates require human review; accepting one creates a competitor.",
    )


async def get_candidate_access(
    session: DBSession, user: CurrentUser, candidate_id: Annotated[uuid.UUID, Path()]
) -> tuple[CompetitorCandidate, ProjectAccess]:
    row = await session.get(CompetitorCandidate, candidate_id)
    if row is None:
        raise NotFoundError("Candidate not found")
    access = await get_project_access(session, user, row.project_id)
    return row, access


CandidateAccess = Annotated[
    tuple[CompetitorCandidate, ProjectAccess], Depends(get_candidate_access)
]


@router.get("", response_model=CandidateView, summary="Get a candidate", responses=_ERRORS)
async def get_candidate(candidate_access: CandidateAccess) -> CandidateView:
    row, access = candidate_access
    _require(access, Permission.DATA_READ)
    return CandidateView.model_validate(row, from_attributes=True)


@router.post(
    "/accept",
    response_model=CompetitorResponse,
    summary="Accept a candidate — creates a competitor (human decision)",
    responses={**_ERRORS, 409: {"description": "Already accepted, or duplicates a competitor"}},
)
async def accept_candidate(
    candidate_access: CandidateAccess,
    session: DBSession,
    user: CurrentUser,
    body: AcceptRequest | None = None,
) -> CompetitorResponse:
    row, access = candidate_access
    _require(access, Permission.DATA_MANAGE)
    body = body or AcceptRequest()
    competitor = await CompetitorDiscoveryService(session).accept(
        row, user_id=user.id, website_url=body.website_url, name=body.name
    )
    await session.commit()
    from app.competitors.service import CompetitorService

    return CompetitorResponse.model_validate(
        await CompetitorService(session).get_in_project(row.project_id, competitor.id)
    )


@router.post(
    "/reject",
    response_model=CandidateView,
    summary="Reject a candidate",
    responses={**_ERRORS, 409: {"description": "Already accepted"}},
)
async def reject_candidate(
    candidate_access: CandidateAccess, session: DBSession, user: CurrentUser
) -> CandidateView:
    row, access = candidate_access
    _require(access, Permission.DATA_MANAGE)
    await CompetitorDiscoveryService(session).reject(row, user_id=user.id)
    await session.commit()
    await session.refresh(row)
    return CandidateView.model_validate(row, from_attributes=True)
