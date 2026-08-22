"""Metadata: titles and meta descriptions.

Length thresholds are soft. A title that is a bit long is `info`; only
extreme lengths or emptiness on indexable pages become `low`/`medium`.
"""

from collections import defaultdict

from app.models.seo import ObservationCategory, Severity
from app.seo.context import AuditContext, PageSnapshot
from app.seo.findings import Finding, urls_evidence

CAT = ObservationCategory.METADATA

TITLE_LONG_SOFT = 60  # commonly truncated in SERPs beyond this
TITLE_LONG_HARD = 90
TITLE_SHORT = 15
DESC_LONG_SOFT = 160
DESC_LONG_HARD = 320
DESC_SHORT = 50


def _page_severity(page: PageSnapshot, indexable: Severity, other: Severity) -> Severity:
    return indexable if page.indexable else other


def check_metadata(ctx: AuditContext) -> list[Finding]:
    findings: list[Finding] = []
    pages = ctx.html_pages

    titles: dict[str, list[PageSnapshot]] = defaultdict(list)
    descriptions: dict[str, list[PageSnapshot]] = defaultdict(list)

    for page in pages:
        title = (page.title or "").strip()
        desc = (page.meta_description or "").strip()

        if not title:
            findings.append(
                Finding(
                    CAT,
                    "title_missing",
                    _page_severity(page, Severity.HIGH, Severity.LOW),
                    "Page has no title tag",
                    "The page does not declare a <title>. Search and AI engines use the title "
                    "as the primary label for the page in results and citations.",
                    "Add a <title> that names the page's primary topic and the brand, e.g. "
                    "'<Topic> – <Brand>'. Keep it specific to this page.",
                    {"http_status": page.http_status, "indexable": page.indexable},
                    page.id,
                    page.url,
                )
            )
        else:
            titles[title.lower()].append(page)
            if len(title) > TITLE_LONG_HARD:
                findings.append(
                    Finding(
                        CAT,
                        "title_too_long",
                        _page_severity(page, Severity.LOW, Severity.INFO),
                        "Title is very long",
                        f"The title is {len(title)} characters. Titles beyond ~{TITLE_LONG_SOFT} "
                        "characters are usually truncated in search results and summaries.",
                        "Move secondary keywords or taglines out of the title; keep the leading "
                        f"~{TITLE_LONG_SOFT} characters self-explanatory.",
                        {"title": title[:200], "length": len(title)},
                        page.id,
                        page.url,
                    )
                )
            elif len(title) > TITLE_LONG_SOFT:
                findings.append(
                    Finding(
                        CAT,
                        "title_long",
                        Severity.INFO,
                        "Title may be truncated",
                        f"The title is {len(title)} characters, slightly over the "
                        f"~{TITLE_LONG_SOFT} characters typically displayed.",
                        "Consider front-loading the most important words so the visible part "
                        "stands on its own. No change is required if the truncation is acceptable.",
                        {"title": title[:200], "length": len(title)},
                        page.id,
                        page.url,
                    )
                )
            elif len(title) < TITLE_SHORT:
                findings.append(
                    Finding(
                        CAT,
                        "title_too_short",
                        _page_severity(page, Severity.LOW, Severity.INFO),
                        "Title is very short",
                        f"The title '{title}' is {len(title)} characters and may not describe the "
                        "page clearly enough to be understood out of context.",
                        "Expand the title to state what the page is about and which entity it "
                        "represents (product, service, topic), e.g. add the brand or category.",
                        {"title": title, "length": len(title)},
                        page.id,
                        page.url,
                    )
                )

        if not desc:
            findings.append(
                Finding(
                    CAT,
                    "description_missing",
                    _page_severity(page, Severity.MEDIUM, Severity.INFO),
                    "Page has no meta description",
                    'No <meta name="description"> was found. Engines then generate their own '
                    "snippet from page text, which is less controllable.",
                    "Write a 1–2 sentence description that summarizes the page's purpose and "
                    "main entity; make it unique per page.",
                    {"indexable": page.indexable},
                    page.id,
                    page.url,
                )
            )
        else:
            descriptions[desc.lower()].append(page)
            if len(desc) > DESC_LONG_HARD:
                findings.append(
                    Finding(
                        CAT,
                        "description_too_long",
                        Severity.LOW,
                        "Meta description is very long",
                        f"The description is {len(desc)} characters; engines typically show "
                        f"~{DESC_LONG_SOFT}.",
                        "Trim the description to the essential summary and keep the key message "
                        "in the first sentence.",
                        {"length": len(desc)},
                        page.id,
                        page.url,
                    )
                )
            elif len(desc) < DESC_SHORT:
                findings.append(
                    Finding(
                        CAT,
                        "description_too_short",
                        Severity.INFO,
                        "Meta description is very short",
                        f"The description is only {len(desc)} characters.",
                        "Expand it to a full sentence that describes what the page offers.",
                        {"description": desc, "length": len(desc)},
                        page.id,
                        page.url,
                    )
                )

    for group in titles.values():
        indexable = [p for p in group if p.indexable]
        if len(indexable) > 1:
            findings.append(
                Finding(
                    CAT,
                    "title_duplicate",
                    Severity.MEDIUM if len(indexable) > 3 else Severity.LOW,
                    "Multiple pages share the same title",
                    f"{len(indexable)} indexable pages use the title '{group[0].title}'. Identical "
                    "titles make it hard for engines to tell the pages apart.",
                    "Create unique titles that clearly describe the primary topic and entity "
                    "represented by each page; if the pages are truly duplicates, canonicalize "
                    "them to one URL instead.",
                    {"title": group[0].title, **urls_evidence([p.url for p in indexable])},
                    None,
                    None,
                )
            )
    for group in descriptions.values():
        indexable = [p for p in group if p.indexable]
        if len(indexable) > 1:
            findings.append(
                Finding(
                    CAT,
                    "description_duplicate",
                    Severity.LOW,
                    "Multiple pages share the same meta description",
                    f"{len(indexable)} indexable pages use an identical description.",
                    "Write a distinct description for each page that reflects its specific "
                    "content; a site-wide boilerplate description adds no information.",
                    {
                        "description": group[0].meta_description,
                        **urls_evidence([p.url for p in indexable]),
                    },
                    None,
                    None,
                )
            )
    return findings
