"""Technical SEO audit endpoints.

Authorization: audits and observations are resolved by id, then the caller's
access to the OWNING PROJECT is checked via `get_project_access` (membership in
the project's organization). Foreign or unknown ids are 404; role checks use
DATA_READ for reads and DATA_MANAGE for starting audits and triaging.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.deps import (
    CurrentUser,
    DBSession,
    ProjectAccess,
    get_project_access,
    require_project_access,
)
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.permissions import Permission, role_has
from app.models.seo import (
    ObservationCategory,
    ObservationStatus,
    SeoAudit,
    SeoObservation,
    Severity,
)
from app.repositories.seo import SeoAuditRepository, SeoObservationRepository
from app.schemas.seo import (
    SeoAuditListResponse,
    SeoAuditResponse,
    SeoAuditStartRequest,
    SeoObservationListResponse,
    SeoObservationResponse,
    SeoObservationUpdateRequest,
)
from app.services.seo import Dispatcher, SeoAuditService
from app.workers.tasks import dispatch_seo_audit

project_router = APIRouter(prefix="/projects/{project_id}/seo-audits", tags=["seo"])
router = APIRouter(tags=["seo"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
}


def get_seo_dispatcher() -> Dispatcher:
    return dispatch_seo_audit


DispatcherDep = Annotated[Dispatcher, Depends(get_seo_dispatcher)]


async def get_audit_access(
    session: DBSession, user: CurrentUser, audit_id: Annotated[uuid.UUID, Path()]
) -> tuple[SeoAudit, ProjectAccess]:
    audit = await SeoAuditRepository(session).get(audit_id)
    if audit is None:
        raise NotFoundError("SEO audit not found")
    access = await get_project_access(session, user, audit.project_id)
    return audit, access


async def get_observation_access(
    session: DBSession, user: CurrentUser, observation_id: Annotated[uuid.UUID, Path()]
) -> tuple[SeoObservation, ProjectAccess]:
    observation = await SeoObservationRepository(session).get(observation_id)
    if observation is None:
        raise NotFoundError("SEO observation not found")
    access = await get_project_access(session, user, observation.project_id)
    return observation, access


AuditAccess = Annotated[tuple[SeoAudit, ProjectAccess], Depends(get_audit_access)]
ObservationAccess = Annotated[tuple[SeoObservation, ProjectAccess], Depends(get_observation_access)]


def _require(access: ProjectAccess, permission: Permission) -> None:
    if not role_has(access.membership.role, permission):
        raise PermissionDeniedError()


# -- project-scoped ----------------------------------------------------------


@project_router.post(
    "",
    response_model=SeoAuditResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a technical SEO audit",
    description=(
        "Queues an analysis of the data collected by a finished crawl (the latest one by "
        "default). Observations and the health score appear when status is `completed`."
    ),
    responses={**_ERRORS, 409: {"description": "Chosen crawl has not finished"}},
)
async def start_audit(
    body: SeoAuditStartRequest,
    access: Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_MANAGE))],
    user: CurrentUser,
    session: DBSession,
    dispatcher: DispatcherDep,
) -> SeoAuditResponse:
    audit = await SeoAuditService(session, dispatcher).start(
        project=access.project, requested_by=user.id, crawl_job_id=body.crawl_job_id
    )
    return SeoAuditResponse.model_validate(audit)


@project_router.get(
    "",
    response_model=SeoAuditListResponse,
    summary="List a project's SEO audits",
    responses=_ERRORS,
)
async def list_audits(
    access: Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))],
    session: DBSession,
    dispatcher: DispatcherDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SeoAuditListResponse:
    audits, total = await SeoAuditService(session, dispatcher).list_for_project(
        access.project, limit=limit, offset=offset
    )
    return SeoAuditListResponse(
        items=[SeoAuditResponse.model_validate(a) for a in audits], total=total
    )


# -- audit / observation scoped ---------------------------------------------


@router.get(
    "/seo-audits/{audit_id}",
    response_model=SeoAuditResponse,
    summary="Get an SEO audit",
    responses=_ERRORS,
)
async def get_audit(audit_access: AuditAccess) -> SeoAuditResponse:
    audit, access = audit_access
    _require(access, Permission.DATA_READ)
    return SeoAuditResponse.model_validate(audit)


@router.get(
    "/seo-audits/{audit_id}/observations",
    response_model=SeoObservationListResponse,
    summary="List an audit's observations",
    description="Ordered by severity (critical first). Filter by category, severity, status.",
    responses=_ERRORS,
)
async def list_observations(
    audit_access: AuditAccess,
    session: DBSession,
    dispatcher: DispatcherDep,
    category: Annotated[ObservationCategory | None, Query()] = None,
    severity: Annotated[Severity | None, Query()] = None,
    status_filter: Annotated[ObservationStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SeoObservationListResponse:
    audit, access = audit_access
    _require(access, Permission.DATA_READ)
    rows, total = await SeoAuditService(session, dispatcher).list_observations(
        audit,
        category=category,
        severity=severity,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return SeoObservationListResponse(
        items=[SeoObservationResponse.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch(
    "/seo-observations/{observation_id}",
    response_model=SeoObservationResponse,
    summary="Triage an observation",
    description="Set status to open, ignored or resolved, with an optional note.",
    responses=_ERRORS,
)
async def update_observation(
    body: SeoObservationUpdateRequest,
    observation_access: ObservationAccess,
    user: CurrentUser,
    session: DBSession,
    dispatcher: DispatcherDep,
) -> SeoObservationResponse:
    observation, access = observation_access
    _require(access, Permission.DATA_MANAGE)
    updated = await SeoAuditService(session, dispatcher).update_observation_status(
        observation, status=body.status, note=body.note, changed_by=user.id
    )
    return SeoObservationResponse.model_validate(updated)
