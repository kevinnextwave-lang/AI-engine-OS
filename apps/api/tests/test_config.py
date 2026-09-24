"""Settings coercions."""

from app.core.config import Settings


def test_database_url_plain_postgres_is_upgraded_to_asyncpg() -> None:
    """Managed hosts (Railway, Heroku) hand out postgres:// or postgresql://
    URLs; the app silently upgrades them to the async driver it requires."""
    for raw in (
        "postgres://u:p@host:5432/db",
        "postgresql://u:p@host:5432/db",
        "postgresql+asyncpg://u:p@host:5432/db",
    ):
        s = Settings(database_url=raw, _env_file=None)
        assert s.database_url == "postgresql+asyncpg://u:p@host:5432/db"
        assert s.sync_database_url == "postgresql://u:p@host:5432/db"


def test_non_postgres_urls_untouched() -> None:
    s = Settings(database_url="sqlite+aiosqlite:///./x.db", _env_file=None)
    assert s.database_url == "sqlite+aiosqlite:///./x.db"
