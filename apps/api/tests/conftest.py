"""Test fixtures.

Tests run against a real Postgres database (TEST_DATABASE_URL, default
ai_search_growth_os_test) so constraints, enums and UUID behaviour match
production. The schema is created from Base.metadata and dropped per session;
each test runs inside a transaction that is rolled back.
"""

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-0123456789abcdef")
os.environ.setdefault("JWT_REFRESH_SECRET", "test-refresh-key-0123456789abcdef")
os.environ.setdefault("REDIS_URL", "redis://localhost:1/0")  # unreachable -> memory limiter
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_search_growth_os_test",
)

from app.api import deps  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.session import get_db_session  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base  # noqa: E402

TEST_DB_URL = os.environ["DATABASE_URL"]


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[object]:
    eng = create_async_engine(TEST_DB_URL, poolclass=None)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest.fixture
async def db_session(engine: object) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        trans = await conn.begin()
        factory = async_sessionmaker(
            conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        async with factory() as session:
            yield session
        await trans.rollback()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    deps._memory_limiter.reset()
    app = create_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session
        await db_session.flush()

    app.dependency_overrides[get_db_session] = _override
    app.state.redis = None
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def settings():  # type: ignore[no-untyped-def]
    return get_settings()


def unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


async def register(client: AsyncClient, email: str | None = None, org: str = "Acme") -> dict:  # type: ignore[type-arg]
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email or unique_email(),
            "password": "CorrectHorseBattery1",
            "full_name": "Test User",
            "organization_name": org,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
