"""Unit tests: URL normalization, SSRF policy, rate limiter, fetcher, robots,
sitemaps, parser, frontier."""

import asyncio

import httpx
import pytest

from app.crawler.fetcher import FetchConfig, Fetcher
from app.crawler.frontier import Frontier, FrontierItem, Priority
from app.crawler.parser import process_html
from app.crawler.ratelimit import HostPolicy, HostRateLimiter
from app.crawler.robots import RobotsCache
from app.crawler.safety import UnsafeURLError, UrlSafetyPolicy, is_public_address
from app.crawler.sitemaps import discover_sitemap_urls
from app.crawler.urls import CrawlURLError, normalize_crawl_url, same_site
from tests.crawler.fakes import FakePage, FakeSite, RecordingSleep, make_resolver

UA = "AI-Search-Growth-OS-Crawler/1.0"


# --- URL normalization ------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://Example.com/page/#section", "https://example.com/page"),
        ("HTTPS://EXAMPLE.COM:443/", "https://example.com/"),
        ("http://example.com:80/a/./b/../c", "http://example.com/a/c"),
        ("https://example.com/a/?utm_source=x&utm_medium=y&id=7", "https://example.com/a?id=7"),
        ("https://example.com/?b=2&a=1&fbclid=zzz", "https://example.com/?a=1&b=2"),
        ("https://example.com/p?page=2", "https://example.com/p?page=2"),
        ("https://example.com/%7Euser/", "https://example.com/~user"),
        ("https://example.com/a b", "https://example.com/a%20b"),
        ("https://example.com:8443/x", "https://example.com:8443/x"),
        ("https://example.com/search?q=&sort=", "https://example.com/search?q=&sort="),
    ],
)
def test_normalize_crawl_url(raw: str, expected: str) -> None:
    assert normalize_crawl_url(raw).normalized == expected


def test_relative_resolution_and_duplicates_collapse() -> None:
    base = "https://example.com/blog/post"
    a = normalize_crawl_url("../about/?utm_campaign=x#top", base=base)
    b = normalize_crawl_url("https://EXAMPLE.com/about", base=base)
    assert a.normalized == b.normalized == "https://example.com/about"


@pytest.mark.parametrize(
    "raw",
    ["", "mailto:a@b.c", "javascript:void(0)", "ftp://x.com", "https://u:p@x.com/", "http://[bad"],
)
def test_normalize_rejects_unusable(raw: str) -> None:
    with pytest.raises(CrawlURLError):
        normalize_crawl_url(raw)


def test_same_site_rules() -> None:
    assert same_site("www.example.com", "example.com", allow_subdomains=False)
    assert same_site("example.com", "www.example.com", allow_subdomains=False)
    assert not same_site("blog.example.com", "example.com", allow_subdomains=False)
    assert same_site("blog.example.com", "www.example.com", allow_subdomains=True)
    assert not same_site("example.com.evil.com", "example.com", allow_subdomains=True)
    assert not same_site("notexample.com", "example.com", allow_subdomains=True)


# --- SSRF -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.5.5",
        "192.168.0.1",
        "169.254.169.254",
        "100.64.1.1",
        "0.0.0.0",  # noqa: S104
        "::1",
        "fe80::1",
        "fd00::1",
        "::ffff:10.0.0.1",
        "224.0.0.1",
        "100.100.100.200",
    ],
)
def test_private_and_metadata_addresses_blocked(address: str) -> None:
    assert not is_public_address(address)


def test_public_addresses_allowed() -> None:
    assert is_public_address("93.184.216.34")
    assert is_public_address("2606:2800:220:1:248:1893:25c8:1946")


@pytest.mark.parametrize(
    ("url", "resolved"),
    [
        ("http://localhost/", None),
        ("http://127.0.0.1/", None),
        ("http://[::1]/", None),
        ("http://169.254.169.254/latest/meta-data/", None),
        ("http://metadata.google.internal/", None),
        ("http://intranet.corp/", None),
        ("http://db.internal/", None),
        ("http://example.com/", ["10.0.0.5"]),  # public name, private A record
        ("http://example.com/", ["93.184.216.34", "192.168.1.1"]),  # one bad address poisons
        ("http://nxdomain.example/", []),
    ],
)
async def test_safety_policy_blocks(url: str, resolved: list[str] | None) -> None:
    mapping = {"example.com": resolved, "nxdomain.example": []} if resolved is not None else {}
    policy = UrlSafetyPolicy(make_resolver(mapping))
    with pytest.raises(UnsafeURLError):
        await policy.check(normalize_crawl_url(url))


