"""Internal links: orphans, weakly linked pages, broken links, depth."""

from app.models.page_intelligence import LinkStatus, LinkType
from app.models.seo import ObservationCategory, Severity
from app.seo.context import AuditContext
from app.seo.findings import Finding, urls_evidence

CAT = ObservationCategory.INTERNAL_LINKS
FEW_LINKS_THRESHOLD = 2
DEEP_DEPTH = 4


def check_internal_links(ctx: AuditContext) -> list[Finding]:
    findings: list[Finding] = []
    root = ctx.by_url.get(ctx.root_url) or ctx.by_url.get(ctx.root_url.rstrip("/") + "/")

    orphans: list[str] = []
    weak: list[tuple[str, int]] = []
    for page in ctx.html_pages:
        if root is not None and page.id == root.id:
            continue
        sources = {link.page_id for link in ctx.incoming.get(page.id, [])}
        if not sources:
            orphans.append(page.url)
        elif len(sources) < FEW_LINKS_THRESHOLD:
            weak.append((page.url, len(sources)))
    if orphans:
        findings.append(
            Finding(
                CAT,
                "orphan_pages",
                Severity.MEDIUM,
                "Pages with no internal links pointing at them",
                f"{len(orphans)} crawled page(s) are reachable only via the sitemap or a "
                "redirect, not from any other page. Engines treat such pages as unimportant.",
                "Link to these pages from relevant content, navigation, or hub pages; if they "
                "are obsolete, remove them from the sitemap.",
                urls_evidence(orphans),
            )
        )
    if weak:
        findings.append(
            Finding(
                CAT,
                "few_internal_links",
                Severity.LOW,
                "Pages with very few internal links",
                f"{len(weak)} page(s) are linked from fewer than {FEW_LINKS_THRESHOLD} "
                "other pages.",
                "Add contextual links from related pages so importance and crawl frequency "
                "are distributed.",
                {
                    "pages": [{"url": u, "incoming_pages": n} for u, n in weak[:25]],
                    "count": len(weak),
                },
            )
        )

    for page in ctx.html_pages:
        broken = [
            link
            for link in page.outgoing
            if link.link_type == LinkType.INTERNAL and link.status == LinkStatus.BROKEN
        ]
        if broken:
            findings.append(
                Finding(
                    CAT,
                    "broken_internal_links",
                    Severity.HIGH,
                    "Page links to broken internal URLs",
                    f"{len(broken)} internal link(s) on this page point to URLs that returned "
                    "4xx/5xx.",
                    "Update or remove these links. If the targets were moved, redirect the old "
                    "URLs to the new ones.",
                    {
                        "links": [
                            {
                                "href": link.href,
                                "anchor": link.anchor_text,
                                "status": link.target_http_status,
                            }
                            for link in broken[:25]
                        ],
                        "count": len(broken),
                    },
                    page.id,
                    page.url,
                )
            )

    deep = [
        (p.url, p.depth) for p in ctx.html_pages if p.depth is not None and p.depth > DEEP_DEPTH
    ]
    if deep:
        findings.append(
            Finding(
                CAT,
                "excessive_link_depth",
                Severity.LOW,
                "Pages are many clicks from the homepage",
                f"{len(deep)} page(s) were first reached more than {DEEP_DEPTH} clicks deep. "
                "Deep pages are crawled less often and receive less internal authority.",
                "Surface these pages through category/hub pages or navigation so they are "
                "within 3–4 clicks of the homepage.",
                {"pages": [{"url": u, "depth": d} for u, d in deep[:25]], "count": len(deep)},
            )
        )
    return findings
