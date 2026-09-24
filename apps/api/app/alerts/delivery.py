"""Webhook delivery for competitive alerts.

Runs ONLY inside worker tasks (never in HTTP request handlers). Every target
URL passes the same SSRF policy the crawler uses — public HTTP(S) endpoints
only, DNS resolved and checked, connections pinned to the validated address —
so a notification channel can never be pointed at the internal network or a
cloud metadata endpoint.

Payloads are signed with HMAC-SHA256 when the channel has a secret
(`X-ASG-Signature: sha256=<hex>` over the raw request body). Secrets and full
URLs are never logged; logs carry the channel id and target host only.
"""

import asyncio
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.crawler.safety import Resolver, UnsafeURLError, UrlSafetyPolicy
from app.crawler.urls import CrawlURL, CrawlURLError, normalize_crawl_url
from app.models.alerts import CompetitiveAlert
from app.models.notification_channels import NotificationChannelConfig

log = get_logger(__name__)

USER_AGENT = "AI-Search-Growth-OS/1.0 (+alert-notifications)"
SIGNATURE_HEADER = "X-ASG-Signature"


class WebhookConfigError(ValueError):
    """The channel's URL is unusable (bad syntax or an unsafe target)."""


def validate_webhook_url(raw: str) -> CrawlURL:
    """Syntactic + host-syntax validation used at channel create/update time.

    DNS is deliberately NOT resolved here (that happens, and is re-checked, at
    delivery time); this catches file://, credentials, localhost, metadata
    hostnames and private-address literals immediately.
    """
    try:
        url = normalize_crawl_url(raw)
    except CrawlURLError as exc:
        raise WebhookConfigError(str(exc)) from exc
    try:
        UrlSafetyPolicy().check_host_syntax(url.host)
    except UnsafeURLError as exc:
        raise WebhookConfigError(str(exc)) from exc
    return url


def alert_payload(alert: CompetitiveAlert) -> dict[str, object]:
    return {
        "event": "competitive_alert",
        "alert": {
            "id": str(alert.id),
            "project_id": str(alert.project_id),
            "alert_type": alert.alert_type,
            "title": alert.title,
            "description": alert.description,
            "severity": alert.severity,
            "status": alert.status,
            "evidence": alert.evidence,
            "detected_at": alert.detected_at.isoformat() if alert.detected_at else None,
        },
    }


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@dataclass
class DeliveryResult:
    ok: bool
    detail: str  # short status for the channel row; never contains the secret


