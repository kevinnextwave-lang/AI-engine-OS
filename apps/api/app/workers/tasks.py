"""Celery tasks. Crawling runs here, never inside HTTP requests."""

import asyncio
import uuid

from app.core.logging import configure_logging, get_logger
from app.workers.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="app.workers.tasks.ping")
def ping() -> str:
    log.info("worker_ping")
    return "pong"


@celery_app.task(
    name="app.workers.tasks.crawler.run_crawl_job",
    bind=True,
    acks_late=True,
    max_retries=0,
    soft_time_limit=60 * 60 * 6,
    time_limit=60 * 60 * 6 + 60,
)
def run_crawl_job_task(self, job_id: str) -> str:  # type: ignore[no-untyped-def]
    """Run one crawl job to completion in its own event loop and DB session."""
    configure_logging()

    async def _main() -> str:
        from app.crawler.runner import run_crawl_job
        from app.db.session import dispose_engine, get_session_factory
        from app.models.crawl import CrawlStatus

        try:
            async with get_session_factory()() as session:
                job = await run_crawl_job(session, uuid.UUID(job_id))
                if job is not None and job.status in (
                    CrawlStatus.COMPLETED,
                    CrawlStatus.PARTIALLY_COMPLETED,
                ):
                    dispatch_entity_analysis(job.project_id)
                return job.status.value if job else "missing"
        finally:
            await dispose_engine()

    return asyncio.run(_main())


def dispatch_crawl_job(job_id: uuid.UUID) -> None:
    """Enqueue a crawl. Callers must have COMMITTED the job row first."""
    run_crawl_job_task.apply_async(args=(str(job_id),), queue="crawler")


@celery_app.task(
    name="app.workers.tasks.analytics.run_seo_audit",
    bind=True,
    acks_late=True,
    max_retries=0,
    soft_time_limit=60 * 30,
    time_limit=60 * 30 + 60,
)
def run_seo_audit_task(self, audit_id: str) -> str:  # type: ignore[no-untyped-def]
    """Run one technical SEO audit over an existing crawl's data."""
    configure_logging()

    async def _main() -> str:
        from app.db.session import dispose_engine, get_session_factory
        from app.models.seo import AuditStatus, SeoAudit
        from app.seo.engine import run_audit

        try:
            async with get_session_factory()() as session:
                audit = await session.get(SeoAudit, uuid.UUID(audit_id))
                if audit is None:
                    log.warning("seo_audit_missing", audit_id=audit_id)
                    return "missing"
                if audit.status != AuditStatus.QUEUED:
                    return audit.status.value
                audit = await run_audit(session, audit)
                return audit.status.value
        finally:
            await dispose_engine()

    return asyncio.run(_main())


def dispatch_seo_audit(audit_id: uuid.UUID) -> None:
    """Enqueue an SEO audit. Callers must have COMMITTED the audit row first."""
    run_seo_audit_task.apply_async(args=(str(audit_id),), queue="analytics")


@celery_app.task(
    name="app.workers.tasks.analytics.run_entity_analysis",
    bind=True,
    acks_late=True,
    max_retries=0,
    soft_time_limit=60 * 30,
    time_limit=60 * 30 + 60,
)
def run_entity_analysis_task(self, project_id: str) -> str:  # type: ignore[no-untyped-def]
    """Rebuild a project's structured-data entities, issues and consistency observations."""
    configure_logging()

    async def _main() -> str:
        from app.db.session import dispose_engine, get_session_factory
        from app.entities.engine import run_entity_analysis

        try:
            async with get_session_factory()() as session:
                try:
                    result = await run_entity_analysis(session, uuid.UUID(project_id))
                except ValueError as exc:
                    log.warning("entity_analysis_skipped", project_id=project_id, reason=str(exc))
                    return "missing"
                return f"entities={result.entities} observations={result.observations}"
        finally:
            await dispose_engine()

    return asyncio.run(_main())


def dispatch_entity_analysis(project_id: uuid.UUID) -> None:
    """Enqueue an entity analysis for a project (idempotent rebuild)."""
    run_entity_analysis_task.apply_async(args=(str(project_id),), queue="analytics")


@celery_app.task(
    name="app.workers.tasks.analytics.run_ai_readiness_audit",
    bind=True,
    acks_late=True,
    max_retries=0,
    soft_time_limit=60 * 30,
    time_limit=60 * 30 + 60,
)
def run_ai_readiness_audit_task(self, audit_id: str) -> str:  # type: ignore[no-untyped-def]
    """Run one AI readiness audit over the project's stored crawl and entity data."""
    configure_logging()

    async def _main() -> str:
        from app.ai_readiness.engine import run_readiness_audit
        from app.db.session import dispose_engine, get_session_factory
        from app.models.ai_readiness import AiReadinessAudit
        from app.models.seo import AuditStatus

        try:
            async with get_session_factory()() as session:
                audit = await session.get(AiReadinessAudit, uuid.UUID(audit_id))
                if audit is None:
                    log.warning("ai_readiness_audit_missing", audit_id=audit_id)
                    return "missing"
                if audit.status != AuditStatus.QUEUED:
                    return audit.status.value
                audit = await run_readiness_audit(session, audit)
                return audit.status.value
        finally:
            await dispose_engine()

    return asyncio.run(_main())


