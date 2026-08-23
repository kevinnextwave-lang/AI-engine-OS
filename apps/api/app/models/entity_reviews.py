"""Entity optimization reviews (Milestone 6E): how well the organization,
products, services and people are represented across the customer's site.

One row per (project, review_key) — e.g. "organization",
"product:<fingerprint>", "consistency". Re-runs replace the analysis but never
the review's status; every proposed modification requires human approval
through the review workflow and the agent-run approval actions. Nothing here
modifies the site or its structured data.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ReviewStatus(enum.StrEnum):
    DRAFT = "draft"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class EntityOptimizationReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entity_optimization_reviews"
    __table_args__ = (
        UniqueConstraint("project_id", "review_key", name="uq_entity_reviews_project_key"),
        Index("ix_entity_reviews_project_id", "project_id"),
        Index("ix_entity_reviews_entity_type", "entity_type"),
        Index("ix_entity_reviews_status", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # The reviewed entity, when one exists ("organization missing entirely" has none).
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    review_key: Mapped[str] = mapped_column(String(200), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    findings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    recommendations: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False, default="low")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ReviewStatus.DRAFT.value
    )
    analysis_version: Mapped[str] = mapped_column(String(40), nullable=False)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
