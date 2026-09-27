"""seed OpenAI web-search models into existing catalogs (idempotent, literal)

Revision ID: e19c7b4d2f83
Revises: c83e5f1a9d24
Create Date: 2026-09-27

"""

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e19c7b4d2f83"
down_revision: str | None = "c83e5f1a9d24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MODELS = (
    (
        "gpt-4o-mini-search-preview",
        "GPT-4o mini + web search",
        {
            "supports_temperature": False,
            "supports_system_prompt": True,
            "max_output_tokens": 16384,
            "context_window": 128000,
            "grounded_search": True,
        },
        {
            "input_per_million": 0.15,
            "output_per_million": 0.60,
            "currency": "USD",
            "version": "2025-06-list",
        },
    ),
    (
        "gpt-4o-search-preview",
        "GPT-4o + web search",
        {
            "supports_temperature": False,
            "supports_system_prompt": True,
            "max_output_tokens": 16384,
            "context_window": 128000,
            "grounded_search": True,
        },
        {
            "input_per_million": 2.50,
            "output_per_million": 10.00,
            "currency": "USD",
            "version": "2025-06-list",
        },
    ),
)


def upgrade() -> None:
    conn = op.get_bind()
    provider_id = conn.execute(
        sa.text("SELECT id FROM ai_providers WHERE provider_key = 'openai'")
    ).scalar()
    if provider_id is None:  # a catalog without openai: nothing to seed onto
        return
    for model_key, display, caps, pricing in _MODELS:
        exists = conn.execute(
            sa.text("SELECT 1 FROM ai_models WHERE provider_id = :pid AND model_key = :mk"),
            {"pid": provider_id, "mk": model_key},
        ).scalar()
        if exists:
            continue
        conn.execute(
            sa.text(
                "INSERT INTO ai_models "
                "(id, provider_id, model_key, display_name, capabilities, pricing, is_enabled) "
                "VALUES (:id, :pid, :mk, :dn, :caps, :pricing, true)"
            ),
            {
                "id": uuid.uuid4(),
                "pid": provider_id,
                "mk": model_key,
                "dn": display,
                "caps": json.dumps(caps),
                "pricing": json.dumps(pricing),
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM ai_models WHERE model_key IN "
            "('gpt-4o-mini-search-preview', 'gpt-4o-search-preview')"
        )
    )
