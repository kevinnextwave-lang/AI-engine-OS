"""Recurring collection schedules: plan gating, CRUD, next-run math, and the
beat sweep (through ExecutionService with stubbed providers/dispatcher)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models import MembershipRole
from app.models.organization import Organization, OrganizationPlan
from app.models.prompt_schedule import PromptSchedule, ScheduleCadence
from app.models.prompts import BatchStatus, PromptRunBatch
from app.services.schedules import compute_next_run, run_due_schedules
from tests.conftest import auth_header
from tests.execution.test_execution import (
    Recorder,
    _setup,
    registry_with,
)
from tests.test_authz import add_member
from tests.test_projects_api import _set_plan

pytestmark = pytest.mark.anyio


@pytest.fixture
def registry(client: AsyncClient) -> object:
    from app.api.v1.routes.execution import get_provider_registry
    from tests.ai.test_providers import OPENAI_OK, json_response

    reg = registry_with({"openai": lambda r: json_response(200, OPENAI_OK)})
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_provider_registry] = lambda: reg
    return reg


@pytest.fixture
def dispatched(client: AsyncClient) -> Recorder:
    from app.api.v1.routes.execution import get_run_dispatcher

    rec = Recorder()
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_run_dispatcher] = lambda: rec
    return rec


def _body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "cadence": "weekly",
        "hour_utc": 6,
        "weekday": 0,
        "providers": ["openai"],
    }
    body.update(overrides)
    return body


# --- next-run math -----------------------------------------------------------


def test_compute_next_run_daily() -> None:
    now = datetime(2026, 9, 28, 5, 30, tzinfo=UTC)  # Monday
    assert compute_next_run(ScheduleCadence.DAILY, 6, None, now=now) == datetime(
        2026, 9, 28, 6, 0, tzinfo=UTC
    )
    # Already past today's hour -> tomorrow.
    assert compute_next_run(ScheduleCadence.DAILY, 5, None, now=now) == datetime(
        2026, 9, 29, 5, 0, tzinfo=UTC
    )


def test_compute_next_run_weekly() -> None:
    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)  # Monday noon
    # Wednesday (2) at 6: this week.
    assert compute_next_run(ScheduleCadence.WEEKLY, 6, 2, now=now) == datetime(
        2026, 9, 30, 6, 0, tzinfo=UTC
    )
    # Monday (0) at 6 already passed -> next Monday.
    assert compute_next_run(ScheduleCadence.WEEKLY, 6, 0, now=now) == datetime(
        2026, 10, 5, 6, 0, tzinfo=UTC
    )


# --- CRUD + plan gating ------------------------------------------------------


async def test_free_plan_cannot_schedule(client: AsyncClient, registry: object) -> None:
    h, _org, _pid, sid = await _setup(client)
    r = await client.put(f"/api/v1/prompt-sets/{sid}/schedule", json=_body(), headers=h)
    assert r.status_code == 422
    assert "upgrade" in r.json()["error"]["message"].lower()


async def test_starter_weekly_ok_daily_rejected(
    client: AsyncClient, registry: object, db_session: AsyncSession
) -> None:
    h, org, _pid, sid = await _setup(client)
    await _set_plan(db_session, org, OrganizationPlan.STARTER)
    r = await client.put(f"/api/v1/prompt-sets/{sid}/schedule", json=_body(), headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["cadence"] == "weekly"
    assert data["next_run_at"] is not None
    r = await client.put(
        f"/api/v1/prompt-sets/{sid}/schedule",
        json=_body(cadence="daily", weekday=None),
        headers=h,
    )
    assert r.status_code == 422
    assert "weekly" in r.json()["error"]["message"]


async def test_schedule_crud_roundtrip(
    client: AsyncClient, registry: object, db_session: AsyncSession
) -> None:
    h, org, _pid, sid = await _setup(client)
    await _set_plan(db_session, org, OrganizationPlan.GROWTH)
    # No schedule yet.
    assert (await client.get(f"/api/v1/prompt-sets/{sid}/schedule", headers=h)).status_code == 404
    created = (
        await client.put(
            f"/api/v1/prompt-sets/{sid}/schedule",
            json=_body(cadence="daily", weekday=None, hour_utc=4),
            headers=h,
        )
    ).json()
    assert created["cadence"] == "daily"
    assert created["weekday"] is None
    # Upsert replaces in place — same row id.
    updated = (
        await client.put(
            f"/api/v1/prompt-sets/{sid}/schedule",
            json=_body(hour_utc=9, weekday=4),
            headers=h,
        )
    ).json()
    assert updated["id"] == created["id"]
    assert updated["cadence"] == "weekly"
    got = (await client.get(f"/api/v1/prompt-sets/{sid}/schedule", headers=h)).json()
    assert got["hour_utc"] == 9
    assert (
        await client.delete(f"/api/v1/prompt-sets/{sid}/schedule", headers=h)
    ).status_code == 204
    assert (await client.get(f"/api/v1/prompt-sets/{sid}/schedule", headers=h)).status_code == 404


async def test_weekly_requires_weekday_and_valid_provider(
    client: AsyncClient, registry: object, db_session: AsyncSession
) -> None:
    h, org, _pid, sid = await _setup(client)
    await _set_plan(db_session, org, OrganizationPlan.GROWTH)
    r = await client.put(f"/api/v1/prompt-sets/{sid}/schedule", json=_body(weekday=None), headers=h)
    assert r.status_code == 422
    r = await client.put(
        f"/api/v1/prompt-sets/{sid}/schedule", json=_body(providers=["nope"]), headers=h
    )
    assert r.status_code == 422


async def test_viewer_cannot_manage_schedule(
    client: AsyncClient, registry: object, db_session: AsyncSession
) -> None:
    h, org, _pid, sid = await _setup(client)
    await _set_plan(db_session, org, OrganizationPlan.GROWTH)
    assert (
        await client.put(f"/api/v1/prompt-sets/{sid}/schedule", json=_body(), headers=h)
    ).status_code == 200
    viewer_id = await add_member(
        db_session, org, f"viewer-{uuid.uuid4().hex[:6]}@example.com", MembershipRole.VIEWER
    )
    vh = auth_header(create_access_token(viewer_id))
    assert (await client.get(f"/api/v1/prompt-sets/{sid}/schedule", headers=vh)).status_code == 200
    assert (
        await client.put(f"/api/v1/prompt-sets/{sid}/schedule", json=_body(), headers=vh)
    ).status_code == 403
    assert (
        await client.delete(f"/api/v1/prompt-sets/{sid}/schedule", headers=vh)
    ).status_code == 403


async def test_cross_tenant_schedule_404(
    client: AsyncClient, registry: object, db_session: AsyncSession
) -> None:
    h, org, _pid, sid = await _setup(client)
    await _set_plan(db_session, org, OrganizationPlan.GROWTH)
    from tests.test_authz import signup

    outsider = await signup(client, org="Other Org")
    oh = auth_header(outsider["access_token"])
    assert (await client.get(f"/api/v1/prompt-sets/{sid}/schedule", headers=oh)).status_code == 404
    assert (
        await client.put(f"/api/v1/prompt-sets/{sid}/schedule", json=_body(), headers=oh)
    ).status_code == 404


# --- the beat sweep ----------------------------------------------------------


async def _make_due(db_session: AsyncSession, sid: str) -> PromptSchedule:
    schedule = await db_session.scalar(
        select(PromptSchedule).where(PromptSchedule.prompt_set_id == uuid.UUID(sid))
    )
    assert schedule is not None
    schedule.next_run_at = datetime.now(UTC) - timedelta(minutes=5)
    # Commit: the sweep's rollback-on-error must not be able to undo this.
    await db_session.commit()
    return schedule


async def test_sweep_fires_due_schedule(
    client: AsyncClient, registry: object, db_session: AsyncSession
) -> None:
    from tests.ai.test_providers import OPENAI_OK as OK
    from tests.ai.test_providers import json_response

    h, org, pid, sid = await _setup(client, prompts=2)
    await _set_plan(db_session, org, OrganizationPlan.GROWTH)
    assert (
        await client.put(
            f"/api/v1/prompt-sets/{sid}/schedule",
            json=_body(cadence="daily", weekday=None),
            headers=h,
        )
    ).status_code == 200
    schedule = await _make_due(db_session, sid)
    reg = registry_with({"openai": lambda r: json_response(200, OK)})
    rec = Recorder()
    counts = await run_due_schedules(db_session, reg, rec)
    assert counts == {"started": 1, "deferred": 0, "skipped": 0}
    assert len(rec.calls) == 2  # 2 prompts x 1 provider
    await db_session.refresh(schedule)
    assert schedule.last_batch_id is not None
    assert schedule.last_error is None
    assert schedule.last_run_at is not None
    assert schedule.next_run_at > datetime.now(UTC)
    batch = await db_session.get(PromptRunBatch, schedule.last_batch_id)
    assert batch is not None
    assert batch.status == BatchStatus.QUEUED
    assert batch.total_runs == 2
    # Nothing due anymore: a second sweep is a no-op.
    counts = await run_due_schedules(db_session, reg, rec)
    assert counts == {"started": 0, "deferred": 0, "skipped": 0}


async def test_sweep_defers_on_active_batch(
    client: AsyncClient, registry: object, dispatched: Recorder, db_session: AsyncSession
) -> None:
    from tests.ai.test_providers import OPENAI_OK as OK
    from tests.ai.test_providers import json_response

    h, org, _pid, sid = await _setup(client, prompts=2)
    await _set_plan(db_session, org, OrganizationPlan.GROWTH)
    assert (
        await client.put(
            f"/api/v1/prompt-sets/{sid}/schedule",
            json=_body(cadence="daily", weekday=None),
            headers=h,
        )
    ).status_code == 200
    # Start a manual batch that stays in flight.
    r = await client.post(
        f"/api/v1/prompt-sets/{sid}/run", json={"providers": ["openai"]}, headers=h
    )
    assert r.status_code == 202, r.text
    schedule = await _make_due(db_session, sid)
    due_at = schedule.next_run_at
    reg = registry_with({"openai": lambda r: json_response(200, OK)})
    counts = await run_due_schedules(db_session, reg, Recorder())
    assert counts == {"started": 0, "deferred": 1, "skipped": 0}
    await db_session.refresh(schedule)
    assert schedule.last_error is not None
    assert "in progress" in schedule.last_error
    assert schedule.next_run_at == due_at  # unchanged: retried next sweep
    assert schedule.last_batch_id is None


async def test_sweep_skips_when_plan_downgraded(
    client: AsyncClient, registry: object, db_session: AsyncSession
) -> None:
    from tests.ai.test_providers import OPENAI_OK as OK
    from tests.ai.test_providers import json_response

    h, org, _pid, sid = await _setup(client, prompts=1)
    await _set_plan(db_session, org, OrganizationPlan.GROWTH)
    assert (
        await client.put(
            f"/api/v1/prompt-sets/{sid}/schedule",
            json=_body(cadence="daily", weekday=None),
            headers=h,
        )
    ).status_code == 200
    schedule = await _make_due(db_session, sid)
    await db_session.execute(
        update(Organization)
        .where(Organization.id == uuid.UUID(org))
        .values(plan=OrganizationPlan.FREE)
    )
    await db_session.flush()
    reg = registry_with({"openai": lambda r: json_response(200, OK)})
    rec = Recorder()
    counts = await run_due_schedules(db_session, reg, rec)
    assert counts == {"started": 0, "deferred": 0, "skipped": 1}
    assert rec.calls == []
    await db_session.refresh(schedule)
    assert schedule.last_error is not None
    assert "plan" in schedule.last_error.lower()
    assert schedule.next_run_at > datetime.now(UTC)  # advanced, no hot loop
