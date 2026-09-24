"""Scheduled monitoring: daily alert detection for active projects.

"Active" means the project has at least one completed AI response inside the
configured activity window — projects nobody is measuring are skipped, so the
scheduled run touches only tenants with fresh data. Detection itself reuses
CompetitiveAlertEngine unchanged (thresholds are the audited defaults) and new
alerts are handed to the injected delivery dispatcher, which enqueues webhook
delivery as its own task.
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

DispatchDelivery = Callable[[uuid.UUID, list[uuid.UUID]], None]


async def active_project_ids(session, since: datetime) -> list[uuid.UUID]:  # type: ignore[no-untyped-def]
    from app.models.prompts import AiResponse, Prompt, PromptRun, PromptSet

    stmt = (
        select(PromptSet.project_id)
        .join(Prompt, Prompt.prompt_set_id == PromptSet.id)
        .join(PromptRun, PromptRun.prompt_id == Prompt.id)
        .join(AiResponse, AiResponse.prompt_run_id == PromptRun.id)
        .where(PromptRun.completed_at >= since)
        .distinct()
    )
    return list((await session.scalars(stmt)).all())


async def run_scheduled_monitoring(*, dispatch_delivery: DispatchDelivery) -> str:
    from app.alerts.engine import CompetitiveAlertEngine
    from app.db.session import dispose_engine, get_session_factory

    settings = get_settings()
    if not settings.monitoring_enabled:
        log.info("scheduled_monitoring_disabled")
        return "disabled"
    since = datetime.now(UTC) - timedelta(days=settings.monitoring_activity_window_days)
    factory = get_session_factory()
    try:
        async with factory() as session:
            project_ids = await active_project_ids(session, since)
        ran = failed = 0
        for project_id in project_ids:
            try:
                async with factory() as session:
                    result = await CompetitiveAlertEngine(session).detect(
                        project_id,
                        window_days=settings.monitoring_detection_window_days,
                    )
                    await session.commit()
                if result.created_alert_ids:
                    try:
                        dispatch_delivery(project_id, result.created_alert_ids)
                    except Exception:  # noqa: BLE001 - detection succeeded; delivery is best-effort
                        log.exception(
                            "scheduled_monitoring_delivery_dispatch_failed",
                            project_id=str(project_id),
                            alerts=len(result.created_alert_ids),
                        )
                ran += 1
            except Exception as exc:  # noqa: BLE001 - one tenant must never block the rest
                failed += 1
                log.error(
                    "scheduled_monitoring_project_failed",
                    project_id=str(project_id),
                    error=str(exc)[:500],
                )
        log.info(
            "scheduled_monitoring_completed",
            projects=len(project_ids),
            ran=ran,
            failed=failed,
        )
        return f"{ran} projects checked, {failed} failed"
    finally:
        await dispose_engine()
