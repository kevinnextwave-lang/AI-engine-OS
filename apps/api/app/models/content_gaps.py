"""Competitive content gaps (Milestone 5E): topics where competitors appear in
AI responses while the customer's own website has weak or missing coverage.

One row per (project, topic, gap type). `competitor_evidence` holds what the
responses showed (mention rates, competitors, citations, prompts);
`customer_coverage` holds what the crawled site showed (matched pages, their
categories, thinness). Re-analysis upserts by the unique key; review status
and note survive.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.gaps import GapConfidence, GapStatus

__all__ = ["ContentGap", "ContentGapType", "GapConfidence", "GapStatus"]


class ContentGapType(enum.StrEnum):
    MISSING_TOPIC = "missing_topic"
    WEAK_TOPIC = "weak_topic"
    MISSING_COMPARISON = "missing_comparison"
    MISSING_USE_CASE = "missing_use_case"
    MISSING_FAQ = "missing_faq"
    MISSING_EVIDENCE = "missing_evidence"
    MISSING_PRODUCT_DETAIL = "missing_product_detail"


class ContentGap(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "content_gaps"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "normalized_topic",
            "gap_type",
            name="uq_content_gaps_project_topic_type",
        ),
        Index("ix_content_gaps_project_id", "project_id"),
        Index("ix_content_gaps_opportunity_score", "opportunity_score"),
        Index("ix_content_gaps_status", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # The prompt the topic was derived from (informational; topic may cover several).
    prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prompts.id", ondelete="SET NULL"), nullable=True
    )
    topic: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_topic: Mapped[str] = mapped_column(String(300), nullable=False)
    gap_type: Mapped[str] = mapped_column(String(30), nullable=False)
    competitor_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    customer_coverage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    opportunity_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[str] = mapped_column(
        String(20), nullable=False, default=GapConfidence.INSUFFICIENT.value
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=GapStatus.NEW.value)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_version: Mapped[str] = mapped_column(String(40), nullable=False)
    window_days: Mapped[int] = mapped_column(nullable=False, default=90)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
