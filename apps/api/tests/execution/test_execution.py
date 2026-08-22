"""Batch creation, queueing, worker execution (mocked providers), retries, rate
limits, cancellation, usage tracking and tenant isolation. No live AI calls."""

import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.execution import execute_prompt_run
from app.ai.pricing import estimate_cost
from app.ai.providers.google import GoogleProvider
from app.ai.providers.openai import OpenAIProvider
from app.ai.registry import ProviderRegistry
from app.ai.throttle import InMemoryProviderThrottle, backoff_seconds
from app.api.v1.routes.execution import get_provider_registry, get_run_dispatcher
from app.core.config import Settings
from app.core.security import create_access_token
from app.models import MembershipRole
from app.models.prompts import (
    AiResponse,
    AiUsageRecord,
    BatchStatus,
    PromptRun,
    PromptRunBatch,
    PromptRunStatus,
)
from tests.ai.test_providers import GOOGLE_OK, OPENAI_OK, json_response, transport
from tests.conftest import auth_header
from tests.test_authz import add_member, org_id_for, signup
from tests.test_projects_api import create_project


def settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "ai_run_retry_base_seconds": 1.0,
        "ai_run_retry_max_seconds": 8.0,
        "ai_run_max_attempts": 3,
        "ai_rate_limit_openai_per_minute": 0,
        "ai_rate_limit_google_per_minute": 0,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


class Recorder:
    """Stands in for the Celery dispatcher."""

    def __init__(self, fail_after: int | None = None) -> None:
        self.calls: list[tuple[uuid.UUID, int]] = []
        self.fail_after = fail_after

    def __call__(self, run_id: uuid.UUID, priority: int) -> None:
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise ConnectionError("broker down")
        self.calls.append((run_id, priority))


@pytest.fixture
def dispatched(client: AsyncClient) -> Recorder:
    rec = Recorder()
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_run_dispatcher] = lambda: rec
    return rec


def registry_with(handlers: dict[str, Any]) -> ProviderRegistry:
    reg = ProviderRegistry(settings())
    if "openai" in handlers:
        reg.register(
            "openai",
            OpenAIProvider("k", client=transport(handlers["openai"]), default_timeout_seconds=2),
        )
    if "google" in handlers:
        reg.register(
            "google",
            GoogleProvider("k", client=transport(handlers["google"]), default_timeout_seconds=2),
        )
    return reg


@pytest.fixture
def registry(client: AsyncClient) -> ProviderRegistry:
    reg = registry_with(
        {
            "openai": lambda r: json_response(200, OPENAI_OK),
            "google": lambda r: json_response(200, GOOGLE_OK),
        }
    )
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_provider_registry] = lambda: reg
    return reg


async def _setup(client: AsyncClient, prompts: int = 3) -> tuple[dict[str, str], str, str, str]:
    owner = await signup(client, org="Exec Org")
    h = auth_header(owner["access_token"])
    org = await org_id_for(client, owner["access_token"])
    pid = (
        await create_project(client, h, name="Ledgerly", website_url="https://ledgerly.example")
    )["id"]
    ps = (
        await client.post(f"/api/v1/projects/{pid}/prompt-sets", json={"name": "Core"}, headers=h)
    ).json()
    for i in range(prompts):
        r = await client.post(
            f"/api/v1/prompt-sets/{ps['id']}/prompts",
            json={"text": f"Which accounting tool is best for startups number {i}?"},
            headers=h,
        )
        assert r.status_code == 201, r.text
    return h, org, pid, ps["id"]


async def _execute_all(
    session: AsyncSession,
    batch_id: uuid.UUID,
    registry: ProviderRegistry,
    throttle: InMemoryProviderThrottle | None = None,
    cfg: Settings | None = None,
) -> list[Any]:
    runs = (
        await session.scalars(
            select(PromptRun).where(PromptRun.batch_id == batch_id).order_by(PromptRun.created_at)
        )
    ).all()
    return [
        await execute_prompt_run(
            session, r.id, registry, throttle or InMemoryProviderThrottle(), cfg or settings()
        )
        for r in runs
    ]


