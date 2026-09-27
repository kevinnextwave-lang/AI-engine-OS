"""Settings coercions and production startup safety checks."""

import pytest

from app.core.config import Settings, validate_settings


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


def _prod_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_env": "production",
        "jwt_secret": "k1" * 24,
        "jwt_refresh_secret": "r2" * 24,
        "cookie_secure": True,
        "cors_origins": ["https://app.mydomain.com"],
        "database_url": "postgresql+asyncpg://u:p@db.internal:5432/db",
        "_env_file": None,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_production_checks_pass_with_strong_config() -> None:
    validate_settings(_prod_settings())


def test_production_rejects_placeholder_secrets() -> None:
    """The exact placeholders shipped in .env.example must refuse to boot —
    they are public values, not secrets."""
    for bad in (
        "dev-only-insecure-secret-change-me",
        "change-me-to-a-long-random-string",
        "change-me-to-a-different-long-random-string",
        "ExAmPlE-" + "x" * 40,
    ):
        with pytest.raises(RuntimeError, match="strong secret"):
            validate_settings(_prod_settings(jwt_secret=bad))
        with pytest.raises(RuntimeError, match="strong secret"):
            validate_settings(_prod_settings(jwt_refresh_secret=bad))


def test_production_rejects_short_secrets() -> None:
    with pytest.raises(RuntimeError, match="at least 32 characters"):
        validate_settings(_prod_settings(jwt_secret="a" * 16 + "b" * 4))


def test_production_rejects_identical_secrets() -> None:
    same = "s3" * 24
    with pytest.raises(RuntimeError, match="must differ"):
        validate_settings(_prod_settings(jwt_secret=same, jwt_refresh_secret=same))


def test_development_skips_production_checks() -> None:
    """Dev keeps its ergonomics: the defaults boot without env vars."""
    validate_settings(Settings(_env_file=None))
