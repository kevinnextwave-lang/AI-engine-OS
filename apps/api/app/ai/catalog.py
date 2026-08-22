"""Default provider/model catalogue. Used by the seed migration and by tests;
editable afterwards in the ai_providers / ai_models tables."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AiModel, AiProvider

DEFAULT_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("openai", "OpenAI"),
    ("anthropic", "Anthropic"),
    ("google", "Google AI"),
)

# Default list prices (USD per million tokens). Editable in ai_models.pricing; the
# version tag is copied onto every usage record so later price changes stay auditable.
PRICING_VERSION = "2025-06-list"
DEFAULT_PRICING: dict[str, dict[str, Any]] = {
    "gpt-4o-mini": {"input_per_million": 0.15, "output_per_million": 0.60},
    "gpt-4o": {"input_per_million": 2.50, "output_per_million": 10.00},
    "claude-3-5-haiku-latest": {"input_per_million": 0.80, "output_per_million": 4.00},
    "claude-sonnet-4-0": {"input_per_million": 3.00, "output_per_million": 15.00},
    "gemini-2.0-flash": {"input_per_million": 0.10, "output_per_million": 0.40},
    "gemini-2.5-pro": {"input_per_million": 1.25, "output_per_million": 10.00},
}


def default_pricing(model_key: str) -> dict[str, Any]:
    base = DEFAULT_PRICING.get(model_key, {"input_per_million": 0.0, "output_per_million": 0.0})
    return {**base, "currency": "USD", "version": PRICING_VERSION}


# (provider_key, model_key, display_name, capabilities)
DEFAULT_MODELS: tuple[tuple[str, str, str, dict[str, Any]], ...] = (
    (
        "openai",
        "gpt-4o-mini",
        "GPT-4o mini",
        {
            "supports_temperature": True,
            "supports_system_prompt": True,
            "max_output_tokens": 16384,
            "context_window": 128000,
            "supports_json_mode": True,
        },
    ),
    (
        "openai",
        "gpt-4o",
        "GPT-4o",
        {
            "supports_temperature": True,
            "supports_system_prompt": True,
            "max_output_tokens": 16384,
            "context_window": 128000,
            "supports_json_mode": True,
        },
    ),
    (
        "anthropic",
        "claude-3-5-haiku-latest",
        "Claude 3.5 Haiku",
        {
            "supports_temperature": True,
            "max_temperature": 1.0,
            "supports_system_prompt": True,
            "max_output_tokens": 8192,
            "context_window": 200000,
        },
    ),
    (
        "anthropic",
        "claude-sonnet-4-0",
        "Claude Sonnet 4",
        {
            "supports_temperature": True,
            "max_temperature": 1.0,
            "supports_system_prompt": True,
            "max_output_tokens": 64000,
            "context_window": 200000,
        },
    ),
    (
        "google",
        "gemini-2.0-flash",
        "Gemini 2.0 Flash",
        {
            "supports_temperature": True,
            "supports_system_prompt": True,
            "max_output_tokens": 8192,
            "context_window": 1048576,
            "supports_json_mode": True,
        },
    ),
    (
        "google",
        "gemini-2.5-pro",
        "Gemini 2.5 Pro",
        {
            "supports_temperature": True,
            "supports_system_prompt": True,
            "max_output_tokens": 65536,
            "context_window": 1048576,
            "supports_json_mode": True,
        },
    ),
)


async def ensure_catalog(session: AsyncSession) -> None:
    """Insert any missing default providers/models (idempotent; never updates existing rows)."""
    existing = {p.provider_key: p for p in (await session.scalars(select(AiProvider))).all()}
    for key, name in DEFAULT_PROVIDERS:
        if key not in existing:
            provider = AiProvider(provider_key=key, name=name, is_enabled=True)
            session.add(provider)
            existing[key] = provider
    await session.flush()
    known = {(m.provider_id, m.model_key) for m in (await session.scalars(select(AiModel))).all()}
    for provider_key, model_key, display, caps in DEFAULT_MODELS:
        provider = existing[provider_key]
        if (provider.id, model_key) not in known:
            session.add(
                AiModel(
                    provider_id=provider.id,
                    model_key=model_key,
                    display_name=display,
                    capabilities=caps,
                    pricing=default_pricing(model_key),
                    is_enabled=True,
                )
            )
    await session.flush()
