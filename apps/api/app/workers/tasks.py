"""Baseline tasks. Real workloads arrive in later milestones."""

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="app.workers.tasks.ping")
def ping() -> str:
    log.info("worker_ping")
    return "pong"
