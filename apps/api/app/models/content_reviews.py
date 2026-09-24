"""Content optimization reviews (Milestone 6D): the GEO Content Optimization
Agent's work product for one crawled page.

`proposed_changes` is a list of change objects
({change_id, location, current_text, proposed_text, reason, evidence,
confidence, decision, decided_text}); the ORIGINAL PAGE IS NEVER TOUCHED —
decisions (accept / edit / reject) live here, and accepted changes can later
be handed to an integration. Reviews are unique per (project, page); re-runs
update the analysis while carrying over decisions on unchanged changes and
never resetting the review's status.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ReviewStatus(enum.StrEnum):
    DRAFT = "draft"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ChangeDecision(enum.StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"


class ContentOptimizationReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "content_optimization_reviews"
    __table_args__ = (
        UniqueConstraint("project_id", "page_id", name="uq_content_reviews_project_page"),
        Index("ix_content_reviews_project_id", "project_id"),
        Index("ix_content_reviews_status", "status"),
        Index("ix_content_reviews_score", "score"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("website_pages.id", ondelete="CASCADE"), nullable=False
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    # 0–100 content-optimization score (transparent deductions in findings).
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    findings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    recommendations: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    proposed_changes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False, default="low")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ReviewStatus.DRAFT.value
    )
    analysis_version: Mapped[str] = mapped_column(String(40), nullable=False)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
