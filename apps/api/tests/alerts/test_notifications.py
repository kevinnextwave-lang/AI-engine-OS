"""Alert notification channels: CRUD + authz, webhook delivery (fake transport,
fake resolver — no live network anywhere), HMAC signing, SSRF blocking, secret
hygiene, and scheduled monitoring project selection."""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.delivery import (
    SIGNATURE_HEADER,
    WebhookChannel,
    WebhookConfigError,
    deliver_alerts,
    deliver_test,
    validate_webhook_url,
)
from app.core.security import create_access_token
from app.models.alerts import CompetitiveAlert
from app.models.membership import MembershipRole
from app.models.notification_channels import DeliveryStatus, NotificationChannelConfig
from app.monitoring.scheduler import active_project_ids
from tests.conftest import auth_header
from tests.test_authz import add_member, signup
from tests.visibility.seed import NOW, Seeder, project_with_competitors

PUBLIC_IP = "93.184.216.34"


async def resolve_public(host: str) -> list[str]:
    return [PUBLIC_IP]


def make_alert(project_id: uuid.UUID) -> CompetitiveAlert:
    return CompetitiveAlert(
        id=uuid.uuid4(),
        project_id=project_id,
        alert_type="visibility_drop",
        title="Brand visibility dropped",
        description="Mention share fell from 60% to 40%.",
        evidence={"previous": 60, "current": 40},
        severity="high",
        status="new",
        detected_at=datetime.now(UTC),
        analysis_version="test/v1",
        dedup_key=f"test:{uuid.uuid4()}",
    )


def channel_row(
    project_id: uuid.UUID, url: str, secret: str | None = None, **kw
) -> NotificationChannelConfig:  # type: ignore[no-untyped-def]
    return NotificationChannelConfig(
        project_id=project_id,
        name="Test hook",
        config={"url": url},
        secret=secret,
        **kw,
    )


# --- URL validation --------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "http://localhost/hook",
        "http://127.0.0.1/hook",
        "http://169.254.169.254/latest",
        "http://metadata.google.internal/",
        "http://hooks.internal/x",
        "https://user:pw@example.com/hook",
        "",
    ],
)
def test_webhook_url_validation_rejects_unsafe(url: str) -> None:
    with pytest.raises(WebhookConfigError):
        validate_webhook_url(url)


def test_webhook_url_validation_normalizes() -> None:
    assert validate_webhook_url("HTTPS://Hooks.Example.com:443/a/").normalized == (
        "https://hooks.example.com/a"
    )


# --- webhook channel -------------------------------------------------------------------


async def test_webhook_delivers_signed_payload(db_session: AsyncSession) -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    row = channel_row(uuid.uuid4(), "https://hooks.example.com/alerts", secret="s3cret-key")
    row.id = uuid.uuid4()
    channel = WebhookChannel(row, transport=httpx.MockTransport(handler), resolver=resolve_public)
    alert = make_alert(row.project_id)
    result = await channel.deliver(alert)
    assert result.ok and result.detail == "http 200"
    [request] = seen
    # pinned connection: connect target is the resolved IP, Host is the real host
    assert request.url.host == PUBLIC_IP
    assert request.headers["host"] == "hooks.example.com"
    body = json.loads(request.content)
    assert body["event"] == "competitive_alert"
    assert body["alert"]["title"] == "Brand visibility dropped"
    assert body["alert"]["evidence"] == {"previous": 60, "current": 40}
    expected = "sha256=" + hmac.new(b"s3cret-key", request.content, hashlib.sha256).hexdigest()
    assert request.headers[SIGNATURE_HEADER] == expected
    assert "s3cret-key" not in request.headers.get("authorization", "")


async def test_webhook_failure_never_raises_and_4xx_does_not_retry() -> None:
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(403)

    row = channel_row(uuid.uuid4(), "https://hooks.example.com/alerts")
    row.id = uuid.uuid4()
    channel = WebhookChannel(row, transport=httpx.MockTransport(handler), resolver=resolve_public)
    result = await channel.deliver(make_alert(row.project_id))
    assert not result.ok and result.detail == "http 403"
    assert calls["n"] == 1  # 4xx is permanent; no retries


async def test_webhook_retries_5xx() -> None:
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    row = channel_row(uuid.uuid4(), "https://hooks.example.com/alerts")
    row.id = uuid.uuid4()
    channel = WebhookChannel(row, transport=httpx.MockTransport(handler), resolver=resolve_public)
    result = await channel.deliver(make_alert(row.project_id))
    assert not result.ok and result.detail == "http 503"
    assert calls["n"] == 3  # initial + 2 retries


