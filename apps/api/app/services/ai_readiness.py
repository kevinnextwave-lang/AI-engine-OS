"""AI readiness audit lifecycle: start (commit, then dispatch), list, get."""

import uuid
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationAppError
from app.core.logging import get_logger
from app.models.ai_readiness import AiReadinessAudit, AiReadinessObservation, ReadinessCategory
from app.models.project import Project
from app.models.seo import AuditStatus, Severity
from app.repositories.ai_readiness import AiReadinessAuditRepository
from app.repositories.crawl import WebsitePageRepository

log = get_logger(__name__)

Dispatcher = Callable[[uuid.UUID], None]


class AiReadinessService:
    def __init__(self, session: AsyncSession, dispatcher: Dispatcher) -> None:
        self._session = session
        self._dispatch = dispatcher
        self._audits = AiReadinessAuditRepository(session)
        self._pages = WebsitePageRepository(session)

    async def start(self, *, project: Project, requested_by: uuid.UUID) -> AiReadinessAudit:
        if not await self._pages.count_for_project(project.id):
            raise ValidationAppError("Project has no crawled pages to analyze")
        audit = AiReadinessAudit(project_id=project.id, requested_by_user_id=requested_by)
        await self._audits.add(audit)
        await self._session.commit()
        try:
            self._dispatch(audit.id)
        except Exception as exc:  # noqa: BLE001 - broker outage must not strand the audit
            log.exception("ai_readiness_dispatch_failed", audit_id=str(audit.id))
            audit.status = AuditStatus.FAILED
            audit.error_message = f"Could not enqueue audit: {type(exc).__name__}"
            await self._session.commit()
        await self._session.refresh(audit)
        log.info("ai_readiness_requested", audit_id=str(audit.id), project_id=str(project.id))
        return audit

    async def list_for_project(
        self, project: Project, *, limit: int, offset: int
    ) -> tuple[list[AiReadinessAudit], int]:
        return await self._audits.list_for_project(project.id, limit=limit, offset=offset)

    async def observations(
        self,
        audit: AiReadinessAudit,
        *,
        category: ReadinessCategory | None,
        severity: Severity | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AiReadinessObservation], int]:
        return await self._audits.observations(
            audit.id, category=category, severity=severity, limit=limit, offset=offset
        )