async def test_safety_policy_allows_public() -> None:
    policy = UrlSafetyPolicy(make_resolver())
    verdict = await policy.check(normalize_crawl_url("https://example.com/"))
    assert verdict.addresses == ("93.184.216.34",)


async def test_file_and_other_schemes_never_reach_policy() -> None:
    for raw in ("file:///etc/passwd", "gopher://x", "ftp://x.com"):
        with pytest.raises(CrawlURLError):
            normalize_crawl_url(raw)


# --- rate limiter --------------------------------------------------------------------


async def test_rate_limiter_spaces_requests_and_caps_concurrency() -> None:
    clock = {"now": 0.0}
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)
        clock["now"] += s

    limiter = HostRateLimiter(
        HostPolicy(concurrency=2, requests_per_second=2.0),
        clock=lambda: clock["now"],
        sleep=fake_sleep,
    )
    for _ in range(3):
        await limiter.acquire("example.com")
        limiter.release("example.com")
    assert sleeps == pytest.approx([0.5, 0.5])
    limiter.set_delay("example.com", 5.0)
    await limiter.acquire("example.com")
    assert sleeps[-1] == pytest.approx(5.0)
    limiter.release("example.com")

    # Concurrency: third concurrent acquire must wait for a release.
    limiter2 = HostRateLimiter(
        HostPolicy(concurrency=2, requests_per_second=1000), sleep=fake_sleep
    )
    await limiter2.acquire("h")
    await limiter2.acquire("h")
    third = asyncio.ensure_future(limiter2.acquire("h"))
    await asyncio.sleep(0.01)
    assert not third.done()
    limiter2.release("h")
    await asyncio.wait_for(third, 1)


# --- fetcher ---------------------------------------------------------------------------


def _fetcher(site: FakeSite, sleep: RecordingSleep | None = None, **cfg: object) -> Fetcher:
    config = FetchConfig(user_agent=UA, retry_backoff=0.1, **cfg)  # type: ignore[arg-type]
    return Fetcher(
        config,
        UrlSafetyPolicy(make_resolver()),
        transport=site.transport(),
        sleep=sleep or RecordingSleep(),
    )


async def test_fetcher_sends_identifiable_user_agent_and_parses_html() -> None:
    site = FakeSite(
        {"https://example.com/": FakePage(html_body := "<html><title>Hi</title></html>")}
    )
    seen_ua: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_ua.append(request.headers["user-agent"])
        return await site.handler(request)

    fetcher = Fetcher(
        FetchConfig(user_agent=UA),
        UrlSafetyPolicy(make_resolver()),
        transport=httpx.MockTransport(handler),
    )
    result = await fetcher.fetch(normalize_crawl_url("https://example.com/"))
    assert result.ok and result.is_html and result.body == html_body.encode()
    assert seen_ua == [UA] and "Googlebot" not in UA


async def test_fetcher_follows_redirects_and_revalidates_each_hop() -> None:
    site = FakeSite(
        {
            "https://example.com/": FakePage(status=301, headers={"location": "/home"}),
            "https://example.com/home": FakePage(
                status=302, headers={"location": "https://example.com/final"}
            ),
            "https://example.com/final": FakePage("<html>done</html>"),
        }
    )
    result = await _fetcher(site).fetch(normalize_crawl_url("https://example.com/"))
    assert result.ok and result.final_url == "https://example.com/final"
    assert result.redirect_chain == ["https://example.com/home", "https://example.com/final"]

    # Redirect to an internal address is blocked mid-chain.
    evil = FakeSite(
        {
            "https://example.com/": FakePage(
                status=302, headers={"location": "http://169.254.169.254/"}
            )
        }
    )
    result = await _fetcher(evil).fetch(normalize_crawl_url("https://example.com/"))
    assert not result.ok and result.error and result.error.startswith("blocked")
    assert evil.requests == ["https://example.com/"]  # never fetched the metadata endpoint


