"""'partial' prompt-run batch status (finished with successes AND failures)

Revision ID: f6a3c8e91b27
Revises: e52b9d3a1c44
Create Date: 2026-09-27

"""

from collections.abc import Sequence

from alembic import op

revision: str = "f6a3c8e91b27"
down_revision: str | None = "e52b9d3a1c44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE prompt_run_batch_status ADD VALUE IF NOT EXISTS 'partial'")


def downgrade() -> None:
    # PostgreSQL cannot drop enum values; rows may reference it. No-op.
    pass
