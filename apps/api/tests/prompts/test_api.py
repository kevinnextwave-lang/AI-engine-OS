"""Prompt set / prompt API: CRUD, generation, dedup, table-ready rows, RBAC, tenancy."""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models import MembershipRole
from app.models.prompts import Prompt, PromptRun, PromptRunStatus
from tests.conftest import auth_header
from tests.test_authz import add_member, org_id_for, signup
from tests.test_projects_api import create_project

PROFILE = {
    "industry": "Accounting software",
    "features": ["automated invoicing"],
    "integrations": ["Stripe"],
    "target_audience": ["small businesses", "startups"],
    "competitors": ["QuickBooks", "Xero"],
    "geographic_market": ["United Kingdom"],
}


async def _setup(client: AsyncClient) -> tuple[dict[str, str], str, str]:
    owner = await signup(client, org="Prompt Org")
    h = auth_header(owner["access_token"])
    org = await org_id_for(client, owner["access_token"])
    pid = (
        await create_project(client, h, name="Ledgerly", website_url="https://ledgerly.example")
    )["id"]
    return h, org, pid


async def _set(client: AsyncClient, h: dict[str, str], pid: str, **body: object) -> dict:  # type: ignore[type-arg]
    payload = {"name": "Buyer journey", "description": "Core questions", **body}
    resp = await client.post(f"/api/v1/projects/{pid}/prompt-sets", json=payload, headers=h)
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


async def test_prompt_set_crud_and_listing(client: AsyncClient) -> None:
    h, _, pid = await _setup(client)
    created = await _set(client, h, pid, category="comparison")
    assert created["status"] == "active" and created["category"] == "comparison"
    assert created["prompt_count"] == 0 and created["last_generated_at"] is None
    await _set(client, h, pid, name="Archived", status="archived")
    listed = (await client.get(f"/api/v1/projects/{pid}/prompt-sets", headers=h)).json()
    assert listed["total"] == 2
    active = (
        await client.get(
            f"/api/v1/projects/{pid}/prompt-sets", params={"status": "active"}, headers=h
        )
    ).json()
    assert [s["name"] for s in active["items"]] == ["Buyer journey"]
    bad = await client.post(f"/api/v1/projects/{pid}/prompt-sets", json={"name": ""}, headers=h)
    assert bad.status_code == 422


