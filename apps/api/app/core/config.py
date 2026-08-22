"""Application settings loaded from environment variables.

All configuration flows through this module. Never read os.environ elsewhere.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
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
    jwt_secret: str = Field(default="dev-only-insecure-secret-change-me", min_length=16)
    jwt_refresh_secret: str = Field(
        default="dev-only-insecure-refresh-secret-change-me", min_length=16
    )
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

    # Crawler (defaults; plan limits in app/crawler/limits.py may cap these)
    crawl_user_agent: str = (
        "AI-Search-Growth-OS-Crawler/1.0 (+https://aisearchgrowth.example/crawler)"
    )
    crawl_concurrency: int = 5
    crawl_requests_per_second: float = 2.0
    crawl_min_delay_seconds: float = 0.0
    crawl_default_max_pages: int = 200
    crawl_default_max_depth: int = 5
    crawl_connect_timeout_seconds: float = 5.0
    crawl_read_timeout_seconds: float = 15.0
    crawl_total_timeout_seconds: float = 30.0
    crawl_max_response_bytes: int = 5 * 1024 * 1024

    # AI providers (credentials never leave the API process; never logged)
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    google_ai_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_base_url: str = "https://api.anthropic.com"
    google_ai_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    anthropic_api_version: str = "2023-06-01"
    # Default model per provider; the catalogue lives in the ai_models table.
    openai_default_model: str = "gpt-4o-mini"
    anthropic_default_model: str = "claude-3-5-haiku-latest"
    google_default_model: str = "gemini-2.0-flash"
    ai_default_timeout_seconds: float = 60.0
    ai_default_max_tokens: int = 1024
    ai_store_response_text: bool = True
    # Prompt execution (Milestone 3C)
    ai_search_system_prompt: str = (
        "You are a helpful assistant. Answer the user's question directly and name specific "
        "products, companies or sources where relevant."
    )
    ai_run_max_attempts: int = 4
    ai_run_retry_base_seconds: float = 5.0
    ai_run_retry_max_seconds: float = 300.0
    # Requests per minute per provider; 0 disables throttling for that provider.
    ai_rate_limit_openai_per_minute: int = 60
    ai_rate_limit_anthropic_per_minute: int = 50
    ai_rate_limit_google_per_minute: int = 60
    # Response intelligence Stage 2 (LLM-assisted interpretation); off by default.
    ai_parser_llm_enabled: bool = False
    # Citation Intelligence (4B): optional JSON overriding/extending app/sources/registry.json.
    source_registry_path: str | None = None
    # Minimum confidence before a domain is given a type other than "unknown".
    source_classification_threshold: float = 0.5
    ai_parser_provider: str = "openai"
    ai_parser_model: str | None = None
    ai_run_max_tokens: int = 1024
    ai_run_temperature: float | None = 0.2

    def ai_rate_limit_for(self, provider_key: str) -> int:
        return int(getattr(self, f"ai_rate_limit_{provider_key}_per_minute", 0) or 0)

    crawl_max_redirects: int = 5
    crawl_max_retries: int = 2
    crawl_retry_backoff_seconds: float = 0.5
    crawl_allow_subdomains: bool = False
    crawl_html_storage: Literal["none", "local"] = "none"
    crawl_html_storage_path: str = "./var/crawl-html"
    crawl_status_check_interval: int = 10  # URLs between cancellation checks

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
    if settings.is_production:
        for name, value in (
            ("JWT_SECRET", settings.jwt_secret),
            ("JWT_REFRESH_SECRET", settings.jwt_refresh_secret),
        ):
            if value.startswith("dev-only"):
                raise RuntimeError(f"{name} must be set to a strong secret in production")
        if settings.jwt_secret == settings.jwt_refresh_secret:
            raise RuntimeError("JWT_SECRET and JWT_REFRESH_SECRET must differ")
    return settings
