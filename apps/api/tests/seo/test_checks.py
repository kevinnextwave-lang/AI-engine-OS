"""Pure check functions over in-memory audit contexts (no DB)."""

import uuid

from app.models.crawl import CrawlUrlStatus
from app.models.page_intelligence import LinkStatus, PageStructuredData, StructuredDataFormat
from app.models.seo import ObservationCategory, Severity
from app.seo.checks.canonical import check_canonical
from app.seo.checks.headings import check_headings
from app.seo.checks.http import check_http, check_indexability
from app.seo.checks.links import check_internal_links
from app.seo.checks.metadata import check_metadata
from app.seo.checks.structured import check_mobile_html, check_structured_data
from app.seo.context import UrlOutcome
from app.seo.engine import run_checks
from app.seo.scoring import CATEGORY_CAP, compute_score
from tests.seo.helpers import ROOT, by_code, codes, context, link, page

# --- metadata ----------------------------------------------------------------


def test_missing_title_is_high_on_indexable_and_low_otherwise() -> None:
    ctx = context([page(ROOT + "a", title=None), page(ROOT + "b", title=None, robots="noindex")])
    found = by_code(check_metadata(ctx), "title_missing")
    assert {f.url: f.severity for f in found} == {
        ROOT + "a": Severity.HIGH,
        ROOT + "b": Severity.LOW,
    }
    assert found[0].category == ObservationCategory.METADATA
    assert "<title>" in found[0].recommendation


def test_duplicate_titles_only_counted_across_indexable_pages() -> None:
    ctx = context(
        [
            page(ROOT + "a", title="Same Title"),
            page(ROOT + "b", title="same title"),
            page(ROOT + "c", title="Same Title", robots="noindex"),
        ]
    )
    dup = by_code(check_metadata(ctx), "title_duplicate")
    assert len(dup) == 1 and dup[0].severity == Severity.LOW
    assert sorted(dup[0].evidence["urls"]) == [ROOT + "a", ROOT + "b"]
    assert dup[0].page_id is None  # site-wide observation


def test_duplicate_titles_across_many_pages_is_medium() -> None:
    ctx = context([page(f"{ROOT}p{i}", title="Same") for i in range(5)])
    dup = by_code(check_metadata(ctx), "title_duplicate")
    assert dup[0].severity == Severity.MEDIUM and dup[0].evidence["count"] == 5


def test_missing_and_duplicate_descriptions() -> None:
    ctx = context(
        [
            page(ROOT + "a", description=None),
            page(ROOT + "b", description="Identical description for two separate pages here."),
            page(ROOT + "c", description="Identical description for two separate pages here."),
        ]
    )
    findings = check_metadata(ctx)
    missing = by_code(findings, "description_missing")
    assert [f.url for f in missing] == [ROOT + "a"] and missing[0].severity == Severity.MEDIUM
    dup = by_code(findings, "description_duplicate")
    assert len(dup) == 1 and dup[0].evidence["count"] == 2


def test_title_length_thresholds() -> None:
    ctx = context(
        [
            page(ROOT + "short", title="Hi"),
            page(ROOT + "long", title="x" * 70),
            page(ROOT + "huge", title="x" * 100),
        ]
    )
    findings = check_metadata(ctx)
    assert by_code(findings, "title_too_short")[0].url == ROOT + "short"
    assert by_code(findings, "title_long")[0].severity == Severity.INFO
    assert by_code(findings, "title_too_long")[0].severity == Severity.LOW


# --- headings ----------------------------------------------------------------


def test_missing_and_multiple_h1() -> None:
    ctx = context(
        [
            page(ROOT + "a", headings={"h1_count": 0, "missing_h1": True, "multiple_h1": False}),
            page(ROOT + "b", headings={"h1_count": 2, "missing_h1": False, "multiple_h1": True}),
            page(
                ROOT + "c",
                robots="noindex",
                headings={"h1_count": 0, "missing_h1": True, "multiple_h1": False},
            ),
        ]
    )
    findings = check_headings(ctx)
    missing = by_code(findings, "h1_missing")
    assert {f.url: f.severity for f in missing} == {
        ROOT + "a": Severity.MEDIUM,
        ROOT + "c": Severity.LOW,
    }
    assert by_code(findings, "h1_multiple")[0].url == ROOT + "b"


def test_heading_hierarchy_and_duplicates() -> None:
    ctx = context(
        [
            page(
                ROOT + "a",
                headings={
                    "h1_count": 1,
                    "missing_h1": False,
                    "multiple_h1": False,
                    "skipped_levels": [[1, 3]],
                    "duplicate_headings": ["Products"],
                },
            )
        ]
    )
    assert set(codes(check_headings(ctx))) == {"heading_hierarchy_skipped", "heading_duplicate"}


