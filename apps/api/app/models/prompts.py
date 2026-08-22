"""Prompt intelligence: Project → PromptSet → Prompt → PromptRun."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _values(e: type[enum.StrEnum]) -> list[str]:
    return [m.value for m in e]


class PromptSetStatus(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class PromptCategory(enum.StrEnum):
    DISCOVERY = "discovery"
    COMPARISON = "comparison"
    RECOMMENDATION = "recommendation"
    PRICING = "pricing"
    PRODUCT = "product"
    ALTERNATIVE = "alternative"
    PROBLEM_SOLUTION = "problem_solution"
    INDUSTRY = "industry"
    LOCAL = "local"
    TRANSACTIONAL = "transactional"


class PromptIntent(enum.StrEnum):
    INFORMATIONAL = "informational"
    COMMERCIAL = "commercial"  # researching options before buying
    TRANSACTIONAL = "transactional"
    NAVIGATIONAL = "navigational"


class FunnelStage(enum.StrEnum):
    AWARENESS = "awareness"
    CONSIDERATION = "consideration"
    DECISION = "decision"
    PURCHASE = "purchase"
    RETENTION = "retention"


class PromptSource(enum.StrEnum):
    GENERATED = "generated"
    MANUAL = "manual"


class PromptRunStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BatchStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"


class ExecutionPriority(enum.StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class PromptSet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "prompt_sets"
    __table_args__ = (
        Index("ix_prompt_sets_project_created", "project_id", "created_at"),
        Index("ix_prompt_sets_created_at", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional focus category for the set; prompts inside may still span categories.
    category: Mapped[PromptCategory | None] = mapped_column(
        Enum(PromptCategory, name="prompt_category", values_callable=_values), nullable=True
    )
    status: Mapped[PromptSetStatus] = mapped_column(
        Enum(PromptSetStatus, name="prompt_set_status", values_callable=_values),
        nullable=False,
        default=PromptSetStatus.ACTIVE,
        server_default=PromptSetStatus.ACTIVE.value,
    )
    # Business profile used for the last generation (inputs are kept for auditability).
    generation_profile: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    last_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Prompt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "prompts"
    __table_args__ = (
        Index("ix_prompts_set_normalized", "prompt_set_id", "normalized_text", unique=True),
        Index("ix_prompts_project_category", "project_id", "category"),
        Index("ix_prompts_created_at", "created_at"),
    )

    prompt_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalized for tenant-scoped queries without a join.
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_text: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[PromptCategory] = mapped_column(
        Enum(PromptCategory, name="prompt_category", values_callable=_values, create_type=False),
        nullable=False,
    )
    intent: Mapped[PromptIntent] = mapped_column(
        Enum(PromptIntent, name="prompt_intent", values_callable=_values), nullable=False
    )
    funnel_stage: Mapped[FunnelStage] = mapped_column(
        Enum(FunnelStage, name="prompt_funnel_stage", values_callable=_values), nullable=False
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    # 1 = highest priority … 5 = lowest.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[PromptSource] = mapped_column(
        Enum(PromptSource, name="prompt_source", values_callable=_values),
        nullable=False,
        default=PromptSource.MANUAL,
    )
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )


class PromptRunBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One "run this prompt set" request; fans out into prompt_runs."""

    __tablename__ = "prompt_run_batches"
    __table_args__ = (
        Index("ix_prompt_run_batches_project_created", "project_id", "created_at"),
        Index("ix_prompt_run_batches_created_at", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prompt_set_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[BatchStatus] = mapped_column(
        Enum(BatchStatus, name="prompt_run_batch_status", values_callable=_values),
        nullable=False,
        default=BatchStatus.QUEUED,
    )
    priority: Mapped[ExecutionPriority] = mapped_column(
        Enum(ExecutionPriority, name="execution_priority", values_callable=_values),
        nullable=False,
        default=ExecutionPriority.NORMAL,
    )
    # [{"provider_key": "openai", "model_key": "gpt-4o-mini"}, ...]
    targets: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    total_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancelled_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def finished_runs(self) -> int:
        return self.completed_runs + self.failed_runs + self.cancelled_runs


class PromptRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One execution of a prompt against one provider/model."""

    __tablename__ = "prompt_runs"
    __table_args__ = (
        Index("ix_prompt_runs_prompt_created", "prompt_id", "created_at"),
        Index("ix_prompt_runs_batch_status", "batch_id", "status"),
        Index("ix_prompt_runs_created_at", "created_at"),
    )

    prompt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_run_batches.id", ondelete="CASCADE"), nullable=True
    )
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="SET NULL"), nullable=True
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_models.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[PromptRunStatus] = mapped_column(
        Enum(PromptRunStatus, name="prompt_run_status", values_callable=_values),
        nullable=False,
        default=PromptRunStatus.QUEUED,
    )
    provider_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_generation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_generations.id", ondelete="SET NULL"), nullable=True
    )
    # e.g. {"brand_mentioned": true, "position": 2, "competitors_mentioned": ["X"]}
    visibility: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AiResponse(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Normalized provider answer for a prompt run. No secrets, no raw provider payloads."""

    __tablename__ = "ai_responses"
    __table_args__ = (Index("ix_ai_responses_created_at", "created_at"),)

    prompt_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_runs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="SET NULL"), nullable=True
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_models.id", ondelete="SET NULL"), nullable=True
    )
    response_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    finish_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Set by the response intelligence parser; reprocessing overwrites these, never the row.
    parser_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parse_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class AiUsageRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Token usage + estimated cost per provider call, for billing and budgets."""

    __tablename__ = "ai_usage_records"
    __table_args__ = (
        Index("ix_ai_usage_records_org_created", "organization_id", "created_at"),
        Index("ix_ai_usage_records_project_created", "project_id", "created_at"),
        Index("ix_ai_usage_records_created_at", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    prompt_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompt_runs.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # USD, 6 decimals; pricing comes from ai_models.pricing (configurable).
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    pricing_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
