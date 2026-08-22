"""Provider-independent generation service.

Resolves provider + model from the catalogue (both must be enabled), applies
model-level capability overrides, calls the adapter through the common
interface, and records the call in `ai_generations`. Nothing here knows
which vendor is behind a provider key.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.registry import ProviderRegistry
from app.ai.types import AIError, AIErrorCategory, AIProviderError, AIRequest, AIResponse
from app.core.config import Settings, get_settings
from app.models.ai import AiGeneration, AiModel, AiProvider
from app.repositories.ai import AiCatalogRepository


@dataclass
class ResolvedTarget:
    provider: AiProvider
    model: AiModel


class AIGenerationService:
    def __init__(
        self,
        session: AsyncSession,
        registry: ProviderRegistry,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._registry = registry
        self._catalog = AiCatalogRepository(session)
        self._settings = settings or get_settings()

    async def resolve(self, provider_key: str, model_key: str | None) -> ResolvedTarget:
        provider = await self._catalog.provider_by_key(provider_key)
        if provider is None:
            raise AIProviderError(
                AIError(
                    AIErrorCategory.INVALID_REQUEST,
                    f"Unknown AI provider '{provider_key}'",
                    provider_code="unknown_provider",
                )
            )
        if not provider.is_enabled:
            raise AIProviderError(
                AIError(
                    AIErrorCategory.INVALID_REQUEST,
                    f"AI provider '{provider_key}' is disabled",
                    provider_code="provider_disabled",
                )
            )
        key = model_key or self._registry.default_model(provider_key)
        if not key:
            raise AIProviderError(
                AIError(
                    AIErrorCategory.INVALID_REQUEST,
                    f"No model specified for '{provider_key}'",
                    provider_code="model_required",
                )
            )
        model = await self._catalog.model_by_key(provider.id, key)
        if model is None:
            raise AIProviderError(
                AIError(
                    AIErrorCategory.INVALID_REQUEST,
                    f"Unknown model '{key}' for provider '{provider_key}'",
                    provider_code="unknown_model",
                )
            )
        if not model.is_enabled:
            raise AIProviderError(
                AIError(
                    AIErrorCategory.INVALID_REQUEST,
                    f"Model '{key}' is disabled",
                    provider_code="model_disabled",
                )
            )
        return ResolvedTarget(provider=provider, model=model)

    @staticmethod
    def _apply_model_capabilities(request: AIRequest, model: AiModel) -> AIRequest:
        caps: dict[str, Any] = model.capabilities or {}
        temperature = request.temperature
        if temperature is not None:
            if caps.get("supports_temperature") is False:
                temperature = None
            else:
                hi = caps.get("max_temperature")
                if isinstance(hi, int | float):
                    temperature = min(float(hi), temperature)
        max_tokens = request.max_tokens
        cap_tokens = caps.get("max_output_tokens")
        if isinstance(cap_tokens, int):
            max_tokens = min(max_tokens, cap_tokens) if max_tokens is not None else None
        request.temperature = temperature
        request.max_tokens = max_tokens
        return request

    async def generate(
        self,
        provider_key: str,
        request: AIRequest,
        *,
        project_id: uuid.UUID | None = None,
        purpose: str = "generic",
        store_text: bool | None = None,
    ) -> AIResponse:
        """Generate through the named provider and persist the call. Resolution
        failures (unknown/disabled provider or model, missing credentials) are
        returned as failed AIResponses too, so callers handle one shape."""
        try:
            target = await self.resolve(provider_key, request.model)
            request.model = target.model.model_key
            adapter = self._registry.get(provider_key)
        except AIProviderError as exc:
            response = AIResponse(
                provider=provider_key,
                model=request.model or "",
                request_id=request.request_id,
                error=exc.error,
            )
            await self._record(response, request, None, project_id, purpose, store_text)
            return response
        request = self._apply_model_capabilities(request, target.model)
        response = await adapter.generate(request)
        await self._record(response, request, target, project_id, purpose, store_text)
        return response

    async def _record(
        self,
        response: AIResponse,
        request: AIRequest,
        target: ResolvedTarget | None,
        project_id: uuid.UUID | None,
        purpose: str,
        store_text: bool | None,
    ) -> None:
        keep_text = self._settings.ai_store_response_text if store_text is None else store_text
        row = AiGeneration(
            request_id=request.request_id,
            project_id=project_id,
            provider_id=target.provider.id if target else None,
            model_id=target.model.id if target else None,
            provider_key=response.provider,
            model_key=response.model,
            purpose=purpose,
            succeeded=response.succeeded,
            finish_reason=response.finish_reason.value,
            error_category=response.error.category.value if response.error else None,
            error_message=response.error.message[:500] if response.error else None,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            total_tokens=response.total_tokens,
            latency_ms=response.latency_ms,
            provider_request_id=response.provider_request_id,
            prompt_text=request.prompt if keep_text else None,
            system_prompt_text=request.system_prompt if keep_text else None,
            response_text=response.response_text if keep_text and response.succeeded else None,
            metadata_={**request.metadata, "raw_response": response.raw_response},
        )
        await self._catalog.add_generation(row)
        await self._session.commit()