# --- canonical ---------------------------------------------------------------


def test_canonical_issues() -> None:
    target = page(ROOT + "target", canonical=ROOT + "elsewhere")
    gone = page(ROOT + "gone", status=404, canonical=None)
    ctx = context(
        [
            page(ROOT + "ok"),
            page(ROOT + "none", canonical=None),
            page(ROOT + "multi", canonical_count=2),
            page(ROOT + "ext", canonical="https://evil.example/"),
            page(ROOT + "sub", canonical="https://blog.acme.com/x"),
            page(ROOT + "chain", canonical=target.url),
            target,
            page(ROOT + "to-404", canonical=gone.url),
            gone,
            page(ROOT + "mismatch", canonical=ROOT + "ok"),
        ]
    )
    findings = check_canonical(ctx)
    by_url = {f.url: f for f in findings}
    assert ROOT + "ok" not in by_url
    assert by_url[ROOT + "none"].code == "canonical_missing"
    assert by_url[ROOT + "multi"].code == "canonical_conflicting"
    assert by_url[ROOT + "multi"].severity == Severity.HIGH
    assert by_url[ROOT + "ext"].code == "canonical_external"
    assert ROOT + "sub" not in by_url or by_url[ROOT + "sub"].code == "canonical_mismatch"
    assert by_url[ROOT + "chain"].code == "canonical_chain"
    assert by_url[ROOT + "target"].code == "canonical_mismatch"
    assert by_url[ROOT + "to-404"].code == "canonical_target_not_ok"
    assert by_url[ROOT + "mismatch"].code == "canonical_mismatch"
    assert by_url[ROOT + "mismatch"].severity == Severity.INFO


# --- http / indexability -----------------------------------------------------


def test_http_status_grouping_and_redirects() -> None:
    pages = [page(ROOT), page(ROOT + "a", status=404), page(ROOT + "b", status=503)]
    urls = [
        UrlOutcome(p.url, CrawlUrlStatus.CRAWLED, p.http_status, p.url, [], None, 0) for p in pages
    ] + [
        UrlOutcome(ROOT + "old", CrawlUrlStatus.CRAWLED, 200, ROOT, [ROOT + "old"], None, 1),
        UrlOutcome(
            ROOT + "x", CrawlUrlStatus.CRAWLED, 200, ROOT, [ROOT + "x", ROOT + "y"], None, 1
        ),
        UrlOutcome(ROOT + "loop", CrawlUrlStatus.FAILED, None, None, [], "too many redirects", 1),
    ]
    findings = check_http(context(pages, urls=urls))
    assert by_code(findings, "client_error")[0].severity == Severity.MEDIUM
    assert by_code(findings, "server_error")[0].severity == Severity.HIGH
    chain = by_code(findings, "redirect_chain")[0]
    assert chain.evidence["chains"][0]["from"] == ROOT + "x" and chain.evidence["count"] == 1
    assert by_code(findings, "redirect_loop")[0].evidence["urls"] == [ROOT + "loop"]
    assert by_code(findings, "redirected_urls")[0].evidence["count"] == 1


def test_noindex_severity_scales_with_share() -> None:
    few = context([page(f"{ROOT}p{i}") for i in range(9)] + [page(ROOT + "n", robots="noindex")])
    many = context([page(ROOT + "a", robots="noindex"), page(ROOT + "b", robots="none")])
    assert by_code(check_indexability(few), "noindex_pages")[0].severity == Severity.INFO
    assert by_code(check_indexability(many), "noindex_pages")[0].severity == Severity.MEDIUM


def test_robots_and_sitemap_signals() -> None:
    base = [page(ROOT)]
    unreachable = context(
        base, site={"robots_txt": {"checked": True, "error": "HTTP 500"}, "sitemap_urls_found": 0}
    )
    f = check_indexability(unreachable)
    assert by_code(f, "robots_txt_unreachable")[0].severity == Severity.HIGH
    assert by_code(f, "sitemap_missing")
    missing = context(base, site={"robots_txt": {"checked": True, "present": False}})
    assert by_code(check_indexability(missing), "robots_txt_missing")[0].severity == Severity.INFO
    blocked = context(
        base,
        urls=[UrlOutcome(ROOT + "admin", CrawlUrlStatus.SKIPPED, None, None, [], "robots", 1)],
    )
    assert by_code(check_indexability(blocked), "robots_blocked_pages")[0].evidence["urls"] == [
        ROOT + "admin"
    ]


# --- internal links ----------------------------------------------------------