# --- batch creation & queueing ----------------------------------------------------------


async def test_run_creates_batch_and_queues_each_run(
    client: AsyncClient, dispatched: Recorder, registry: ProviderRegistry, db_session: AsyncSession
) -> None:
    h, _, pid, set_id = await _setup(client, prompts=3)
    resp = await client.post(
        f"/api/v1/prompt-sets/{set_id}/run",
        json={"providers": ["openai", "google"], "priority": "high"},
        headers=h,
    )
    assert resp.status_code == 202, resp.text
    batch = resp.json()
    assert batch["status"] == "queued" and batch["total_runs"] == 6 and batch["priority"] == "high"
    assert batch["targets"] == [
        {"provider_key": "openai", "model_key": "gpt-4o-mini"},
        {"provider_key": "google", "model_key": "gemini-2.0-flash"},
    ]
    assert batch["completed_runs"] == batch["failed_runs"] == 0
    assert len(dispatched.calls) == 6 and {p for _, p in dispatched.calls} == {9}
    runs = (
        await db_session.scalars(
            select(PromptRun).where(PromptRun.batch_id == uuid.UUID(batch["id"]))
        )
    ).all()
    assert {r.status for r in runs} == {PromptRunStatus.QUEUED} and {r.id for r in runs} == {
        rid for rid, _ in dispatched.calls
    }
    assert all(r.provider_id and r.model_id for r in runs)
    listed = (await client.get(f"/api/v1/prompt-sets/{set_id}/batches", headers=h)).json()
    assert listed["total"] == 1 and listed["items"][0]["id"] == batch["id"]
    got = (await client.get(f"/api/v1/prompt-run-batches/{batch['id']}", headers=h)).json()
    assert got["usage"] == {"input_tokens": 0, "output_tokens": 0, "estimated_cost": "0"}


async def test_run_validates_targets_and_prompt_selection(
    client: AsyncClient, dispatched: Recorder, registry: ProviderRegistry
) -> None:
    h, _, pid, set_id = await _setup(client, prompts=2)
    bad = await client.post(
        f"/api/v1/prompt-sets/{set_id}/run", json={"providers": ["anthropic"]}, headers=h
    )
    assert bad.status_code == 422 and "no credentials" in bad.text
    bad = await client.post(
        f"/api/v1/prompt-sets/{set_id}/run",
        json={"providers": ["openai"], "models": {"openai": "gpt-99"}},
        headers=h,
    )
    assert bad.status_code == 422 and "gpt-99" in bad.text
    bad = await client.post(
        f"/api/v1/prompt-sets/{set_id}/run", json={"providers": ["nope"]}, headers=h
    )
    assert bad.status_code == 422
    assert dispatched.calls == []
    ok = await client.post(
        f"/api/v1/prompt-sets/{set_id}/run",
        json={"providers": ["openai"], "models": {"openai": "gpt-4o"}, "priority": "low"},
        headers=h,
    )
    assert ok.status_code == 202 and ok.json()["targets"] == [
        {"provider_key": "openai", "model_key": "gpt-4o"}
    ]
    assert {p for _, p in dispatched.calls} == {3}
    empty = (
        await client.post(f"/api/v1/projects/{pid}/prompt-sets", json={"name": "Empty"}, headers=h)
    ).json()
    assert (
        await client.post(
            f"/api/v1/prompt-sets/{empty['id']}/run", json={"providers": ["openai"]}, headers=h
        )
    ).status_code == 422


