"""Controlled HTTP client for the crawler.

- connect / read / total timeouts
- hard cap on response size (streamed; aborted once exceeded)
- redirects followed manually so every hop is re-validated by the SSRF policy
- bounded retries with exponential backoff for transient failures
- identifiable user agent, gzip/deflate/brotli accepted
- no cookies are persisted; no Authorization is ever sent
"""

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin

import httpx

from app.core.logging import get_logger
from app.crawler.safety import UnsafeURLError, UrlSafetyPolicy
from app.crawler.urls import CrawlURL, CrawlURLError, normalize_crawl_url

log = get_logger("crawler.fetcher")

HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")
_RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class FetchConfig:
    user_agent: str
    connect_timeout: float = 5.0
    read_timeout: float = 15.0
    total_timeout: float = 30.0
    max_response_bytes: int = 5 * 1024 * 1024
    max_redirects: int = 5
    max_retries: int = 2
    retry_backoff: float = 0.5


@dataclass
class FetchResult:
    requested_url: str
    final_url: str
    status_code: int | None
    content_type: str | None
    body: bytes | None
    redirect_chain: list[str] = field(default_factory=list)
    error: str | None = None
    skipped_reason: str | None = None
    attempts: int = 1

    @property
    def ok(self) -> bool:
        return self.error is None and self.status_code is not None and self.status_code < 400

    @property
    def mime_type(self) -> str | None:
        if not self.content_type:
            return None
        return self.content_type.split(";")[0].strip().lower() or None

    @property
    def is_html(self) -> bool:
        return self.mime_type in HTML_CONTENT_TYPES


class FetchError(Exception):
    pass


class Fetcher:
    def __init__(
        self,
        config: FetchConfig,
        safety: UrlSafetyPolicy,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._config = config
        self._safety = safety
        self._sleep = sleep
        self._client = httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            timeout=httpx.Timeout(
                connect=config.connect_timeout,
                read=config.read_timeout,
                write=config.read_timeout,
                pool=config.connect_timeout,
            ),
            headers={
                "User-Agent": config.user_agent,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept-Language": "en;q=0.9,*;q=0.5",
            },
            cookies=None,
            trust_env=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch(self, url: CrawlURL, *, allow_non_html: bool = False) -> FetchResult:
        """Fetch with redirects, retries and size limits. Never raises for HTTP errors."""
        try:
            return await asyncio.wait_for(
                self._fetch_with_redirects(url, allow_non_html), timeout=self._config.total_timeout
            )
        except TimeoutError:
            return FetchResult(
                requested_url=url.normalized,
                final_url=url.normalized,
                status_code=None,
                content_type=None,
                body=None,
                error="total timeout exceeded",
            )

    async def _fetch_with_redirects(self, start: CrawlURL, allow_non_html: bool) -> FetchResult:
        current = start
        chain: list[str] = []
        attempts_total = 0
        for _hop in range(self._config.max_redirects + 1):
            try:
                await self._safety.check(current)
            except UnsafeURLError as exc:
                return FetchResult(
                    requested_url=start.normalized,
                    final_url=current.normalized,
                    status_code=None,
                    content_type=None,
                    body=None,
                    redirect_chain=chain,
                    error=f"blocked: {exc}",
                )
            response, error, attempts = await self._request_with_retries(current.normalized)
            attempts_total += attempts
            if response is None:
                return FetchResult(
                    requested_url=start.normalized,
                    final_url=current.normalized,
                    status_code=None,
                    content_type=None,
                    body=None,
                    redirect_chain=chain,
                    error=error,
                    attempts=attempts_total,
                )
            if response.is_redirect:
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    return self._result(
                        start, current, response, None, chain, "redirect without location"
                    )
                try:
                    nxt = normalize_crawl_url(urljoin(current.normalized, location))
                except CrawlURLError as exc:
                    return self._result(
                        start, current, response, None, chain, f"bad redirect: {exc}"
                    )
                chain.append(nxt.normalized)
                current = nxt
                continue
            content_type = response.headers.get("content-type", "")
            mime = content_type.split(";")[0].strip().lower()
            if not allow_non_html and mime not in HTML_CONTENT_TYPES:
                await response.aclose()
                result = self._result(start, current, response, None, chain, None)
                result.skipped_reason = f"unsupported content type: {mime or 'unknown'}"
                result.attempts = attempts_total
                return result
            body, size_error = await self._read_limited(response)
            result = self._result(start, current, response, body, chain, size_error)
            result.attempts = attempts_total
            return result
        return FetchResult(
            requested_url=start.normalized,
            final_url=current.normalized,
            status_code=None,
            content_type=None,
            body=None,
            redirect_chain=chain,
            error="too many redirects",
            attempts=attempts_total,
        )

    @staticmethod
    def _result(
        start: CrawlURL,
        current: CrawlURL,
        response: httpx.Response,
        body: bytes | None,
        chain: list[str],
        error: str | None,
    ) -> FetchResult:
        return FetchResult(
            requested_url=start.normalized,
            final_url=current.normalized,
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            body=body,
            redirect_chain=chain,
            error=error,
        )

    async def _request_with_retries(
        self, url: str
    ) -> tuple[httpx.Response | None, str | None, int]:
        last_error = "unknown error"
        for attempt in range(self._config.max_retries + 1):
            try:
                request = self._client.build_request("GET", url)
                response = await self._client.send(request, stream=True)
            except httpx.TimeoutException:
                last_error = "timeout"
            except httpx.TransportError as exc:
                last_error = f"connection error: {type(exc).__name__}"
            except httpx.HTTPError as exc:
                return None, f"http error: {type(exc).__name__}", attempt + 1
            else:
                if response.status_code in _RETRY_STATUSES and attempt < self._config.max_retries:
                    await response.aclose()
                    last_error = f"http {response.status_code}"
                else:
                    return response, None, attempt + 1
            if attempt < self._config.max_retries:
                delay = self._config.retry_backoff * (2**attempt) * (1 + random.random() * 0.25)  # noqa: S311
                await self._sleep(delay)
        return None, last_error, self._config.max_retries + 1

    async def _read_limited(self, response: httpx.Response) -> tuple[bytes | None, str | None]:
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self._config.max_response_bytes:
            await response.aclose()
            return None, "response too large"
        chunks: list[bytes] = []
        size = 0
        try:
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > self._config.max_response_bytes:
                    return None, "response too large"
                chunks.append(chunk)
        except httpx.HTTPError as exc:
            return None, f"read error: {type(exc).__name__}"
        finally:
            await response.aclose()
        return b"".join(chunks), None
