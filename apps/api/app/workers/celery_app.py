"""Celery application.

Background jobs live here, separate from HTTP request processing. Future
modules (crawler, AI search workers, agent orchestration, analytics) register
their tasks under dedicated queues so they can be split into their own
deployments without code changes.
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ai_search_growth_os",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    # Redis priority support for the ai_search queue (0 = lowest, 9 = highest)
    broker_transport_options={
        "priority_steps": list(range(10)),
        "queue_order_strategy": "priority",
    },
    task_routes={
        "app.workers.tasks.crawler.*": {"queue": "crawler"},
        "app.workers.tasks.ai_search.*": {"queue": "ai_search"},
        "app.workers.tasks.agents.*": {"queue": "agents"},
        "app.workers.tasks.analytics.*": {"queue": "analytics"},
    },
    # Scheduled monitoring fires only when an operator runs `celery beat`
    # (e.g. `celery -A app.workers.celery_app beat`). The task itself also
    # honours MONITORING_ENABLED, so it can be switched off without redeploys.
    beat_schedule=(
        {
            "daily-competitive-monitoring": {
                "task": "app.workers.tasks.monitoring.run_scheduled_monitoring",
                "schedule": crontab(minute=0, hour=settings.monitoring_hour_utc),
            }
        }
        if settings.monitoring_enabled
        else {}
    ),
)
