"""Recurring collection schedules: validation, next-run math, and the sweep.

The hourly beat sweep starts due batches through ExecutionService — the exact
code path of a manual run — so plan caps, the one-active-batch rule, and the
daily budget all apply. A blocked attempt (batch in flight, budget reached)
keeps next_run_at unchanged and is retried on the next sweep; a structurally
failed attempt (archived set, no prompts, plan gate) records why and moves on
to the next occurrence so it cannot hot-loop.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.registry import ProviderRegistry
from app.billing.plans import limits_for
from app.core.errors import ConflictError, RateLimitedError, ValidationAppError
from app.core.logging import get_logger
from app.models.organization import Organization, OrganizationPlan, OrganizationStatus
from app.models.project import Project
from app.models.prompt_schedule import PromptSchedule, ScheduleCadence
from app.models.prompts import ExecutionPriority, PromptSet
from app.services.execution import ExecutionService, RunDispatcher

log = get_logger("services.schedules")

# Bound one sweep's work; anything beyond is picked up next hour.
SWEEP_LIMIT = 200


def compute_next_run(
    cadence: ScheduleCadence,
    hour_utc: int,
    weekday: int | None,
    *,
    now: datetime | None = None,
) -> datetime:
    """Next occurrence strictly in the future (UTC). weekday: 0=Mon … 6=Sun."""
    now = now or datetime.now(UTC)
    candidate = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if cadence == ScheduleCadence.DAILY:
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate
    if weekday is None:  # pragma: no cover - validated at save time
        raise ValidationAppError("Weekly schedules need a weekday")
    days_ahead = (weekday - candidate.weekday()) % 7
    candidate += timedelta(days=days_ahead)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


class ScheduleService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_set(self, prompt_set_id: uuid.UUID) -> PromptSchedule | None:
        return await self._session.scalar(  # type: ignore[no-any-return]
            select(PromptSchedule).where(PromptSchedule.prompt_set_id == prompt_set_id)
        )

    async def upsert(
        self,
        prompt_set: PromptSet,
        *,
        plan: OrganizationPlan,
        registry: ProviderRegistry,
        cadence: ScheduleCadence,
        hour_utc: int,
        weekday: int | None,
        providers: list[str],
        models: dict[str, str] | None,
        is_active: bool,
        user_id: uuid.UUID | None,
    ) -> PromptSchedule:
        allowed = limits_for(plan).schedule_cadences
        if cadence.value not in allowed:
            label = limits_for(plan).label
            hint = (
                f"The {label} plan allows {' and '.join(allowed)} schedules."
                if allowed
                else (
                    f"The {label} plan does not include scheduled collections — "
                    "upgrade to enable them."
                )
            )
            raise ValidationAppError(f"'{cadence.value}' scheduling is not available. {hint}")
        if cadence == ScheduleCadence.WEEKLY and weekday is None:
            raise ValidationAppError("Weekly schedules need a weekday (0=Monday … 6=Sunday)")
        if cadence == ScheduleCadence.DAILY:
            weekday = None
        # Same target validation as a manual run — bad providers fail at save
        # time, in front of the user, not silently at 3am.
        await ExecutionService(self._session, registry, _no_dispatch).resolve_targets(
            providers, models
        )
        schedule = await self.get_for_set(prompt_set.id)
        if schedule is None:
            schedule = PromptSchedule(
                prompt_set_id=prompt_set.id,
                project_id=prompt_set.project_id,
                created_by_user_id=user_id,
            )
            self._session.add(schedule)
        schedule.cadence = cadence
        schedule.hour_utc = hour_utc
        schedule.weekday = weekday
        schedule.providers = list(dict.fromkeys(providers))
        schedule.models = models
        schedule.is_active = is_active
        schedule.next_run_at = compute_next_run(cadence, hour_utc, weekday)
        await self._session.flush()
        log.info(
            "prompt_schedule_saved",
            prompt_set_id=str(prompt_set.id),
            cadence=cadence.value,
            hour_utc=hour_utc,
            weekday=weekday,
            is_active=is_active,
        )
        return schedule

    async def delete(self, schedule: PromptSchedule) -> None:
        await self._session.delete(schedule)
        await self._session.flush()


def _no_dispatch(run_id: uuid.UUID, priority: int) -> None:  # pragma: no cover
    raise AssertionError("validation-only ExecutionService must not dispatch")


async def run_due_schedules(
    session: AsyncSession,
    registry: ProviderRegistry,
    dispatcher: RunDispatcher,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """The beat sweep. Returns counters for the task's log line."""
    now = now or datetime.now(UTC)
    due = (
        await session.scalars(
            select(PromptSchedule)
            .where(PromptSchedule.is_active.is_(True), PromptSchedule.next_run_at <= now)
            .order_by(PromptSchedule.next_run_at)
            .limit(SWEEP_LIMIT)
        )
    ).all()
    started = deferred = skipped = 0
    for schedule in due:
        schedule_id = schedule.id
        try:
            outcome = await _fire(session, registry, dispatcher, schedule, now=now)
        except (ConflictError, RateLimitedError) as exc:
            # Retryable: batch in flight or daily budget reached. Keep
            # next_run_at so the next hourly sweep tries again.
            await session.rollback()
            reloaded = await _reload(session, schedule_id)
            if reloaded is not None:
                reloaded.last_error = str(exc)
                await session.commit()
            deferred += 1
            continue
        except Exception as exc:  # noqa: BLE001 - one schedule must not sink the sweep
            await session.rollback()
            reloaded = await _reload(session, schedule_id)
            if reloaded is not None:
                reloaded.last_error = f"{type(exc).__name__}: {exc}"
                reloaded.next_run_at = compute_next_run(
                    reloaded.cadence, reloaded.hour_utc, reloaded.weekday, now=now
                )
                await session.commit()
            log.warning("prompt_schedule_failed", schedule_id=str(schedule_id), error=str(exc))
            skipped += 1
            continue
        if outcome:
            started += 1
        else:
            skipped += 1
    if started or deferred or skipped:
        log.info("prompt_schedules_swept", started=started, deferred=deferred, skipped=skipped)
    return {"started": started, "deferred": deferred, "skipped": skipped}