async def test_webhook_blocks_private_resolution_without_request() -> None:
    async def resolve_private(host: str) -> list[str]:
        return ["10.0.0.5"]

    async def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("must never be called")

    row = channel_row(uuid.uuid4(), "https://hooks.example.com/alerts")
    row.id = uuid.uuid4()
    channel = WebhookChannel(row, transport=httpx.MockTransport(handler), resolver=resolve_private)
    result = await channel.deliver(make_alert(row.project_id))
    assert not result.ok and result.detail.startswith("blocked")


# --- delivery orchestration ------------------------------------------------------------


async def _project(client: AsyncClient) -> tuple[dict, uuid.UUID]:
    headers, _, pid = await project_with_competitors(client)
    return headers, uuid.UUID(pid)


async def test_deliver_alerts_updates_channel_state(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, pid = await _project(client)
    ok_row = channel_row(pid, "https://hooks.example.com/ok")
    bad_row = channel_row(pid, "https://hooks.example.com/bad")
    off_row = channel_row(pid, "https://hooks.example.com/off", enabled=False)
    alert = make_alert(pid)
    db_session.add_all([ok_row, bad_row, off_row, alert])
    await db_session.flush()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500 if request.url.path == "/bad" else 200)

    summary = await deliver_alerts(
        db_session,
        pid,
        [alert.id],
        transport=httpx.MockTransport(handler),
        resolver=resolve_public,
    )
    assert summary == {"channels": 2, "delivered": 1, "failed": 1}
    await db_session.refresh(ok_row)
    await db_session.refresh(bad_row)
    await db_session.refresh(off_row)
    assert ok_row.last_delivery_status == DeliveryStatus.DELIVERED
    assert ok_row.last_delivery_error is None
    assert bad_row.last_delivery_status == DeliveryStatus.FAILED
    assert bad_row.last_delivery_error == "http 500"
    assert off_row.last_delivery_status is None  # disabled channels never fire


