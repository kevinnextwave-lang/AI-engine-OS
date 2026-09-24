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

# No result backend: nothing in the app ever reads a task result (task state
# lives in the database rows the tasks update). A configured backend makes
# every dispatching process subscribe to result channels — pure overhead, and
# its reconnect loop can crash the API outright when Redis is unavailable.
celery_app = Celery(
    "ai_search_growth_os",
    broker=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    # Dispatch sites handle enqueue failure themselves (rows are marked FAILED
    # / reported queued:false). Without these bounds a dead broker blocks the
    # API's event loop ~19s per request while kombu retries.
    task_publish_retry=False,
    broker_connection_timeout=5,
    # Without this, acks_late tasks whose worker dies (OOM, SIGKILL, hard time
    # limit) are acked anyway and silently lost; rejecting requeues them, and
    # every task's "still QUEUED?" guard makes the redelivery a no-op when the
    # first run actually finished.
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    # Redis priority support for the ai_search queue (0 = lowest, 9 = highest)
    broker_transport_options={
        "priority_steps": list(range(10)),
        "queue_order_strategy": "priority",
        # Longer than the longest task (crawls: 6h) so Redis does not
        # redeliver still-running work; default is 1h.
        "visibility_timeout": 8 * 3600,
        # Bound every broker socket operation (see task_publish_retry above).
        "socket_connect_timeout": 3,
        "socket_timeout": 5,
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
    beat_schedule={
        # Backstop for workers that die unobserved (OOM/node loss): fail
        # stale RUNNING jobs so users can retry and crawls can't block a
        # project forever. Always on.
        "hourly-stale-job-reaper": {
            "task": "app.workers.tasks.monitoring.reap_stale_jobs",
            "schedule": crontab(minute=17),
        },
        **(
            {
                "daily-competitive-monitoring": {
                    "task": "app.workers.tasks.monitoring.run_scheduled_monitoring",
                    "schedule": crontab(minute=0, hour=settings.monitoring_hour_utc),
                }
            }
            if settings.monitoring_enabled
            else {}
        ),
    },
)
