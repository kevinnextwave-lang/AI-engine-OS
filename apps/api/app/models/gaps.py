"""Citation gaps (Milestone 4C): per project, per source domain, where the
brand is under-cited relative to competitors or to the source's importance."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class GapType(enum.StrEnum):
    BRAND_ABSENT = "brand_absent"
    COMPETITOR_ADVANTAGE = "competitor_advantage"
    SOURCE_UNDERREPRESENTED = "source_underrepresented"
    SOURCE_OVERREPRESENTED = "source_overrepresented"
    SHARED_SOURCE = "shared_source"
    EMERGING_SOURCE = "emerging_source"


class GapStatus(enum.StrEnum):
    NEW = "new"
    REVIEWING = "reviewing"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class GapConfidence(enum.StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


class CitationGap(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "citation_gaps"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "source_domain_id",
            "source_page_id",
            name="uq_citation_gaps_project_domain_page",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_citation_gaps_project_id", "project_id"),
        Index("ix_citation_gaps_source_domain_id", "source_domain_id"),
        Index("ix_citation_gaps_opportunity_score", "opportunity_score"),
        Index("ix_citation_gaps_status", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_domain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_domains.id", ondelete="CASCADE"), nullable=False
    )
    source_page_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_pages.id", ondelete="CASCADE"), nullable=True
    )
    gap_type: Mapped[str] = mapped_column(String(30), nullable=False)
    brand_citations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    competitor_citations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relevant_response_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    opportunity_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[str] = mapped_column(
        String(20), nullable=False, default=GapConfidence.INSUFFICIENT.value
    )
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=GapStatus.NEW.value)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-competitor citation counts {name: n} and the scoring inputs/components,
    # so every number can be explained and filtered on.
    competitors: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    analysis_version: Mapped[str] = mapped_column(String(40), nullable=False)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
