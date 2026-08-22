"""Parsing persisted through the execution engine; reprocessing; API; tenancy."""

import uuid

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.execution import execute_prompt_run
from app.ai.providers.openai import OpenAIProvider
from app.ai.registry import ProviderRegistry
from app.ai.throttle import InMemoryProviderThrottle
from app.api.v1.routes.execution import get_provider_registry, get_run_dispatcher
from app.core.security import create_access_token
from app.intelligence import PARSER_VERSION
from app.models import MembershipRole
from app.models.intelligence import BrandMention, CompetitorMention, ResponseCitation, ResponseClaim
from app.models.prompts import AiResponse, PromptRun
from app.services.intelligence import ResponseIntelligenceService
from tests.ai.test_providers import OPENAI_OK, json_response, transport
from tests.conftest import auth_header
from tests.execution.test_execution import Recorder, settings
from tests.intelligence import fixtures as fx
from tests.test_authz import add_member, org_id_for, signup
from tests.test_projects_api import create_project


def registry_answering(text: str) -> ProviderRegistry:
    body = {**OPENAI_OK, "choices": [{"message": {"content": text}, "finish_reason": "stop"}]}
    reg = ProviderRegistry(settings())
    reg.register(
        "openai",
        OpenAIProvider(
            "k", client=transport(lambda r: json_response(200, body)), default_timeout_seconds=2
        ),
    )
    return reg


async def _setup(
    client: AsyncClient, answer: str
) -> tuple[dict[str, str], str, str, str, ProviderRegistry]:
    owner = await signup(client, org="Intel Org")
    h = auth_header(owner["access_token"])
    org = await org_id_for(client, owner["access_token"])
    pid = (
        await create_project(client, h, name="Ledgerly", website_url="https://www.ledgerly.example")
    )["id"]
    for name, url in (
        ("QuickBooks", "https://quickbooks.intuit.com"),
        ("Xero", "https://www.xero.com"),
    ):
        await client.post(
            f"/api/v1/projects/{pid}/competitors",
            json={"name": name, "website_url": url},
            headers=h,
        )
    ps = (
        await client.post(f"/api/v1/projects/{pid}/prompt-sets", json={"name": "Core"}, headers=h)
    ).json()
    await client.post(
        f"/api/v1/prompt-sets/{ps['id']}/prompts",
        json={"text": "What are the best accounting tools for startups?"},
        headers=h,
    )
    reg = registry_answering(answer)
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_provider_registry] = lambda: reg
    app.dependency_overrides[get_run_dispatcher] = lambda: Recorder()
    return h, org, pid, ps["id"], reg


async def _run_batch(
    client: AsyncClient,
    db_session: AsyncSession,
    h: dict[str, str],
    set_id: str,
    reg: ProviderRegistry,
) -> tuple[str, uuid.UUID]:
    batch = (
        await client.post(
            f"/api/v1/prompt-sets/{set_id}/run", json={"providers": ["openai"]}, headers=h
        )
    ).json()
    run_id = (
        await db_session.scalars(
            select(PromptRun.id).where(PromptRun.batch_id == uuid.UUID(batch["id"]))
        )
    ).one()
    outcome = await execute_prompt_run(
        db_session, run_id, reg, InMemoryProviderThrottle(), settings()
    )
    assert outcome.status is not None and outcome.status.value == "completed"
    return batch["id"], run_id


async def test_completed_run_is_parsed_and_exposed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid, set_id, reg = await _setup(client, fx.LIST_RECOMMENDATIONS)
    batch_id, run_id = await _run_batch(client, db_session, h, set_id, reg)

    got = (await client.get(f"/api/v1/prompt-runs/{run_id}/intelligence", headers=h)).json()
    assert got["parser_version"] == PARSER_VERSION and got["parsed_at"]
    assert got["summary"]["brand_mentioned"] and got["summary"]["brand_position"] == 3
    assert got["summary"]["competitors_mentioned"] == ["QuickBooks", "Xero"]
    assert [m["brand_name"] for m in got["mentions"]] == ["Ledgerly"]
    comp: dict[str, list[dict]] = {}  # type: ignore[type-arg]
    for m in got["competitor_mentions"]:
        comp.setdefault(m["brand_name"], []).append(m)
    assert comp["QuickBooks"][0]["position"] == 1 and comp["QuickBooks"][0]["competitor_id"]
    assert any(m["recommendation_strength"] == "moderate" for m in comp["Xero"])
    assert [c["citation_position"] for c in got["citations"]] == [1, 2, 3]
    assert any(c["subject"] == "Ledgerly" and c["predicate"] == "offers" for c in got["claims"])
    # prompt table row carries the visibility result
    prompts = (await client.get(f"/api/v1/prompt-sets/{set_id}/prompts", headers=h)).json()["items"]
    assert (
        prompts[0]["visibility_result"]["brand_mentioned"] is True
        and prompts[0]["visibility_result"]["position"] == 3
    )
    assert prompts[0]["visibility_result"]["competitors_mentioned"] == ["QuickBooks", "Xero"]
    # competitor ids resolve to the project's competitors
    cm = (
        await db_session.scalars(
            select(CompetitorMention).where(CompetitorMention.project_id == uuid.UUID(pid))
        )
    ).all()
    assert all(m.competitor_id is not None for m in cm)


