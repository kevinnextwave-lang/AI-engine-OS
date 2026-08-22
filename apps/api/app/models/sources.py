"""Citation Intelligence data model (Milestone 4A).

    AI response → citation → source page → source domain
                      └──→ citation entity (brand / competitor / …)
    project_sources: per-project aggregate of how often each domain/page is cited.

`source_domains` and `source_pages` are shared reference data (a hostname is a
fact about the web, not about a tenant). Everything that says *who* cited a
source — citations, citation_entities, project_sources — carries project_id
and is tenant-scoped.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DomainType(enum.StrEnum):
    COMPANY = "company"
    MEDIA = "media"
    REVIEW = "review"
    COMMUNITY = "community"
    DIRECTORY = "directory"
    GOVERNMENT = "government"
    EDUCATION = "education"
    SOCIAL = "social"
    FORUM = "forum"
    BLOG = "blog"
    RESEARCH = "research"
    OTHER = "other"
    UNKNOWN = "unknown"


class CitationRelationship(enum.StrEnum):
    BRAND = "brand"
    COMPETITOR = "competitor"
    INDUSTRY = "industry"
    PRODUCT = "product"
    UNKNOWN = "unknown"


class CitationEntityType(enum.StrEnum):
    """What `entity_id` points at."""

    PROJECT = "project"  # the customer's own brand (entity_id = projects.id)
    COMPETITOR = "competitor"  # entity_id = competitors.id
    ENTITY = "entity"  # entity_id = entities.id (structured-data entity)
    NAME = "name"  # no row; only entity_name is known


class SourceDomain(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_domains"
    __table_args__ = (
        UniqueConstraint("normalized_hostname", name="uq_source_domains_normalized_hostname"),
        Index("ix_source_domains_hostname", "hostname"),
        Index("ix_source_domains_last_seen_at", "last_seen_at"),
    )

    hostname: Mapped[str] = mapped_column(String(253), nullable=False)
    normalized_hostname: Mapped[str] = mapped_column(String(253), nullable=False)
    display_name: Mapped[str] = mapped_column(String(253), nullable=False)
    domain_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DomainType.UNKNOWN.value
    )
    authority_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SourcePage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_pages"
    __table_args__ = (
        UniqueConstraint("normalized_url", name="uq_source_pages_normalized_url"),
        Index("ix_source_pages_source_domain_id", "source_domain_id"),
        Index("ix_source_pages_last_seen_at", "last_seen_at"),
    )

    source_domain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_domains.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CitationEntity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A citation's observed relationship to an entity. Only written when the
    evidence is clear (e.g. the cited host is a project domain or a configured
    competitor's host); uncertain citations simply have no row."""

    __tablename__ = "citation_entities"
    __table_args__ = (
        Index("ix_citation_entities_citation_id", "citation_id"),
        Index("ix_citation_entities_project_id", "project_id"),
        Index("ix_citation_entities_entity_id", "entity_id"),
    )

    citation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("citations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    entity_name: Mapped[str] = mapped_column(String(200), nullable=False)
    relationship: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CitationRelationship.UNKNOWN.value
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)


class ProjectSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """How important a source is *within one customer's market*: citation
    counts per (project, domain) and per (project, domain, page). Domain-level
    rows have source_page_id NULL."""

    __tablename__ = "project_sources"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "source_domain_id",
            "source_page_id",
            name="uq_project_sources_project_domain_page",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_project_sources_project_id", "project_id"),
        Index("ix_project_sources_source_domain_id", "source_domain_id"),
        Index("ix_project_sources_source_page_id", "source_page_id"),
        Index("ix_project_sources_citation_count", "citation_count"),
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
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    brand_citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    competitor_citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_cited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_cited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
