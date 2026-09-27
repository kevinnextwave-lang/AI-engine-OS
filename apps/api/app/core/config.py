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
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("log_level", mode="before")
    @classmethod
    def _uppercase_log_level(cls, value: object) -> object:
        # LOG_LEVEL=info worked before this became a Literal; keep it working.
        return value.upper() if isinstance(value, str) else value

    api_v1_prefix: str = "/api/v1"

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/ai_search_growth_os"
    )
    db_echo: bool = False

    @field_validator("database_url", mode="before")
    @classmethod
    def _coerce_async_driver(cls, value: object) -> object:
        """Accept plain postgres URLs (as managed hosts like Railway/Heroku
        provide them) and upgrade to the async driver the app requires."""
        if isinstance(value, str):
            if value.startswith("postgres://"):
                value = "postgresql://" + value.removeprefix("postgres://")
            if value.startswith("postgresql://"):
                value = "postgresql+asyncpg://" + value.removeprefix("postgresql://")
        return value

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    jwt_secret: str = Field(default="dev-only-insecure-secret-change-me", min_length=16)
    jwt_refresh_secret: str = Field(
        default="dev-only-insecure-refresh-secret-change-me", min_length=16
    )
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    password_reset_token_expire_minutes: int = 60
    email_verification_token_expire_hours: int = 72
    # Check new passwords against Have I Been Pwned (k-anonymity range API).
    # Fails open when the API is unreachable. Off by default.
    hibp_password_check: bool = False

    # Observability. Setting SENTRY_DSN turns on error tracking in both the
    # API and the worker; unset means zero overhead.
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.0

    # Data retention (days; 0 disables that pruner). Applied by the daily
    # retention task on celery beat. Current-state tables (website_pages,
    # ai_responses, observations) are never pruned — these cover history
    # and security bookkeeping that otherwise grow without bound.
    retention_crawl_urls_days: int = 90
    retention_page_versions_days: int = 180  # newest version per page always kept
    retention_auth_audit_days: int = 365
    retention_refresh_tokens_days: int = 60  # revoked/expired ones only
    retention_account_tokens_days: int = 30  # used/expired ones only

    # Email delivery (password reset, email verification).
    # console: log the email instead of sending (development default).
    # smtp:    any SMTP relay (stdlib smtplib, STARTTLS by default).
    # resend:  Resend's HTTP API (RESEND_API_KEY required).
    email_backend: Literal["console", "smtp", "resend"] = "console"
    email_from: str = "AI Search Growth OS <no-reply@localhost>"
    # Base URL of the web app, used to build emailed links (reset/verify).
    web_base_url: str = "http://localhost:3000"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    resend_api_key: SecretStr | None = None

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
    perplexity_api_key: SecretStr | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_base_url: str = "https://api.anthropic.com"
    google_ai_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    perplexity_base_url: str = "https://api.perplexity.ai"
    anthropic_api_version: str = "2023-06-01"
    # Google Search grounding for Gemini calls: real retrieval with real
    # source citations, billed extra per grounded request. Off by default.
    google_ai_grounding: bool = False
    # Default model per provider; the catalogue lives in the ai_models table.
    openai_default_model: str = "gpt-4o-mini"
    anthropic_default_model: str = "claude-3-5-haiku-latest"
    google_default_model: str = "gemini-2.0-flash"
    perplexity_default_model: str = "sonar"
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
    # Cost controls. One batch = prompts × providers paid LLM calls, so both
    # knobs bound worst-case spend per request; the daily ceiling bounds it
    # per organization per UTC day (0 disables the ceiling, e.g. self-hosted).
    ai_run_max_prompts_per_batch: int = 500
    ai_daily_cost_limit_usd: float = 25.0
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

    # Alert notifications (webhook delivery runs in workers, never in requests)
    notification_webhook_timeout_seconds: float = 10.0
    notification_webhook_max_retries: int = 2
    notification_webhook_retry_backoff_seconds: float = 1.0

    # Scheduled monitoring (requires a `celery beat` process; see docs)
    monitoring_enabled: bool = True
    monitoring_hour_utc: int = Field(default=6, ge=0, le=23)  # daily detection run, UTC hour
    monitoring_activity_window_days: int = 2  # only projects with recent responses
    monitoring_detection_window_days: int = 30

    # Stripe (SecretStr keeps them out of reprs/dumps). Billing is enabled
    # exactly when the secret key is set; price IDs map Stripe prices onto
    # the self-serve plans.
    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None
    stripe_price_starter: str | None = None
    stripe_price_growth: str | None = None

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


# Substrings that mark a signing secret as a known placeholder rather than a
# generated value. This deliberately catches the examples shipped in this
# repo's own .env.example files ("change-me-…"): a deploy that copied them
# verbatim must refuse to start, because those values are public.
_PLACEHOLDER_SECRET_MARKERS = (
    "dev-only",
    "change-me",
    "change_me",
    "changeme",
    "example",
    "placeholder",
    "insecure",
    "your-secret",
)

_PRODUCTION_SECRET_MIN_LENGTH = 32


def validate_settings(settings: Settings) -> Settings:
    """Startup safety checks. Split from get_settings so tests can exercise
    the production rules without touching the process environment."""
    if settings.is_production:
        for name, value in (
            ("JWT_SECRET", settings.jwt_secret),
            ("JWT_REFRESH_SECRET", settings.jwt_refresh_secret),
        ):
            lowered = value.lower()
            if any(marker in lowered for marker in _PLACEHOLDER_SECRET_MARKERS):
                raise RuntimeError(f"{name} must be set to a strong secret in production")
            if len(value) < _PRODUCTION_SECRET_MIN_LENGTH:
                raise RuntimeError(
                    f"{name} must be at least {_PRODUCTION_SECRET_MIN_LENGTH} characters "
                    "in production (use e.g. `openssl rand -base64 48`)"
                )
        if settings.jwt_secret == settings.jwt_refresh_secret:
            raise RuntimeError("JWT_SECRET and JWT_REFRESH_SECRET must differ")
        if not settings.cookie_secure:
            raise RuntimeError("COOKIE_SECURE must be true in production")
        if "*" in settings.cors_origins:
            # Starlette echoes the request origin for "*" when credentials are
            # allowed, which would open the credentialed API to any site.
            raise RuntimeError("CORS_ORIGINS must list explicit origins in production, not '*'")
        if "localhost" in settings.database_url:
            raise RuntimeError("DATABASE_URL still points at localhost in production")
        if settings.email_backend == "resend" and settings.resend_api_key is None:
            raise RuntimeError("EMAIL_BACKEND=resend requires RESEND_API_KEY")
        if settings.email_backend != "console" and "localhost" in settings.web_base_url:
            raise RuntimeError(
                "WEB_BASE_URL still points at localhost in production — emailed "
                "password-reset/verification links would be broken"
            )
    if settings.cookie_samesite == "none" and not settings.cookie_secure:
        raise RuntimeError("COOKIE_SAMESITE=none requires COOKIE_SECURE=true (browser rule)")
    return settings


@lru_cache
def get_settings() -> Settings:
    return validate_settings(Settings())
