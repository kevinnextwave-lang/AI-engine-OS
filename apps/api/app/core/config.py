"""Application settings loaded from environment variables.

All configuration flows through this module. Never read os.environ elsewhere.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "AI Search Growth OS API"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_search_growth_os"
    )
    db_echo: bool = False

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    jwt_secret_key: str = Field(default="dev-only-insecure-secret-change-me", min_length=16)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    # Cookies
    cookie_secure: bool = False
    cookie_domain: str | None = None
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    refresh_cookie_name: str = "asg_refresh_token"

    # CORS
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    # Rate limiting
    rate_limit_auth_per_minute: int = 10
    rate_limit_default_per_minute: int = 120

    # Stripe (config only in Milestone 1)
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [o.strip() for o in value.split(",") if o.strip()]
        return value

    @field_validator("cookie_domain", mode="before")
    @classmethod
    def _empty_domain_is_none(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            if " " in value or "#" in value:
                raise ValueError("COOKIE_DOMAIN must be a bare hostname")
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def sync_database_url(self) -> str:
        """Driver-less URL for Alembic / sync tooling."""
        return self.database_url.replace("+asyncpg", "").replace("+aiosqlite", "")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_production and settings.jwt_secret_key.startswith("dev-only"):
        raise RuntimeError("JWT_SECRET_KEY must be set to a strong secret in production")
    return settings
