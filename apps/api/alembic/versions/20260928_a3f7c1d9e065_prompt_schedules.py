"""prompt_schedules: recurring collection schedules

Revision ID: a3f7c1d9e065
Revises: e19c7b4d2f83
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3f7c1d9e065"
down_revision: str | None = "e19c7b4d2f83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("prompt_set_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "cadence",
            postgresql.ENUM("daily", "weekly", name="prompt_schedule_cadence"),
            nullable=False,
        ),
        sa.Column("hour_utc", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=True),
        sa.Column("providers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("models", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_batch_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["prompt_set_id"], ["prompt_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["last_batch_id"], ["prompt_run_batches.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prompt_set_id"),
    )
    op.create_index("ix_prompt_schedules_due", "prompt_schedules", ["is_active", "next_run_at"])
    op.create_index(
        op.f("ix_prompt_schedules_project_id"), "prompt_schedules", ["project_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_prompt_schedules_project_id"), table_name="prompt_schedules")
    op.drop_index("ix_prompt_schedules_due", table_name="prompt_schedules")
    op.drop_table("prompt_schedules")
    postgresql.ENUM(name="prompt_schedule_cadence").drop(op.get_bind(), checkfirst=True)
