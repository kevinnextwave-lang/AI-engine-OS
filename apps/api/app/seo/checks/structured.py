"""Structured data and mobile / basic HTML indicators."""

from collections import Counter

from app.models.seo import ObservationCategory, Severity
from app.seo.context import AuditContext
from app.seo.findings import Finding, urls_evidence

SD = ObservationCategory.STRUCTURED_DATA
MH = ObservationCategory.MOBILE_HTML


def check_structured_data(ctx: AuditContext) -> list[Finding]:
    findings: list[Finding] = []
    types: Counter[str] = Counter()
    formats: Counter[str] = Counter()
    without: list[str] = []
    for page in ctx.indexable_pages:
        valid_blocks = [sd for sd in page.structured if sd.is_valid]
        invalid = [sd for sd in page.structured if not sd.is_valid]
        for sd in valid_blocks:
            formats[sd.format.value] += 1
            types.update(sd.schema_types)
        if invalid:
            findings.append(
                Finding(
                    SD,
                    "structured_data_invalid",
                    Severity.MEDIUM,
                    "Structured data block cannot be parsed",
                    f"{len(invalid)} JSON-LD block(s) on this page are not valid JSON, so engines "
                    "ignore them.",
                    "Validate the JSON-LD (e.g. with the Schema.org validator) and fix the syntax; "
                    "common causes are trailing commas and unescaped quotes.",
                    {"errors": [sd.error for sd in invalid][:10]},
                    page.id,
                    page.url,
                )
            )
        if not valid_blocks:
            without.append(page.url)
    if formats:
        findings.append(
            Finding(
                SD,
                "structured_data_detected",
                Severity.INFO,
                "Structured data found",
                f"Structured data is present on {len(ctx.indexable_pages) - len(without)} of "
                f"{len(ctx.indexable_pages)} indexable pages.",
                "No action needed. Keep schema types aligned with page content as it changes.",
                {
                    "formats": dict(formats),
                    "schema_types": dict(types.most_common(30)),
                },
            )
        )
    if without and ctx.indexable_pages:
        share = len(without) / len(ctx.indexable_pages)
        findings.append(
            Finding(
                SD,
                "structured_data_missing",
                Severity.LOW if share > 0.5 else Severity.INFO,
                "Pages without structured data",
                f"{len(without)} indexable page(s) declare no JSON-LD, Microdata or RDFa. "
                "Structured data helps engines and AI systems identify the entities on a page.",
                "Add JSON-LD for the page's main entity (Organization or WebSite on the "
                "homepage; Article, Product, Service, FAQPage, etc. elsewhere).",
                urls_evidence(without),
            )
        )
    return findings


def check_mobile_html(ctx: AuditContext) -> list[Finding]:
    findings: list[Finding] = []
    no_viewport: list[str] = []
    no_lang: list[str] = []
    no_charset: list[str] = []
    no_doctype: list[str] = []
    multi_title: list[str] = []
    for page in ctx.html_pages:
        if not page.viewport:
            no_viewport.append(page.url)
        if not page.html_lang:
            no_lang.append(page.url)
        if not page.charset:
            no_charset.append(page.url)
        if not page.has_doctype:
            no_doctype.append(page.url)
        if page.title_count > 1:
            multi_title.append(page.url)

    total = max(1, len(ctx.html_pages))

    def sev(count: int, high: Severity, low: Severity) -> Severity:
        return high if count / total > 0.5 else low

    if no_viewport:
        findings.append(
            Finding(
                MH,
                "viewport_missing",
                sev(len(no_viewport), Severity.MEDIUM, Severity.LOW),
                "Pages without a viewport meta tag",
                f'{len(no_viewport)} page(s) lack <meta name="viewport">. Mobile browsers '
                "render them at desktop width, and mobile-first indexing treats this as a "
                "usability problem.",
                'Add <meta name="viewport" content="width=device-width, initial-scale=1"> '
                "to the site template.",
                urls_evidence(no_viewport),
            )
        )
    if no_lang:
        findings.append(
            Finding(
                MH,
                "lang_missing",
                Severity.LOW,
                "Pages without a lang attribute",
                f"{len(no_lang)} page(s) do not declare <html lang>. Language detection then "
                "falls back to heuristics.",
                'Set <html lang="xx"> (BCP 47 code) in the template, per language version.',
                urls_evidence(no_lang),
            )
        )
    if no_charset:
        findings.append(
            Finding(
                MH,
                "charset_missing",
                Severity.LOW,
                "Pages without a declared character set",
                f"{len(no_charset)} page(s) have no <meta charset>, risking mis-rendered text.",
                'Add <meta charset="utf-8"> as the first element in <head>.',
                urls_evidence(no_charset),
            )
        )
    if no_doctype:
        findings.append(
            Finding(
                MH,
                "doctype_missing",
                Severity.LOW,
                "Pages without a DOCTYPE",
                f"{len(no_doctype)} page(s) omit <!DOCTYPE html>, which triggers quirks-mode "
                "rendering.",
                "Start every HTML document with <!DOCTYPE html>.",
                urls_evidence(no_doctype),
            )
        )
    if multi_title:
        findings.append(
            Finding(
                MH,
                "title_multiple",
                Severity.LOW,
                "Pages with more than one title tag",
                f"{len(multi_title)} page(s) contain multiple <title> elements; engines may "
                "pick either.",
                "Keep a single <title> in <head>; check for duplicate injection by plugins.",
                urls_evidence(multi_title),
            )
        )
    return findings