async def test_dispatch_failure_marks_remaining_runs_failed(
    client: AsyncClient, registry: ProviderRegistry, db_session: AsyncSession
) -> None:
    h, _, pid, set_id = await _setup(client, prompts=3)
    rec = Recorder(fail_after=1)
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_run_dispatcher] = lambda: rec
    resp = await client.post(
        f"/api/v1/prompt-sets/{set_id}/run", json={"providers": ["openai"]}, headers=h
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["failed_runs"] == 2 and body["status"] == "queued"
    runs = (
        await db_session.scalars(
            select(PromptRun).where(PromptRun.batch_id == uuid.UUID(body["id"]))
        )
    ).all()
    assert sorted(r.status.value for r in runs) == ["failed", "failed", "queued"]
    assert {r.error_code for r in runs if r.status == PromptRunStatus.FAILED} == {"dispatch_failed"}


# --- execution -----------------------------------------------------------------------------


async def test_successful_execution_persists_response_usage_and_finishes_batch(
    client: AsyncClient, dispatched: Recorder, registry: ProviderRegistry, db_session: AsyncSession
) -> None:
    h, org, pid, set_id = await _setup(client, prompts=2)
    batch = (
        await client.post(
            f"/api/v1/prompt-sets/{set_id}/run", json={"providers": ["openai", "google"]}, headers=h
        )
    ).json()
    outcomes = await _execute_all(db_session, uuid.UUID(batch["id"]), registry)
    assert [o.status for o in outcomes] == [PromptRunStatus.COMPLETED] * 4
    assert not any(o.should_retry for o in outcomes)

    got = (await client.get(f"/api/v1/prompt-run-batches/{batch['id']}", headers=h)).json()
    assert got["status"] == "completed" and got["completed_runs"] == 4 and got["failed_runs"] == 0
    assert got["started_at"] and got["completed_at"]
    # usage: openai 11+5 ×2, google 7+3 ×2
    assert got["usage"]["input_tokens"] == 36 and got["usage"]["output_tokens"] == 16
    expected = (
        estimate_cost({"input_per_million": 0.15, "output_per_million": 0.60}, 11, 5).amount * 2
        + estimate_cost({"input_per_million": 0.10, "output_per_million": 0.40}, 7, 3).amount * 2
    )
    assert Decimal(got["usage"]["estimated_cost"]) == expected

    runs = (await client.get(f"/api/v1/prompt-run-batches/{batch['id']}/runs", headers=h)).json()
    assert runs["total"] == 4
    row = next(r for r in runs["items"] if r["provider_key"] == "openai")
    assert row["status"] == "completed" and row["attempts"] == 1 and row["latency_ms"] is not None
    assert (
        row["response"]["response_text"] == "Hello from OpenAI"
        and row["response"]["finish_reason"] == "stop"
    )
    assert row["response"]["total_tokens"] == 16 and row["response"]["raw_metadata"].keys() <= {
        "finish_reason",
        "system_fingerprint",
    }
    usage = (
        await db_session.scalars(
            select(AiUsageRecord).where(AiUsageRecord.project_id == uuid.UUID(pid))
        )
    ).all()
    assert len(usage) == 4 and {u.organization_id for u in usage} == {uuid.UUID(org)}
    assert {u.pricing_version for u in usage} == {"2025-06-list"}
    db_run = await db_session.get(PromptRun, uuid.UUID(row["id"]))
    assert db_run is not None and db_run.ai_generation_id is not None


async def test_non_retryable_failure_fails_run_immediately(
    client: AsyncClient, dispatched: Recorder, db_session: AsyncSession
) -> None:
    reg = registry_with({"openai": lambda r: json_response(401, {"error": {"message": "bad key"}})})
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_provider_registry] = lambda: reg
    h, _, pid, set_id = await _setup(client, prompts=1)
    batch = (
        await client.post(
            f"/api/v1/prompt-sets/{set_id}/run", json={"providers": ["openai"]}, headers=h
        )
    ).json()
    (outcome,) = await _execute_all(db_session, uuid.UUID(batch["id"]), reg)
    assert outcome.status == PromptRunStatus.FAILED and not outcome.should_retry
    run = (
        await db_session.scalars(
            select(PromptRun).where(PromptRun.batch_id == uuid.UUID(batch["id"]))
        )
    ).one()
    assert (
        run.attempts == 1
        and run.error_code == "authentication_error"
        and run.error_message == "bad key"
    )
    got = (await client.get(f"/api/v1/prompt-run-batches/{batch['id']}", headers=h)).json()
    assert got["status"] == "failed" and got["failed_runs"] == 1
    assert (await db_session.scalars(select(AiResponse))).first() is None


