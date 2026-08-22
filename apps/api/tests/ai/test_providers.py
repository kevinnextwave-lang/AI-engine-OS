"""Adapter tests against httpx.MockTransport — no network, no real API calls."""

import asyncio
import json
from typing import Any

import httpx
import pytest

from app.ai.providers.anthropic import AnthropicProvider
from app.ai.providers.google import GoogleProvider
from app.ai.providers.openai import OpenAIProvider
from app.ai.types import AIErrorCategory, AIRequest, FinishReason, ProviderCapabilities


def transport(handler):  # type: ignore[no-untyped-def]
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def json_response(status: int, body: Any, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers or {})


OPENAI_OK = {
    "id": "chatcmpl-1",
    "model": "gpt-4o-mini-2024",
    "choices": [
        {"message": {"role": "assistant", "content": "Hello from OpenAI"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16},
}
ANTHROPIC_OK = {
    "id": "msg_1",
    "model": "claude-3-5-haiku-latest",
    "content": [{"type": "text", "text": "Hello from "}, {"type": "text", "text": "Anthropic"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 9, "output_tokens": 4},
}
GOOGLE_OK = {
    "responseId": "resp-1",
    "modelVersion": "gemini-2.0-flash-001",
    "candidates": [{"content": {"parts": [{"text": "Hello from Google"}]}, "finishReason": "STOP"}],
    "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3, "totalTokenCount": 10},
}


def make(provider: str, handler):  # type: ignore[no-untyped-def]
    client = transport(handler)
    if provider == "openai":
        return OpenAIProvider("sk-test", client=client, default_timeout_seconds=2)
    if provider == "anthropic":
        return AnthropicProvider("sk-ant-test", client=client, default_timeout_seconds=2)
    return GoogleProvider("g-test", client=client, default_timeout_seconds=2)


PROVIDERS = ["openai", "anthropic", "google"]
OK_BODIES = {"openai": OPENAI_OK, "anthropic": ANTHROPIC_OK, "google": GOOGLE_OK}


# --- success + token normalization ------------------------------------------------------


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_successful_response_is_normalized(provider: str) -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["headers"] = dict(req.headers)
        seen["body"] = json.loads(req.content)
        return json_response(
            200, OK_BODIES[provider], {"x-request-id": "prov-req-1", "request-id": "prov-req-1"}
        )

    p = make(provider, handler)
    res = await p.generate(
        AIRequest(model="m", prompt="Hi", system_prompt="Be brief", temperature=0.3, max_tokens=50)
    )
    assert res.succeeded and res.error is None
    assert res.provider == provider
    assert res.response_text.startswith("Hello from")
    assert res.finish_reason == FinishReason.STOP
    assert res.latency_ms >= 0 and res.provider_request_id == "prov-req-1"
    # token normalization
    expected = {"openai": (11, 5, 16), "anthropic": (9, 4, 13), "google": (7, 3, 10)}[provider]
    assert (res.input_tokens, res.output_tokens, res.total_tokens) == expected
    # the key never appears in the URL; raw payload is not exposed
    assert "test" not in seen["url"]
    assert set(res.raw_response) <= {
        "finish_reason",
        "stop_reason",
        "stop_sequence",
        "system_fingerprint",
        "model_version",
    }
    # parameter mapping per provider
    body = seen["body"]
    if provider == "openai":
        assert body["messages"][0] == {"role": "system", "content": "Be brief"}
        assert body["max_completion_tokens"] == 50 and body["temperature"] == 0.3
        assert seen["headers"]["authorization"] == "Bearer sk-test"
    elif provider == "anthropic":
        assert body["system"] == "Be brief" and body["max_tokens"] == 50
        assert (
            seen["headers"]["x-api-key"] == "sk-ant-test" and "anthropic-version" in seen["headers"]
        )
    else:
        assert body["systemInstruction"]["parts"][0]["text"] == "Be brief"
        assert body["generationConfig"] == {"temperature": 0.3, "maxOutputTokens": 50}
        assert seen["headers"]["x-goog-api-key"] == "g-test"


def test_capability_normalization_clamps_temperature_and_drops_unsupported() -> None:
    p = AnthropicProvider("k", client=transport(lambda r: json_response(200, ANTHROPIC_OK)))
    norm = p.normalize_request(AIRequest(model="m", prompt="x", temperature=1.7))
    assert norm.temperature == 1.0  # Anthropic max is 1.0

    class NoSystem(OpenAIProvider):
        capabilities = ProviderCapabilities(
            supports_system_prompt=False, supports_temperature=False
        )

    q = NoSystem("k", client=transport(lambda r: json_response(200, OPENAI_OK)))
    norm = q.normalize_request(
        AIRequest(model="m", prompt="ask", system_prompt="rules", temperature=0.5)
    )
    assert norm.temperature is None and norm.system_prompt is None
    assert norm.prompt == "rules\n\nask"  # instructions folded into the prompt


async def test_anthropic_max_tokens_defaults_when_missing() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        return json_response(200, ANTHROPIC_OK)

    p = AnthropicProvider("k", client=transport(handler), default_max_tokens=321)
    await p.generate(AIRequest(model="m", prompt="x"))
    assert seen["body"]["max_tokens"] == 321


# --- error normalization --------------------------------------------------------------


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_timeout_is_normalized(provider: str) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=req)

    res = await make(provider, handler).generate(AIRequest(model="m", prompt="x"))
    assert not res.succeeded
    assert res.error is not None and res.error.category == AIErrorCategory.TIMEOUT
    assert res.error.retryable and res.finish_reason == FinishReason.ERROR


async def test_hung_provider_hits_wall_clock_timeout() -> None:
    async def slow(req: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return json_response(200, OPENAI_OK)

    p = OpenAIProvider("k", client=transport(slow), default_timeout_seconds=0.05)
    res = await p.generate(AIRequest(model="m", prompt="x"))
    assert res.error is not None and res.error.category == AIErrorCategory.TIMEOUT


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_rate_limit_is_normalized(provider: str) -> None:
    res = await make(
        provider,
        lambda r: json_response(
            429, {"error": {"message": "Too many requests", "type": "rate_limit_error"}}
        ),
    ).generate(AIRequest(model="m", prompt="x"))
    assert res.error is not None
    assert res.error.category == AIErrorCategory.RATE_LIMIT and res.error.status_code == 429
    assert res.error.message == "Too many requests" and res.error.retryable


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_authentication_failure_is_normalized(provider: str) -> None:
    res = await make(
        provider,
        lambda r: json_response(
            401, {"error": {"message": "Invalid API key", "code": "invalid_api_key"}}
        ),
    ).generate(AIRequest(model="m", prompt="x"))
    assert res.error is not None
    assert res.error.category == AIErrorCategory.AUTHENTICATION_ERROR
    assert res.error.provider_code == "invalid_api_key" and not res.error.retryable


@pytest.mark.parametrize(
    ("provider", "body"),
    [
        ("openai", {"id": "x"}),  # no choices
        ("openai", {"choices": []}),
        ("anthropic", {"content": "not-a-list"}),
        ("google", {"candidates": "nope"}),
        ("google", {}),
    ],
)
async def test_malformed_provider_response(provider: str, body: Any) -> None:
    res = await make(provider, lambda r: json_response(200, body)).generate(
        AIRequest(model="m", prompt="x")
    )
    assert res.error is not None and res.error.category == AIErrorCategory.PROVIDER_ERROR
    assert "Malformed provider response" in res.error.message


async def test_invalid_json_body_is_malformed() -> None:
    res = await make(
        "openai", lambda r: httpx.Response(200, content=b"<html>oops</html>")
    ).generate(AIRequest(model="m", prompt="x"))
    assert res.error is not None and res.error.category == AIErrorCategory.PROVIDER_ERROR


async def test_server_error_and_bad_request() -> None:
    res = await make("google", lambda r: httpx.Response(503, content=b"unavailable")).generate(
        AIRequest(model="m", prompt="x")
    )
    assert res.error is not None and res.error.category == AIErrorCategory.PROVIDER_ERROR
    res = await make(
        "openai", lambda r: json_response(400, {"error": {"message": "bad model"}})
    ).generate(AIRequest(model="m", prompt="x"))
    assert res.error is not None and res.error.category == AIErrorCategory.INVALID_REQUEST


async def test_content_filter_is_normalized_per_provider() -> None:
    openai_blocked = {
        **OPENAI_OK,
        "choices": [{"message": {"content": None}, "finish_reason": "content_filter"}],
    }
    res = await make("openai", lambda r: json_response(200, openai_blocked)).generate(
        AIRequest(model="m", prompt="x")
    )
    assert res.error is not None and res.error.category == AIErrorCategory.CONTENT_FILTER

    google_blocked = {"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []}
    res = await make("google", lambda r: json_response(200, google_blocked)).generate(
        AIRequest(model="m", prompt="x")
    )
    assert res.error is not None and res.error.category == AIErrorCategory.CONTENT_FILTER

    google_truncated = {
        **GOOGLE_OK,
        "candidates": [{"content": {"parts": [{"text": "partial"}]}, "finishReason": "SAFETY"}],
    }
    res = await make("google", lambda r: json_response(200, google_truncated)).generate(
        AIRequest(model="m", prompt="x")
    )
    assert (
        res.succeeded
        and res.finish_reason == FinishReason.CONTENT_FILTER
        and res.response_text == "partial"
    )


async def test_length_finish_reason() -> None:
    body = {**ANTHROPIC_OK, "stop_reason": "max_tokens"}
    res = await make("anthropic", lambda r: json_response(200, body)).generate(
        AIRequest(model="m", prompt="x")
    )
    assert res.succeeded and res.finish_reason == FinishReason.LENGTH
