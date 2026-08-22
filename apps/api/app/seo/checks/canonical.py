"""Canonicalization."""

from urllib.parse import urlsplit

from app.crawler.urls import same_site
from app.models.seo import ObservationCategory, Severity
from app.seo.context import AuditContext
from app.seo.findings import Finding

CAT = ObservationCategory.CANONICALIZATION


def check_canonical(ctx: AuditContext) -> list[Finding]:
    findings: list[Finding] = []
    for page in ctx.html_pages:
        if page.canonical_count > 1:
            findings.append(
                Finding(
                    CAT,
                    "canonical_conflicting",
                    Severity.HIGH,
                    "Multiple canonical tags",
                    f'The page declares {page.canonical_count} <link rel="canonical"> elements. '
                    "Engines ignore conflicting canonicals, so the page gets no canonical at all.",
                    "Keep exactly one canonical tag in <head>. Check templates and plugins that "
                    "each inject their own.",
                    {"canonical_count": page.canonical_count, "first": page.canonical_url},
                    page.id,
                    page.url,
                )
            )
            continue
        canonical = page.canonical_url
        if canonical is None:
            findings.append(
                Finding(
                    CAT,
                    "canonical_missing",
                    Severity.LOW if page.indexable else Severity.INFO,
                    "No canonical tag",
                    'The page has no <link rel="canonical">. Without it, parameterized or '
                    "mirrored copies of the page may compete with it.",
                    "Add a self-referencing canonical pointing at the preferred absolute URL "
                    f"({page.url}).",
                    {},
                    page.id,
                    page.url,
                )
            )
            continue
        host = urlsplit(canonical).hostname or ""
        if ctx.root_host and not same_site(host, ctx.root_host, allow_subdomains=True):
            findings.append(
                Finding(
                    CAT,
                    "canonical_external",
                    Severity.HIGH,
                    "Canonical points to another domain",
                    f"The canonical URL is {canonical}, which is outside {ctx.root_host}. This "
                    "tells engines the page is a copy of content owned elsewhere.",
                    "Unless this page is intentionally syndicated, point the canonical at the "
                    "page's own URL.",
                    {"canonical": canonical},
                    page.id,
                    page.url,
                )
            )
            continue
        if canonical != page.url:
            target = ctx.by_url.get(canonical)
            if target is not None and target.canonical_url and target.canonical_url != target.url:
                findings.append(
                    Finding(
                        CAT,
                        "canonical_chain",
                        Severity.MEDIUM,
                        "Canonical points to a page that canonicalizes elsewhere",
                        f"This page canonicalizes to {canonical}, which itself canonicalizes to "
                        f"{target.canonical_url}. Chained canonicals are often ignored.",
                        f"Point this page's canonical directly at {target.canonical_url}.",
                        {"canonical": canonical, "next": target.canonical_url},
                        page.id,
                        page.url,
                    )
                )
            elif target is not None and target.http_status != 200:
                findings.append(
                    Finding(
                        CAT,
                        "canonical_target_not_ok",
                        Severity.HIGH,
                        "Canonical target is not a 200 page",
                        f"The canonical URL {canonical} returned HTTP {target.http_status}.",
                        "Point the canonical at a URL that returns 200, or fix the target page.",
                        {"canonical": canonical, "target_status": target.http_status},
                        page.id,
                        page.url,
                    )
                )
            else:
                findings.append(
                    Finding(
                        CAT,
                        "canonical_mismatch",
                        Severity.INFO,
                        "Canonical differs from the crawled URL",
                        f"The page declares {canonical} as canonical. This is expected for "
                        "parameterized or duplicate URLs, and means this URL is not the one "
                        "engines will index.",
                        "No action if intentional. If this URL should be indexed, change the "
                        "canonical to self-reference.",
                        {"canonical": canonical, "target_crawled": target is not None},
                        page.id,
                        page.url,
                    )
                )
    return findings
