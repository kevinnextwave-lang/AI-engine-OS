"""Entity intelligence: entities extracted from structured data, their external
profile links, schema validation issues and cross-page consistency observations.

All rows are rebuilt per project by `app.entities.engine.run_entity_analysis`;
they are derived data, never edited by hand.
"""

import enum
import uuid
from typing import Any

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.page_intelligence import StructuredDataFormat


class EntityScope(enum.StrEnum):
    PAGE = "page"  # extracted from one block on one page
    PROJECT = "project"  # consolidated across pages (e.g. the project organization)


class Entity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entities"
    __table_args__ = (
        Index("ix_entities_project_type", "project_id", "entity_type"),
        Index("ix_entities_project_fingerprint", "project_id", "fingerprint"),
        Index("ix_entities_created_at", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Source page; NULL for project-scope entities.
    page_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("website_pages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    structured_data_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("page_structured_data.id", ondelete="CASCADE"), nullable=True
    )
    scope: Mapped[EntityScope] = mapped_column(
        Enum(EntityScope, name="entity_scope", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=EntityScope.PAGE,
    )
    source_format: Mapped[StructuredDataFormat | None] = mapped_column(
        Enum(
            StructuredDataFormat,
            name="structured_data_format",
            values_callable=lambda e: [m.value for m in e],
            create_type=False,
        ),
        nullable=True,
    )
    entity_type: Mapped[str] = mapped_column(String(120), nullable=False)
    # Additional @type values when a node declares several (first one is entity_type).
    extra_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    same_as: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    identifier: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Where inside the block the node was found ("" = root, "@graph[2].publisher", ...).
    json_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # type|normalized name — used to match the same real-world thing across pages.
    fingerprint: Mapped[str | None] = mapped_column(String(700), nullable=True)
    is_known_type: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class EntityLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A sameAs / external profile relationship of an entity."""

    __tablename__ = "entity_links"
    __table_args__ = (
        Index("ix_entity_links_project_platform", "project_id", "platform"),
        Index("ix_entity_links_created_at", "created_at"),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    platform: Mapped[str] = mapped_column(String(40), nullable=False)  # linkedin, wikipedia, ...
    is_authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SchemaIssue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A validation problem in one structured-data block."""

    __tablename__ = "schema_issues"
    __table_args__ = (
        Index("ix_schema_issues_project_code", "project_id", "code"),
        Index("ix_schema_issues_created_at", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("website_pages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    structured_data_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("page_structured_data.id", ondelete="CASCADE"), nullable=True
    )
    format: Mapped[StructuredDataFormat] = mapped_column(
        Enum(
            StructuredDataFormat,
            name="structured_data_format",
            values_callable=lambda e: [m.value for m in e],
            create_type=False,
        ),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)  # high | medium | low | info
    message: Mapped[str] = mapped_column(Text, nullable=False)
    json_path: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    block_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class EntityObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Cross-page finding about entities (inconsistency, duplicates, ...)."""

    __tablename__ = "entity_observations"
    __table_args__ = (
        Index("ix_entity_observations_project_code", "project_id", "code"),
        Index("ix_entity_observations_created_at", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    entity_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
