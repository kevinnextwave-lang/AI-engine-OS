"""Structured observations parsed from AI responses (Milestone 3D)."""

import uuid

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BrandMention(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "brand_mentions"
    __table_args__ = (
        Index("ix_brand_mentions_project_created", "project_id", "created_at"),
        Index("ix_brand_mentions_created_at", "created_at"),
    )

    ai_response_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_responses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    brand_name: Mapped[str] = mapped_column(String(200), nullable=False)
    mention_text: Mapped[str] = mapped_column(String(500), nullable=False)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sentiment: Mapped[str] = mapped_column(String(10), nullable=False, default="unknown")
    recommendation_strength: Mapped[str] = mapped_column(
        String(10), nullable=False, default="unknown"
    )
    context: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="deterministic")
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False)


class CompetitorMention(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "competitor_mentions"
    __table_args__ = (
        Index("ix_competitor_mentions_competitor_created", "competitor_id", "created_at"),
        Index("ix_competitor_mentions_created_at", "created_at"),
    )

    ai_response_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_responses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    competitor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("competitors.id", ondelete="SET NULL"), nullable=True
    )
    competitor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    mention_text: Mapped[str] = mapped_column(String(500), nullable=False)
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sentiment: Mapped[str] = mapped_column(String(10), nullable=False, default="unknown")
    recommendation_strength: Mapped[str] = mapped_column(
        String(10), nullable=False, default="unknown"
    )
    context: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="deterministic")
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False)


class ResponseClaim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "claims"
    __table_args__ = (
        Index("ix_claims_project_created", "project_id", "created_at"),
        Index("ix_claims_created_at", "created_at"),
    )

    ai_response_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_responses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    predicate: Mapped[str] = mapped_column(String(100), nullable=False)
    object: Mapped[str] = mapped_column(String(500), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    context: Mapped[str] = mapped_column(Text, nullable=False, default="")
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False)


class ResponseCitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A citation observed in one AI response. `source_domain_id` /
    `source_page_id` link it into the Citation Intelligence graph (Milestone 4A);
    they are NULL until the citation has been resolved (new citations are
    resolved on parse, historical ones by the backfill) or when the parser saw
    neither a URL nor a domain."""

    __tablename__ = "citations"
    __table_args__ = (
        Index("ix_citations_domain", "domain"),
        Index("ix_citations_created_at", "created_at"),
        Index("ix_citations_project_id", "project_id"),
        Index("ix_citations_source_domain_id", "source_domain_id"),
        Index("ix_citations_source_page_id", "source_page_id"),
    )

    ai_response_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_responses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(253), nullable=True)
    anchor_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    citation_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    citation_type: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    extraction_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    source_domain_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_domains.id", ondelete="SET NULL"), nullable=True
    )
    source_page_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_pages.id", ondelete="SET NULL"), nullable=True
    )
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False)