async def test_deliver_alerts_is_project_scoped(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Alerts from another project are never sent even if their ids are passed."""
    _, pid = await _project(client)
    _, other_pid = await _project(client)
    row = channel_row(pid, "https://hooks.example.com/ok")
    foreign_alert = make_alert(other_pid)
    db_session.add_all([row, foreign_alert])
    await db_session.flush()
    sent: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.url.path)
        return httpx.Response(200)

    summary = await deliver_alerts(
        db_session,
        pid,
        [foreign_alert.id],
        transport=httpx.MockTransport(handler),
        resolver=resolve_public,
    )
    assert summary["delivered"] == 0 and sent == []


async def test_deliver_test_sends_synthetic_alert(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    _, pid = await _project(client)
    row = channel_row(pid, "https://hooks.example.com/test")
    db_session.add(row)
    await db_session.flush()
    bodies: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200)

    result = await deliver_test(
        db_session, row.id, transport=httpx.MockTransport(handler), resolver=resolve_public
    )
    assert result is not None and result.ok
    [body] = bodies
    assert body["alert"]["alert_type"] == "test"
    assert body["alert"]["evidence"] == {"test": True}
    await db_session.refresh(row)
    assert row.last_delivery_status == DeliveryStatus.DELIVERED
    # the synthetic alert is never persisted
    count = (
        await db_session.scalars(select(CompetitiveAlert).where(CompetitiveAlert.project_id == pid))
    ).all()
    assert count == []


# --- API -------------------------------------------------------------------------------


async def test_channel_crud_and_secret_hygiene(client: AsyncClient) -> None:
    headers, _, pid = await project_with_competitors(client)
    created = await client.post(
        f"/api/v1/projects/{pid}/notification-channels",
        json={
            "name": "Ops hook",
            "url": "https://hooks.example.com/asg",
            "secret": "super-secret-value",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["has_secret"] is True and body["url"] == "https://hooks.example.com/asg"
    assert "secret" not in body and "super-secret-value" not in created.text
    cid = body["id"]

    listing = await client.get(f"/api/v1/projects/{pid}/notification-channels", headers=headers)
    assert listing.status_code == 200 and listing.json()["total"] == 1
    assert "super-secret-value" not in listing.text

    patched = await client.patch(
        f"/api/v1/notification-channels/{cid}",
        json={"enabled": False, "clear_secret": True},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False and patched.json()["has_secret"] is False

    deleted = await client.delete(f"/api/v1/notification-channels/{cid}", headers=headers)
    assert deleted.status_code == 204


async def test_channel_create_rejects_unsafe_urls(client: AsyncClient) -> None:
    headers, _, pid = await project_with_competitors(client)
    for url in ("http://localhost/x", "file:///etc/passwd", "http://169.254.169.254/"):
        resp = await client.post(
            f"/api/v1/projects/{pid}/notification-channels",
            json={"name": "Bad hook", "url": url},
            headers=headers,
        )
        assert resp.status_code == 422, url


async def test_channel_tenant_isolation_and_roles(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers, org_id, pid = await project_with_competitors(client)
    created = await client.post(
        f"/api/v1/projects/{pid}/notification-channels",
        json={"name": "Ops hook", "url": "https://hooks.example.com/asg"},
        headers=headers,
    )
    cid = created.json()["id"]

    # outsider: 404 on both scopes
    outsider = await signup(client, org="Other Org")
    out_headers = auth_header(outsider["access_token"])
    r = await client.get(f"/api/v1/projects/{pid}/notification-channels", headers=out_headers)
    assert r.status_code == 404
    r = await client.get(f"/api/v1/notification-channels/{cid}", headers=out_headers)
    assert r.status_code == 404

    # viewer: can list, cannot manage
    viewer_headers = auth_header(
        create_access_token(
            await add_member(
                db_session, org_id, f"v-{uuid.uuid4().hex[:6]}@x.com", MembershipRole.VIEWER
            )
        )
    )
    r = await client.get(f"/api/v1/projects/{pid}/notification-channels", headers=viewer_headers)
    assert r.status_code == 200
    r = await client.delete(f"/api/v1/notification-channels/{cid}", headers=viewer_headers)
    assert r.status_code == 403
    r = await client.post(f"/api/v1/notification-channels/{cid}/test", headers=viewer_headers)
    assert r.status_code == 403


async def test_channel_test_endpoint_queues(client: AsyncClient) -> None:
    from app.api.v1.routes.notification_channels import get_test_dispatcher

    app = client._transport.app  # type: ignore[attr-defined]
    headers, _, pid = await project_with_competitors(client)
    created = await client.post(
        f"/api/v1/projects/{pid}/notification-channels",
        json={"name": "Ops hook", "url": "https://hooks.example.com/asg"},
        headers=headers,
    )
    cid = created.json()["id"]
    queued: list[str] = []
    app.dependency_overrides[get_test_dispatcher] = lambda: (
        lambda channel_id: queued.append(str(channel_id))
    )
    try:
        resp = await client.post(f"/api/v1/notification-channels/{cid}/test", headers=headers)
    finally:
        app.dependency_overrides.pop(get_test_dispatcher, None)
    assert resp.status_code == 202 and queued == [cid]


async def test_detect_enqueues_delivery_for_new_alerts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.api.v1.routes.alerts import get_delivery_dispatcher

    app = client._transport.app  # type: ignore[attr-defined]
    headers, _, pid = await project_with_competitors(client)
    s = Seeder(db_session, uuid.UUID(pid))
    # previous period: brand strong; current period: brand gone -> visibility_drop
    for i in range(12):
        await s.observation(prompt=f"p{i}", days_ago=40 + i, mentioned=True, position=1)
    for i in range(12):
        await s.observation(prompt=f"p{i}", days_ago=1 + i, mentioned=False)
    await db_session.commit()

    dispatched: list[tuple[str, int]] = []
    app.dependency_overrides[get_delivery_dispatcher] = lambda: (
        lambda project_id, alert_ids: dispatched.append((str(project_id), len(alert_ids)))
    )
    try:
        resp = await client.post(
            f"/api/v1/projects/{pid}/competitive-alerts/detect",
            json={"window_days": 30},
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_delivery_dispatcher, None)
    assert resp.status_code == 200, resp.text
    assert resp.json()["alerts_created"] >= 1
    assert "created_alert_ids" not in resp.json()
    assert dispatched and dispatched[0][0] == pid and dispatched[0][1] >= 1

    # re-detection updates, creates nothing new, dispatches nothing
    dispatched.clear()
    app.dependency_overrides[get_delivery_dispatcher] = lambda: (
        lambda project_id, alert_ids: dispatched.append((str(project_id), len(alert_ids)))
    )
    try:
        resp = await client.post(
            f"/api/v1/projects/{pid}/competitive-alerts/detect",
            json={"window_days": 30},
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_delivery_dispatcher, None)
    assert resp.status_code == 200 and resp.json()["alerts_created"] == 0
    assert dispatched == []


# --- scheduled monitoring --------------------------------------------------------------


async def test_active_project_selection(client: AsyncClient, db_session: AsyncSession) -> None:
    _, active_pid = await _project(client)
    _, stale_pid = await _project(client)
    active = Seeder(db_session, active_pid)
    stale = Seeder(db_session, stale_pid)
    await active.observation(prompt="fresh", days_ago=0, mentioned=True)
    await stale.observation(prompt="old", days_ago=30, mentioned=True)
    await db_session.flush()
    since = NOW - timedelta(days=2)
    ids = await active_project_ids(db_session, since)
    assert active_pid in ids and stale_pid not in ids
