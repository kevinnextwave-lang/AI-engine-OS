"""AI search readiness audits (deterministic; no LLM calls).

An audit records *signals* about how clearly a site communicates its entities,
offerings, authorship and evidence. Nothing here measures or predicts AI
ranking; see docs/ai-readiness-score.md.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.seo import AuditStatus, Severity


def _values(e: type[enum.StrEnum]) -> list[str]:
    return [m.value for m in e]


class ReadinessCategory(enum.StrEnum):
    ENTITY_CLARITY = "entity_clarity"
    PRODUCT_CLARITY = "product_clarity"
    EVIDENCE = "evidence"
    AUTHORITY = "authority"
    CONTENT_STRUCTURE = "content_structure"
    FAQ = "faq"
    COMPARISON = "comparison"
    FACTUAL_CONSISTENCY = "factual_consistency"


class AiReadinessAudit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_readiness_audits"
    __table_args__ = (
        Index("ix_ai_readiness_audits_project_created", "project_id", "created_at"),
        Index("ix_ai_readiness_audits_created_at", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[AuditStatus] = mapped_column(
        Enum(AuditStatus, name="seo_audit_status", values_callable=_values, create_type=False),
        nullable=False,
        default=AuditStatus.QUEUED,
        server_default=AuditStatus.QUEUED.value,
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    pages_analyzed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # AI Readiness Score (0-100, internal metric; docs/ai-readiness-score.md)
    readiness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AiReadinessObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_readiness_observations"
    __table_args__ = (
        Index("ix_ai_readiness_observations_audit_category", "audit_id", "category"),
        Index("ix_ai_readiness_observations_audit_severity", "audit_id", "severity"),
        Index("ix_ai_readiness_observations_created_at", "created_at"),
    )

    audit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_readiness_audits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("website_pages.id", ondelete="SET NULL"), nullable=True
    )
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    category: Mapped[ReadinessCategory] = mapped_column(
        Enum(ReadinessCategory, name="ai_readiness_category", values_callable=_values),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="seo_severity", values_callable=_values, create_type=False),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
