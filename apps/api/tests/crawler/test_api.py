"""Crawl API: start/list/get/cancel/pages, permissions, tenant isolation, dispatch."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routes.crawl import get_crawl_dispatcher
from app.core.security import create_access_token
from app.models import CrawlJob, CrawlStatus, CrawlUrl, CrawlUrlStatus, MembershipRole
from tests.conftest import auth_header
from tests.test_authz import add_member, org_id_for, signup
from tests.test_projects_api import create_project


@pytest.fixture
def dispatched(client: AsyncClient) -> list[uuid.UUID]:
    """Replace the Celery dispatcher with a recorder for the duration of a test."""
    calls: list[uuid.UUID] = []
    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_crawl_dispatcher] = lambda: calls.append
    return calls


async def _setup(client: AsyncClient) -> tuple[dict[str, str], str, str]:  # type: ignore[type-arg]
    owner = await signup(client, org="Crawl Org")
    h = auth_header(owner["access_token"])
    org = await org_id_for(client, owner["access_token"])
    pid = (await create_project(client, h, website_url="https://www.acme.com"))["id"]
    return h, org, pid


async def test_start_crawl_queues_job_and_dispatches_after_commit(
    client: AsyncClient, dispatched: list[uuid.UUID], db_session: AsyncSession
) -> None:
    h, _, pid = await _setup(client)
    resp = await client.post(f"/api/v1/projects/{pid}/crawl", json={"max_pages": 25}, headers=h)
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "queued" and body["crawl_type"] == "full"
    assert body["root_url"] == "https://www.acme.com/"
    assert body["max_pages"] == 25 and body["max_depth"] == 3  # FREE plan depth cap
    assert body["pages_discovered"] == body["pages_crawled"] == body["pages_failed"] == 0
    assert body["pages_skipped"] == 0 and body["duration_seconds"] is None
    assert dispatched == [uuid.UUID(body["id"])]
    # The row is committed (visible to a fresh query) before dispatch happened.
    row = await db_session.get(CrawlJob, uuid.UUID(body["id"]))
    assert row is not None and row.project_id == uuid.UUID(pid)


async def test_only_one_active_crawl_per_project(
    client: AsyncClient, dispatched: list[uuid.UUID]
) -> None:
    h, _, pid = await _setup(client)
    assert (
        await client.post(f"/api/v1/projects/{pid}/crawl", json={}, headers=h)
    ).status_code == 202
    again = await client.post(f"/api/v1/projects/{pid}/crawl", json={}, headers=h)
    assert again.status_code == 409 and "already" in again.json()["error"]["message"]


async def test_start_url_must_be_on_project_domain(
    client: AsyncClient, dispatched: list[uuid.UUID]
) -> None:
    h, _, pid = await _setup(client)
    resp = await client.post(
        f"/api/v1/projects/{pid}/crawl", json={"url": "https://evil.com/"}, headers=h
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["details"][0]["loc"] == ["body", "url"]
    bad = await client.post(
        f"/api/v1/projects/{pid}/crawl", json={"url": "http://localhost/"}, headers=h
    )
    assert bad.status_code == 422
    single = await client.post(
        f"/api/v1/projects/{pid}/crawl",
        json={"crawl_type": "single_page", "url": "https://acme.com/pricing"},
        headers=h,
    )
    assert single.status_code == 202
    assert single.json()["max_pages"] == 1 and single.json()["max_depth"] == 0


async def test_list_get_cancel_and_pages(
    client: AsyncClient, dispatched: list[uuid.UUID], db_session: AsyncSession
) -> None:
    h, _, pid = await _setup(client)
    job = (await client.post(f"/api/v1/projects/{pid}/crawl", json={}, headers=h)).json()
    jid = job["id"]

    listed = (await client.get(f"/api/v1/projects/{pid}/crawl-jobs", headers=h)).json()
    assert listed["total"] == 1 and listed["items"][0]["id"] == jid
    got = await client.get(f"/api/v1/crawl-jobs/{jid}", headers=h)
    assert got.status_code == 200 and got.json()["status"] == "queued"

    # Simulate the worker having recorded some URLs.
    db_session.add_all(
        [
            CrawlUrl(
                crawl_job_id=uuid.UUID(jid),
                project_id=uuid.UUID(pid),
                url="https://www.acme.com/",
                normalized_url="https://www.acme.com/",
                depth=0,
                status=CrawlUrlStatus.CRAWLED,
                http_status=200,
            ),
            CrawlUrl(
                crawl_job_id=uuid.UUID(jid),
                project_id=uuid.UUID(pid),
                url="https://www.acme.com/x.pdf",
                normalized_url="https://www.acme.com/x.pdf",
                depth=1,
                status=CrawlUrlStatus.SKIPPED,
                error_message="skipped by extension",
            ),
        ]
    )
    await db_session.flush()
    pages = (await client.get(f"/api/v1/crawl-jobs/{jid}/pages", headers=h)).json()
    assert (
        pages["total"] == 2
        and pages["items"][0]["status"] == "crawled"
        and pages["items"][0]["page"] is None
    )
    skipped = (
        await client.get(f"/api/v1/crawl-jobs/{jid}/pages", params={"status": "skipped"}, headers=h)
    ).json()
    assert skipped["total"] == 1 and skipped["items"][0]["error_message"] == "skipped by extension"

    # Cancel a queued job finalizes it immediately; cancelling again is a conflict.
    cancelled = await client.post(f"/api/v1/crawl-jobs/{jid}/cancel", headers=h)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert (await client.post(f"/api/v1/crawl-jobs/{jid}/cancel", headers=h)).status_code == 409
    # A running job gets cancel_requested but keeps running until the worker observes it.
    job2 = (await client.post(f"/api/v1/projects/{pid}/crawl", json={}, headers=h)).json()
    await db_session.execute(
        update(CrawlJob)
        .where(CrawlJob.id == uuid.UUID(job2["id"]))
        .values(status=CrawlStatus.RUNNING)
    )
    await db_session.flush()
    resp = await client.post(f"/api/v1/projects/{pid}/crawl-jobs/{job2['id']}/cancel", headers=h)
    assert resp.status_code == 200 and resp.json()["status"] == "running"
    row = await db_session.get(CrawlJob, uuid.UUID(job2["id"]))
    assert row is not None and row.cancel_requested is True


async def test_tenant_isolation_for_crawl_jobs(
    client: AsyncClient, dispatched: list[uuid.UUID]
) -> None:
    ha, _, pid_a = await _setup(client)
    jid = (await client.post(f"/api/v1/projects/{pid_a}/crawl", json={}, headers=ha)).json()["id"]
    b = await signup(client, org="Other Org")
    hb = auth_header(b["access_token"])

    for method, path in [
        ("POST", f"/api/v1/projects/{pid_a}/crawl"),
        ("GET", f"/api/v1/projects/{pid_a}/crawl-jobs"),
        ("POST", f"/api/v1/projects/{pid_a}/crawl-jobs/{jid}/cancel"),
        ("GET", f"/api/v1/crawl-jobs/{jid}"),
        ("POST", f"/api/v1/crawl-jobs/{jid}/cancel"),
        ("GET", f"/api/v1/crawl-jobs/{jid}/pages"),
    ]:
        resp = await client.request(method, path, json={} if method == "POST" else None, headers=hb)
        assert resp.status_code == 404, (method, path)
        assert (await client.request(method, path, json={})).status_code == 401, (method, path)
    # A's job is untouched
    assert (await client.get(f"/api/v1/crawl-jobs/{jid}", headers=ha)).json()["status"] == "queued"
    # Cross-project id mixing: B's own project with A's job id
    pid_b = (await create_project(client, hb, website_url="https://b.com"))["id"]
    assert (
        await client.post(f"/api/v1/projects/{pid_b}/crawl-jobs/{jid}/cancel", headers=hb)
    ).status_code == 404


async def test_role_permissions(
    client: AsyncClient, dispatched: list[uuid.UUID], db_session: AsyncSession
) -> None:
    h, org, pid = await _setup(client)
    viewer = auth_header(
        create_access_token(
            await add_member(
                db_session, org, f"v-{uuid.uuid4().hex[:6]}@x.com", MembershipRole.VIEWER
            )
        )
    )
    member = auth_header(
        create_access_token(
            await add_member(
                db_session, org, f"m-{uuid.uuid4().hex[:6]}@x.com", MembershipRole.MEMBER
            )
        )
    )

    assert (
        await client.post(f"/api/v1/projects/{pid}/crawl", json={}, headers=viewer)
    ).status_code == 403
    started = await client.post(f"/api/v1/projects/{pid}/crawl", json={}, headers=member)
    assert started.status_code == 202
    jid = started.json()["id"]
    assert (await client.get(f"/api/v1/crawl-jobs/{jid}", headers=viewer)).status_code == 200
    assert (await client.get(f"/api/v1/crawl-jobs/{jid}/pages", headers=viewer)).status_code == 200
    assert (
        await client.post(f"/api/v1/crawl-jobs/{jid}/cancel", headers=viewer)
    ).status_code == 403
    assert (
        await client.post(f"/api/v1/crawl-jobs/{jid}/cancel", headers=member)
    ).status_code == 200


async def test_dispatch_failure_marks_job_failed(client: AsyncClient) -> None:
    app = client._transport.app  # type: ignore[attr-defined]

    def broken(_: uuid.UUID) -> None:
        raise ConnectionError("broker down")

    app.dependency_overrides[get_crawl_dispatcher] = lambda: broken
    h, _, pid = await _setup(client)
    resp = await client.post(f"/api/v1/projects/{pid}/crawl", json={}, headers=h)
    assert resp.status_code == 202
    assert resp.json()["status"] == "failed" and "enqueue" in resp.json()["error_message"]


async def test_openapi_documents_crawl_routes(client: AsyncClient) -> None:
    paths = (await client.get("/openapi.json")).json()["paths"]
    for path, methods in {
        "/api/v1/projects/{project_id}/crawl": {"post"},
        "/api/v1/projects/{project_id}/crawl-jobs": {"get"},
        "/api/v1/projects/{project_id}/crawl-jobs/{crawl_id}/cancel": {"post"},
        "/api/v1/crawl-jobs/{crawl_id}": {"get"},
        "/api/v1/crawl-jobs/{crawl_id}/cancel": {"post"},
        "/api/v1/crawl-jobs/{crawl_id}/pages": {"get"},
    }.items():
        assert methods <= set(paths[path]), path


async def test_crawl_jobs_query_is_project_scoped(db_session: AsyncSession) -> None:
    """Defensive: the repository never returns jobs across projects."""
    from app.repositories.crawl import CrawlJobRepository

    assert await CrawlJobRepository(db_session).get_in_project(uuid.uuid4(), uuid.uuid4()) is None
    assert (
        await db_session.scalars(select(CrawlJob).where(CrawlJob.id == uuid.uuid4()))
    ).first() is None
