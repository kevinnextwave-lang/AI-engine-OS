"""Registry (configuration) and the DB-backed generation service."""

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.openai import OpenAIProvider
from app.ai.registry import ProviderRegistry
from app.ai.types import AIErrorCategory, AIProviderError, AIRequest
from app.core.config import Settings
from app.models.ai import AiGeneration, AiModel, AiProvider
from app.services.ai import AIGenerationService
from tests.ai.test_providers import OPENAI_OK, json_response, transport


def settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


# --- registry ---------------------------------------------------------------------------


def test_unknown_provider_raises_normalized_error() -> None:
    reg = ProviderRegistry(settings())
    with pytest.raises(AIProviderError) as exc:
        reg.get("mistral")
    assert exc.value.error.category == AIErrorCategory.INVALID_REQUEST
    assert exc.value.error.provider_code == "unknown_provider"


def test_provider_without_credentials_is_not_configured() -> None:
    reg = ProviderRegistry(settings())
    assert reg.known_keys == ["openai", "anthropic", "google"]
    assert not reg.is_configured("openai")
    with pytest.raises(AIProviderError) as exc:
        reg.get("openai")
    assert exc.value.error.category == AIErrorCategory.AUTHENTICATION_ERROR
    assert exc.value.error.provider_code == "not_configured"


def test_configured_providers_are_built_from_settings_and_cached() -> None:
    reg = ProviderRegistry(settings(openai_api_key="sk-x", google_ai_api_key="g-x"))
    assert reg.is_configured("openai") and reg.is_configured("google")
    assert not reg.is_configured("anthropic")
    assert reg.get("openai") is reg.get("openai")
    assert reg.default_model("openai") == "gpt-4o-mini"
    # secrets are not printable
    assert "sk-x" not in repr(settings(openai_api_key="sk-x"))


# --- service (real catalogue rows from the migration seed) --------------------------------


def registry_with_mock(handler) -> ProviderRegistry:  # type: ignore[no-untyped-def]
    reg = ProviderRegistry(settings())
    reg.register(
        "openai", OpenAIProvider("sk-test", client=transport(handler), default_timeout_seconds=2)
    )
    return reg


async def test_service_generates_and_records(db_session: AsyncSession) -> None:
    reg = registry_with_mock(lambda r: json_response(200, OPENAI_OK, {"x-request-id": "rq"}))
    service = AIGenerationService(db_session, reg, settings())
    req = AIRequest(
        model="gpt-4o-mini",
        prompt="Say hi",
        system_prompt="Brief",
        temperature=1.5,
        metadata={"k": "v"},
    )
    res = await service.generate("openai", req, purpose="test")
    assert res.succeeded and res.response_text == "Hello from OpenAI"
    row = (
        await db_session.scalars(
            select(AiGeneration).where(AiGeneration.request_id == req.request_id)
        )
    ).one()
    assert row.succeeded and row.provider_key == "openai" and row.model_key == "gpt-4o-mini-2024"
    assert (row.input_tokens, row.output_tokens, row.total_tokens) == (11, 5, 16)
    assert row.response_text == "Hello from OpenAI" and row.prompt_text == "Say hi"
    assert row.metadata_["k"] == "v" and row.provider_request_id == "rq"
    assert row.provider_id is not None and row.model_id is not None


async def test_service_uses_default_model_and_can_skip_text(db_session: AsyncSession) -> None:
    reg = registry_with_mock(lambda r: json_response(200, OPENAI_OK))
    service = AIGenerationService(db_session, reg, settings(ai_store_response_text=False))
    req = AIRequest(model="", prompt="secret customer text")
    res = await service.generate("openai", req)
    assert res.succeeded
    row = (
        await db_session.scalars(
            select(AiGeneration).where(AiGeneration.request_id == req.request_id)
        )
    ).one()
    assert row.response_text is None and row.prompt_text is None
    assert row.model_key == "gpt-4o-mini-2024"  # resolved from settings default, echoed by provider


async def test_model_capabilities_cap_tokens_and_temperature(db_session: AsyncSession) -> None:
    seen: dict[str, object] = {}

    def handler(r: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(r.content))
        return json_response(200, OPENAI_OK)

    provider = (
        await db_session.scalars(select(AiProvider).where(AiProvider.provider_key == "openai"))
    ).one()
    model = (
        await db_session.scalars(
            select(AiModel).where(
                AiModel.provider_id == provider.id, AiModel.model_key == "gpt-4o-mini"
            )
        )
    ).one()
    model.capabilities = {**model.capabilities, "max_output_tokens": 100, "max_temperature": 0.5}
    await db_session.flush()
    service = AIGenerationService(db_session, registry_with_mock(handler), settings())
    await service.generate(
        "openai", AIRequest(model="gpt-4o-mini", prompt="x", max_tokens=5000, temperature=1.9)
    )
    assert seen["max_completion_tokens"] == 100 and seen["temperature"] == 0.5


async def test_provider_disabled_is_rejected_and_recorded(db_session: AsyncSession) -> None:
    provider = (
        await db_session.scalars(select(AiProvider).where(AiProvider.provider_key == "openai"))
    ).one()
    provider.is_enabled = False
    await db_session.flush()
    calls: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        calls.append(r)
        return json_response(200, OPENAI_OK)

    service = AIGenerationService(db_session, registry_with_mock(handler), settings())
    req = AIRequest(model="gpt-4o-mini", prompt="x")
    res = await service.generate("openai", req)
    assert not res.succeeded and res.error is not None
    assert res.error.provider_code == "provider_disabled" and calls == []
    row = (
        await db_session.scalars(
            select(AiGeneration).where(AiGeneration.request_id == req.request_id)
        )
    ).one()
    assert row.error_category == "invalid_request" and not row.succeeded


async def test_unknown_provider_and_model_via_service(db_session: AsyncSession) -> None:
    service = AIGenerationService(
        db_session, registry_with_mock(lambda r: json_response(200, OPENAI_OK)), settings()
    )
    res = await service.generate("nope", AIRequest(model="m", prompt="x"))
    assert res.error is not None and res.error.provider_code == "unknown_provider"
    res = await service.generate("openai", AIRequest(model="gpt-99", prompt="x"))
    assert res.error is not None and res.error.provider_code == "unknown_model"
    model = (await db_session.scalars(select(AiModel).where(AiModel.model_key == "gpt-4o"))).one()
    model.is_enabled = False
    await db_session.flush()
    res = await service.generate("openai", AIRequest(model="gpt-4o", prompt="x"))
    assert res.error is not None and res.error.provider_code == "model_disabled"


async def test_missing_credentials_via_service(db_session: AsyncSession) -> None:
    service = AIGenerationService(db_session, ProviderRegistry(settings()), settings())
    req = AIRequest(model="claude-3-5-haiku-latest", prompt="x")
    res = await service.generate("anthropic", req)
    assert res.error is not None and res.error.category == AIErrorCategory.AUTHENTICATION_ERROR
    assert res.error.provider_code == "not_configured"
    assert (
        await db_session.scalars(
            select(AiGeneration).where(AiGeneration.request_id == req.request_id)
        )
    ).one().error_category == "authentication_error"


async def test_request_ids_are_unique_per_generation(db_session: AsyncSession) -> None:
    service = AIGenerationService(
        db_session, registry_with_mock(lambda r: json_response(200, OPENAI_OK)), settings()
    )
    a = await service.generate("openai", AIRequest(model="gpt-4o-mini", prompt="x"))
    b = await service.generate("openai", AIRequest(model="gpt-4o-mini", prompt="x"))
    assert a.request_id != b.request_id and isinstance(a.request_id, uuid.UUID)
