"""AI provider catalogue and generation log.

Credentials are NEVER stored here; they come from environment variables.
`ai_generations` records every call's metadata (and optionally the text) so
results can be audited and reused without re-querying a provider.
"""

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AiProvider(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_providers"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AiModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_models"
    __table_args__ = (
        UniqueConstraint("provider_id", "model_key", name="uq_ai_models_provider_model"),
        Index("ix_ai_models_created_at", "created_at"),
    )

    provider_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_key: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    # e.g. {"supports_temperature": true, "max_output_tokens": 8192, "context_window": 128000}
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # {"input_per_million": 0.15, "output_per_million": 0.6, "currency": "USD", "version": "..."}
    pricing: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AiGeneration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One provider call. Prompts/responses are stored only when the caller
    asks for it and AI_STORE_RESPONSE_TEXT allows it."""

    __tablename__ = "ai_generations"
    __table_args__ = (
        Index("ix_ai_generations_project_created", "project_id", "created_at"),
        Index("ix_ai_generations_created_at", "created_at"),
        Index("ix_ai_generations_request_id", "request_id", unique=True),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_providers.id", ondelete="SET NULL"), nullable=True
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_models.id", ondelete="SET NULL"), nullable=True
    )
    provider_key: Mapped[str] = mapped_column(String(40), nullable=False)
    model_key: Mapped[str] = mapped_column(String(120), nullable=False)
    purpose: Mapped[str] = mapped_column(String(60), nullable=False, default="generic")
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    finish_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
