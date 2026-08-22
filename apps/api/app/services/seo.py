"""Technical SEO audit lifecycle: start, list, inspect, triage observations.

Same shape as CrawlService: the audit row is COMMITTED before the worker is
dispatched, and a dispatch failure marks the audit failed instead of leaving
it queued forever. The analysis itself runs in app.seo.engine on a worker.
"""

import uuid
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.models.crawl import CrawlJob, CrawlStatus
from app.models.project import Project
from app.models.seo import (
    AuditStatus,
    ObservationCategory,
    ObservationStatus,
    SeoAudit,
    SeoObservation,
    Severity,
)
from app.repositories.crawl import CrawlJobRepository
from app.repositories.seo import SeoAuditRepository, SeoObservationRepository

log = get_logger(__name__)

Dispatcher = Callable[[uuid.UUID], None]

AUDITABLE_CRAWL_STATUSES = frozenset({CrawlStatus.COMPLETED, CrawlStatus.PARTIALLY_COMPLETED})


class SeoAuditService:
    def __init__(self, session: AsyncSession, dispatcher: Dispatcher) -> None:
        self._session = session
        self._dispatch = dispatcher
        self._audits = SeoAuditRepository(session)
        self._observations = SeoObservationRepository(session)
        self._jobs = CrawlJobRepository(session)

    async def _resolve_crawl_job(
        self, project: Project, crawl_job_id: uuid.UUID | None
    ) -> CrawlJob:
        if crawl_job_id is not None:
            job = await self._jobs.get_in_project(project.id, crawl_job_id)
            if job is None:
                raise NotFoundError("Crawl job not found")
            if job.status not in AUDITABLE_CRAWL_STATUSES:
                raise ConflictError(f"Crawl job is {job.status.value}; it must have finished")
            return job
        jobs, _ = await self._jobs.list_for_project(project.id, limit=50, offset=0)
        for job in jobs:  # newest first
            if job.status in AUDITABLE_CRAWL_STATUSES:
                return job
        raise ValidationAppError("Project has no completed crawl to audit")

    async def start(
        self, *, project: Project, requested_by: uuid.UUID, crawl_job_id: uuid.UUID | None
    ) -> SeoAudit:
        job = await self._resolve_crawl_job(project, crawl_job_id)
        audit = SeoAudit(
            project_id=project.id, crawl_job_id=job.id, requested_by_user_id=requested_by
        )
        await self._audits.add(audit)
        await self._session.commit()
        try:
            self._dispatch(audit.id)
        except Exception as exc:  # noqa: BLE001 - broker outage must not strand the audit
            log.exception("seo_audit_dispatch_failed", audit_id=str(audit.id))
            audit.status = AuditStatus.FAILED
            audit.error_message = f"Could not enqueue audit: {type(exc).__name__}"
            await self._session.commit()
        await self._session.refresh(audit)
        log.info("seo_audit_requested", audit_id=str(audit.id), project_id=str(project.id))
        return audit

    async def list_for_project(
        self, project: Project, *, limit: int, offset: int
    ) -> tuple[list[SeoAudit], int]:
        return await self._audits.list_for_project(project.id, limit=limit, offset=offset)

    async def list_observations(
        self,
        audit: SeoAudit,
        *,
        category: ObservationCategory | None,
        severity: Severity | None,
        status: ObservationStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[SeoObservation], int]:
        return await self._observations.list_for_audit(
            audit.id,
            category=category,
            severity=severity,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def update_observation_status(
        self,
        observation: SeoObservation,
        *,
        status: ObservationStatus,
        note: str | None,
        changed_by: uuid.UUID,
    ) -> SeoObservation:
        observation.status = status
        observation.status_note = note
        observation.status_changed_by_user_id = changed_by
        await self._session.commit()
        await self._session.refresh(observation)
        return observation