async def test_retry_with_backoff_then_success(
    client: AsyncClient, dispatched: Recorder, db_session: AsyncSession
) -> None:
    calls: list[int] = []

    def flaky(r: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return json_response(429, {"error": {"message": "slow down"}})
        return json_response(200, OPENAI_OK)

    reg = registry_with({"openai": flaky})
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_provider_registry] = lambda: reg
    h, _, pid, set_id = await _setup(client, prompts=1)
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
    throttle = InMemoryProviderThrottle()

    first = await execute_prompt_run(db_session, run_id, reg, throttle, settings())
    assert first.should_retry and first.retry_in == backoff_seconds(1, base=1.0, cap=8.0) == 1.0
    assert first.reason == "rate_limit"
    run = await db_session.get(PromptRun, run_id)
    assert (
        run is not None
        and run.status == PromptRunStatus.QUEUED
        and run.attempts == 1
        and run.error_code == "rate_limit"
    )

    second = await execute_prompt_run(db_session, run_id, reg, throttle, settings())
    assert second.should_retry and second.retry_in == 2.0
    third = await execute_prompt_run(db_session, run_id, reg, throttle, settings())
    assert third.status == PromptRunStatus.COMPLETED and not third.should_retry
    await db_session.refresh(run)
    assert run.attempts == 3 and run.error_code is None and len(calls) == 3
    assert (await client.get(f"/api/v1/prompt-run-batches/{batch['id']}", headers=h)).json()[
        "status"
    ] == "completed"


async def test_retries_are_bounded_and_timeouts_retry(
    client: AsyncClient, dispatched: Recorder, db_session: AsyncSession
) -> None:
    def always_timeout(r: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=r)

    reg = registry_with({"openai": always_timeout})
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_provider_registry] = lambda: reg
    h, _, pid, set_id = await _setup(client, prompts=1)
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
    cfg = settings(ai_run_max_attempts=3)
    delays = []
    for _ in range(2):
        o = await execute_prompt_run(db_session, run_id, reg, InMemoryProviderThrottle(), cfg)
        assert o.should_retry and o.reason == "timeout"
        delays.append(o.retry_in)
    assert delays == [1.0, 2.0]
    final = await execute_prompt_run(db_session, run_id, reg, InMemoryProviderThrottle(), cfg)
    assert final.status == PromptRunStatus.FAILED and not final.should_retry
    run = await db_session.get(PromptRun, run_id)
    assert run is not None and run.attempts == 3 and run.error_code == "timeout"
    assert backoff_seconds(10, base=1.0, cap=8.0) == 8.0


async def test_provider_throttle_defers_without_consuming_attempt(
    client: AsyncClient, dispatched: Recorder, registry: ProviderRegistry, db_session: AsyncSession
) -> None:
    h, _, pid, set_id = await _setup(client, prompts=3)
    batch = (
        await client.post(
            f"/api/v1/prompt-sets/{set_id}/run", json={"providers": ["openai"]}, headers=h
        )
    ).json()
    throttle = InMemoryProviderThrottle()
    cfg = settings(ai_rate_limit_openai_per_minute=2)
    outcomes = await _execute_all(db_session, uuid.UUID(batch["id"]), registry, throttle, cfg)
    assert [o.status for o in outcomes[:2]] == [PromptRunStatus.COMPLETED] * 2
    deferred = outcomes[2]
    assert (
        deferred.should_retry
        and deferred.reason == "provider throttle"
        and 0 < deferred.retry_in <= 60.5
    )
    run = await db_session.get(PromptRun, deferred.run_id)
    assert run is not None and run.status == PromptRunStatus.QUEUED and run.attempts == 0
    throttle.reset()
    again = await execute_prompt_run(db_session, deferred.run_id, registry, throttle, cfg)
    assert again.status == PromptRunStatus.COMPLETED


