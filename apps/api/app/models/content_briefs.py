"""Content briefs (Milestone 6C): the Content Strategy Agent's work product.

A brief describes what should be created and why — never the content itself.
Everything in a brief is derived from observed project data; evidence
requirements say what real material must be collected and explicitly forbid
fabrication. Briefs are unique per (project, source_key) so re-running the
agent updates a brief in place without touching its review status.
"""

import enum
import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ContentBriefStatus(enum.StrEnum):
    DRAFT = "draft"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ContentType(enum.StrEnum):
    NEW_ARTICLE = "new_article"
    EXISTING_PAGE_OPTIMIZATION = "existing_page_optimization"
    COMPARISON_PAGE = "comparison_page"
    ALTERNATIVE_PAGE = "alternative_page"
    USE_CASE_PAGE = "use_case_page"
    FAQ_PAGE = "faq_page"
    PRODUCT_PAGE = "product_page"
    RESEARCH_CONTENT = "research_content"
    CASE_STUDY = "case_study"
    GLOSSARY = "glossary"
    DOCUMENTATION = "documentation"


class ContentBrief(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "content_briefs"
    __table_args__ = (
        UniqueConstraint("project_id", "source_key", name="uq_content_briefs_project_source_key"),
        Index("ix_content_briefs_project_id", "project_id"),
        Index("ix_content_briefs_status", "status"),
        Index("ix_content_briefs_content_type", "content_type"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    # What the brief was derived from (e.g. "content_gap:<id>"); upsert key.
    source_key: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_prompt_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    competitor_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    search_intent: Mapped[str] = mapped_column(Text, nullable=False, default="")
    audience: Mapped[str] = mapped_column(Text, nullable=False, default="")
    differentiation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    outline: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    information_requirements: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    evidence_requirements: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    citation_opportunities: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    entity_requirements: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    internal_link_recommendations: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    confidence: Mapped[str] = mapped_column(String(10), nullable=False, default="low")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ContentBriefStatus.DRAFT.value
    )
