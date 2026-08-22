"""Competitor intelligence data model (Milestone 5A).

`competitors` predates 5A (name, website_url, hostname). 5A extends it rather
than replacing it: `hostname` is the competitor's `domain` and
`normalized_domain` its canonical form; `description`, `source`, `status`,
`confidence` and `normalized_name` are new. Aliases, domains and products live
in their own tables. Everything is organization-owned through project_id.
"""

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.project import Project


class CompetitorSource(enum.StrEnum):
    MANUAL = "manual"
    DISCOVERED = "discovered"
    IMPORTED = "imported"
    AI_DETECTED = "ai_detected"


class CompetitorStatus(enum.StrEnum):
    ACTIVE = "active"
    IGNORED = "ignored"
    ARCHIVED = "archived"


class CompetitorConfidence(enum.StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CompetitorDomainType(enum.StrEnum):
    PRIMARY = "primary"
    PRODUCT = "product"
    SUPPORT = "support"
    BLOG = "blog"
    COMMUNITY = "community"
    OTHER = "other"


class Competitor(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A competing brand tracked by a project. Organization-owned through project_id."""

    __tablename__ = "competitors"
    __table_args__ = (
        UniqueConstraint("project_id", "hostname", name="uq_competitors_project_hostname"),
        UniqueConstraint(
            "project_id", "normalized_name", name="uq_competitors_project_normalized_name"
        ),
        Index("ix_competitors_hostname", "hostname"),
        Index("ix_competitors_normalized_domain", "normalized_domain"),
        Index("ix_competitors_status", "status"),
        Index("ix_competitors_created_at", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    website_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    # `hostname` is the competitor's domain as entered (lower-cased);
    # `normalized_domain` strips `www.` and applies IDNA.
    hostname: Mapped[str] = mapped_column(String(253), nullable=False)
    normalized_domain: Mapped[str] = mapped_column(String(253), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CompetitorSource.MANUAL.value
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CompetitorStatus.ACTIVE.value
    )
    confidence: Mapped[str] = mapped_column(
        String(10), nullable=False, default=CompetitorConfidence.HIGH.value
    )

    project: Mapped["Project"] = relationship(back_populates="competitors")
    aliases: Mapped[list["CompetitorAlias"]] = relationship(
        back_populates="competitor",
        cascade="all, delete-orphan",
        order_by="CompetitorAlias.created_at",
    )
    domains: Mapped[list["CompetitorDomain"]] = relationship(
        back_populates="competitor",
        cascade="all, delete-orphan",
        order_by="CompetitorDomain.created_at",
    )
    products: Mapped[list["CompetitorProduct"]] = relationship(
        back_populates="competitor",
        cascade="all, delete-orphan",
        order_by="CompetitorProduct.created_at",
    )


class CompetitorAlias(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Another name the competitor is known by: company names, product names,
    abbreviations, alternate spellings."""

    __tablename__ = "competitor_aliases"
    __table_args__ = (
        # Alternate spellings of the same identity ("Fresh Books" for FreshBooks) are
        # legitimate aliases, so uniqueness is on the alias text, not its normalised form.
        UniqueConstraint("competitor_id", "alias", name="uq_competitor_aliases_competitor_alias"),
        Index("ix_competitor_aliases_competitor_id", "competitor_id"),
        Index("ix_competitor_aliases_normalized_alias", "normalized_alias"),
    )

    competitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(200), nullable=False)

    competitor: Mapped[Competitor] = relationship(back_populates="aliases")


class CompetitorDomain(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "competitor_domains"
    __table_args__ = (
        UniqueConstraint("competitor_id", "domain", name="uq_competitor_domains_competitor_domain"),
        Index("ix_competitor_domains_competitor_id", "competitor_id"),
        Index("ix_competitor_domains_domain", "domain"),
    )

    competitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String(253), nullable=False)  # normalized hostname
    domain_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CompetitorDomainType.OTHER.value
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    competitor: Mapped[Competitor] = relationship(back_populates="domains")


class CompetitorProduct(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "competitor_products"
    __table_args__ = (
        UniqueConstraint(
            "competitor_id", "normalized_name", name="uq_competitor_products_competitor_name"
        ),
        Index("ix_competitor_products_competitor_id", "competitor_id"),
    )

    competitor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    competitor: Mapped[Competitor] = relationship(back_populates="products")
