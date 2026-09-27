"""Operator notifications: a single optional webhook for platform-level
events (not tenant alerts — those go through per-project notification
channels). Best-effort by design: monitoring must never break the thing
it monitors."""

from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("monitoring.ops")


async def notify_ops(event: str, payload: dict[str, Any]) -> bool:
    """POST {event, ...payload} to OPS_WEBHOOK_URL if configured.
    Returns whether a delivery was attempted and accepted."""
    settings = get_settings()
    url = settings.ops_webhook_url
    if not url:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json={"event": event, **payload})
            resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001 - best-effort by design
        log.warning("ops_webhook_failed", ops_event=event, error=type(exc).__name__)
        return False
