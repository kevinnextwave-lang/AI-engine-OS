"""Technical SEO audits and their observations."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _values(e: type[enum.StrEnum]) -> list[str]:
    return [m.value for m in e]


class AuditStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ObservationCategory(enum.StrEnum):
    INDEXABILITY = "indexability"
    METADATA = "metadata"
    HEADINGS = "headings"
    CANONICALIZATION = "canonicalization"
    INTERNAL_LINKS = "internal_links"
    HTTP = "http"
    STRUCTURED_DATA = "structured_data"
    MOBILE_HTML = "mobile_html"


class Severity(enum.StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ObservationStatus(enum.StrEnum):
    OPEN = "open"
    IGNORED = "ignored"
    RESOLVED = "resolved"


class SeoAudit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "seo_audits"
    __table_args__ = (
        Index("ix_seo_audits_project_created", "project_id", "created_at"),
        Index("ix_seo_audits_created_at", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    crawl_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crawl_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[AuditStatus] = mapped_column(
        Enum(AuditStatus, name="seo_audit_status", values_callable=_values),
        nullable=False,
        default=AuditStatus.QUEUED,
        server_default=AuditStatus.QUEUED.value,
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    pages_analyzed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Technical SEO Health Score (0-100, preliminary; see docs/technical-seo-health-score.md)
    health_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SeoObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "seo_observations"
    __table_args__ = (
        Index("ix_seo_observations_audit_category", "audit_id", "category"),
        Index("ix_seo_observations_audit_severity", "audit_id", "severity"),
        Index("ix_seo_observations_audit_status", "audit_id", "status"),
        Index("ix_seo_observations_page", "page_id"),
        Index("ix_seo_observations_created_at", "created_at"),
    )

    audit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seo_audits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("website_pages.id", ondelete="SET NULL"), nullable=True
    )
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    category: Mapped[ObservationCategory] = mapped_column(
        Enum(ObservationCategory, name="seo_observation_category", values_callable=_values),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="seo_severity", values_callable=_values), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ObservationStatus] = mapped_column(
        Enum(ObservationStatus, name="seo_observation_status", values_callable=_values),
        nullable=False,
        default=ObservationStatus.OPEN,
        server_default=ObservationStatus.OPEN.value,
    )
    status_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status_changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
