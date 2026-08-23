"""Competitor discovery candidates (Milestone 5B). Never auto-promoted: a
person accepts a candidate to create a competitor."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CandidateSource(enum.StrEnum):
    AI_RESPONSES = "ai_responses"  # deterministic extraction from stored AI answers
    WEBSITE_INTELLIGENCE = "website_intelligence"
    AI_ASSISTED = "ai_assisted"  # the configured AI provider proposed it (strict JSON)
    COMBINED = "combined"  # found by more than one source


class CandidateStatus(enum.StrEnum):
    NEW = "new"
    REVIEWING = "reviewing"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class CompetitorCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "competitor_candidates"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "normalized_name", name="uq_competitor_candidates_project_name"
        ),
        Index("ix_competitor_candidates_project_id", "project_id"),
        Index("ix_competitor_candidates_status", "status"),
        Index("ix_competitor_candidates_confidence", "confidence"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(253), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # 0–1
    confidence_label: Mapped[str] = mapped_column(String(10), nullable=False, default="low")
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CandidateStatus.NEW.value
    )
    competitor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("competitors.id", ondelete="SET NULL"), nullable=True
    )
    discovery_version: Mapped[str] = mapped_column(String(40), nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
