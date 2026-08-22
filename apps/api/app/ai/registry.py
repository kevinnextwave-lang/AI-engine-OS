"""Builds adapters from settings. Adding a provider = one adapter class + one
registration line here; the search engine never changes."""

from collections.abc import Callable

import httpx

from app.ai.base import AIProvider
from app.ai.providers.anthropic import AnthropicProvider
from app.ai.providers.google import GoogleProvider
from app.ai.providers.openai import OpenAIProvider
from app.ai.types import AIError, AIErrorCategory, AIProviderError
from app.core.config import Settings, get_settings

Factory = Callable[[Settings, httpx.AsyncClient | None], AIProvider | None]


def _openai(s: Settings, client: httpx.AsyncClient | None) -> AIProvider | None:
    if not s.openai_api_key:
        return None
    return OpenAIProvider(
        s.openai_api_key.get_secret_value(),
        base_url=s.openai_base_url,
        client=client,
        default_timeout_seconds=s.ai_default_timeout_seconds,
    )


def _anthropic(s: Settings, client: httpx.AsyncClient | None) -> AIProvider | None:
    if not s.anthropic_api_key:
        return None
    return AnthropicProvider(
        s.anthropic_api_key.get_secret_value(),
        base_url=s.anthropic_base_url,
        api_version=s.anthropic_api_version,
        client=client,
        default_timeout_seconds=s.ai_default_timeout_seconds,
        default_max_tokens=s.ai_default_max_tokens,
    )


def _google(s: Settings, client: httpx.AsyncClient | None) -> AIProvider | None:
    if not s.google_ai_api_key:
        return None
    return GoogleProvider(
        s.google_ai_api_key.get_secret_value(),
        base_url=s.google_ai_base_url,
        client=client,
        default_timeout_seconds=s.ai_default_timeout_seconds,
    )


FACTORIES: dict[str, Factory] = {"openai": _openai, "anthropic": _anthropic, "google": _google}

DEFAULT_MODEL_SETTING = {
    "openai": "openai_default_model",
    "anthropic": "anthropic_default_model",
    "google": "google_default_model",
}


class ProviderRegistry:
    def __init__(
        self, settings: Settings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client
        self._providers: dict[str, AIProvider] = {}

    @property
    def known_keys(self) -> list[str]:
        return list(FACTORIES)

    def is_configured(self, key: str) -> bool:
        return self.get_optional(key) is not None

    def get_optional(self, key: str) -> AIProvider | None:
        if key in self._providers:
            return self._providers[key]
        factory = FACTORIES.get(key)
        if factory is None:
            return None
        provider = factory(self._settings, self._client)
        if provider is not None:
            self._providers[key] = provider
        return provider

    def get(self, key: str) -> AIProvider:
        if key not in FACTORIES:
            raise AIProviderError(
                AIError(
                    AIErrorCategory.INVALID_REQUEST,
                    f"Unknown AI provider '{key}'",
                    provider_code="unknown_provider",
                )
            )
        provider = self.get_optional(key)
        if provider is None:
            raise AIProviderError(
                AIError(
                    AIErrorCategory.AUTHENTICATION_ERROR,
                    f"AI provider '{key}' has no credentials configured",
                    provider_code="not_configured",
                )
            )
        return provider

    def default_model(self, key: str) -> str | None:
        setting = DEFAULT_MODEL_SETTING.get(key)
        return getattr(self._settings, setting) if setting else None

    def register(self, key: str, provider: AIProvider) -> None:
        """Inject a provider instance (tests, future plug-ins)."""
        FACTORIES.setdefault(key, lambda _s, _c: None)
        self._providers[key] = provider
