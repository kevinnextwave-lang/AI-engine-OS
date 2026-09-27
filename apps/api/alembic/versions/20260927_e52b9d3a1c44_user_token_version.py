"""users.token_version for immediate access-token revocation

Revision ID: e52b9d3a1c44
Revises: d41a8c2b7f10
Create Date: 2026-09-27

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e52b9d3a1c44"
down_revision: str | None = "d41a8c2b7f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
