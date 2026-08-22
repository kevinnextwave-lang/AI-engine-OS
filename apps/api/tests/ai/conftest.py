import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.catalog import ensure_catalog


@pytest.fixture(autouse=True)
async def catalog(db_session: AsyncSession) -> None:
    """The test DB is built from metadata, not migrations, so seed the catalogue here."""
    await ensure_catalog(db_session)
