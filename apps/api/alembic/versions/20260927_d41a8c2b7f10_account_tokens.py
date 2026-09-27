"""account tokens (password reset, email verification) + new auth events

Revision ID: d41a8c2b7f10
Revises: a7c41f09d2be
Create Date: 2026-09-27

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d41a8c2b7f10"
down_revision: str | None = "a7c41f09d2be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_account_tokens_user_id",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_account_tokens_user_id"), "account_tokens", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_account_tokens_token_hash"), "account_tokens", ["token_hash"], unique=True
    )
    # New audit events for the account flows. ADD VALUE is idempotent-guarded;
    # PostgreSQL 12+ allows it inside a transaction as long as the new value
    # isn't used in the same transaction (it isn't).
    for value in ("password_reset_requested", "password_reset_completed", "email_verified"):
        op.execute(f"ALTER TYPE auth_event ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    op.drop_index(op.f("ix_account_tokens_token_hash"), table_name="account_tokens")
    op.drop_index(op.f("ix_account_tokens_user_id"), table_name="account_tokens")
    op.drop_table("account_tokens")
    # Enum values are deliberately left in place: PostgreSQL cannot drop enum
    # values, and rows may reference them.
