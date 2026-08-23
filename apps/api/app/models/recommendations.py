"""Recommendations (Milestone 4E): evidence-based, human-reviewed opportunities
derived from Citation Intelligence. Nothing here executes anything."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RecommendationType(enum.StrEnum):
    CITATION = "citation"
    CONTENT = "content"
    ENTITY = "entity"
    TECHNICAL = "technical"
    AUTHORITY = "authority"
    REPUTATION = "reputation"


class RecommendationPriority(enum.StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RecommendationStatus(enum.StrEnum):
    NEW = "new"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    DISMISSED = "dismissed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


# Allowed human transitions. Every change goes through a person; nothing moves on its own.
TRANSITIONS: dict[RecommendationStatus, frozenset[RecommendationStatus]] = {
    RecommendationStatus.NEW: frozenset(
        {
            RecommendationStatus.REVIEWING,
            RecommendationStatus.APPROVED,
            RecommendationStatus.DISMISSED,
        }
    ),
    RecommendationStatus.REVIEWING: frozenset(
        {RecommendationStatus.APPROVED, RecommendationStatus.DISMISSED}
    ),
    RecommendationStatus.APPROVED: frozenset(
        {RecommendationStatus.IN_PROGRESS, RecommendationStatus.DISMISSED}
    ),
    RecommendationStatus.IN_PROGRESS: frozenset(
        {RecommendationStatus.COMPLETED, RecommendationStatus.DISMISSED}
    ),
    RecommendationStatus.DISMISSED: frozenset({RecommendationStatus.REVIEWING}),  # reopen
    RecommendationStatus.COMPLETED: frozenset(),
}


class Recommendation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint("project_id", "source_key", name="uq_recommendations_project_source_key"),
        Index("ix_recommendations_project_id", "project_id"),
        Index("ix_recommendations_status", "status"),
        Index("ix_recommendations_priority", "priority"),
        Index("ix_recommendations_opportunity_score", "opportunity_score"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    recommendation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Stable identity of what the recommendation is about (e.g. `citation:gap:<domain>`),
    # so regeneration updates the same row and keeps its review status.
    source_key: Mapped[str] = mapped_column(String(200), nullable=False)
    citation_gap_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("citation_gaps.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Five answers: observed, why_it_matters, investigate, evidence_summary, confidence_statement.
    explanation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    priority: Mapped[str] = mapped_column(String(10), nullable=False)
    opportunity_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RecommendationStatus.NEW.value
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    generator_version: Mapped[str] = mapped_column(String(40), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
