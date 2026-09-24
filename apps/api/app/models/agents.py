"""Agent framework persistence (Milestone 6A): runs and proposed actions.

Agents never execute customer-facing changes themselves: they *propose* actions
(`agent_actions`). Anything marked `approval_required` starts `pending` and can
only move forward through an explicit human approval; execution of approved
actions is a later milestone (`executed_at` / `execution_result` are reserved).
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AgentRunStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    AWAITING_APPROVAL = "awaiting_approval"
    CANCELLED = "cancelled"


class ActionRiskLevel(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ActionStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXECUTED = "executed"


class AgentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_project_id", "project_id"),
        Index("ix_agent_runs_status", "status"),
        Index("ix_agent_runs_agent_name", "agent_name"),
        Index("ix_agent_runs_created_at", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AgentRunStatus.QUEUED.value
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The serialized AgentResult (summary, findings, recommendations, evidence,
    # confidence, warnings, tool usage). Proposed actions live in agent_actions.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    actions: Mapped[list["AgentAction"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AgentAction.created_at"
    )


class AgentAction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_actions"
    __table_args__ = (
        Index("ix_agent_actions_agent_run_id", "agent_run_id"),
        Index("ix_agent_actions_status", "status"),
    )

    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    risk_level: Mapped[str] = mapped_column(
        String(10), nullable=False, default=ActionRiskLevel.LOW.value
    )
    approval_required: Mapped[bool] = mapped_column(nullable=False, default=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ActionStatus.PENDING.value
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    run: Mapped[AgentRun] = relationship(back_populates="actions")