# --- cancellation ------------------------------------------------------------------------------


async def test_cancel_flips_queued_runs_and_in_flight_runs_finish_safely(
    client: AsyncClient, dispatched: Recorder, db_session: AsyncSession
) -> None:
    h, _, pid, set_id = await _setup(client, prompts=3)
    state: dict[str, Any] = {"batch_id": None, "cancel_status": None}

    async def provider_that_gets_cancelled_mid_call(r: httpx.Request) -> httpx.Response:
        # While this provider call is "in flight", the user cancels the batch.
        resp = await client.post(
            f"/api/v1/prompt-run-batches/{state['batch_id']}/cancel", headers=h
        )
        state["cancel_status"] = resp.status_code
        state["cancel_body"] = resp.json()
        return json_response(200, OPENAI_OK)

    reg = registry_with({"openai": provider_that_gets_cancelled_mid_call})
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_provider_registry] = lambda: reg
    batch = (
        await client.post(
            f"/api/v1/prompt-sets/{set_id}/run", json={"providers": ["openai"]}, headers=h
        )
    ).json()
    state["batch_id"] = batch["id"]
    run_ids = list(
        (
            await db_session.scalars(
                select(PromptRun.id)
                .where(PromptRun.batch_id == uuid.UUID(batch["id"]))
                .order_by(PromptRun.created_at)
            )
        ).all()
    )

    first = await execute_prompt_run(
        db_session, run_ids[0], reg, InMemoryProviderThrottle(), settings()
    )
    # The cancel landed while the provider call was running: queued siblings were cancelled
    # immediately, the in-flight run still completed and its answer was kept.
    assert state["cancel_status"] == 200
    assert (
        state["cancel_body"]["status"] == "cancelling"
        and state["cancel_body"]["cancelled_runs"] == 2
    )
    assert first.status == PromptRunStatus.COMPLETED
    final = (await client.get(f"/api/v1/prompt-run-batches/{batch['id']}", headers=h)).json()
    assert final["status"] == "cancelled"
    assert final["completed_runs"] == 1 and final["cancelled_runs"] == 2 and final["completed_at"]
    assert (
        await db_session.scalars(select(AiResponse).where(AiResponse.prompt_run_id == run_ids[0]))
    ).one()

    # Late workers for cancelled runs do nothing, and the batch cannot be cancelled twice.
    late = await execute_prompt_run(
        db_session, run_ids[1], reg, InMemoryProviderThrottle(), settings()
    )
    assert late.status is None and "cancelled" in (late.reason or "")
    assert (
        await client.post(f"/api/v1/prompt-run-batches/{batch['id']}/cancel", headers=h)
    ).status_code == 409


async def test_queued_run_sees_cancelling_batch_before_calling_provider(
    client: AsyncClient, dispatched: Recorder, registry: ProviderRegistry, db_session: AsyncSession
) -> None:
    h, _, pid, set_id = await _setup(client, prompts=1)
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
    row = await db_session.get(PromptRunBatch, uuid.UUID(batch["id"]))
    assert row is not None
    row.status = BatchStatus.CANCELLING  # cancel raced ahead of the worker but after its queue read
    await db_session.commit()
    outcome = await execute_prompt_run(
        db_session, run_id, registry, InMemoryProviderThrottle(), settings()
    )
    assert outcome.status == PromptRunStatus.CANCELLED
    final = (await client.get(f"/api/v1/prompt-run-batches/{batch['id']}", headers=h)).json()
    assert final["status"] == "cancelled" and final["cancelled_runs"] == 1


