"""OpenAI Chat Completions adapter (REST via httpx; no SDK)."""

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
    ProviderCitation,
)

_FINISH = {
    "stop": FinishReason.STOP,
    "length": FinishReason.LENGTH,
    "content_filter": FinishReason.CONTENT_FILTER,
    "tool_calls": FinishReason.TOOL_USE,
    "function_call": FinishReason.TOOL_USE,
}


class OpenAIProvider(AIProvider):
    key = "openai"
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
        base_url: str = "https://api.openai.com/v1",
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
        # The web-search models perform live retrieval and reject sampling
        # parameters — sending temperature is a guaranteed 400.
        grounded_model = "search-preview" in request.model
        if request.temperature is not None and not grounded_model:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_completion_tokens"] = request.max_tokens
        res = await self._client.post(
            f"{self._base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=timeout_seconds,
        )
        raise_for_error(res, provider=self.key)
        body = res.json()
        choices = body["choices"]
        if not isinstance(choices, list) or not choices:
            raise ValueError("no choices in response")
        choice = choices[0]
        finish_raw = str(choice.get("finish_reason") or "")
        finish = _FINISH.get(finish_raw, FinishReason.UNKNOWN)
        content = (choice.get("message") or {}).get("content")
        if finish == FinishReason.CONTENT_FILTER and not content:
            raise AIProviderError(
                AIError(
                    AIErrorCategory.CONTENT_FILTER,
                    "Response blocked by the provider's content filter",
                    res.status_code,
                    finish_raw,
                )
            )
        usage = body.get("usage") or {}
        # Web-search models attach url_citation annotations: the sources the
        # model's live retrieval actually consulted — genuine citations.
        citations: list[ProviderCitation] = []
        annotations = (choice.get("message") or {}).get("annotations")
        if isinstance(annotations, list):
            seen: set[str] = set()
            for ann in annotations[:50]:
                if not isinstance(ann, dict) or ann.get("type") != "url_citation":
                    continue
                cite = ann.get("url_citation") or {}
                url = str(cite.get("url") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                title = str(cite.get("title") or "").strip() or None
                citations.append(ProviderCitation(url=url[:2048], title=title))
        return AIResponse(
            provider=self.key,
            model=str(body.get("model") or request.model),
            request_id=request.request_id,
            response_text=content if isinstance(content, str) else "",
            finish_reason=finish,
            input_tokens=as_int(usage.get("prompt_tokens")),
            output_tokens=as_int(usage.get("completion_tokens")),
            total_tokens=as_int(usage.get("total_tokens")),
            provider_request_id=res.headers.get("x-request-id")
            or (str(body.get("id")) if body.get("id") else None),
            raw_response={
                "finish_reason": finish_raw,
                "system_fingerprint": body.get("system_fingerprint"),
                "grounded": grounded_model,
            },
            citations=citations,
        )
