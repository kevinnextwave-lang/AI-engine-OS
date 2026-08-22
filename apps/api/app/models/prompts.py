"""Prompt intelligence: Project → PromptSet → Prompt → PromptRun."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text
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


class PromptRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One execution of a prompt against one provider/model (populated by the
    AI Visibility engine in a later milestone)."""

    __tablename__ = "prompt_runs"
    __table_args__ = (
        Index("ix_prompt_runs_prompt_created", "prompt_id", "created_at"),
        Index("ix_prompt_runs_created_at", "created_at"),
    )

    prompt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[PromptRunStatus] = mapped_column(
        Enum(PromptRunStatus, name="prompt_run_status", values_callable=_values),
        nullable=False,
        default=PromptRunStatus.QUEUED,
    )
    provider_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ai_generation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_generations.id", ondelete="SET NULL"), nullable=True
    )
    # e.g. {"brand_mentioned": true, "position": 2, "competitors_mentioned": ["X"]}
    visibility: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
