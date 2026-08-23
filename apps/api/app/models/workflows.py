"""Agent workflows (Milestone 6F): multiple agents collaborating in sequence.

A workflow is an ordered chain of agent runs. No agent gains any extra access
by being in a workflow — each step runs through the same orchestrator, context
builder and tool registry as a standalone run, and no action executes
automatically. The workflow pauses for explicit human approval whenever a step
proposes content, entity or external changes.
"""

import enum
import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WorkflowStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowStepStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentWorkflow(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_workflows"
    __table_args__ = (
        Index("ix_agent_workflows_project_id", "project_id"),
        Index("ix_agent_workflows_status", "status"),
        Index("ix_agent_workflows_created_at", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    workflow_type: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=WorkflowStatus.QUEUED.value
    )
    # 1-based sequence of the step being (or about to be) executed.
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Why the workflow is paused / awaiting approval, for the UI.
    hold_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The consolidated action plan, built after the final step.
    action_plan: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)

    steps: Mapped[list["AgentWorkflowStep"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="AgentWorkflowStep.sequence",
    )


class AgentWorkflowStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_workflow_steps"
    __table_args__ = (
        UniqueConstraint("workflow_id", "sequence", name="uq_workflow_steps_workflow_sequence"),
        Index("ix_workflow_steps_workflow_id", "workflow_id"),
        Index("ix_workflow_steps_status", "status"),
    )

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent_workflows.id", ondelete="CASCADE"), nullable=False
    )
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=WorkflowStepStatus.PENDING.value
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    input_context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    workflow: Mapped[AgentWorkflow] = relationship(back_populates="steps")
