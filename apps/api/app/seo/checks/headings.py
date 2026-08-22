"""Headings: facts come from page_content_metrics.heading_observations."""

from app.models.seo import ObservationCategory, Severity
from app.seo.context import AuditContext
from app.seo.findings import Finding

CAT = ObservationCategory.HEADINGS


def check_headings(ctx: AuditContext) -> list[Finding]:
    findings: list[Finding] = []
    for page in ctx.html_pages:
        obs = page.heading_observations or {}
        if not obs:
            continue
        if obs.get("missing_h1"):
            findings.append(
                Finding(
                    CAT,
                    "h1_missing",
                    Severity.MEDIUM if page.indexable else Severity.LOW,
                    "Page has no H1",
                    "No <h1> element was found. The H1 is the strongest on-page signal of the "
                    "page's main topic for both search engines and AI summarizers.",
                    "Add a single <h1> that states the page's main subject; it usually mirrors "
                    "the title without being identical.",
                    {"h1_count": 0},
                    page.id,
                    page.url,
                )
            )
        elif obs.get("multiple_h1"):
            findings.append(
                Finding(
                    CAT,
                    "h1_multiple",
                    Severity.LOW,
                    "Page has multiple H1 headings",
                    f"{obs.get('h1_count')} <h1> elements were found. Several top-level headings "
                    "dilute the signal of what the page is primarily about.",
                    "Keep one <h1> for the main subject and demote the others to <h2>.",
                    {"h1_count": obs.get("h1_count")},
                    page.id,
                    page.url,
                )
            )
        skipped = obs.get("skipped_levels") or []
        if skipped:
            findings.append(
                Finding(
                    CAT,
                    "heading_hierarchy_skipped",
                    Severity.LOW,
                    "Heading levels are skipped",
                    f"{len(skipped)} heading(s) jump more than one level (e.g. H2 → H4). "
                    "Skipped levels weaken the document outline used by assistive technology "
                    "and content parsers.",
                    "Use consecutive levels (H2 under H1, H3 under H2). If a heading is only "
                    "styled smaller, change the CSS rather than the level.",
                    {"skipped": skipped[:20]},
                    page.id,
                    page.url,
                )
            )
        duplicates = obs.get("duplicate_headings") or []
        if duplicates:
            findings.append(
                Finding(
                    CAT,
                    "heading_duplicate",
                    Severity.INFO,
                    "Repeated heading text",
                    f"{len(duplicates)} heading text(s) appear more than once on the page.",
                    "Make repeated headings distinct so each section can be identified by its "
                    "heading alone; repeated headings in UI components (e.g. card labels) can "
                    "be ignored.",
                    {"headings": duplicates[:20]},
                    page.id,
                    page.url,
                )
            )
        long_positions = obs.get("long_heading_positions") or []
        if long_positions:
            findings.append(
                Finding(
                    CAT,
                    "heading_too_long",
                    Severity.INFO,
                    "Very long heading(s)",
                    f"{len(long_positions)} heading(s) exceed 70 characters.",
                    "Shorten long headings to a concise label and move detail into the "
                    "paragraph beneath.",
                    {"positions": long_positions[:20]},
                    page.id,
                    page.url,
                )
            )
    return findings
