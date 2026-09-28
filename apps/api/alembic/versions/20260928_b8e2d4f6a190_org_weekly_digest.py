"""organizations.weekly_digest_enabled

Revision ID: b8e2d4f6a190
Revises: a3f7c1d9e065
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e2d4f6a190"
down_revision: str | None = "a3f7c1d9e065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("weekly_digest_enabled", sa.Boolean(), server_default="true", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("organizations", "weekly_digest_enabled")
