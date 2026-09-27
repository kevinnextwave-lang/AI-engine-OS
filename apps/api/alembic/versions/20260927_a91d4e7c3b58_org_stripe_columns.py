"""organizations.stripe_customer_id / stripe_subscription_id

Revision ID: a91d4e7c3b58
Revises: f6a3c8e91b27
Create Date: 2026-09-27

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a91d4e7c3b58"
down_revision: str | None = "f6a3c8e91b27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations", sa.Column("stripe_customer_id", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "organizations", sa.Column("stripe_subscription_id", sa.String(length=64), nullable=True)
    )
    op.create_index(
        op.f("ix_organizations_stripe_customer_id"),
        "organizations",
        ["stripe_customer_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_organizations_stripe_customer_id"), table_name="organizations")
    op.drop_column("organizations", "stripe_subscription_id")
    op.drop_column("organizations", "stripe_customer_id")