async def test_fetcher_redirect_limit() -> None:
    pages = {
        f"https://example.com/{i}": FakePage(status=301, headers={"location": f"/{i + 1}"})
        for i in range(10)
    }
    result = await _fetcher(FakeSite(pages), max_redirects=3).fetch(
        normalize_crawl_url("https://example.com/0")
    )
    assert result.error == "too many redirects"


async def test_fetcher_retries_with_backoff_then_succeeds() -> None:
    site = FakeSite({"https://example.com/": FakePage("<html>ok</html>", fail_times=2)})
    sleep = RecordingSleep()
    result = await _fetcher(site, sleep, max_retries=2).fetch(
        normalize_crawl_url("https://example.com/")
    )
    assert result.ok and result.attempts == 3
    assert len(sleep.calls) == 2 and sleep.calls[1] > sleep.calls[0]  # exponential


async def test_fetcher_gives_up_after_retries_and_reports_timeout() -> None:
    site = FakeSite({"https://example.com/": FakePage(raise_timeout=True)})
    result = await _fetcher(site, max_retries=1).fetch(normalize_crawl_url("https://example.com/"))
    assert not result.ok and result.error == "timeout" and result.attempts == 2


async def test_fetcher_total_timeout() -> None:
    site = FakeSite({"https://example.com/": FakePage("<html>slow</html>", delay=0.5)})
    result = await _fetcher(site, total_timeout=0.05).fetch(
        normalize_crawl_url("https://example.com/")
    )
    assert result.error == "total timeout exceeded"


async def test_fetcher_enforces_max_response_size() -> None:
    big = FakeSite({"https://example.com/": FakePage("<html>" + "x" * 10_000 + "</html>")})
    result = await _fetcher(big, max_response_bytes=1000).fetch(
        normalize_crawl_url("https://example.com/")
    )
    assert result.error == "response too large" and result.body is None
    declared = FakeSite(
        {
            "https://example.com/": FakePage(
                "<html>x</html>", headers={"content-length": "999999999"}
            )
        }
    )
    result = await _fetcher(declared, max_response_bytes=1000).fetch(
        normalize_crawl_url("https://example.com/")
    )
    assert result.error == "response too large"


async def test_fetcher_skips_non_html_without_downloading_body() -> None:
    site = FakeSite(
        {
            "https://example.com/file.pdf": FakePage(
                b"%PDF-1.4 " + b"0" * 5000, content_type="application/pdf"
            )
        }
    )
    result = await _fetcher(site).fetch(normalize_crawl_url("https://example.com/file.pdf"))
    assert (
        result.skipped_reason == "unsupported content type: application/pdf" and result.body is None
    )


# --- robots ---------------------------------------------------------------------------


async def test_robots_rules_and_crawl_delay() -> None:
    site = FakeSite(
        {
            "https://example.com/robots.txt": FakePage(
                "User-agent: *\nDisallow: /private/\nCrawl-delay: 2\nSitemap: https://example.com/sm.xml\n",
                content_type="text/plain",
            )
        }
    )
    cache = RobotsCache(_fetcher(site), UA)
    rules = await cache.rules_for(normalize_crawl_url("https://example.com/x"))
    assert cache.allows(rules, "https://example.com/public")
    assert not cache.allows(rules, "https://example.com/private/page")
    assert rules.crawl_delay == 2.0 and rules.sitemaps == ["https://example.com/sm.xml"]
    await cache.rules_for(normalize_crawl_url("https://example.com/y"))
    assert site.requests.count("https://example.com/robots.txt") == 1  # cached


async def test_robots_missing_allows_all_but_5xx_disallows() -> None:
    missing = RobotsCache(_fetcher(FakeSite({})), UA)
    rules = await missing.rules_for(normalize_crawl_url("https://example.com/"))
    assert missing.allows(rules, "https://example.com/anything")
    broken = RobotsCache(
        _fetcher(
            FakeSite({"https://example.com/robots.txt": FakePage("", status=503)}), max_retries=0
        ),
        UA,
    )
    rules = await broken.rules_for(normalize_crawl_url("https://example.com/"))
    assert not broken.allows(rules, "https://example.com/anything")


