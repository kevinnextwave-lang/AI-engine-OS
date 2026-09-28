"""Recurring prompt-set execution schedules.

One optional schedule per prompt set. A beat task sweeps hourly for rows
whose next_run_at has passed and starts a batch through ExecutionService —
the same code path as a manual run, so every cost control (plan batch cap,
one active batch per project, daily budget) applies unchanged.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _values(e: type[enum.StrEnum]) -> list[str]:
    return [m.value for m in e]


class ScheduleCadence(enum.StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


class PromptSchedule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "prompt_schedules"
    __table_args__ = (
        # The sweep's whole query: active rows that are due.
        Index("ix_prompt_schedules_due", "is_active", "next_run_at"),
    )

    prompt_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_sets.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # Denormalized for tenant-scoped queries without a join.
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    cadence: Mapped[ScheduleCadence] = mapped_column(
        Enum(ScheduleCadence, name="prompt_schedule_cadence", values_callable=_values),
        nullable=False,
    )
    hour_utc: Mapped[int] = mapped_column(Integer, nullable=False)
    # 0 = Monday … 6 = Sunday (Python weekday()); required for WEEKLY, null for DAILY.
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Same shapes as RunPromptSetRequest: provider keys + optional model overrides.
    providers: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    models: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_run_batches.id", ondelete="SET NULL"), nullable=True
    )
    # Why the last attempt did not produce a batch (None after a success).
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
