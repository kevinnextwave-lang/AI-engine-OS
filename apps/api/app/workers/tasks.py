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

        try:
            async with get_session_factory()() as session:
                job = await run_crawl_job(session, uuid.UUID(job_id))
                return job.status.value if job else "missing"
        finally:
            await dispose_engine()

    return asyncio.run(_main())


def dispatch_crawl_job(job_id: uuid.UUID) -> None:
    """Enqueue a crawl. Callers must have COMMITTED the job row first."""
    run_crawl_job_task.apply_async(args=(str(job_id),), queue="crawler")
