"""Builds a fully configured CrawlEngine for a job and runs it.

Used by the Celery task (production) and by tests (with a fake transport
and resolver injected). Keeps construction logic out of the task module.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.crawler.engine import CrawlEngine, CrawlSettings
from app.crawler.fetcher import FetchConfig, Fetcher
from app.crawler.limits import limits_for_plan
from app.crawler.ratelimit import HostPolicy, HostRateLimiter
from app.crawler.safety import Resolver, UrlSafetyPolicy
from app.crawler.storage import HtmlStorage, html_storage_from_settings
from app.crawler.urls import normalize_crawl_url
from app.models.crawl import CrawlJob, CrawlStatus
from app.models.organization import Organization
from app.models.project import Project
from app.repositories.crawl import CrawlJobRepository

log = get_logger("crawler.runner")


@dataclass
class RunnerOptions:
    transport: httpx.AsyncBaseTransport | None = None
    resolver: Resolver | None = None
    storage: HtmlStorage | None = None
    settings: Settings | None = None
    sleep: Callable[..., object] | None = None


async def run_crawl_job(
    session: AsyncSession, job_id: uuid.UUID, options: RunnerOptions | None = None
) -> CrawlJob | None:
    options = options or RunnerOptions()
    settings = options.settings or get_settings()
    jobs = CrawlJobRepository(session)
    job = await jobs.get(job_id)
    if job is None:
        log.warning("crawl_job_missing", crawl_job_id=str(job_id))
        return None
    if job.status != CrawlStatus.QUEUED:
        log.info("crawl_job_not_queued", crawl_job_id=str(job_id), status=job.status.value)
        return job
    if job.cancel_requested:
        job.status = CrawlStatus.CANCELLED
        await session.commit()
        return job

    project = await session.get(Project, job.project_id)
    organization = await session.get(Organization, project.organization_id) if project else None
    if project is None or organization is None:
        job.status = CrawlStatus.FAILED
        job.error_message = "Project or organization no longer exists"
        await session.commit()
        return job

    limits = limits_for_plan(organization.plan, settings)
    root = normalize_crawl_url(job.root_url)
    crawl_settings = CrawlSettings(
        max_pages=min(job.max_pages, limits.max_pages_cap),
        max_depth=min(job.max_depth, limits.max_depth_cap),
        concurrency=max(1, limits.concurrency),
        allowed_hosts=frozenset({root.host}),
        allow_subdomains=limits.allow_subdomains,
        status_check_interval=settings.crawl_status_check_interval,
    )
    fetch_config = FetchConfig(
        user_agent=settings.crawl_user_agent,
        connect_timeout=settings.crawl_connect_timeout_seconds,
        read_timeout=settings.crawl_read_timeout_seconds,
        total_timeout=settings.crawl_total_timeout_seconds,
        max_response_bytes=settings.crawl_max_response_bytes,
        max_redirects=settings.crawl_max_redirects,
        max_retries=settings.crawl_max_retries,
        retry_backoff=settings.crawl_retry_backoff_seconds,
    )
    fetcher_kwargs: dict[str, object] = {"transport": options.transport}
    if options.sleep is not None:
        fetcher_kwargs["sleep"] = options.sleep
    fetcher = Fetcher(fetch_config, UrlSafetyPolicy(options.resolver), **fetcher_kwargs)  # type: ignore[arg-type]
    limiter_kwargs: dict[str, object] = {}
    if options.sleep is not None:
        limiter_kwargs["sleep"] = options.sleep
    limiter = HostRateLimiter(
        HostPolicy(
            concurrency=crawl_settings.concurrency,
            requests_per_second=limits.requests_per_second,
            min_delay_seconds=settings.crawl_min_delay_seconds,
        ),
        **limiter_kwargs,  # type: ignore[arg-type]
    )
    engine = CrawlEngine(
        session=session,
        job=job,
        settings=crawl_settings,
        fetcher=fetcher,
        limiter=limiter,
        user_agent=settings.crawl_user_agent,
        storage=options.storage or html_storage_from_settings(settings),
    )
    try:
        return await engine.run()
    finally:
        await fetcher.aclose()
