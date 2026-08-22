"""AI search readiness audit endpoints.

Authorization mirrors the SEO audit routes: project from the path for the
collection, project derived from the audit row for the item; DATA_MANAGE to
start, DATA_READ to read; foreign audits are 404.
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
from app.models.ai_readiness import AiReadinessAudit, ReadinessCategory
from app.models.seo import Severity
from app.repositories.ai_readiness import AiReadinessAuditRepository
from app.schemas.ai_readiness import (
    AiReadinessAuditDetailResponse,
    AiReadinessAuditListResponse,
    AiReadinessAuditResponse,
    AiReadinessObservationResponse,
)
from app.services.ai_readiness import AiReadinessService, Dispatcher
from app.workers.tasks import dispatch_ai_readiness_audit

project_router = APIRouter(
    prefix="/projects/{project_id}/ai-readiness-audits", tags=["ai-readiness"]
)
router = APIRouter(prefix="/ai-readiness-audits", tags=["ai-readiness"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
}


def get_readiness_dispatcher() -> Dispatcher:
    return dispatch_ai_readiness_audit


DispatcherDep = Annotated[Dispatcher, Depends(get_readiness_dispatcher)]


async def get_audit_access(
    session: DBSession, user: CurrentUser, audit_id: Annotated[uuid.UUID, Path()]
) -> tuple[AiReadinessAudit, ProjectAccess]:
    audit = await AiReadinessAuditRepository(session).get(audit_id)
    if audit is None:
        raise NotFoundError("AI readiness audit not found")
    access = await get_project_access(session, user, audit.project_id)
    if not role_has(access.membership.role, Permission.DATA_READ):
        raise PermissionDeniedError()
    return audit, access


AuditAccess = Annotated[tuple[AiReadinessAudit, ProjectAccess], Depends(get_audit_access)]


@project_router.post(
    "",
    response_model=AiReadinessAuditResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start an AI readiness audit",
    description=(
        "Queues a deterministic analysis of the crawled pages, page intelligence and entity "
        "layer. No external AI system is queried. Requires at least one crawled page."
    ),
    responses={**_ERRORS, 422: {"description": "Project has no crawled pages"}},
)
async def start_audit(
    access: Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_MANAGE))],
    user: CurrentUser,
    session: DBSession,
    dispatcher: DispatcherDep,
) -> AiReadinessAuditResponse:
    audit = await AiReadinessService(session, dispatcher).start(
        project=access.project, requested_by=user.id
    )
    return AiReadinessAuditResponse.model_validate(audit)


@project_router.get(
    "",
    response_model=AiReadinessAuditListResponse,
    summary="List a project's AI readiness audits",
    responses=_ERRORS,
)
async def list_audits(
    access: Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))],
    session: DBSession,
    dispatcher: DispatcherDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AiReadinessAuditListResponse:
    audits, total = await AiReadinessService(session, dispatcher).list_for_project(
        access.project, limit=limit, offset=offset
    )
    return AiReadinessAuditListResponse(
        items=[AiReadinessAuditResponse.model_validate(a) for a in audits], total=total
    )


@router.get(
    "/{audit_id}",
    response_model=AiReadinessAuditDetailResponse,
    summary="Get an AI readiness audit with its observations",
    description="Observations are ordered by severity; filter with `category` and `severity`.",
    responses=_ERRORS,
)
async def get_audit(
    audit_access: AuditAccess,
    session: DBSession,
    dispatcher: DispatcherDep,
    category: Annotated[ReadinessCategory | None, Query()] = None,
    severity: Annotated[Severity | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AiReadinessAuditDetailResponse:
    audit, _ = audit_access
    rows, total = await AiReadinessService(session, dispatcher).observations(
        audit, category=category, severity=severity, limit=limit, offset=offset
    )
    base = AiReadinessAuditResponse.model_validate(audit).model_dump()
    return AiReadinessAuditDetailResponse(
        **base,
        observations=[AiReadinessObservationResponse.model_validate(r) for r in rows],
        observations_total=total,
    )
