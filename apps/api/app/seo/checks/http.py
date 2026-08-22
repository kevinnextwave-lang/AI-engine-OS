"""HTTP and indexability: status codes, redirects, robots, noindex, sitemaps."""

from collections import defaultdict

from app.models.crawl import CrawlUrlStatus
from app.models.seo import ObservationCategory, Severity
from app.seo.context import AuditContext
from app.seo.findings import Finding, urls_evidence

HTTP = ObservationCategory.HTTP
IDX = ObservationCategory.INDEXABILITY
REDIRECT_CHAIN_MIN = 2  # more than one hop


def check_http(ctx: AuditContext) -> list[Finding]:
    findings: list[Finding] = []
    by_status: dict[int, list[str]] = defaultdict(list)
    for page in ctx.pages:
        if page.http_status != 200:
            by_status[page.http_status].append(page.url)

    for status, urls in sorted(by_status.items()):
        if 500 <= status:
            sev, code, title = Severity.HIGH, "server_error", f"Pages return HTTP {status}"
            rec = (
                "Investigate server logs for these URLs; 5xx responses make pages drop out "
                "of the index and waste crawl budget."
            )
        elif 400 <= status:
            sev = Severity.MEDIUM if status == 404 else Severity.LOW
            code, title = "client_error", f"Pages return HTTP {status}"
            rec = (
                "Restore the content, redirect the URL to its closest replacement, or remove the "
                "internal links pointing at it."
                if status in (404, 410)
                else "Check access rules for these URLs; crawlers should not be blocked "
                "from public pages."
            )
        else:
            sev, code, title = Severity.INFO, "non_200", f"Pages return HTTP {status}"
            rec = "Confirm that this response is intended."
        findings.append(
            Finding(
                HTTP,
                code,
                sev,
                title,
                f"{len(urls)} crawled page(s) returned HTTP {status} instead of 200.",
                rec,
                {"http_status": status, **urls_evidence(urls)},
            )
        )

    # Redirect chains and loops from crawl outcomes.
    chains = [u for u in ctx.urls if len(u.redirect_chain) >= REDIRECT_CHAIN_MIN]
    if chains:
        findings.append(
            Finding(
                HTTP,
                "redirect_chain",
                Severity.MEDIUM,
                "Redirect chains",
                f"{len(chains)} URL(s) reach their destination only after {REDIRECT_CHAIN_MIN}+ "
                "redirects. Each hop adds latency and can lose ranking signals.",
                "Update the source links to point directly at the final URL and collapse the "
                "intermediate redirects into a single hop.",
                {
                    "chains": [{"from": u.url, "hops": u.redirect_chain} for u in chains[:25]],
                    "count": len(chains),
                },
            )
        )
    loops = [u for u in ctx.urls if u.error_message == "too many redirects"]
    if loops:
        findings.append(
            Finding(
                HTTP,
                "redirect_loop",
                Severity.HIGH,
                "Redirect loops or excessive redirects",
                f"{len(loops)} URL(s) never resolved because the redirect limit was exceeded. "
                "These pages are unreachable for crawlers and users.",
                "Trace the redirect rules for these URLs and remove the cycle.",
                urls_evidence([u.url for u in loops]),
            )
        )
    single_redirects = [u for u in ctx.urls if len(u.redirect_chain) == 1]
    if single_redirects:
        findings.append(
            Finding(
                HTTP,
                "redirected_urls",
                Severity.INFO,
                "Internally linked URLs redirect",
                f"{len(single_redirects)} linked URL(s) redirect once before serving content.",
                "Optional: link to the final URLs directly to avoid the extra request.",
                {
                    "redirects": [
                        {"from": u.url, "to": u.final_url} for u in single_redirects[:25]
                    ],
                    "count": len(single_redirects),
                },
            )
        )
    return findings


def check_indexability(ctx: AuditContext) -> list[Finding]:
    findings: list[Finding] = []
    site = ctx.site or {}
    robots = site.get("robots_txt") or {}
    if robots.get("checked"):
        if robots.get("error"):
            findings.append(
                Finding(
                    IDX,
                    "robots_txt_unreachable",
                    Severity.HIGH,
                    "robots.txt could not be retrieved",
                    f"Fetching robots.txt failed ({robots['error']}). Crawlers that cannot read "
                    "robots.txt may stop crawling the site entirely.",
                    "Make /robots.txt return 200 with valid rules (or 404 if you have none); "
                    "never let it return 5xx.",
                    {"error": robots.get("error")},
                )
            )
        elif not robots.get("present"):
            findings.append(
                Finding(
                    IDX,
                    "robots_txt_missing",
                    Severity.INFO,
                    "No robots.txt",
                    "The site has no robots.txt, so every path is crawlable by default.",
                    "Optional: add a robots.txt that lists your sitemap and excludes private "
                    "paths (admin, search results, cart).",
                    {},
                )
            )
    blocked = [
        u
        for u in ctx.urls
        if u.status == CrawlUrlStatus.SKIPPED and "robots" in (u.error_message or "")
    ]
    if blocked:
        findings.append(
            Finding(
                IDX,
                "robots_blocked_pages",
                Severity.INFO,
                "Internally linked pages are blocked by robots.txt",
                f"{len(blocked)} linked URL(s) are disallowed for crawlers.",
                "Confirm these paths should be hidden from search. If they contain content you "
                "want indexed, allow them in robots.txt.",
                urls_evidence([u.url for u in blocked]),
            )
        )
    noindex = [p for p in ctx.html_pages if p.noindex]
    if noindex:
        findings.append(
            Finding(
                IDX,
                "noindex_pages",
                Severity.MEDIUM
                if len(noindex) > max(1, len(ctx.html_pages) // 5)
                else Severity.INFO,
                "Pages marked noindex",
                f"{len(noindex)} page(s) carry a robots meta tag with noindex and will not "
                "appear in search results.",
                "Verify each noindex is intentional. Remove the directive from pages that "
                "should rank; keep it on thin or utility pages.",
                urls_evidence([p.url for p in noindex]),
            )
        )
    if "sitemap_urls_found" in site and site.get("sitemap_urls_found", 0) == 0:
        findings.append(
            Finding(
                IDX,
                "sitemap_missing",
                Severity.LOW,
                "No XML sitemap found",
                "Neither robots.txt nor /sitemap.xml led to a sitemap with URLs. Sitemaps help "
                "engines discover pages that are deep or weakly linked.",
                "Publish an XML sitemap of canonical, indexable URLs and reference it from "
                "robots.txt with a `Sitemap:` line.",
                {"sitemaps_declared": robots.get("sitemaps_declared", [])},
            )
        )
    return findings