async def test_generate_uses_project_data_and_overrides(client: AsyncClient) -> None:
    h, _, pid = await _setup(client)
    await client.post(
        f"/api/v1/projects/{pid}/competitors",
        json={"name": "FreshBooks", "website_url": "https://freshbooks.example"},
        headers=h,
    )
    ps = await _set(client, h, pid)
    resp = await client.post(
        f"/api/v1/prompt-sets/{ps['id']}/generate",
        json={
            "profile": {"industry": "Accounting software", "target_audience": ["freelancers"]},
            "max_prompts": 30,
        },
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["generated"] == 30 == len(body["items"])
    assert body["profile"]["company_name"] == "Ledgerly"  # from the project
    assert body["profile"]["website"] == "https://ledgerly.example"
    assert body["profile"]["competitors"] == ["FreshBooks"]  # from the competitors table
    texts = [i["prompt"] for i in body["items"]]
    assert any("FreshBooks" in t for t in texts) and any("freelancers" in t for t in texts)
    row = body["items"][0]
    assert set(row) >= {
        "prompt",
        "category",
        "intent",
        "funnel_stage",
        "priority",
        "status",
        "last_run",
        "visibility_result",
        "quality_score",
    }
    assert (
        row["status"] == "active" and row["last_run"] is None and row["visibility_result"] is None
    )
    assert row["source"] == "generated" and 0 <= row["quality_score"] <= 100
    listed = (await client.get(f"/api/v1/projects/{pid}/prompt-sets", headers=h)).json()
    assert listed["items"][0]["prompt_count"] == 30 and listed["items"][0]["last_generated_at"]


async def test_generate_twice_adds_only_new_prompts(client: AsyncClient) -> None:
    h, _, pid = await _setup(client)
    ps = await _set(client, h, pid)
    first = (
        await client.post(
            f"/api/v1/prompt-sets/{ps['id']}/generate",
            json={"profile": PROFILE, "max_prompts": 20},
            headers=h,
        )
    ).json()
    second = (
        await client.post(
            f"/api/v1/prompt-sets/{ps['id']}/generate",
            json={"profile": PROFILE, "max_prompts": 20},
            headers=h,
        )
    ).json()
    first_texts = {i["prompt"] for i in first["items"]}
    assert first_texts.isdisjoint({i["prompt"] for i in second["items"]})
    all_rows = (
        await client.get(
            f"/api/v1/prompt-sets/{ps['id']}/prompts", params={"limit": 500}, headers=h
        )
    ).json()
    assert all_rows["total"] == len({i["prompt"].lower() for i in all_rows["items"]})


async def test_list_prompts_filters_ordering_and_run_info(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, _, pid = await _setup(client)
    ps = await _set(client, h, pid)
    await client.post(
        f"/api/v1/prompt-sets/{ps['id']}/generate",
        json={"profile": PROFILE, "max_prompts": 25},
        headers=h,
    )
    pricing = (
        await client.get(
            f"/api/v1/prompt-sets/{ps['id']}/prompts", params={"category": "pricing"}, headers=h
        )
    ).json()
    assert pricing["total"] > 0 and all(i["category"] == "pricing" for i in pricing["items"])
    decision = (
        await client.get(
            f"/api/v1/prompt-sets/{ps['id']}/prompts",
            params={"funnel_stage": "decision"},
            headers=h,
        )
    ).json()
    assert all(i["funnel_stage"] == "decision" for i in decision["items"])
    rows = (await client.get(f"/api/v1/prompt-sets/{ps['id']}/prompts", headers=h)).json()["items"]
    priorities = [r["priority"] for r in rows]
    assert priorities == sorted(priorities)

    # a completed run with a visibility result surfaces on the row
    prompt_id = uuid.UUID(rows[0]["id"])
    now = datetime.now(UTC)
    db_session.add(
        PromptRun(
            prompt_id=prompt_id,
            project_id=uuid.UUID(pid),
            status=PromptRunStatus.COMPLETED,
            provider_key="openai",
            model_key="gpt-4o-mini",
            visibility={"brand_mentioned": True, "position": 2},
            started_at=now,
            completed_at=now,
        )
    )
    db_session.add(
        PromptRun(
            prompt_id=prompt_id,
            project_id=uuid.UUID(pid),
            status=PromptRunStatus.QUEUED,
            provider_key="google",
            model_key="gemini-2.0-flash",
            created_at=now + timedelta(seconds=5),
        )
    )
    await db_session.flush()
    rows = (await client.get(f"/api/v1/prompt-sets/{ps['id']}/prompts", headers=h)).json()["items"]
    row = next(r for r in rows if r["id"] == str(prompt_id))
    assert row["last_run"]["status"] == "queued" and row["last_run"]["provider_key"] == "google"
    assert row["visibility_result"] == {"brand_mentioned": True, "position": 2}


async def test_manual_prompt_crud_with_inference_and_dedup(client: AsyncClient) -> None:
    h, _, pid = await _setup(client)
    ps = await _set(client, h, pid)
    resp = await client.post(
        f"/api/v1/prompt-sets/{ps['id']}/prompts",
        json={"text": "How much does Ledgerly cost per month?"},
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    p = resp.json()
    assert (
        p["category"] == "pricing"
        and p["intent"] == "transactional"
        and p["funnel_stage"] == "decision"
    )
    assert (
        p["source"] == "manual" and p["priority"] == 3 and p["quality_score"] is None
    )  # no profile yet
    # exact duplicate (different casing/punctuation) and near duplicate are rejected
    dup = await client.post(
        f"/api/v1/prompt-sets/{ps['id']}/prompts",
        json={"text": "how much does ledgerly cost per month"},
        headers=h,
    )
    assert dup.status_code == 409
    near = await client.post(
        f"/api/v1/prompt-sets/{ps['id']}/prompts",
        json={"text": "How much does Ledgerly cost each month?"},
        headers=h,
    )
    assert near.status_code == 409 and "Similar to" in near.text
    # explicit category override is respected
    other = (
        await client.post(
            f"/api/v1/prompt-sets/{ps['id']}/prompts",
            json={
                "text": "Ledgerly vs Xero for freelancers?",
                "category": "recommendation",
                "priority": 1,
            },
            headers=h,
        )
    ).json()
    assert other["category"] == "recommendation" and other["priority"] == 1

    # PATCH text re-classifies; PATCH flags only
    upd = await client.patch(
        f"/api/v1/prompts/{p['id']}",
        json={"text": "What are the best alternatives to Ledgerly?"},
        headers=h,
    )
    assert upd.status_code == 200 and upd.json()["category"] == "alternative"
    upd = await client.patch(
        f"/api/v1/prompts/{p['id']}", json={"is_active": False, "priority": 5}, headers=h
    )
    assert (
        upd.json()["status"] == "inactive"
        and upd.json()["priority"] == 5
        and upd.json()["category"] == "alternative"
    )
    clash = await client.patch(
        f"/api/v1/prompts/{p['id']}", json={"text": "Ledgerly vs Xero for freelancers"}, headers=h
    )
    assert clash.status_code == 409
    inactive = (
        await client.get(
            f"/api/v1/prompt-sets/{ps['id']}/prompts", params={"is_active": "false"}, headers=h
        )
    ).json()
    assert [i["id"] for i in inactive["items"]] == [p["id"]]

    assert (await client.delete(f"/api/v1/prompts/{p['id']}", headers=h)).status_code == 200
    assert (await client.delete(f"/api/v1/prompts/{p['id']}", headers=h)).status_code == 404
    remaining = (await client.get(f"/api/v1/prompt-sets/{ps['id']}/prompts", headers=h)).json()
    assert remaining["total"] == 1


async def test_manual_prompt_scored_after_generation(client: AsyncClient) -> None:
    h, _, pid = await _setup(client)
    ps = await _set(client, h, pid)
    await client.post(
        f"/api/v1/prompt-sets/{ps['id']}/generate",
        json={"profile": PROFILE, "max_prompts": 5},
        headers=h,
    )
    p = (
        await client.post(
            f"/api/v1/prompt-sets/{ps['id']}/prompts",
            json={
                "text": (
                    "Is Ledgerly cheaper than QuickBooks for small businesses in the "
                    "United Kingdom?"
                )
            },
            headers=h,
        )
    ).json()
    assert p["quality_score"] is not None and p["quality_score"] > 70 and p["priority"] <= 2
    assert p["quality_breakdown"]["components"]["geographic_relevance"] == 1.0


async def test_archived_set_rejects_generation_and_adds(client: AsyncClient) -> None:
    h, _, pid = await _setup(client)
    ps = await _set(client, h, pid, status="archived")
    assert (
        await client.post(
            f"/api/v1/prompt-sets/{ps['id']}/generate", json={"profile": PROFILE}, headers=h
        )
    ).status_code == 409
    assert (
        await client.post(
            f"/api/v1/prompt-sets/{ps['id']}/prompts",
            json={"text": "Anything goes here?"},
            headers=h,
        )
    ).status_code == 409


async def test_authorization_and_invalid_project_access(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, org, pid = await _setup(client)
    ps = await _set(client, h, pid)
    gen = (
        await client.post(
            f"/api/v1/prompt-sets/{ps['id']}/generate",
            json={"profile": PROFILE, "max_prompts": 3},
            headers=h,
        )
    ).json()
    prompt_id = gen["items"][0]["id"]

    stranger = auth_header((await signup(client, org="Other Org"))["access_token"])
    assert (
        await client.get(f"/api/v1/projects/{pid}/prompt-sets", headers=stranger)
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/projects/{pid}/prompt-sets", json={"name": "x"}, headers=stranger
        )
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/prompt-sets/{ps['id']}/generate", json={}, headers=stranger)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/prompt-sets/{ps['id']}/prompts", headers=stranger)
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/prompt-sets/{ps['id']}/prompts",
            json={"text": "Hijack attempt?"},
            headers=stranger,
        )
    ).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/prompts/{prompt_id}", json={"is_active": False}, headers=stranger
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/prompts/{prompt_id}", headers=stranger)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/prompt-sets/{uuid.uuid4()}/prompts", headers=h)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/projects/{uuid.uuid4()}/prompt-sets", headers=h)
    ).status_code == 404
    assert (await client.get(f"/api/v1/projects/{pid}/prompt-sets")).status_code == 401
    # the stranger's own project cannot receive this tenant's prompt set id either
    own_pid = (
        await create_project(client, stranger, name="Theirs", website_url="https://theirs.example")
    )["id"]
    assert (await client.get(f"/api/v1/projects/{own_pid}/prompt-sets", headers=stranger)).json()[
        "total"
    ] == 0
    # nothing changed
    row = await db_session.get(Prompt, uuid.UUID(prompt_id))
    assert row is not None and row.is_active

    viewer = await add_member(
        db_session, org, f"viewer-{uuid.uuid4().hex[:6]}@example.com", MembershipRole.VIEWER
    )
    v = auth_header(create_access_token(viewer))
    assert (await client.get(f"/api/v1/projects/{pid}/prompt-sets", headers=v)).status_code == 200
    assert (
        await client.get(f"/api/v1/prompt-sets/{ps['id']}/prompts", headers=v)
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/projects/{pid}/prompt-sets", json={"name": "x"}, headers=v)
    ).status_code == 403
    assert (
        await client.post(f"/api/v1/prompt-sets/{ps['id']}/generate", json={}, headers=v)
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/prompt-sets/{ps['id']}/prompts",
            json={"text": "Viewer adds a prompt?"},
            headers=v,
        )
    ).status_code == 403
    assert (
        await client.patch(f"/api/v1/prompts/{prompt_id}", json={"is_active": False}, headers=v)
    ).status_code == 403
    assert (await client.delete(f"/api/v1/prompts/{prompt_id}", headers=v)).status_code == 403
    member = await add_member(
        db_session, org, f"member-{uuid.uuid4().hex[:6]}@example.com", MembershipRole.MEMBER
    )
    m = auth_header(create_access_token(member))
    assert (
        await client.patch(f"/api/v1/prompts/{prompt_id}", json={"is_active": False}, headers=m)
    ).status_code == 200