class WebhookChannel:
    """Sends one alert to one configured webhook. Never raises on failure."""

    key = "webhook"

    def __init__(
        self,
        channel: NotificationChannelConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        self._channel = channel
        self._transport = transport
        self._safety = UrlSafetyPolicy(resolver)
        self._settings = get_settings()

    async def deliver(self, alert: CompetitiveAlert) -> DeliveryResult:
        raw_url = str(self._channel.config.get("url", ""))
        try:
            url = normalize_crawl_url(raw_url)
            verdict = await self._safety.check(url)
        except (CrawlURLError, UnsafeURLError) as exc:
            log.warning(
                "alert_webhook_blocked",
                channel_id=str(self._channel.id),
                host=raw_url.split("/")[2] if "://" in raw_url else "?",
                error=str(exc),
            )
            return DeliveryResult(ok=False, detail=f"blocked: {exc}")

        body = json.dumps(alert_payload(alert), separators=(",", ":")).encode()
        headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
        if self._channel.secret:
            headers[SIGNATURE_HEADER] = sign(self._channel.secret, body)

        # Pin the connection to the address the safety check validated (same
        # DNS-rebinding defence as the crawler's fetcher).
        target = httpx.URL(url.normalized).copy_with(host=verdict.addresses[0])
        headers["Host"] = url.host if url.port is None else f"{url.host}:{url.port}"
        extensions = {"sni_hostname": url.host} if url.scheme == "https" else {}

        timeout = self._settings.notification_webhook_timeout_seconds
        retries = self._settings.notification_webhook_max_retries
        last_detail = "unknown error"
        async with httpx.AsyncClient(
            transport=self._transport, timeout=timeout, trust_env=False
        ) as client:
            for attempt in range(retries + 1):
                try:
                    response = await client.post(
                        target, content=body, headers=headers, extensions=extensions
                    )
                except httpx.HTTPError as exc:
                    last_detail = f"connection error: {type(exc).__name__}"
                else:
                    if response.status_code < 300:
                        log.info(
                            "alert_webhook_delivered",
                            channel_id=str(self._channel.id),
                            host=url.host,
                            status=response.status_code,
                        )
                        return DeliveryResult(ok=True, detail=f"http {response.status_code}")
                    last_detail = f"http {response.status_code}"
                    if response.status_code < 500 and response.status_code != 429:
                        break  # 4xx (other than 429) will not improve on retry
                if attempt < retries:
                    await asyncio.sleep(
                        self._settings.notification_webhook_retry_backoff_seconds * (2**attempt)
                    )
        log.warning(
            "alert_webhook_failed",
            channel_id=str(self._channel.id),
            host=url.host,
            error=last_detail,
        )
        return DeliveryResult(ok=False, detail=last_detail)


# -- orchestration (called from worker tasks only) -----------------------------------


async def _record(channel: NotificationChannelConfig, results: list[DeliveryResult]) -> None:
    from datetime import UTC, datetime

    from app.models.notification_channels import DeliveryStatus

    if not results:
        return
    ok = all(r.ok for r in results)
    channel.last_delivery_at = datetime.now(UTC)
    channel.last_delivery_status = DeliveryStatus.DELIVERED if ok else DeliveryStatus.FAILED
    channel.last_delivery_error = None if ok else next(r.detail for r in results if not r.ok)[:2000]


async def deliver_alerts(
    session: "AsyncSession",
    project_id: "uuid.UUID",
    alert_ids: list["uuid.UUID"],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    resolver: Resolver | None = None,
) -> dict[str, int]:
    """Send the given alerts through every enabled channel of the project.

    Channel failures never raise and never block other channels; each
    channel's last-delivery fields record the outcome.
    """
    from sqlalchemy import select

    from app.models.notification_channels import NotificationChannelConfig as Chan

    channels = list(
        (
            await session.scalars(
                select(Chan).where(Chan.project_id == project_id, Chan.enabled.is_(True))
            )
        ).all()
    )
    if not channels:
        return {"channels": 0, "delivered": 0, "failed": 0}
    alerts = list(
        (
            await session.scalars(
                select(CompetitiveAlert).where(
                    CompetitiveAlert.project_id == project_id,
                    CompetitiveAlert.id.in_(alert_ids),
                )
            )
        ).all()
    )
    delivered = failed = 0
    for channel in channels:
        sender = WebhookChannel(channel, transport=transport, resolver=resolver)
        results = [await sender.deliver(alert) for alert in alerts]
        delivered += sum(1 for r in results if r.ok)
        failed += sum(1 for r in results if not r.ok)
        await _record(channel, results)
    await session.commit()
    return {"channels": len(channels), "delivered": delivered, "failed": failed}


def _test_alert(project_id: "uuid.UUID") -> CompetitiveAlert:
    """A synthetic, never-persisted alert used by the channel test endpoint."""
    import uuid as _uuid
    from datetime import UTC, datetime

    return CompetitiveAlert(
        id=_uuid.uuid4(),
        project_id=project_id,
        alert_type="test",
        title="Test notification",
        description="This is a test delivery from AI Search Growth OS.",
        evidence={"test": True},
        severity="low",
        status="new",
        detected_at=datetime.now(UTC),
        analysis_version="notification-test/v1",
    )


async def deliver_test(
    session: "AsyncSession",
    channel_id: "uuid.UUID",
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    resolver: Resolver | None = None,
) -> DeliveryResult | None:
    from app.models.notification_channels import NotificationChannelConfig as Chan

    channel = await session.get(Chan, channel_id)
    if channel is None:
        return None
    sender = WebhookChannel(channel, transport=transport, resolver=resolver)
    result = await sender.deliver(_test_alert(channel.project_id))
    await _record(channel, [result])
    await session.commit()
    return result
