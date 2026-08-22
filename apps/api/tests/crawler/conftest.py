"""Engine tests commit for real, so they get dedicated sessions on the test DB
(the shared `db_session` fixture is a single rolled-back transaction)."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session_factory
from app.models import Organization


@pytest.fixture
async def engine_session(engine: object) -> AsyncIterator[AsyncSession]:
    """A committing session; everything it creates is removed afterwards via org cascade."""
    created: list[object] = []
    factory = get_session_factory()
    async with factory() as session:
        session.info["created_org_ids"] = created
        yield session
    async with factory() as cleanup:
        await cleanup.execute(delete(Organization).where(Organization.slug.like("crawl-%")))
        await cleanup.commit()