# --- sitemaps ---------------------------------------------------------------------------


async def test_sitemap_index_and_urlset_are_followed_with_bounds() -> None:
    ns = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
    site = FakeSite(
        {
            "https://example.com/sitemap.xml": FakePage(
                f"<sitemapindex {ns}><sitemap><loc>https://example.com/s1.xml</loc></sitemap>"
                f"<sitemap><loc>https://other.com/evil.xml</loc></sitemap></sitemapindex>",
                content_type="application/xml",
            ),
            "https://example.com/s1.xml": FakePage(
                f"<urlset {ns}><url><loc>https://example.com/a</loc></url><url><loc>https://example.com/b</loc></url></urlset>",
                content_type="application/xml",
            ),
            "https://example.com/bomb.xml": FakePage(
                '<!DOCTYPE x [<!ENTITY a "aaaa">]><urlset><url><loc>&a;</loc></url></urlset>',
                content_type="application/xml",
            ),
        }
    )
    root = normalize_crawl_url("https://example.com/")
    urls = await discover_sitemap_urls(_fetcher(site), root, ["https://example.com/bomb.xml"])
    assert urls == ["https://example.com/a", "https://example.com/b"]
    assert "https://other.com/evil.xml" not in site.requests


# --- parser ----------------------------------------------------------------------------


def test_parser_extracts_metadata_links_text_and_hashes() -> None:
    page = normalize_crawl_url("https://example.com/blog/post")
    doc = b"""<html lang="en-GB"><head><title> Hello  World </title>
    <meta name="description" content="Desc"><meta name="robots" content="noindex, nofollow">
    <link rel="canonical" href="/blog/post-canonical"></head>
    <body><nav><a href="/">Home</a><a href="/about">About</a></nav>
    <main><a href="../contact?utm_source=x">C</a><a href="https://ext.com/x" rel="nofollow">E</a>
    <a href="mailto:a@b.c">m</a><a href="#top">t</a><p>Some body   text here</p></main>
    <script>ignored()</script></body></html>"""
    out = process_html(doc, page)
    assert out.title == "Hello World" and out.meta_description == "Desc" and out.language == "en-GB"
    assert out.canonical_url == "https://example.com/blog/post-canonical"
    assert out.robots_noindex and out.robots_nofollow
    assert [link.url.normalized for link in out.links] == [
        "https://example.com/",
        "https://example.com/about",
        "https://example.com/contact",
        "https://ext.com/x",
    ]
    assert [link.in_navigation for link in out.links] == [True, True, False, False]
    assert out.links[3].nofollow
    assert "ignored" not in out.extracted_text and "Some body text here" in out.extracted_text
    assert out.word_count > 0 and len(out.html_hash) == 64 and len(out.content_hash) == 64
    retitled = process_html(doc.replace(b"Hello  World", b"Other Title"), page)
    assert retitled.content_hash == out.content_hash  # body text unchanged
    assert retitled.html_hash != out.html_hash
    reworded = process_html(doc.replace(b"Some body", b"Different body"), page)
    assert reworded.content_hash != out.content_hash


# --- frontier -----------------------------------------------------------------------------


def test_frontier_priority_and_dedupe() -> None:
    f = Frontier()
    assert f.push(FrontierItem("https://e.com/c", 2, Priority.CONTENT, None, "link"))
    assert f.push(FrontierItem("https://e.com/", 0, Priority.HOMEPAGE, None, "seed"))
    assert f.push(FrontierItem("https://e.com/s", 1, Priority.SITEMAP, None, "sitemap"))
    assert f.push(FrontierItem("https://e.com/n", 1, Priority.NAVIGATION, None, "link"))
    assert not f.push(
        FrontierItem("https://e.com/c", 1, Priority.HOMEPAGE, None, "link")
    )  # duplicate
    order = [f.pop().url for _ in range(4)]  # type: ignore[union-attr]
    assert order == ["https://e.com/", "https://e.com/s", "https://e.com/n", "https://e.com/c"]
    assert f.pop() is None and f.seen_count == 4
