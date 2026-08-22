"""multi-tenant database foundation

Revision ID: b2c4d6e8f0a1
Revises: e31fcb5b380e
Create Date: 2026-08-22

- users: full_name -> first_name/last_name (data preserved), email_verified bool
- organizations: plan + status enums
- memberships -> organization_members (table + constraint/index renames, data preserved)
- new tables: projects, domains, competitors
- created_at indexes on major tables
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b2c4d6e8f0a1"
down_revision: str | None = "e31fcb5b380e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORG_PLAN = ("free", "starter", "growth", "pro", "agency", "enterprise")
ORG_STATUS = ("active", "suspended", "deleted")
PROJECT_STATUS = ("active", "paused", "archived")


def upgrade() -> None:
    bind = op.get_bind()

    # --- users -----------------------------------------------------------
    op.add_column("users", sa.Column("first_name", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(length=100), nullable=True))
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Split existing full_name on the first space; carry verified state over.
    op.execute(
        """
        UPDATE users SET
            first_name = NULLIF(split_part(btrim(full_name), ' ', 1), ''),
            last_name  = NULLIF(btrim(substr(btrim(full_name), length(split_part(btrim(full_name), ' ', 1)) + 1)), ''),
            email_verified = (email_verified_at IS NOT NULL)
        WHERE full_name IS NOT NULL OR email_verified_at IS NOT NULL
        """
    )
    op.drop_column("users", "full_name")
    op.drop_column("users", "email_verified_at")
    op.create_index("ix_users_created_at", "users", ["created_at"])

    # --- organizations ---------------------------------------------------
    org_plan = postgresql.ENUM(*ORG_PLAN, name="organization_plan")
    org_status = postgresql.ENUM(*ORG_STATUS, name="organization_status")
    org_plan.create(bind, checkfirst=True)
    org_status.create(bind, checkfirst=True)
    op.add_column(
        "organizations",
        sa.Column("plan", org_plan, nullable=False, server_default="free"),
    )
    op.add_column(
        "organizations",
        sa.Column("status", org_status, nullable=False, server_default="active"),
    )
    op.execute("UPDATE organizations SET status = 'deleted' WHERE deleted_at IS NOT NULL")
    op.create_index("ix_organizations_created_at", "organizations", ["created_at"])

    # --- memberships -> organization_members -----------------------------
    op.rename_table("memberships", "organization_members")
    op.execute(
        "ALTER TABLE organization_members RENAME CONSTRAINT uq_membership_org_user "
        "TO uq_organization_members_org_user"
    )
    op.execute(
        "ALTER INDEX ix_memberships_organization_id RENAME TO ix_organization_members_organization_id"
    )
    op.execute("ALTER INDEX ix_memberships_user_id RENAME TO ix_organization_members_user_id")
    op.create_index("ix_organization_members_created_at", "organization_members", ["created_at"])

    # --- projects --------------------------------------------------------
    project_status = postgresql.ENUM(*PROJECT_STATUS, name="project_status", create_type=False)
    project_status.create(bind, checkfirst=True)
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("status", project_status, nullable=False, server_default="active"),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "slug", name="uq_projects_org_slug"),
    )
    op.create_index("ix_projects_organization_id", "projects", ["organization_id"])
    op.create_index("ix_projects_created_at", "projects", ["created_at"])

    # --- domains ---------------------------------------------------------
    op.create_table(
        "domains",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("hostname", sa.String(length=253), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_domains_project_id", "domains", ["project_id"])
    op.create_index("ix_domains_hostname", "domains", ["hostname"])
    op.create_index("ix_domains_created_at", "domains", ["created_at"])
    op.create_index(
        "uq_domains_project_primary",
        "domains",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )

    # --- competitors -----------------------------------------------------
    op.create_table(
        "competitors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("website_url", sa.String(length=2048), nullable=False),
        sa.Column("hostname", sa.String(length=253), nullable=False),
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
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_competitors_project_id", "competitors", ["project_id"])
    op.create_index("ix_competitors_hostname", "competitors", ["hostname"])
    op.create_index("ix_competitors_created_at", "competitors", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_table("competitors")
    op.drop_table("domains")
    op.drop_table("projects")
    postgresql.ENUM(name="project_status").drop(bind, checkfirst=True)

    op.drop_index("ix_organization_members_created_at", table_name="organization_members")
    op.execute("ALTER INDEX ix_organization_members_user_id RENAME TO ix_memberships_user_id")
    op.execute(
        "ALTER INDEX ix_organization_members_organization_id RENAME TO ix_memberships_organization_id"
    )
    op.execute(
        "ALTER TABLE organization_members RENAME CONSTRAINT uq_organization_members_org_user "
        "TO uq_membership_org_user"
    )
    op.rename_table("organization_members", "memberships")

    op.drop_index("ix_organizations_created_at", table_name="organizations")
    op.drop_column("organizations", "status")
    op.drop_column("organizations", "plan")
    postgresql.ENUM(name="organization_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="organization_plan").drop(bind, checkfirst=True)

    op.drop_index("ix_users_created_at", table_name="users")
    op.add_column("users", sa.Column("full_name", sa.String(length=200), nullable=True))
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        """
        UPDATE users SET
            full_name = NULLIF(btrim(concat_ws(' ', first_name, last_name)), ''),
            email_verified_at = CASE WHEN email_verified THEN now() ELSE NULL END
        """
    )
    op.drop_column("users", "email_verified")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