def test_orphans_broken_links_and_depth() -> None:
    home, a, orphan, deep = (
        page(ROOT, depth=0),
        page(ROOT + "a"),
        page(ROOT + "orphan"),
        page(ROOT + "deep", depth=6),
    )
    links = [link(home, a), link(home, deep), link(a, None, status=LinkStatus.BROKEN)]
    findings = check_internal_links(context([home, a, orphan, deep], links=links))
    assert by_code(findings, "orphan_pages")[0].evidence["urls"] == [ROOT + "orphan"]
    broken = by_code(findings, "broken_internal_links")
    assert len(broken) == 1 and broken[0].url == a.url and broken[0].severity == Severity.HIGH
    depth = by_code(findings, "excessive_link_depth")[0]
    assert depth.evidence["pages"] == [{"url": ROOT + "deep", "depth": 6}]
    weak = by_code(findings, "few_internal_links")[0]
    assert {p["url"] for p in weak.evidence["pages"]} == {a.url, deep.url}


# --- structured data / mobile-html ------------------------------------------


def _sd(fmt: StructuredDataFormat, types: list[str], valid: bool = True) -> PageStructuredData:
    return PageStructuredData(
        page_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        format=fmt,
        schema_types=types,
        payload={},
        is_valid=valid,
        error=None if valid else "bad json",
        position=0,
    )


def test_structured_data_detection() -> None:
    with_sd = page(ROOT)
    with_sd.structured = [_sd(StructuredDataFormat.JSON_LD, ["Organization"])]
    bad = page(ROOT + "bad")
    bad.structured = [_sd(StructuredDataFormat.JSON_LD, [], valid=False)]
    ctx = context([with_sd, bad, page(ROOT + "none")])
    findings = check_structured_data(ctx)
    detected = by_code(findings, "structured_data_detected")[0]
    assert detected.evidence["schema_types"] == {"Organization": 1}
    assert detected.evidence["formats"] == {"json_ld": 1}
    assert by_code(findings, "structured_data_invalid")[0].url == ROOT + "bad"
    missing = by_code(findings, "structured_data_missing")[0]
    assert sorted(missing.evidence["urls"]) == [ROOT + "bad", ROOT + "none"]
    assert missing.severity == Severity.LOW  # 2 of 3 > 50%


def test_mobile_html_basics() -> None:
    ctx = context(
        [page(ROOT, viewport=None, lang=None, charset=None, doctype=False, title_count=2)]
    )
    assert set(codes(check_mobile_html(ctx))) == {
        "viewport_missing",
        "lang_missing",
        "charset_missing",
        "doctype_missing",
        "title_multiple",
    }


# --- scoring -----------------------------------------------------------------


def test_clean_site_scores_100_and_info_costs_nothing() -> None:
    home = page(
        ROOT,
        depth=0,
        title="Acme Home – durable widgets",
        description="Acme makes durable widgets for everyone, shipped worldwide.",
    )
    a = page(
        ROOT + "a",
        title="Widgets catalogue – Acme",
        description="All widgets made by Acme, in one place, with prices and specs.",
    )
    b = page(
        ROOT + "b",
        title="About the company – Acme",
        description="The Acme story, our team, and how to contact us directly.",
    )
    for p in (home, a, b):
        p.structured = [_sd(StructuredDataFormat.JSON_LD, ["WebPage"])]
    links = [link(home, a), link(home, b), link(a, b), link(b, a), link(a, home), link(b, home)]
    ctx = context(
        [home, a, b], links=links, site={"robots_txt": {"checked": True, "present": True}}
    )
    findings = run_checks(ctx)
    assert {f.severity for f in findings} <= {Severity.INFO}
    result = compute_score(findings, len(ctx.html_pages))
    assert result.score == 100.0
    assert result.breakdown["method"] == "technical-seo-health-score/v1"


def test_score_deductions_are_weighted_capped_and_explained() -> None:
    ctx = context(
        [
            page(f"{ROOT}p{i}", title=None, description=f"Unique description number {i} " * 3)
            for i in range(10)
        ]
    )
    findings = check_metadata(ctx)  # 10 × title_missing (HIGH, 1 page each of 10)
    result = compute_score(findings, 10)
    meta = result.breakdown["categories"]["metadata"]
    # Each HIGH finding: 12 × max(0.25, 1/10) = 3.0 → raw 30, capped to 15.
    assert meta["raw_deduction"] == 30.0
    assert meta["applied_deduction"] == CATEGORY_CAP[ObservationCategory.METADATA]
    assert result.score == 85.0
    assert meta["contributions"][0]["deduction"] == 3.0
    assert all(
        c["applied_deduction"] == 0
        for k, c in result.breakdown["categories"].items()
        if k != "metadata"
    )


def test_score_never_below_zero() -> None:
    from app.seo.findings import Finding

    findings = [
        Finding(cat, "x", Severity.CRITICAL, "t", "d", "r", {"count": 100})
        for cat in ObservationCategory
        for _ in range(5)
    ]
    assert compute_score(findings, 1).score == 0.0
