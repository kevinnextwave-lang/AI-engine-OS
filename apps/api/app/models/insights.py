"""Competitive insights (Milestone 5D): evidence-backed observations about why a
competitor *may* be appearing more often or more favourably in AI responses.

Insights describe observed patterns, never causation. They are regenerated from
the response/citation graph; the unique key (project, competitor, type) makes
re-analysis an upsert, and insights whose evidence disappears are removed.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.competitor import Competitor


class InsightType(enum.StrEnum):
    CONTENT_ADVANTAGE = "content_advantage"
    CITATION_ADVANTAGE = "citation_advantage"
    ENTITY_ADVANTAGE = "entity_advantage"
    EVIDENCE_ADVANTAGE = "evidence_advantage"
    POSITIONING_ADVANTAGE = "positioning_advantage"
    COVERAGE_ADVANTAGE = "coverage_advantage"


class InsightConfidence(enum.StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class InsightImpact(enum.StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CompetitiveInsight(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "competitive_insights"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "competitor_id",
            "insight_type",
            name="uq_competitive_insights_project_competitor_type",
        ),
        Index("ix_competitive_insights_project_id", "project_id"),
        Index("ix_competitive_insights_competitor_id", "competitor_id"),
        Index("ix_competitive_insights_impact", "impact"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    competitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False
    )
    insight_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[str] = mapped_column(
        String(10), nullable=False, default=InsightConfidence.LOW.value
    )
    impact: Mapped[str] = mapped_column(String(10), nullable=False, default=InsightImpact.LOW.value)
    # A 0–100 magnitude used only for ordering within an impact band.
    strength: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    analysis_version: Mapped[str] = mapped_column(String(50), nullable=False)
    window_days: Mapped[int] = mapped_column(nullable=False, default=90)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    competitor: Mapped[Competitor] = relationship()