async def test_no_brand_answer_is_unknown_not_negative(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid, set_id, reg = await _setup(client, fx.NO_BRAND)
    _, run_id = await _run_batch(client, db_session, h, set_id, reg)
    got = (await client.get(f"/api/v1/prompt-runs/{run_id}/intelligence", headers=h)).json()
    assert got["mentions"] == [] and got["summary"]["sentiment"] == "unknown"
    assert got["summary"]["brand_mentioned"] is False and got["summary"]["brand_position"] is None


async def test_reprocess_replaces_observations_without_duplicating_response(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid, set_id, reg = await _setup(client, fx.NEGATIVE)
    batch_id, run_id = await _run_batch(client, db_session, h, set_id, reg)
    response = (
        await db_session.scalars(select(AiResponse).where(AiResponse.prompt_run_id == run_id))
    ).one()
    # Simulate rows written by an older parser version.
    response.parser_version = "response-parser/v0"
    for model in (BrandMention, CompetitorMention, ResponseClaim, ResponseCitation):
        for row in (
            await db_session.scalars(select(model).where(model.ai_response_id == response.id))
        ).all():  # type: ignore[attr-defined]
            row.parser_version = "response-parser/v0"
    db_session.add(
        BrandMention(
            ai_response_id=response.id,
            project_id=uuid.UUID(pid),
            brand_name="Ledgerly",
            mention_text="stale",
            position=9,
            sentiment="positive",
            recommendation_strength="strong",
            context="stale row",
            parser_version="response-parser/v0",
        )
    )
    await db_session.flush()
    before = await db_session.scalar(
        select(func.count())
        .select_from(BrandMention)
        .where(BrandMention.ai_response_id == response.id)
    )
    assert before == 2

    # Service-level reprocessing: skip when current unless forced, replace otherwise.
    service = ResponseIntelligenceService(db_session)
    assert (
        await service.parse_and_store(response, force=False) is not None
    )  # stale version → re-parsed
    assert await service.parse_and_store(response, force=False) is None  # already current
    await db_session.commit()

    responses = await db_session.scalar(
        select(func.count()).select_from(AiResponse).where(AiResponse.prompt_run_id == run_id)
    )
    assert responses == 1
    rows = (
        await db_session.scalars(
            select(BrandMention).where(BrandMention.ai_response_id == response.id)
        )
    ).all()
    assert (
        len(rows) == 1
        and rows[0].mention_text == "Ledgerly"
        and rows[0].parser_version == PARSER_VERSION
    )
    assert rows[0].sentiment == "negative"

    # API reprocess endpoints (run + batch)
    rerun = await client.post(f"/api/v1/prompt-runs/{run_id}/reprocess", headers=h)
    assert rerun.status_code == 200 and rerun.json()["parser_version"] == PARSER_VERSION
    assert len(rerun.json()["mentions"]) == 1
    batch = await client.post(f"/api/v1/prompt-run-batches/{batch_id}/reprocess", headers=h)
    assert batch.status_code == 200 and batch.json() == {
        "reprocessed": 1,
        "parser_version": PARSER_VERSION,
    }
    assert (
        await db_session.scalar(
            select(func.count()).select_from(AiResponse).where(AiResponse.prompt_run_id == run_id)
        )
        == 1
    )


async def test_tenant_isolation_and_roles(client: AsyncClient, db_session: AsyncSession) -> None:
    h, org, pid, set_id, reg = await _setup(client, fx.PROSE)
    batch_id, run_id = await _run_batch(client, db_session, h, set_id, reg)
    stranger = auth_header((await signup(client, org="Other Org"))["access_token"])
    assert (
        await client.get(f"/api/v1/prompt-runs/{run_id}/intelligence", headers=stranger)
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/prompt-runs/{run_id}/reprocess", headers=stranger)
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/prompt-run-batches/{batch_id}/reprocess", headers=stranger)
    ).status_code == 404
    assert (await client.get(f"/api/v1/prompt-runs/{run_id}/intelligence")).status_code == 401
    assert (
        await client.get(f"/api/v1/prompt-runs/{uuid.uuid4()}/intelligence", headers=h)
    ).status_code == 404
    viewer = await add_member(
        db_session, org, f"viewer-{uuid.uuid4().hex[:6]}@example.com", MembershipRole.VIEWER
    )
    v = auth_header(create_access_token(viewer))
    assert (
        await client.get(f"/api/v1/prompt-runs/{run_id}/intelligence", headers=v)
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/prompt-runs/{run_id}/reprocess", headers=v)
    ).status_code == 403
    assert (
        await client.post(f"/api/v1/prompt-run-batches/{batch_id}/reprocess", headers=v)
    ).status_code == 403
