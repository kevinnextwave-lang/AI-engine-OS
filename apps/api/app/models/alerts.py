"""Competitive AI alerts (Milestone 5F): meaningful changes in AI search
visibility, detected against configurable thresholds.

Deduplication: every alert carries a `dedup_key` describing what it is about
(type + subject + change fingerprint). Re-detection of the same situation
updates the existing row's evidence instead of creating a duplicate, and a
dismissed alert stays dismissed.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.competitor import Competitor


class AlertType(enum.StrEnum):
    COMPETITOR_OVERTAKES_BRAND = "competitor_overtakes_brand"
    VISIBILITY_DROP = "visibility_drop"
    COMPETITOR_VISIBILITY_JUMP = "competitor_visibility_jump"
    NEW_COMPETITOR = "new_competitor"
    NEW_CITATION_SOURCE = "new_citation_source"
    CITATION_GAP_INCREASE = "citation_gap_increase"
    NEW_COMPETITOR_CLAIM = "new_competitor_claim"
    CONTENT_GAP = "content_gap"


class AlertSeverity(enum.StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AlertStatus(enum.StrEnum):
    NEW = "new"
    READ = "read"
    DISMISSED = "dismissed"


class CompetitiveAlert(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "competitive_alerts"
    __table_args__ = (
        UniqueConstraint("project_id", "dedup_key", name="uq_competitive_alerts_project_dedup"),
        Index("ix_competitive_alerts_project_id", "project_id"),
        Index("ix_competitive_alerts_status", "status"),
        Index("ix_competitive_alerts_severity", "severity"),
        Index("ix_competitive_alerts_detected_at", "detected_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    alert_type: Mapped[str] = mapped_column(String(40), nullable=False)
    competitor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("competitors.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    severity: Mapped[str] = mapped_column(
        String(10), nullable=False, default=AlertSeverity.LOW.value
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False, default=AlertStatus.NEW.value)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # What the alert is about — makes re-detection an update, not a duplicate.
    dedup_key: Mapped[str] = mapped_column(String(400), nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(40), nullable=False)

    competitor: Mapped[Competitor | None] = relationship()
