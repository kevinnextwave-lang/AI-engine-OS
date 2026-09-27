"""Prompt-set execution: create a batch + one run per (prompt × target), commit,
then enqueue. Cancellation flips queued runs immediately and lets in-flight
provider calls finish safely."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.registry import ProviderRegistry
from app.billing.plans import limits_for
from app.core.config import Settings, get_settings
from app.core.errors import ConflictError, RateLimitedError, ValidationAppError
from app.core.logging import get_logger
from app.models.ai import AiModel, AiProvider
from app.models.organization import Organization, OrganizationPlan
from app.models.project import Project
from app.models.prompts import (
    BatchStatus,
    ExecutionPriority,
    PromptRun,
    PromptRunBatch,
    PromptRunStatus,
    PromptSet,
    PromptSetStatus,
)
from app.repositories.ai import AiCatalogRepository
from app.repositories.execution import BatchRepository, PromptRunRepository
from app.repositories.prompts import PromptRepository

log = get_logger(__name__)

# (run_id, celery priority 0-9)
RunDispatcher = Callable[[uuid.UUID, int], None]

CELERY_PRIORITY = {ExecutionPriority.LOW: 3, ExecutionPriority.NORMAL: 5, ExecutionPriority.HIGH: 9}


class ExecutionService:
    def __init__(
        self,
        session: AsyncSession,
        registry: ProviderRegistry,
        dispatcher: RunDispatcher,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._registry = registry
        self._dispatch = dispatcher
        self._settings = settings or get_settings()
        self._batches = BatchRepository(session)
        self._runs = PromptRunRepository(session)
        self._catalog = AiCatalogRepository(session)

    async def resolve_targets(
        self, providers: list[str], models: dict[str, str] | None
    ) -> list[tuple[AiProvider, AiModel]]:
        """Validate provider/model selection against the catalogue and credentials."""
        if not providers:
            raise ValidationAppError("Select at least one provider")
        targets: list[tuple[AiProvider, AiModel]] = []
        problems: list[dict[str, object]] = []
        for key in dict.fromkeys(providers):
            provider = await self._catalog.provider_by_key(key)
            if provider is None:
                problems.append({"loc": ["body", "providers"], "msg": f"Unknown provider '{key}'"})
                continue
            if not provider.is_enabled:
                problems.append(
                    {"loc": ["body", "providers"], "msg": f"Provider '{key}' is disabled"}
                )
                continue
            if not self._registry.is_configured(key):
                problems.append(
                    {
                        "loc": ["body", "providers"],
                        "msg": f"Provider '{key}' has no credentials configured",
                    }
                )
                continue
            model_key = (models or {}).get(key) or self._registry.default_model(key)
            model = await self._catalog.model_by_key(provider.id, model_key) if model_key else None
            if model is None or not model.is_enabled:
                problems.append(
                    {
                        "loc": ["body", "models", key],
                        "msg": f"Model '{model_key}' is not available for '{key}'",
                    }
                )
                continue
            targets.append((provider, model))
        if problems:
            raise ValidationAppError("Invalid execution targets", details=problems)
        return targets

    async def run_prompt_set(
        self,
        prompt_set: PromptSet,
        *,
        providers: list[str],
        models: dict[str, str] | None,
        priority: ExecutionPriority,
        requested_by: uuid.UUID | None,
        prompt_ids: list[uuid.UUID] | None = None,
    ) -> PromptRunBatch:
        if prompt_set.status == PromptSetStatus.ARCHIVED:
            raise ConflictError("Prompt set is archived")
        settings = self._settings
        targets = await self.resolve_targets(providers, models)
        prompts, _ = await PromptRepository(self._session).list_for_set(
            prompt_set.id, is_active=True, limit=10_000
        )
        if prompt_ids is not None:
            wanted = set(prompt_ids)
            prompts = [p for p in prompts if p.id in wanted]
        if not prompts:
            raise ValidationAppError("Prompt set has no active prompts to run")
        org = await self._session.scalar(
            select(Organization)
            .join(Project, Project.organization_id == Organization.id)
            .where(Project.id == prompt_set.project_id)
        )
        plan_limits = limits_for(org.plan if org else OrganizationPlan.FREE)
        # Cost control 1: bound the per-request blast radius. One batch is
        # prompts × providers paid calls. The plan's cap and the operator's
        # global cap both apply — the lower one wins.
        max_prompts = min(settings.ai_run_max_prompts_per_batch, plan_limits.prompts_per_batch)
        if len(prompts) > max_prompts:
            raise ValidationAppError(
                f"This run would execute {len(prompts)} prompts; the "
                f"{plan_limits.label} plan's per-batch limit is {max_prompts}. "
                "Run a subset via prompt_ids or deactivate prompts."
            )
        # Cost control 2: one in-flight batch per project. Repeat-clicking
        # "run" (or a script in a loop) must not stack paid batches. Checked
        # after the set's own validation so an invalid request still gets its
        # specific error even while another batch runs.
        active = await self._batches.active_for_project(prompt_set.project_id)
        if active is not None:
            raise ConflictError(
                "A prompt run batch is already in progress for this project. "
                "Wait for it to finish or cancel it before starting another."
            )
        # Cost control 3: per-organization daily spend ceiling, enforced
        # against the usage metering that every provider call already writes.
        # The plan's budget applies; a positive global setting is an operator
        # ceiling on top (lower wins).
        daily_limit = plan_limits.ai_daily_cost_usd
        if settings.ai_daily_cost_limit_usd > 0:
            daily_limit = min(daily_limit, settings.ai_daily_cost_limit_usd)
        if daily_limit > 0 and org is not None:
            day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            spent = await self._batches.org_spend_since(org.id, day_start)
            if spent >= daily_limit:
                raise RateLimitedError(
                    f"This organization has reached its daily AI usage budget for the "
                    f"{plan_limits.label} plan (${daily_limit:.2f}). Try again after "
                    "midnight UTC, or upgrade the plan."
                )

        batch = PromptRunBatch(
            project_id=prompt_set.project_id,
            prompt_set_id=prompt_set.id,
            requested_by_user_id=requested_by,
            status=BatchStatus.QUEUED,
            priority=priority,
            targets=[
                {"provider_key": p.provider_key, "model_key": m.model_key} for p, m in targets
            ],
            total_runs=len(prompts) * len(targets),
        )
        await self._batches.add(batch)
        runs = [
            PromptRun(
                prompt_id=prompt.id,
                project_id=prompt_set.project_id,
                batch_id=batch.id,
                provider_id=provider.id,
                model_id=model.id,
                provider_key=provider.provider_key,
                model_key=model.model_key,
                status=PromptRunStatus.QUEUED,
            )
            for prompt in prompts
            for provider, model in targets
        ]
        self._session.add_all(runs)
        await self._session.flush()
        # Commit BEFORE enqueueing so workers can see the rows.
        await self._session.commit()
        celery_priority = CELERY_PRIORITY[priority]
        enqueued = 0
        try:
            for run in runs:
                self._dispatch(run.id, celery_priority)
                enqueued += 1
        except Exception as exc:  # noqa: BLE001 - broker outage must not strand queued rows
            log.exception("prompt_run_dispatch_failed", batch_id=str(batch.id), enqueued=enqueued)
            for run in runs[enqueued:]:
                run.status = PromptRunStatus.FAILED
                run.error_code = "dispatch_failed"
                run.error_message = f"Could not enqueue run: {type(exc).__name__}"
                run.completed_at = datetime.now(UTC)
            # Server-side increment: workers may already be recording outcomes
            # for the runs that WERE enqueued, so never overwrite the counter.
            batch.failed_runs = PromptRunBatch.failed_runs + (len(runs) - enqueued)
            await self._session.flush()
            await self._batches.finalize_if_done(batch.id)
            await self._session.commit()
        await self._session.refresh(batch)
        log.info(
            "prompt_batch_created",
            batch_id=str(batch.id),
            prompt_set_id=str(prompt_set.id),
            runs=len(runs),
            targets=len(targets),
            priority=priority.value,
        )
        return batch

    async def cancel(self, batch: PromptRunBatch) -> PromptRunBatch:
        if batch.status in (
            BatchStatus.COMPLETED,
            BatchStatus.PARTIAL,
            BatchStatus.FAILED,
            BatchStatus.CANCELLED,
        ):
            raise ConflictError(f"Batch is already {batch.status.value}")
        batch.status = BatchStatus.CANCELLING
        await self._session.flush()
        cancelled = await self._batches.cancel_queued_runs(batch.id)
        # Runs currently inside a provider call finish on their own; the batch
        # becomes `cancelled` once they report back (see BatchRepository.finalize_if_done).
        refreshed = await self._batches.finalize_if_done(batch.id)
        await self._session.commit()
        await self._session.refresh(batch)
        log.info(
            "prompt_batch_cancel_requested", batch_id=str(batch.id), cancelled_queued=cancelled
        )
        return refreshed or batch
