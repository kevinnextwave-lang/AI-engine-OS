"""Normalized page intelligence. One row set per website_page (latest crawl);
rows are replaced when the page is re-crawled. JSONB only where the shape is
open-ended (Open Graph / Twitter cards / other metas / heading observations)."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


class LinkType(enum.StrEnum):
    INTERNAL = "internal"
    EXTERNAL = "external"


class LinkStatus(enum.StrEnum):
    UNKNOWN = "unknown"  # target not crawled (yet)
    OK = "ok"
    BROKEN = "broken"  # target crawled and returned 4xx/5xx
    INVALID = "invalid"  # href could not be parsed


class _PageScoped:
    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("website_pages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("page_versions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PageHeading(UUIDPrimaryKeyMixin, _PageScoped, Base):
    __tablename__ = "page_headings"
    __table_args__ = (Index("ix_page_headings_page_position", "page_id", "position"),)

    level: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(String(1000), nullable=False)


class PageLink(UUIDPrimaryKeyMixin, _PageScoped, Base):
    __tablename__ = "page_links"
    __table_args__ = (
        Index("ix_page_links_page_position", "page_id", "position"),
        Index("ix_page_links_project_target", "project_id", "normalized_url"),
        Index("ix_page_links_project_type", "project_id", "link_type"),
    )

    href: Mapped[str] = mapped_column(String(2048), nullable=False)
    normalized_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    anchor_text: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    link_type: Mapped[LinkType] = mapped_column(
        Enum(LinkType, name="page_link_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    status: Mapped[LinkStatus] = mapped_column(
        Enum(LinkStatus, name="page_link_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=LinkStatus.UNKNOWN,
        server_default=LinkStatus.UNKNOWN.value,
    )
    target_page_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("website_pages.id", ondelete="SET NULL"), nullable=True
    )
    target_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_nofollow: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_sponsored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_ugc: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    in_navigation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class PageImage(UUIDPrimaryKeyMixin, _PageScoped, Base):
    __tablename__ = "page_images"
    __table_args__ = (Index("ix_page_images_page_position", "page_id", "position"),)

    src: Mapped[str] = mapped_column(String(2048), nullable=False)
    alt: Mapped[str | None] = mapped_column(String(1000), nullable=True)  # None = attribute absent
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    loading: Mapped[str | None] = mapped_column(String(20), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class PageMetadata(UUIDPrimaryKeyMixin, _PageScoped, Base):
    __tablename__ = "page_metadata"
    __table_args__ = (Index("uq_page_metadata_page", "page_id", unique=True),)

    pathname: Mapped[str] = mapped_column(String(2048), nullable=False)
    robots: Mapped[str | None] = mapped_column(String(500), nullable=True)
    viewport: Mapped[str | None] = mapped_column(String(200), nullable=True)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    charset: Mapped[str | None] = mapped_column(String(40), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    html_lang: Mapped[str | None] = mapped_column(String(35), nullable=True)
    language: Mapped[str | None] = mapped_column(String(35), nullable=True)
    language_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    language_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_graph: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    twitter: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    other: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class PageContentMetrics(UUIDPrimaryKeyMixin, _PageScoped, Base):
    __tablename__ = "page_content_metrics"
    __table_args__ = (
        Index("uq_page_content_metrics_page", "page_id", unique=True),
        Index("ix_page_content_metrics_project_words", "project_id", "word_count"),
    )

    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    paragraph_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sentence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reading_time_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    text_to_html_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    html_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    heading_count: Mapped[int] = mapped_column(Integer, nullable=False)
    h1_count: Mapped[int] = mapped_column(Integer, nullable=False)
    link_count: Mapped[int] = mapped_column(Integer, nullable=False)
    internal_link_count: Mapped[int] = mapped_column(Integer, nullable=False)
    external_link_count: Mapped[int] = mapped_column(Integer, nullable=False)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False)
    images_missing_alt: Mapped[int] = mapped_column(Integer, nullable=False)
    # Facts for the scoring layer (missing/multiple H1, skipped levels, duplicates, long).
    heading_observations: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    clean_text: Mapped[str | None] = mapped_column(Text, nullable=True)