async def _reload(session: AsyncSession, schedule_id: uuid.UUID) -> PromptSchedule | None:
    return await session.get(PromptSchedule, schedule_id)


async def _fire(
    session: AsyncSession,
    registry: ProviderRegistry,
    dispatcher: RunDispatcher,
    schedule: PromptSchedule,
    *,
    now: datetime,
) -> bool:
    """Run one due schedule. True = a batch was started. Raises to signal
    a retryable (Conflict/RateLimited) or unexpected failure."""
    prompt_set = await session.get(PromptSet, schedule.prompt_set_id)
    if prompt_set is None:
        schedule.is_active = False
        schedule.last_error = "Prompt set no longer exists"
        await session.commit()
        return False
    org = await session.scalar(
        select(Organization)
        .join(Project, Project.organization_id == Organization.id)
        .where(Project.id == schedule.project_id)
    )
    advance = compute_next_run(schedule.cadence, schedule.hour_utc, schedule.weekday, now=now)
    if org is None or org.deleted_at is not None or org.status != OrganizationStatus.ACTIVE:
        schedule.last_error = "Organization is not active"
        schedule.next_run_at = advance
        await session.commit()
        return False
    if schedule.cadence.value not in limits_for(org.plan).schedule_cadences:
        schedule.last_error = (
            f"The {limits_for(org.plan).label} plan no longer allows "
            f"{schedule.cadence.value} schedules"
        )
        schedule.next_run_at = advance
        await session.commit()
        return False
    models = {str(k): str(v) for k, v in (schedule.models or {}).items()} or None
    batch = await ExecutionService(session, registry, dispatcher).run_prompt_set(
        prompt_set,
        providers=list(schedule.providers),
        models=models,
        priority=ExecutionPriority.LOW,
        requested_by=schedule.created_by_user_id,
    )
    # run_prompt_set committed; schedule is not expired (expire_on_commit=False).
    schedule.last_run_at = now
    schedule.last_batch_id = batch.id
    schedule.last_error = None
    schedule.next_run_at = advance
    await session.commit()
    log.info(
        "prompt_schedule_fired",
        schedule_id=str(schedule.id),
        batch_id=str(batch.id),
        next_run_at=advance.isoformat(),
    )
    return True
