"""Executes one prompt run: throttle → provider → persist → batch bookkeeping.

Pure asyncio; the Celery task is a thin wrapper that maps `Outcome.retry_in`
onto `self.retry(countdown=...)`. Never raises for provider problems — every
failure becomes a recorded status so the batch can finish.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pricing import estimate_cost
from app.ai.registry import ProviderRegistry
from app.ai.throttle import ProviderThrottle, backoff_seconds
from app.ai.types import AIErrorCategory, AIRequest, AIResponse
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.models.ai import AiGeneration, AiModel
from app.models.project import Project
from app.models.prompts import (
    AiResponse,
    AiUsageRecord,
    BatchStatus,
    Prompt,
    PromptRun,
    PromptRunStatus,
)
from app.repositories.execution import BatchRepository, PromptRunRepository
from app.services.ai import AIGenerationService

log = get_logger("ai.execution")

NON_RETRYABLE = frozenset(
    {
        AIErrorCategory.AUTHENTICATION_ERROR,
        AIErrorCategory.INVALID_REQUEST,
        AIErrorCategory.CONTENT_FILTER,
        AIErrorCategory.UNKNOWN_ERROR,
    }
)


@dataclass
class Outcome:
    run_id: uuid.UUID
    status: PromptRunStatus | None  # None when the run was skipped (not claimable)
    retry_in: float | None = None  # seconds; set when the task should run again
    reason: str | None = None

    @property
    def should_retry(self) -> bool:
        return self.retry_in is not None


async def execute_prompt_run(
    session: AsyncSession,
    run_id: uuid.UUID,
    registry: ProviderRegistry,
    throttle: ProviderThrottle,
    settings: Settings | None = None,
) -> Outcome:
    settings = settings or get_settings()
    runs = PromptRunRepository(session)
    batches = BatchRepository(session)

    run = await runs.get(run_id)
    if run is None:
        return Outcome(run_id, None, reason="missing")
    if run.status != PromptRunStatus.QUEUED:
        # cancelled, or already finished by another worker
        return Outcome(run_id, None, reason=f"not queued ({run.status.value})")
    if run.batch_id is not None:
        batch = await batches.get(run.batch_id)
        if batch is not None and batch.status in (BatchStatus.CANCELLING, BatchStatus.CANCELLED):
            run.status = PromptRunStatus.CANCELLED
            run.completed_at = datetime.now(UTC)
            await session.flush()
            await batches.record_outcome(run.batch_id, PromptRunStatus.CANCELLED)
            await session.commit()
            return Outcome(run_id, PromptRunStatus.CANCELLED, reason="batch cancelled")

    # Provider throttle: defer without occupying the worker.
    provider_key = run.provider_key or ""
    wait = await throttle.acquire(provider_key, settings.ai_rate_limit_for(provider_key))
    if wait > 0:
        await session.commit()
        return Outcome(run_id, PromptRunStatus.QUEUED, retry_in=wait, reason="provider throttle")

    claimed = await runs.claim(run_id)
    if claimed is None:
        return Outcome(run_id, None, reason="claim lost")
    run = claimed
    if run.batch_id is not None:
        await batches.mark_running(run.batch_id)
    await session.commit()

    prompt = await session.get(Prompt, run.prompt_id)
    project = await session.get(Project, run.project_id)
    if prompt is None or project is None:
        return await _finish_failed(
            session, run, "invalid_request", "prompt or project no longer exists"
        )

    request = AIRequest(
        model=run.model_key or "",
        prompt=prompt.text,
        system_prompt=settings.ai_search_system_prompt,
        temperature=settings.ai_run_temperature,
        max_tokens=settings.ai_run_max_tokens,
        timeout_seconds=settings.ai_default_timeout_seconds,
        metadata={
            "prompt_run_id": str(run.id),
            "batch_id": str(run.batch_id) if run.batch_id else None,
        },
    )
    response = await AIGenerationService(session, registry, settings).generate(
        provider_key, request, project_id=project.id, purpose="prompt_run"
    )
    # AIGenerationService committed the ai_generations row; link it.
    generation = await _generation_id(session, request.request_id)
    run.ai_generation_id = generation

    if response.succeeded:
        return await _finish_completed(session, run, response, project)

    error = response.error
    if error is None:  # defensive: succeeded is False only when error is set
        return await _finish_failed(session, run, "unknown_error", "provider returned no error")
    retryable = error.category not in NON_RETRYABLE
    if retryable and run.attempts < settings.ai_run_max_attempts:
        delay = backoff_seconds(
            run.attempts,
            base=settings.ai_run_retry_base_seconds,
            cap=settings.ai_run_retry_max_seconds,
        )
        run.error_code = error.category.value
        run.error_message = error.message[:2000]
        run.latency_ms = response.latency_ms
        await runs.requeue(run)
        await session.commit()
        log.warning(
            "prompt_run_retry",
            run_id=str(run.id),
            provider=provider_key,
            attempt=run.attempts,
            error_category=error.category.value,
            retry_in=delay,
        )
        return Outcome(run_id, PromptRunStatus.QUEUED, retry_in=delay, reason=error.category.value)
    return await _finish_failed(
        session, run, error.category.value, error.message, response.latency_ms
    )


async def _generation_id(session: AsyncSession, request_id: uuid.UUID) -> uuid.UUID | None:
    value: uuid.UUID | None = await session.scalar(
        select(AiGeneration.id).where(AiGeneration.request_id == request_id)
    )
    return value


async def _finish_completed(
    session: AsyncSession, run: PromptRun, response: AIResponse, project: Project
) -> Outcome:
    now = datetime.now(UTC)
    model = await session.get(AiModel, run.model_id) if run.model_id else None
    session.add(
        AiResponse(
            prompt_run_id=run.id,
            provider_id=run.provider_id,
            model_id=run.model_id,
            response_text=response.response_text,
            finish_reason=response.finish_reason.value,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            total_tokens=response.total_tokens,
            latency_ms=response.latency_ms,
            provider_request_id=response.provider_request_id,
            raw_metadata=response.raw_response,
        )
    )
    cost = estimate_cost(
        model.pricing if model else None, response.input_tokens, response.output_tokens
    )
    session.add(
        AiUsageRecord(
            organization_id=project.organization_id,
            project_id=project.id,
            prompt_run_id=run.id,
            provider=response.provider,
            model=response.model,
            input_tokens=response.input_tokens or 0,
            output_tokens=response.output_tokens or 0,
            estimated_cost=cost.amount,
            currency=cost.currency,
            pricing_version=cost.pricing_version,
        )
    )
    run.status = PromptRunStatus.COMPLETED
    run.latency_ms = response.latency_ms
    run.error_code = None
    run.error_message = None
    run.completed_at = now
    await session.flush()
    if run.batch_id is not None:
        await BatchRepository(session).record_outcome(run.batch_id, PromptRunStatus.COMPLETED)
    await session.commit()
    log.info(
        "prompt_run_completed",
        run_id=str(run.id),
        provider=response.provider,
        model=response.model,
        latency_ms=response.latency_ms,
        total_tokens=response.total_tokens,
        estimated_cost=str(cost.amount),
    )
    return Outcome(run.id, PromptRunStatus.COMPLETED)


async def _finish_failed(
    session: AsyncSession, run: PromptRun, code: str, message: str, latency_ms: int | None = None
) -> Outcome:
    run.status = PromptRunStatus.FAILED
    run.error_code = code
    run.error_message = message[:2000]
    run.latency_ms = latency_ms
    run.completed_at = datetime.now(UTC)
    await session.flush()
    if run.batch_id is not None:
        await BatchRepository(session).record_outcome(run.batch_id, PromptRunStatus.FAILED)
    await session.commit()
    log.warning("prompt_run_failed", run_id=str(run.id), provider=run.provider_key, error_code=code)
    return Outcome(run.id, PromptRunStatus.FAILED, reason=code)
