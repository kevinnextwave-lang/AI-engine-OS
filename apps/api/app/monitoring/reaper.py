"""Stale-job reaper.

Rows can be stranded in RUNNING when a worker dies in a way nothing can
observe (kernel OOM kill, node loss, a hard time limit landing at the wrong
moment). Every task guards on QUEUED, so a redelivered message won't touch a
RUNNING row — this periodic sweep is the backstop that turns such rows into
FAILED so users can retry (a stuck RUNNING crawl otherwise blocks its project
from ever crawling again).

Thresholds are each job type's hard time limit plus a generous margin, so a
legitimately running job is never reaped.

Rows can also be stranded in QUEUED: the broker loses the message, or the
task fails before the engine ever claims the row (dispatch succeeded but the
worker crashed pre-claim and retries were exhausted). A QUEUED crawl is the
worst case — ACTIVE_CRAWL_STATUSES includes QUEUED, so the project 409s on
every new crawl forever — and a QUEUED prompt run keeps its batch from ever
finalizing. The QUEUED sweep uses created_at (queued rows have no
started_at) with thresholds far above any legitimate queue wait.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.agents import AgentRun, AgentRunStatus
from app.models.ai_readiness import AiReadinessAudit
from app.models.crawl import CrawlJob, CrawlStatus
from app.models.prompts import PromptRun, PromptRunStatus
from app.models.seo import AuditStatus, SeoAudit
from app.repositories.execution import BatchRepository

log = get_logger("monitoring.reaper")

_REAPED_MESSAGE = "Marked as failed by the stale-job reaper: the worker stopped reporting."

# hard time limit + margin
CRAWL_MAX_AGE = timedelta(hours=7)
AUDIT_MAX_AGE = timedelta(hours=1)
PROMPT_RUN_MAX_AGE = timedelta(hours=1)
AGENT_RUN_MAX_AGE = timedelta(hours=1)

# QUEUED ceilings. Crawls/audits/agent runs are dispatched immediately, so
# hours in QUEUED means the message is gone. Prompt runs legitimately wait in
# QUEUED through throttle deferrals during large backlogs, so their ceiling
# is much higher — the point is "eventually finalize the batch", not speed.
QUEUED_MAX_AGE = timedelta(hours=2)
PROMPT_QUEUED_MAX_AGE = timedelta(hours=12)

_QUEUED_MESSAGE = "Marked as failed by the stale-job reaper: never picked up by a worker."


@dataclass
class ReapResult:
    crawls: int = 0
    seo_audits: int = 0
    readiness_audits: int = 0
    prompt_runs: int = 0
    agent_runs: int = 0
    reaped_ids: list[uuid.UUID] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            self.crawls
            + self.seo_audits
            + self.readiness_audits
            + self.prompt_runs
            + self.agent_runs
        )


async def reap_stale_jobs(session: AsyncSession, *, now: datetime | None = None) -> ReapResult:
    """Fail every RUNNING row whose start time is beyond its type's ceiling."""
    now = now or datetime.now(UTC)
    result = ReapResult()

    crawls = (
        await session.scalars(
            select(CrawlJob).where(
                CrawlJob.status == CrawlStatus.RUNNING,
                CrawlJob.started_at < now - CRAWL_MAX_AGE,
            )
        )
    ).all()
    for job in crawls:
        job.status = CrawlStatus.FAILED
        job.error_message = _REAPED_MESSAGE
        job.completed_at = now
        result.crawls += 1
        result.reaped_ids.append(job.id)

    seo_rows = (
        await session.scalars(
            select(SeoAudit).where(
                SeoAudit.status == AuditStatus.RUNNING,
                SeoAudit.started_at < now - AUDIT_MAX_AGE,
            )
        )
    ).all()
    for seo_audit in seo_rows:
        seo_audit.status = AuditStatus.FAILED
        seo_audit.error_message = _REAPED_MESSAGE
        seo_audit.completed_at = now
        result.seo_audits += 1
        result.reaped_ids.append(seo_audit.id)

    readiness_rows = (
        await session.scalars(
            select(AiReadinessAudit).where(
                AiReadinessAudit.status == AuditStatus.RUNNING,
                AiReadinessAudit.started_at < now - AUDIT_MAX_AGE,
            )
        )
    ).all()
    for readiness_audit in readiness_rows:
        readiness_audit.status = AuditStatus.FAILED
        readiness_audit.error_message = _REAPED_MESSAGE
        readiness_audit.completed_at = now
        result.readiness_audits += 1
        result.reaped_ids.append(readiness_audit.id)

    batches = BatchRepository(session)
    runs = (
        await session.scalars(
            select(PromptRun).where(
                PromptRun.status == PromptRunStatus.RUNNING,
                PromptRun.started_at < now - PROMPT_RUN_MAX_AGE,
            )
        )
    ).all()
    for run in runs:
        run.status = PromptRunStatus.FAILED
        run.error_code = "worker_lost"
        run.error_message = _REAPED_MESSAGE
        run.completed_at = now
        result.prompt_runs += 1
        result.reaped_ids.append(run.id)
        if run.batch_id is not None:
            # Keep the batch counters honest so the batch can finalize.
            await batches.record_outcome(run.batch_id, PromptRunStatus.FAILED)

    agent_runs = (
        await session.scalars(
            select(AgentRun).where(
                AgentRun.status == AgentRunStatus.RUNNING.value,
                AgentRun.started_at < now - AGENT_RUN_MAX_AGE,
            )
        )
    ).all()
    for arun in agent_runs:
        arun.status = AgentRunStatus.FAILED.value
        arun.error_message = _REAPED_MESSAGE
        arun.completed_at = now
        result.agent_runs += 1
        result.reaped_ids.append(arun.id)

    # --- QUEUED sweeps: rows whose message never reached a worker. ---

    stale_queued_crawls = (
        await session.scalars(
            select(CrawlJob).where(
                CrawlJob.status == CrawlStatus.QUEUED,
                CrawlJob.created_at < now - QUEUED_MAX_AGE,
            )
        )
    ).all()
    for job in stale_queued_crawls:
        job.status = CrawlStatus.FAILED
        job.error_message = _QUEUED_MESSAGE
        job.completed_at = now
        result.crawls += 1
        result.reaped_ids.append(job.id)

    stale_queued_seo = (
        await session.scalars(
            select(SeoAudit).where(
                SeoAudit.status == AuditStatus.QUEUED,
                SeoAudit.created_at < now - QUEUED_MAX_AGE,
            )
        )
    ).all()
    for seo_audit in stale_queued_seo:
        seo_audit.status = AuditStatus.FAILED
        seo_audit.error_message = _QUEUED_MESSAGE
        seo_audit.completed_at = now
        result.seo_audits += 1
        result.reaped_ids.append(seo_audit.id)

    stale_queued_readiness = (
        await session.scalars(
            select(AiReadinessAudit).where(
                AiReadinessAudit.status == AuditStatus.QUEUED,
                AiReadinessAudit.created_at < now - QUEUED_MAX_AGE,
            )
        )
    ).all()
    for readiness_audit in stale_queued_readiness:
        readiness_audit.status = AuditStatus.FAILED
        readiness_audit.error_message = _QUEUED_MESSAGE
        readiness_audit.completed_at = now
        result.readiness_audits += 1
        result.reaped_ids.append(readiness_audit.id)

    stale_queued_runs = (
        await session.scalars(
            select(PromptRun).where(
                PromptRun.status == PromptRunStatus.QUEUED,
                PromptRun.created_at < now - PROMPT_QUEUED_MAX_AGE,
            )
        )
    ).all()
    for run in stale_queued_runs:
        run.status = PromptRunStatus.FAILED
        run.error_code = "never_started"
        run.error_message = _QUEUED_MESSAGE
        run.completed_at = now
        result.prompt_runs += 1
        result.reaped_ids.append(run.id)
        if run.batch_id is not None:
            await batches.record_outcome(run.batch_id, PromptRunStatus.FAILED)

    stale_queued_agents = (
        await session.scalars(
            select(AgentRun).where(
                AgentRun.status == AgentRunStatus.QUEUED.value,
                AgentRun.created_at < now - QUEUED_MAX_AGE,
            )
        )
    ).all()
    for arun in stale_queued_agents:
        arun.status = AgentRunStatus.FAILED.value
        arun.error_message = _QUEUED_MESSAGE
        arun.completed_at = now
        result.agent_runs += 1
        result.reaped_ids.append(arun.id)

    await session.commit()
    if result.total:
        log.warning(
            "stale_jobs_reaped",
            crawls=result.crawls,
            seo_audits=result.seo_audits,
            readiness_audits=result.readiness_audits,
            prompt_runs=result.prompt_runs,
            agent_runs=result.agent_runs,
        )
    return result
