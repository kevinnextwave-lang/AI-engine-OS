"""Website intelligence: crawl jobs, crawl URLs, pages and page versions.

Every row carries project_id so tenant scoping never needs a join chain
longer than project -> organization.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.project import Project


def _values(e: type[enum.StrEnum]) -> list[str]:
    return [m.value for m in e]


class CrawlStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_CRAWL_STATUSES = frozenset({CrawlStatus.QUEUED, CrawlStatus.RUNNING})


class CrawlType(enum.StrEnum):
    FULL = "full"
    INCREMENTAL = "incremental"
    SINGLE_PAGE = "single_page"


class CrawlUrlStatus(enum.StrEnum):
    DISCOVERED = "discovered"
    QUEUED = "queued"
    CRAWLING = "crawling"
    CRAWLED = "crawled"
    FAILED = "failed"
    SKIPPED = "skipped"


class CrawlJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "crawl_jobs"
    __table_args__ = (
        Index("ix_crawl_jobs_project_created", "project_id", "created_at"),
        Index("ix_crawl_jobs_status", "status"),
        Index("ix_crawl_jobs_created_at", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    root_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[CrawlStatus] = mapped_column(
        Enum(CrawlStatus, name="crawl_status", values_callable=_values),
        nullable=False,
        default=CrawlStatus.QUEUED,
        server_default=CrawlStatus.QUEUED.value,
    )
    crawl_type: Mapped[CrawlType] = mapped_column(
        Enum(CrawlType, name="crawl_type", values_callable=_values),
        nullable=False,
        default=CrawlType.FULL,
        server_default=CrawlType.FULL.value,
    )
    max_pages: Mapped[int] = mapped_column(Integer, nullable=False)
    max_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    pages_discovered: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    pages_crawled: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    pages_failed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    pages_skipped: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Effective settings used for this run (concurrency, rps, allowed hosts...).
    config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["Project"] = relationship()
    urls: Mapped[list["CrawlUrl"]] = relationship(
        back_populates="crawl_job", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_CRAWL_STATUSES

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.completed_at or datetime.now(self.started_at.tzinfo)
        return max(0.0, (end - self.started_at).total_seconds())


class CrawlUrl(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "crawl_urls"
    __table_args__ = (
        UniqueConstraint("crawl_job_id", "normalized_url", name="uq_crawl_urls_job_normalized"),
        Index("ix_crawl_urls_job_status", "crawl_job_id", "status"),
        Index("ix_crawl_urls_project_normalized", "project_id", "normalized_url"),
        Index("ix_crawl_urls_discovered_at", "discovered_at"),
    )

    crawl_job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("crawl_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    parent_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    status: Mapped[CrawlUrlStatus] = mapped_column(
        Enum(CrawlUrlStatus, name="crawl_url_status", values_callable=_values),
        nullable=False,
        default=CrawlUrlStatus.DISCOVERED,
        server_default=CrawlUrlStatus.DISCOVERED.value,
    )
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    page_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("website_pages.id", ondelete="SET NULL"), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    crawl_job: Mapped["CrawlJob"] = relationship(back_populates="urls")


class WebsitePage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Latest known version of a page within a project."""

    __tablename__ = "website_pages"
    __table_args__ = (
        UniqueConstraint("project_id", "normalized_url", name="uq_website_pages_project_url"),
        Index("ix_website_pages_project_content_hash", "project_id", "content_hash"),
        Index("ix_website_pages_last_crawled_at", "last_crawled_at"),
        Index("ix_website_pages_created_at", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    http_status: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(35), nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    html_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("website_pages.id", ondelete="SET NULL"), nullable=True
    )
    first_crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    versions: Mapped[list["PageVersion"]] = relationship(
        back_populates="page", cascade="all, delete-orphan", passive_deletes=True
    )


class PageVersion(UUIDPrimaryKeyMixin, Base):
    """Historical snapshot. Raw HTML lives outside Postgres (html_storage_reference)."""

    __tablename__ = "page_versions"
    __table_args__ = (
        Index("ix_page_versions_page_crawled", "page_id", "crawled_at"),
        Index("ix_page_versions_crawl_job", "crawl_job_id"),
    )

    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("website_pages.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    crawl_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("crawl_jobs.id", ondelete="SET NULL"), nullable=True
    )
    http_status: Mapped[int] = mapped_column(Integer, nullable=False)
    html_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Bounded extracted text for downstream analysis (capped by the processor).
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    html_storage_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    page: Mapped["WebsitePage"] = relationship(back_populates="versions")