def dispatch_ai_readiness_audit(audit_id: uuid.UUID) -> None:
    """Enqueue an AI readiness audit. Callers must have COMMITTED the audit row first."""
    run_ai_readiness_audit_task.apply_async(args=(str(audit_id),), queue="analytics")


@celery_app.task(
    name="app.workers.tasks.ai_search.run_prompt",
    bind=True,
    acks_late=True,
    max_retries=None,  # attempts are bounded by AI_RUN_MAX_ATTEMPTS inside execute_prompt_run
    soft_time_limit=60 * 10,
    time_limit=60 * 10 + 30,
)
def run_prompt_run_task(self, run_id: str) -> str:  # type: ignore[no-untyped-def]
    """Execute one prompt run. Retries with backoff are driven by the executor's
    Outcome so the worker never sleeps while waiting on a provider."""
    configure_logging()

    async def _main() -> tuple[str, float | None]:
        from redis.asyncio import Redis

        from app.ai.execution import execute_prompt_run
        from app.ai.registry import ProviderRegistry
        from app.ai.throttle import RedisProviderThrottle
        from app.core.config import get_settings
        from app.db.session import dispose_engine, get_session_factory

        settings = get_settings()
        redis = Redis.from_url(settings.redis_url)
        try:
            async with get_session_factory()() as session:
                outcome = await execute_prompt_run(
                    session,
                    uuid.UUID(run_id),
                    ProviderRegistry(settings),
                    RedisProviderThrottle(redis),
                )
                return (outcome.status.value if outcome.status else "skipped"), outcome.retry_in
        finally:
            await redis.aclose()
            await dispose_engine()

    status, retry_in = asyncio.run(_main())
    if retry_in is not None:
        raise self.retry(countdown=retry_in)
    return status


def dispatch_prompt_run(run_id: uuid.UUID, priority: int = 5) -> None:
    """Enqueue one prompt run. Callers must have COMMITTED the run row first."""
    run_prompt_run_task.apply_async(args=(str(run_id),), queue="ai_search", priority=priority)


@celery_app.task(
    name="app.workers.tasks.analytics.backfill_sources",
    bind=True,
    acks_late=True,
    max_retries=0,
    soft_time_limit=60 * 60,
    time_limit=60 * 60 + 60,
)
def backfill_sources_task(self, project_id: str | None = None, force: bool = False) -> str:  # type: ignore[no-untyped-def]
    """Citation Intelligence backfill: resolve historical citations into
    source_domains / source_pages / project_sources. No AI calls."""
    configure_logging()

    async def _main() -> str:
        from app.db.session import dispose_engine, get_session_factory
        from app.sources.service import SourceIntelligenceService

        try:
            async with get_session_factory()() as session:
                stats = await SourceIntelligenceService(session).backfill(
                    project_id=uuid.UUID(project_id) if project_id else None, force=force
                )
                return f"resolved={stats.resolved} skipped={stats.skipped}"
        finally:
            await dispose_engine()

    return asyncio.run(_main())


def dispatch_source_backfill(project_id: uuid.UUID | None = None, *, force: bool = False) -> None:
    backfill_sources_task.apply_async(
        kwargs={"project_id": str(project_id) if project_id else None, "force": force},
        queue="analytics",
    )


@celery_app.task(
    name="app.workers.tasks.analytics.analyze_citation_gaps",
    bind=True,
    acks_late=True,
    max_retries=0,
    soft_time_limit=60 * 20,
    time_limit=60 * 20 + 60,
)
def analyze_citation_gaps_task(self, project_id: str, window_days: int = 90) -> str:  # type: ignore[no-untyped-def]
    """Recompute one project's citation gaps from stored citations (no AI calls)."""
    configure_logging()

    async def _main() -> str:
        from app.db.session import dispose_engine, get_session_factory
        from app.gaps.engine import CitationGapEngine

        try:
            async with get_session_factory()() as session:
                result = await CitationGapEngine(session).analyze(
                    uuid.UUID(project_id), window_days=window_days
                )
                await session.commit()
                return f"sources={result.sources_observed} written={result.gaps_written}"
        finally:
            await dispose_engine()

    return asyncio.run(_main())


def dispatch_citation_gap_analysis(project_id: uuid.UUID, *, window_days: int = 90) -> None:
    analyze_citation_gaps_task.apply_async(
        kwargs={"project_id": str(project_id), "window_days": window_days}, queue="analytics"
    )
