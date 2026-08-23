"""Competitive AI alerts (Milestone 5F).

Project-scoped list/detect use `require_project_access`; the alert PATCH
derives the project from the row (non-members 404). DATA_READ for reads,
DATA_MANAGE to detect; marking read/dismissed only needs DATA_READ (it is a
per-user-facing inbox action, but stored per project).
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import select

from app.alerts.engine import CompetitiveAlertEngine
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
from app.models.alerts import AlertSeverity, AlertStatus, AlertType, CompetitiveAlert
from app.schemas.alerts import (
    AlertDetectRequest,
    AlertDetectResponse,
    AlertListResponse,
    AlertUpdateRequest,
    AlertView,
)

project_router = APIRouter(prefix="/projects/{project_id}/competitive-alerts", tags=["alerts"])
alert_router = APIRouter(prefix="/competitive-alerts/{alert_id}", tags=["alerts"])

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"description": "Not authenticated"},
    403: {"description": "Role lacks permission"},
    404: {"description": "Not found, or not a member of the owning organization"},
}
ReadAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_READ))]
ManageAccess = Annotated[ProjectAccess, Depends(require_project_access(Permission.DATA_MANAGE))]

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@project_router.get(
    "",
    response_model=AlertListResponse,
    summary="Competitive alerts for a project",
    responses=_ERRORS,
)
async def list_alerts(
    access: ReadAccess,
    session: DBSession,
    status: Annotated[AlertStatus | None, Query()] = None,
    alert_type: Annotated[AlertType | None, Query()] = None,
    severity: Annotated[AlertSeverity | None, Query()] = None,
    competitor_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AlertListResponse:
    stmt = select(CompetitiveAlert).where(CompetitiveAlert.project_id == access.project.id)
    if status is not None:
        stmt = stmt.where(CompetitiveAlert.status == status.value)
    if alert_type is not None:
        stmt = stmt.where(CompetitiveAlert.alert_type == alert_type.value)
    if severity is not None:
        stmt = stmt.where(CompetitiveAlert.severity == severity.value)
    if competitor_id is not None:
        stmt = stmt.where(CompetitiveAlert.competitor_id == competitor_id)
    rows = list((await session.scalars(stmt)).all())
    rows.sort(
        key=lambda r: (_SEVERITY_ORDER.get(r.severity, 4), -r.detected_at.timestamp(), r.title)
    )
    unread = sum(1 for r in rows if r.status == AlertStatus.NEW.value)
    page = rows[offset : offset + limit]
    return AlertListResponse(
        items=[AlertView.model_validate(r) for r in page],
        total=len(rows),
        unread=unread,
        limit=limit,
        offset=offset,
        detected_at=max((r.detected_at for r in rows), default=None),
    )


@project_router.post(
    "/detect",
    response_model=AlertDetectResponse,
    summary="Run alert detection (configurable thresholds; deduplicated)",
    responses=_ERRORS,
)
async def detect_alerts(
    access: ManageAccess, session: DBSession, body: AlertDetectRequest | None = None
) -> AlertDetectResponse:
    body = body or AlertDetectRequest()
    result = await CompetitiveAlertEngine(session).detect(
        access.project.id, window_days=body.window_days, thresholds=body.thresholds
    )
    await session.commit()
    return AlertDetectResponse(**result.__dict__)


async def get_alert_access(
    session: DBSession, user: CurrentUser, alert_id: Annotated[uuid.UUID, Path()]
) -> tuple[CompetitiveAlert, ProjectAccess]:
    alert = (
        await session.scalars(select(CompetitiveAlert).where(CompetitiveAlert.id == alert_id))
    ).one_or_none()
    if alert is None:
        raise NotFoundError("Alert not found")
    access = await get_project_access(session, user, alert.project_id)
    return alert, access


AlertAccess = Annotated[tuple[CompetitiveAlert, ProjectAccess], Depends(get_alert_access)]


@alert_router.get("", response_model=AlertView, summary="Get an alert", responses=_ERRORS)
async def get_alert(alert_access: AlertAccess) -> AlertView:
    alert, access = alert_access
    _require(access, Permission.DATA_READ)
    return AlertView.model_validate(alert)


@alert_router.patch(
    "",
    response_model=AlertView,
    summary="Mark an alert read / dismissed (or back to new)",
    responses=_ERRORS,
)
async def update_alert(
    alert_access: AlertAccess, body: AlertUpdateRequest, session: DBSession
) -> AlertView:
    alert, access = alert_access
    _require(access, Permission.DATA_READ)
    alert.status = body.status.value
    await session.commit()
    await session.refresh(alert)
    return AlertView.model_validate(alert)
