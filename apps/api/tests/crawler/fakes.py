"""Test doubles: an in-memory website served through httpx.MockTransport,
a deterministic DNS resolver, and a recording sleep."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

PUBLIC_IP = "93.184.216.34"


@dataclass
class FakePage:
    body: str | bytes = ""
    status: int = 200
    content_type: str = "text/html; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0.0
    fail_times: int = 0  # raise ConnectError this many times before succeeding
    raise_timeout: bool = False


class FakeSite:
    """Maps full URLs (normalized form) to responses; records requests."""

    def __init__(self, pages: dict[str, FakePage]) -> None:
        self.pages = pages
        self.requests: list[str] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.timestamps: list[float] = []
        self._fail_counts: dict[str, int] = {}
        self.on_request: Callable[[str], None] | None = None

    async def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        self.timestamps.append(asyncio.get_running_loop().time())
        if self.on_request:
            self.on_request(url)
        page = self.pages.get(url)
        if page is None:
            return httpx.Response(404, text="not found", headers={"content-type": "text/html"})
        failed = self._fail_counts.get(url, 0)
        if failed < page.fail_times:
            self._fail_counts[url] = failed + 1
            raise httpx.ConnectError("connection refused", request=request)
        if page.raise_timeout:
            raise httpx.ReadTimeout("read timed out", request=request)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if page.delay:
                await asyncio.sleep(page.delay)
        finally:
            self.in_flight -= 1
        body = page.body.encode() if isinstance(page.body, str) else page.body
        headers = {"content-type": page.content_type, **page.headers}
        return httpx.Response(page.status, content=body, headers=headers)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def html(
    title: str,
    links: tuple[str, ...] | list[str] = (),
    *,
    body: str = "",
    nav: tuple[str, ...] | list[str] = (),
    extra_head: str = "",
) -> str:
    nav_html = "".join(f'<a href="{h}">{h}</a>' for h in nav)
    link_html = "".join(f'<a href="{h}">{h}</a>' for h in links)
    return (
        f"<!doctype html><html lang='en'><head><title>{title}</title>"
        f"<meta name='description' content='About {title}'>{extra_head}</head>"
        f"<body><nav>{nav_html}</nav><main><h1>{title}</h1><p>{body or 'Content of ' + title}</p>"
        f"{link_html}</main><script>var x=1</script></body></html>"
    )


def make_resolver(mapping: dict[str, list[str]] | None = None, default: str = PUBLIC_IP):  # type: ignore[no-untyped-def]
    async def resolve(host: str) -> list[str]:
        if mapping and host in mapping:
            return mapping[host]
        return [default]

    return resolve


class RecordingSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        await asyncio.sleep(0)
