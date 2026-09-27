"""Operator webhook: fires when configured, silent and safe when not."""

import httpx
import pytest

from app.core.config import Settings
from app.monitoring import ops


async def test_notify_ops_posts_event(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(
        ops,
        "get_settings",
        lambda: Settings(ops_webhook_url="https://ops.example/hook", _env_file=None),
    )
    real_client = httpx.AsyncClient

    def fake_client(**kwargs: object) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ops.httpx, "AsyncClient", fake_client)

    ok = await ops.notify_ops("stale_jobs_reaped", {"total": 3, "crawls": 1})
    assert ok is True
    assert seen["url"] == "https://ops.example/hook"
    assert seen["body"] == {"event": "stale_jobs_reaped", "total": 3, "crawls": 1}


async def test_notify_ops_noop_without_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ops, "get_settings", lambda: Settings(_env_file=None))
    assert await ops.notify_ops("anything", {}) is False


async def test_notify_ops_fails_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ops,
        "get_settings",
        lambda: Settings(ops_webhook_url="https://ops.example/hook", _env_file=None),
    )

    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        ops.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(boom)),
    )
    assert await ops.notify_ops("stale_jobs_reaped", {"total": 1}) is False
