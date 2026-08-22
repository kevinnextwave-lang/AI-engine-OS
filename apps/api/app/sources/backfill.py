"""One-off / operator entry point:  python -m app.sources.backfill [--project ID] [--force]

Resolves existing citations into the Citation Intelligence tables without
re-running any AI query. Safe to run repeatedly."""

import argparse
import asyncio
import uuid

from app.core.logging import configure_logging
from app.db.session import dispose_engine, get_session_factory
from app.sources.service import SourceIntelligenceService


async def _run(project_id: uuid.UUID | None, force: bool) -> None:
    try:
        async with get_session_factory()() as session:
            stats = await SourceIntelligenceService(session).backfill(
                project_id=project_id, force=force
            )
            print(stats)  # noqa: T201 - CLI output
    finally:
        await dispose_engine()


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=uuid.UUID, default=None)
    parser.add_argument("--force", action="store_true", help="re-resolve already linked citations")
    args = parser.parse_args()
    asyncio.run(_run(args.project, args.force))


if __name__ == "__main__":
    main()
