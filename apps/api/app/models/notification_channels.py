"""Notification channels: where a project's competitive alerts get delivered.

Only the generic signed webhook is implemented. Email / Slack / Teams remain
design notes in app/alerts/notifications.py — no external providers are wired.
The webhook secret is write-only: it is stored for HMAC signing and never
returned by the API or written to logs.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _values(e: type[enum.StrEnum]) -> list[str]:
    return [m.value for m in e]


class NotificationChannelType(enum.StrEnum):
    WEBHOOK = "webhook"


class DeliveryStatus(enum.StrEnum):
    DELIVERED = "delivered"
    FAILED = "failed"


class NotificationChannelConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notification_channels"
    __table_args__ = (Index("ix_notification_channels_project_enabled", "project_id", "enabled"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_type: Mapped[NotificationChannelType] = mapped_column(
        Enum(NotificationChannelType, name="notification_channel_type", values_callable=_values),
        nullable=False,
        default=NotificationChannelType.WEBHOOK,
        server_default=NotificationChannelType.WEBHOOK.value,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Channel settings; for webhooks: {"url": "https://..."}. Secrets are NOT
    # stored here — they live in the dedicated write-only column below.
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # HMAC-SHA256 signing secret (optional). Never serialized, never logged.
    secret: Mapped[str | None] = mapped_column(String(512), nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_delivery_status: Mapped[DeliveryStatus | None] = mapped_column(
        Enum(DeliveryStatus, name="notification_delivery_status", values_callable=_values),
        nullable=True,
    )
    last_delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