async def test_cancel_after_partial_completion_keeps_results(
    client: AsyncClient, dispatched: Recorder, registry: ProviderRegistry, db_session: AsyncSession
) -> None:
    h, _, pid, set_id = await _setup(client, prompts=2)
    batch = (
        await client.post(
            f"/api/v1/prompt-sets/{set_id}/run", json={"providers": ["openai"]}, headers=h
        )
    ).json()
    run_ids = list(
        (
            await db_session.scalars(
                select(PromptRun.id)
                .where(PromptRun.batch_id == uuid.UUID(batch["id"]))
                .order_by(PromptRun.created_at)
            )
        ).all()
    )
    assert (
        await execute_prompt_run(
            db_session, run_ids[0], registry, InMemoryProviderThrottle(), settings()
        )
    ).status == PromptRunStatus.COMPLETED
    body = (await client.post(f"/api/v1/prompt-run-batches/{batch['id']}/cancel", headers=h)).json()
    assert (
        body["status"] == "cancelled"
        and body["completed_runs"] == 1
        and body["cancelled_runs"] == 1
    )
    runs = (
        await client.get(
            f"/api/v1/prompt-run-batches/{batch['id']}/runs",
            params={"status": "completed"},
            headers=h,
        )
    ).json()
    assert (
        runs["total"] == 1 and runs["items"][0]["response"]["response_text"] == "Hello from OpenAI"
    )


# --- tenant isolation -----------------------------------------------------------------------------


async def test_tenant_isolation_and_roles(
    client: AsyncClient, dispatched: Recorder, registry: ProviderRegistry, db_session: AsyncSession
) -> None:
    h, org, pid, set_id = await _setup(client, prompts=1)
    batch = (
        await client.post(
            f"/api/v1/prompt-sets/{set_id}/run", json={"providers": ["openai"]}, headers=h
        )
    ).json()
    stranger = auth_header((await signup(client, org="Other Org"))["access_token"])
    for method, path in (
        ("post", f"/api/v1/prompt-sets/{set_id}/run"),
        ("get", f"/api/v1/prompt-sets/{set_id}/batches"),
        ("get", f"/api/v1/prompt-run-batches/{batch['id']}"),
        ("get", f"/api/v1/prompt-run-batches/{batch['id']}/runs"),
        ("post", f"/api/v1/prompt-run-batches/{batch['id']}/cancel"),
    ):
        kwargs: dict[str, Any] = {"json": {"providers": ["openai"]}} if method == "post" else {}
        assert (
            await getattr(client, method)(path, headers=stranger, **kwargs)
        ).status_code == 404, path
        assert (await getattr(client, method)(path, **kwargs)).status_code == 401, path
    assert (
        await client.get(f"/api/v1/prompt-run-batches/{uuid.uuid4()}", headers=h)
    ).status_code == 404
    still = await db_session.get(PromptRunBatch, uuid.UUID(batch["id"]))
    assert still is not None and still.status == BatchStatus.QUEUED and len(dispatched.calls) == 1

    viewer = await add_member(
        db_session, org, f"viewer-{uuid.uuid4().hex[:6]}@example.com", MembershipRole.VIEWER
    )
    v = auth_header(create_access_token(viewer))
    assert (
        await client.get(f"/api/v1/prompt-run-batches/{batch['id']}", headers=v)
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/prompt-sets/{set_id}/run", json={"providers": ["openai"]}, headers=v
        )
    ).status_code == 403
    assert (
        await client.post(f"/api/v1/prompt-run-batches/{batch['id']}/cancel", headers=v)
    ).status_code == 403


# --- cost configuration ---------------------------------------------------------------


def test_cost_estimation_is_config_driven() -> None:
    c = estimate_cost(
        {"input_per_million": 2.5, "output_per_million": 10, "currency": "USD", "version": "v1"},
        1000,
        500,
    )
    assert c.amount == Decimal("0.007500") and c.currency == "USD" and c.pricing_version == "v1"
    assert estimate_cost(None, 1000, 1000).amount == Decimal("0")
    assert estimate_cost({"input_per_million": 1}, None, None).amount == Decimal("0")
