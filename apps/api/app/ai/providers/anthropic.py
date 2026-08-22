"""Anthropic Messages adapter (REST via httpx; no SDK)."""

from typing import Any

import httpx

from app.ai.base import AIProvider
from app.ai.providers._http import as_int, raise_for_error
from app.ai.types import (
    AIError,
    AIErrorCategory,
    AIProviderError,
    AIRequest,
    AIResponse,
    FinishReason,
    ProviderCapabilities,
)

_FINISH = {
    "end_turn": FinishReason.STOP,
    "stop_sequence": FinishReason.STOP,
    "max_tokens": FinishReason.LENGTH,
    "tool_use": FinishReason.TOOL_USE,
    "refusal": FinishReason.CONTENT_FILTER,
}


class AnthropicProvider(AIProvider):
    key = "anthropic"
    # Anthropic temperature range is 0..1 and max_tokens is mandatory.
    capabilities = ProviderCapabilities(
        supports_system_prompt=True, supports_temperature=True, max_temperature=1.0
    )

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.anthropic.com",
        api_version: str = "2023-06-01",
        client: httpx.AsyncClient | None = None,
        default_timeout_seconds: float = 60.0,
        default_max_tokens: int = 1024,
    ) -> None:
        super().__init__(default_timeout_seconds=default_timeout_seconds)
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._version = api_version
        self._client = client or httpx.AsyncClient()
        self._default_max_tokens = default_max_tokens

    async def _generate(self, request: AIRequest, timeout_seconds: float) -> AIResponse:
        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens or self._default_max_tokens,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.system_prompt:
            payload["system"] = request.system_prompt
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        res = await self._client.post(
            f"{self._base_url}/v1/messages",
            json=payload,
            headers={"x-api-key": self._api_key, "anthropic-version": self._version},
            timeout=timeout_seconds,
        )
        raise_for_error(res, provider=self.key)
        body = res.json()
        blocks = body["content"]
        if not isinstance(blocks, list):
            raise ValueError("content is not a list")
        text = "".join(
            b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"
        )
        stop_raw = str(body.get("stop_reason") or "")
        finish = _FINISH.get(stop_raw, FinishReason.UNKNOWN)
        if finish == FinishReason.CONTENT_FILTER and not text:
            raise AIProviderError(
                AIError(
                    AIErrorCategory.CONTENT_FILTER,
                    "Response refused by the provider",
                    res.status_code,
                    stop_raw,
                )
            )
        usage = body.get("usage") or {}
        return AIResponse(
            provider=self.key,
            model=str(body.get("model") or request.model),
            request_id=request.request_id,
            response_text=text,
            finish_reason=finish,
            input_tokens=as_int(usage.get("input_tokens")),
            output_tokens=as_int(usage.get("output_tokens")),
            provider_request_id=res.headers.get("request-id")
            or (str(body.get("id")) if body.get("id") else None),
            raw_response={"stop_reason": stop_raw, "stop_sequence": body.get("stop_sequence")},
        )
