"""one active crawl per project, enforced by the database

The service checks "no queued/running crawl exists" before inserting, but two
concurrent requests can both pass that check. This partial unique index makes
the database the referee; the service turns the violation into a 409.

Revision ID: a7c41f09d2be
Revises: c09256688932
Create Date: 2026-09-25

"""

from collections.abc import Sequence

from alembic import op

revision: str = "a7c41f09d2be"
down_revision: str | None = "c09256688932"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "uq_crawl_jobs_one_active_per_project"


def upgrade() -> None:
    # If historical races already left several active crawls on one project,
    # fail all but the newest so the index can be created.
    op.execute(
        """
        UPDATE crawl_jobs SET status = 'failed',
            error_message = 'Superseded by a newer crawl (concurrency cleanup)',
            completed_at = NOW()
        WHERE status IN ('queued', 'running')
          AND id NOT IN (
            SELECT DISTINCT ON (project_id) id FROM crawl_jobs
            WHERE status IN ('queued', 'running')
            ORDER BY project_id, created_at DESC
          )
        """
    )
    op.execute(
        f"CREATE UNIQUE INDEX {INDEX} ON crawl_jobs (project_id) "
        "WHERE status IN ('queued', 'running')"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX}")
