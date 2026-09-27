"""Perplexity adapter (OpenAI-compatible chat completions, REST via httpx).

Perplexity is a real AI SEARCH engine: every answer is produced from live
web retrieval and the response carries the retrieved sources. Those arrive
as `search_results` (objects with title/url) on current API versions, with
a legacy top-level `citations` (bare URL list) fallback — both are mapped
onto AIResponse.citations as genuine, grounded citations.
"""

from typing import Any

import httpx

from app.ai.base import AIProvider
from app.ai.providers._http import as_int, raise_for_error
from app.ai.types import AIRequest, AIResponse, FinishReason, ProviderCapabilities, ProviderCitation

_FINISH = {
    "stop": FinishReason.STOP,
    "length": FinishReason.LENGTH,
    "content_filter": FinishReason.CONTENT_FILTER,
}

_MAX_CITATIONS = 50


def _extract_citations(body: dict[str, Any]) -> list[ProviderCitation]:
    citations: list[ProviderCitation] = []
    seen: set[str] = set()
    results = body.get("search_results")
    if isinstance(results, list):
        for item in results[:_MAX_CITATIONS]:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            title = str(item.get("title") or "").strip() or None
            citations.append(ProviderCitation(url=url[:2048], title=title))
    legacy = body.get("citations")
    if isinstance(legacy, list):
        for raw in legacy[:_MAX_CITATIONS]:
            url = str(raw or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            citations.append(ProviderCitation(url=url[:2048]))
    return citations[:_MAX_CITATIONS]


class PerplexityProvider(AIProvider):
    key = "perplexity"
    capabilities = ProviderCapabilities(
        supports_system_prompt=True,
        supports_temperature=True,
        max_temperature=1.99,  # Perplexity rejects temperature >= 2
    )

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.perplexity.ai",
        client: httpx.AsyncClient | None = None,
        default_timeout_seconds: float = 60.0,
    ) -> None:
        super().__init__(default_timeout_seconds=default_timeout_seconds)
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None

    async def _generate(self, request: AIRequest, timeout_seconds: float) -> AIResponse:
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})
        payload: dict[str, Any] = {"model": request.model, "messages": messages}
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        res = await self._client.post(
            f"{self._base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=timeout_seconds,
        )
        raise_for_error(res, provider=self.key)
        body = res.json()
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("no choices in response")
        choice = choices[0]
        finish_raw = str(choice.get("finish_reason") or "")
        content = (choice.get("message") or {}).get("content")
        usage = body.get("usage") or {}
        citations = _extract_citations(body)
        return AIResponse(
            provider=self.key,
            model=str(body.get("model") or request.model),
            request_id=request.request_id,
            response_text=content if isinstance(content, str) else "",
            finish_reason=_FINISH.get(finish_raw, FinishReason.UNKNOWN),
            input_tokens=as_int(usage.get("prompt_tokens")),
            output_tokens=as_int(usage.get("completion_tokens")),
            total_tokens=as_int(usage.get("total_tokens")),
            provider_request_id=str(body.get("id")) if body.get("id") else None,
            raw_response={"finish_reason": finish_raw, "grounded": True},
            citations=citations,
        )
