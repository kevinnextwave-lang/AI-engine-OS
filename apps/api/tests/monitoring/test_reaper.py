"""Stale-job reaper: RUNNING rows past their ceiling become FAILED; fresh ones don't."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CrawlJob, CrawlStatus, CrawlType, Organization, Project
from app.models.ai import AiModel, AiProvider
from app.models.prompts import (
    BatchStatus,
    FunnelStage,
    Prompt,
    PromptCategory,
    PromptIntent,
    PromptRun,
    PromptRunBatch,
    PromptRunStatus,
    PromptSet,
)
from app.monitoring.reaper import reap_stale_jobs

NOW = datetime.now(UTC)


async def _project(session: AsyncSession) -> Project:
    org = Organization(name="Reap Co", slug=f"reap-{uuid.uuid4().hex[:8]}")
    project = Project(organization=org, name="Site", slug=f"site-{uuid.uuid4().hex[:6]}")
    session.add(project)
    await session.flush()
    return project


def _crawl(project: Project, *, started_hours_ago: float, status: CrawlStatus) -> CrawlJob:
    return CrawlJob(
        project_id=project.id,
        root_url="https://example.com/",
        crawl_type=CrawlType.FULL,
        max_pages=10,
        max_depth=2,
        status=status,
        started_at=NOW - timedelta(hours=started_hours_ago),
    )


async def test_reaper_fails_stale_running_jobs_only(db_session: AsyncSession) -> None:
    # Separate projects: the DB now enforces one active crawl per project.
    project = await _project(db_session)
    other = await _project(db_session)
    stale = _crawl(project, started_hours_ago=8, status=CrawlStatus.RUNNING)
    fresh = _crawl(other, started_hours_ago=1, status=CrawlStatus.RUNNING)
    done = _crawl(project, started_hours_ago=30, status=CrawlStatus.COMPLETED)
    db_session.add_all([stale, fresh, done])
    await db_session.flush()

    result = await reap_stale_jobs(db_session, now=NOW)

    assert result.crawls == 1
    assert stale.id in result.reaped_ids
    assert stale.status == CrawlStatus.FAILED
    assert stale.error_message is not None and "reaper" in stale.error_message
    assert fresh.status == CrawlStatus.RUNNING
    assert done.status == CrawlStatus.COMPLETED


async def test_reaper_finalizes_batch_counters(db_session: AsyncSession) -> None:
    project = await _project(db_session)
    provider = AiProvider(provider_key=f"prov-{uuid.uuid4().hex[:6]}", name="P")
    db_session.add(provider)
    await db_session.flush()
    model = AiModel(provider_id=provider.id, model_key="m1", display_name="M1")
    prompt_set = PromptSet(project_id=project.id, name="Set")
    db_session.add_all([model, prompt_set])
    await db_session.flush()
    prompt = Prompt(
        prompt_set_id=prompt_set.id,
        project_id=project.id,
        text="best tool?",
        normalized_text="best tool?",
        intent=PromptIntent.INFORMATIONAL,
        category=PromptCategory.DISCOVERY,
        funnel_stage=FunnelStage.AWARENESS,
    )
    db_session.add(prompt)
    await db_session.flush()
    batch = PromptRunBatch(
        project_id=project.id, prompt_set_id=prompt_set.id, total_runs=1, status=BatchStatus.RUNNING
    )
    db_session.add(batch)
    await db_session.flush()
    run = PromptRun(
        prompt_id=prompt.id,
        project_id=project.id,
        batch_id=batch.id,
        provider_id=provider.id,
        model_id=model.id,
        provider_key=provider.provider_key,
        model_key=model.model_key,
        status=PromptRunStatus.RUNNING,
        started_at=NOW - timedelta(hours=2),
    )
    db_session.add(run)
    await db_session.flush()

    result = await reap_stale_jobs(db_session, now=NOW)

    assert result.prompt_runs == 1
    assert run.status == PromptRunStatus.FAILED
    await db_session.refresh(batch)
    assert batch.failed_runs == 1


async def test_reaper_fails_stale_queued_crawls_only(db_session: AsyncSession) -> None:
    """A QUEUED crawl whose message is gone would otherwise block its project
    forever (one-active-crawl index counts QUEUED as active)."""
    project = await _project(db_session)
    other = await _project(db_session)
    lost = _crawl(project, started_hours_ago=0, status=CrawlStatus.QUEUED)
    lost.started_at = None
    lost.created_at = NOW - timedelta(hours=3)
    waiting = _crawl(other, started_hours_ago=0, status=CrawlStatus.QUEUED)
    waiting.started_at = None
    waiting.created_at = NOW - timedelta(minutes=30)
    db_session.add_all([lost, waiting])
    await db_session.flush()

    result = await reap_stale_jobs(db_session, now=NOW)

    assert result.crawls == 1
    assert lost.status == CrawlStatus.FAILED
    assert lost.error_message is not None and "never picked up" in lost.error_message
    assert waiting.status == CrawlStatus.QUEUED


async def test_reaper_queued_prompt_run_finalizes_batch(db_session: AsyncSession) -> None:
    """Prompt runs get a much higher QUEUED ceiling (throttle deferrals are
    legitimate waiting), but a run stuck past it must fail so its batch can
    finalize instead of hanging forever."""
    project = await _project(db_session)
    provider = AiProvider(provider_key=f"prov-{uuid.uuid4().hex[:6]}", name="P")
    db_session.add(provider)
    await db_session.flush()
    model = AiModel(provider_id=provider.id, model_key="m1", display_name="M1")
    prompt_set = PromptSet(project_id=project.id, name="Set")
    db_session.add_all([model, prompt_set])
    await db_session.flush()
    prompt = Prompt(
        prompt_set_id=prompt_set.id,
        project_id=project.id,
        text="best tool?",
        normalized_text="best tool?",
        intent=PromptIntent.INFORMATIONAL,
        category=PromptCategory.DISCOVERY,
        funnel_stage=FunnelStage.AWARENESS,
    )
    db_session.add(prompt)
    await db_session.flush()
    batch = PromptRunBatch(
        project_id=project.id, prompt_set_id=prompt_set.id, total_runs=2, status=BatchStatus.RUNNING
    )
    db_session.add(batch)
    await db_session.flush()

    def _run(created_hours_ago: float) -> PromptRun:
        r = PromptRun(
            prompt_id=prompt.id,
            project_id=project.id,
            batch_id=batch.id,
            provider_id=provider.id,
            model_id=model.id,
            provider_key=provider.provider_key,
            model_key=model.model_key,
            status=PromptRunStatus.QUEUED,
        )
        r.created_at = NOW - timedelta(hours=created_hours_ago)
        return r

    orphaned = _run(13)
    deferred = _run(3)  # legitimately waiting on throttle backlog
    db_session.add_all([orphaned, deferred])
    await db_session.flush()

    result = await reap_stale_jobs(db_session, now=NOW)

    assert result.prompt_runs == 1
    assert orphaned.status == PromptRunStatus.FAILED
    assert orphaned.error_code == "never_started"
    assert deferred.status == PromptRunStatus.QUEUED
    await db_session.refresh(batch)
    assert batch.failed_runs == 1
