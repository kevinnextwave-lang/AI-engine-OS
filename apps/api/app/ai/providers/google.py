"""Google Gemini generateContent adapter (REST via httpx; no SDK)."""

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
    "STOP": FinishReason.STOP,
    "MAX_TOKENS": FinishReason.LENGTH,
    "SAFETY": FinishReason.CONTENT_FILTER,
    "RECITATION": FinishReason.CONTENT_FILTER,
    "BLOCKLIST": FinishReason.CONTENT_FILTER,
    "PROHIBITED_CONTENT": FinishReason.CONTENT_FILTER,
    "SPII": FinishReason.CONTENT_FILTER,
}


class GoogleProvider(AIProvider):
    key = "google"
    capabilities = ProviderCapabilities(
        supports_system_prompt=True,
        supports_temperature=True,
        max_temperature=2.0,
        supports_json_mode=True,
    )

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        client: httpx.AsyncClient | None = None,
        default_timeout_seconds: float = 60.0,
    ) -> None:
        super().__init__(default_timeout_seconds=default_timeout_seconds)
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient()

    async def _generate(self, request: AIRequest, timeout_seconds: float) -> AIResponse:
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": request.prompt}]}],
        }
        if request.system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": request.system_prompt}]}
        config: dict[str, Any] = {}
        if request.temperature is not None:
            config["temperature"] = request.temperature
        if request.max_tokens is not None:
            config["maxOutputTokens"] = request.max_tokens
        if config:
            payload["generationConfig"] = config
        # The key travels in a header, not the query string, so it never lands in URL logs.
        res = await self._client.post(
            f"{self._base_url}/models/{request.model}:generateContent",
            json=payload,
            headers={"x-goog-api-key": self._api_key},
            timeout=timeout_seconds,
        )
        raise_for_error(res, provider=self.key)
        body = res.json()
        feedback = body.get("promptFeedback") or {}
        if feedback.get("blockReason"):
            raise AIProviderError(
                AIError(
                    AIErrorCategory.CONTENT_FILTER,
                    f"Prompt blocked: {feedback['blockReason']}",
                    res.status_code,
                    str(feedback["blockReason"]),
                )
            )
        candidates = body.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ValueError("no candidates in response")
        candidate = candidates[0]
        finish_raw = str(candidate.get("finishReason") or "")
        finish = _FINISH.get(finish_raw, FinishReason.UNKNOWN)
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        if finish == FinishReason.CONTENT_FILTER and not text:
            raise AIProviderError(
                AIError(
                    AIErrorCategory.CONTENT_FILTER,
                    "Response blocked by safety settings",
                    res.status_code,
                    finish_raw,
                )
            )
        usage = body.get("usageMetadata") or {}
        return AIResponse(
            provider=self.key,
            model=str(body.get("modelVersion") or request.model),
            request_id=request.request_id,
            response_text=text,
            finish_reason=finish,
            input_tokens=as_int(usage.get("promptTokenCount")),
            output_tokens=as_int(usage.get("candidatesTokenCount")),
            total_tokens=as_int(usage.get("totalTokenCount")),
            provider_request_id=res.headers.get("x-request-id")
            or (str(body.get("responseId")) if body.get("responseId") else None),
            raw_response={"finish_reason": finish_raw, "model_version": body.get("modelVersion")},
        )
