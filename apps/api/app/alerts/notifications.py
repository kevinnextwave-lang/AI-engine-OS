"""Notification design for competitive alerts.

Alerts are persisted first; delivery is a separate, pluggable concern. A
channel implements `NotificationChannel` and is registered on the dispatcher;
the detection engine hands every newly created alert to the dispatcher after
commit-safe persistence.

Future channels (NOT implemented yet — no external calls are made anywhere in
this module): email (SMTP/provider API), Slack (incoming webhook), Microsoft
Teams (incoming webhook), generic webhook (signed POST). Each would be a small
class implementing `send`, configured per project/organization, with delivery
results recorded for observability. Until then the dispatcher only logs.
"""

from typing import Protocol

from app.core.logging import get_logger
from app.models.alerts import CompetitiveAlert

log = get_logger(__name__)


class NotificationChannel(Protocol):
    """One delivery mechanism (email, Slack, Teams, webhook…)."""

    key: str

    async def send(self, alert: CompetitiveAlert) -> None:
        """Deliver one alert. Implementations must not raise on delivery failure;
        they log and record the failure instead."""
        ...


class NotificationDispatcher:
    """Fans newly created alerts out to registered channels. Ships with none."""

    def __init__(self, channels: list[NotificationChannel] | None = None) -> None:
        self._channels = list(channels or [])

    def register(self, channel: NotificationChannel) -> None:
        self._channels.append(channel)

    async def dispatch(self, alerts: list[CompetitiveAlert]) -> None:
        if not alerts:
            return
        if not self._channels:
            log.info("alerts_created_no_channels", count=len(alerts))
            return
        for alert in alerts:
            for channel in self._channels:
                await channel.send(alert)
