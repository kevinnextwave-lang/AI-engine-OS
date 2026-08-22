import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.catalog import ensure_catalog


@pytest.fixture(autouse=True)
async def catalog(db_session: AsyncSession) -> None:
    await ensure_catalog(db_session)
