"""Provider interface + the shared generate() pipeline.

Adapters implement `_generate` and `_normalize_error`. `generate` applies
capability normalization, timing, timeout handling, error normalization and
observability so every adapter behaves identically from the outside.
"""

import asyncio
import time
from abc import ABC, abstractmethod

import httpx

from app.ai.types import (
    AIError,
    AIErrorCategory,
    AIProviderError,
    AIRequest,
    AIResponse,
    FinishReason,
    ProviderCapabilities,
)
from app.core.logging import get_logger

log = get_logger("ai.provider")


class AIProvider(ABC):
    """Common interface. `key` is the stable provider identifier ("openai", ...)."""

    key: str
    capabilities: ProviderCapabilities = ProviderCapabilities()

    def __init__(self, *, default_timeout_seconds: float = 60.0) -> None:
        self._default_timeout = default_timeout_seconds

    @abstractmethod
    async def _generate(self, request: AIRequest, timeout_seconds: float) -> AIResponse:
        """Perform the provider call. May raise AIProviderError, httpx errors or
        ValueError/KeyError for malformed payloads; `generate` normalizes them."""

    def normalize_request(self, request: AIRequest) -> AIRequest:
        """Drop or clamp parameters the provider does not support."""
        caps = self.capabilities
        temperature = request.temperature
        if temperature is not None:
            if not caps.supports_temperature:
                temperature = None
            else:
                temperature = max(caps.min_temperature, min(caps.max_temperature, temperature))
        max_tokens = request.max_tokens
        if max_tokens is not None and caps.max_output_tokens is not None:
            max_tokens = min(max_tokens, caps.max_output_tokens)
        system_prompt = request.system_prompt if caps.supports_system_prompt else None
        prompt = request.prompt
        if request.system_prompt and not caps.supports_system_prompt:
            # Fold instructions into the prompt so intent is preserved.
            prompt = f"{request.system_prompt}\n\n{request.prompt}"
        return AIRequest(
            model=request.model,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=request.timeout_seconds,
            metadata=request.metadata,
            request_id=request.request_id,
        )

    async def generate(self, request: AIRequest) -> AIResponse:
        normalized = self.normalize_request(request)
        timeout = normalized.timeout_seconds or self._default_timeout
        started = time.perf_counter()
        try:
            response = await asyncio.wait_for(
                self._generate(normalized, timeout), timeout=timeout + 1
            )
        except AIProviderError as exc:
            response = self._failed(normalized, exc.error)
        except (TimeoutError, httpx.TimeoutException):
            response = self._failed(
                normalized,
                AIError(AIErrorCategory.TIMEOUT, f"Provider did not respond within {timeout:.0f}s"),
            )
        except httpx.HTTPError as exc:
            response = self._failed(
                normalized,
                AIError(AIErrorCategory.PROVIDER_ERROR, f"Transport error: {type(exc).__name__}"),
            )
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            response = self._failed(
                normalized,
                AIError(
                    AIErrorCategory.PROVIDER_ERROR,
                    f"Malformed provider response: {type(exc).__name__}: {exc}"[:300],
                ),
            )
        except Exception as exc:  # noqa: BLE001 - never leak provider exceptions upward
            response = self._failed(
                normalized,
                AIError(AIErrorCategory.UNKNOWN_ERROR, f"{type(exc).__name__}: {exc}"[:300]),
            )
        response.latency_ms = int((time.perf_counter() - started) * 1000)
        if response.total_tokens is None and (
            response.input_tokens is not None or response.output_tokens is not None
        ):
            response.total_tokens = (response.input_tokens or 0) + (response.output_tokens or 0)
        log.info(
            "ai_generation",
            provider=self.key,
            model=normalized.model,
            request_id=str(normalized.request_id),
            success=response.succeeded,
            latency_ms=response.latency_ms,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            total_tokens=response.total_tokens,
            finish_reason=response.finish_reason.value,
            error_category=response.error.category.value if response.error else None,
            status_code=response.error.status_code if response.error else None,
        )
        return response

    def _failed(self, request: AIRequest, error: AIError) -> AIResponse:
        return AIResponse(
            provider=self.key,
            model=request.model,
            request_id=request.request_id,
            finish_reason=FinishReason.ERROR,
            error=error,
        )


def category_for_status(status: int) -> AIErrorCategory:
    if status in (401, 403):
        return AIErrorCategory.AUTHENTICATION_ERROR
    if status == 429:
        return AIErrorCategory.RATE_LIMIT
    if status in (408, 504):
        return AIErrorCategory.TIMEOUT
    if 400 <= status < 500:
        return AIErrorCategory.INVALID_REQUEST
    if status >= 500:
        return AIErrorCategory.PROVIDER_ERROR
    return AIErrorCategory.UNKNOWN_ERROR
