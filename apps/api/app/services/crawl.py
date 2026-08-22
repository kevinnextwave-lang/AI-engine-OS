"""Crawl job lifecycle: start, list, inspect, cancel.

Starting a crawl creates the job row, COMMITS, then dispatches to the worker.
The dispatcher is injected so the API layer (and tests) control how jobs are
enqueued; the engine itself never runs inside a request.
"""

import uuid
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.crawler.limits import limits_for_plan
from app.crawler.urls import CrawlURLError, normalize_crawl_url, same_site
from app.models.crawl import CrawlJob, CrawlStatus, CrawlType, CrawlUrl, CrawlUrlStatus
from app.models.organization import Organization
from app.models.project import Project
from app.repositories.crawl import CrawlJobRepository, CrawlUrlRepository, WebsitePageRepository
from app.repositories.projects import DomainRepository

log = get_logger(__name__)

Dispatcher = Callable[[uuid.UUID], None]


class CrawlService:
    def __init__(self, session: AsyncSession, dispatcher: Dispatcher) -> None:
        self._session = session
        self._dispatch = dispatcher
        self._jobs = CrawlJobRepository(session)
        self._urls = CrawlUrlRepository(session)
        self._pages = WebsitePageRepository(session)
        self._domains = DomainRepository(session)
        self._settings = get_settings()

    async def start(
        self,
        *,
        project: Project,
        organization: Organization,
        requested_by: uuid.UUID,
        crawl_type: CrawlType,
        max_pages: int | None,
        max_depth: int | None,
        url: str | None,
    ) -> CrawlJob:
        if await self._jobs.active_for_project(project.id):
            raise ConflictError("A crawl is already queued or running for this project")

        domains = await self._domains.list_for_project(project.id)
        if not domains:
            raise ValidationAppError("Project has no domains to crawl")
        primary = next((d for d in domains if d.is_primary), domains[0])
        root_url = url or primary.url
        try:
            root = normalize_crawl_url(root_url)
        except CrawlURLError as exc:
            raise ValidationAppError(f"Invalid start URL: {exc}") from exc
        allowed = {d.hostname for d in domains}
        if not any(
            same_site(root.host, host, allow_subdomains=self._settings.crawl_allow_subdomains)
            for host in allowed
        ):
            raise ValidationAppError(
                "Start URL must be on one of the project's domains",
                details=[{"loc": ["body", "url"], "msg": f"{root.host} is not a project domain"}],
            )

        limits = limits_for_plan(organization.plan, self._settings)
        if crawl_type == CrawlType.SINGLE_PAGE:
            effective_pages, effective_depth = 1, 0
        else:
            effective_pages = min(
                max_pages or self._settings.crawl_default_max_pages, limits.max_pages_cap
            )
            effective_depth = min(
                max_depth if max_depth is not None else self._settings.crawl_default_max_depth,
                limits.max_depth_cap,
            )

        job = CrawlJob(
            project_id=project.id,
            root_url=root.normalized,
            crawl_type=crawl_type,
            max_pages=effective_pages,
            max_depth=effective_depth,
            requested_by_user_id=requested_by,
            config={"plan": organization.plan.value, "allowed_hosts": sorted(allowed)},
        )
        await self._jobs.add(job)
        # Commit BEFORE dispatch so the worker can see the row (and so a failed
        # commit never leaves a phantom queued task).
        await self._session.commit()
        try:
            self._dispatch(job.id)
        except Exception as exc:  # noqa: BLE001 - broker outage must not strand the job as "queued"
            log.exception("crawl_dispatch_failed", crawl_job_id=str(job.id))
            job.status = CrawlStatus.FAILED
            job.error_message = f"Could not enqueue crawl: {type(exc).__name__}"
            await self._session.commit()
        await self._session.refresh(job)  # DB-side timestamps
        log.info("crawl_requested", crawl_job_id=str(job.id), project_id=str(project.id))
        return job

    async def list_for_project(
        self, project: Project, *, limit: int, offset: int
    ) -> tuple[list[CrawlJob], int]:
        return await self._jobs.list_for_project(project.id, limit=limit, offset=offset)

    async def cancel(self, job: CrawlJob) -> CrawlJob:
        if not job.is_active:
            raise ConflictError(f"Crawl is already {job.status.value}")
        await self._jobs.request_cancel(job)
        await self._session.commit()
        await self._session.refresh(job)
        log.info("crawl_cancel_requested", crawl_job_id=str(job.id))
        return job

    async def list_urls(
        self, job: CrawlJob, *, status: CrawlUrlStatus | None, limit: int, offset: int
    ) -> tuple[list[CrawlUrl], int, dict[uuid.UUID, object]]:
        rows, total = await self._urls.list_for_job(
            job.id, status=status, limit=limit, offset=offset
        )
        pages = await self._pages.get_many([r.page_id for r in rows if r.page_id])
        return rows, total, dict(pages)

    async def get_for_project(self, project_id: uuid.UUID, job_id: uuid.UUID) -> CrawlJob:
        job = await self._jobs.get_in_project(project_id, job_id)
        if job is None:
            raise NotFoundError("Crawl job not found")
        return job
