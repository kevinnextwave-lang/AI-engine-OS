"""seed the Perplexity provider + sonar models into existing catalogs

Values are literal (not imported from app.ai.catalog) so this migration
stays stable regardless of later catalog edits. Idempotent: existing rows
are left untouched.

Revision ID: b74f2c9e8d31
Revises: a91d4e7c3b58
Create Date: 2026-09-27

"""

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b74f2c9e8d31"
down_revision: str | None = "a91d4e7c3b58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MODELS = (
    (
        "sonar",
        "Perplexity Sonar",
        {
            "supports_temperature": True,
            "max_temperature": 1.99,
            "supports_system_prompt": True,
            "context_window": 128000,
            "grounded_search": True,
        },
        {
            "input_per_million": 1.00,
            "output_per_million": 1.00,
            "currency": "USD",
            "version": "2025-06-list",
        },
    ),
    (
        "sonar-pro",
        "Perplexity Sonar Pro",
        {
            "supports_temperature": True,
            "max_temperature": 1.99,
            "supports_system_prompt": True,
            "context_window": 200000,
            "grounded_search": True,
        },
        {
            "input_per_million": 3.00,
            "output_per_million": 15.00,
            "currency": "USD",
            "version": "2025-06-list",
        },
    ),
)


def upgrade() -> None:
    conn = op.get_bind()
    provider_id = conn.execute(
        sa.text("SELECT id FROM ai_providers WHERE provider_key = 'perplexity'")
    ).scalar()
    if provider_id is None:
        provider_id = uuid.uuid4()
        conn.execute(
            sa.text(
                "INSERT INTO ai_providers (id, provider_key, name, is_enabled) "
                "VALUES (:id, 'perplexity', 'Perplexity', true)"
            ),
            {"id": provider_id},
        )
    for model_key, display, caps, pricing in _MODELS:
        exists = conn.execute(
            sa.text(
                "SELECT 1 FROM ai_models WHERE provider_id = :pid AND model_key = :mk"
            ),
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
            "DELETE FROM ai_models WHERE provider_id = "
            "(SELECT id FROM ai_providers WHERE provider_key = 'perplexity')"
        )
    )
    conn.execute(sa.text("DELETE FROM ai_providers WHERE provider_key = 'perplexity'"))
