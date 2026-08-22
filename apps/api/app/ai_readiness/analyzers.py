"""Readiness analyzers. Each returns findings plus the check results that feed
the score, so the breakdown can show exactly which signals were detected.

Wording rule: observations describe *signals* ("AI readability signal",
"entity clarity", "citation readiness"). They never claim a ranking effect.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.ai_readiness import signals as sig
from app.ai_readiness.context import PageSnapshot, ReadinessContext
from app.ai_readiness.findings import Finding, urls_evidence
from app.models.ai_readiness import ReadinessCategory as C
from app.models.seo import Severity

S = Severity

MIN_DESCRIPTION_WORDS = 40
MIN_PRODUCT_WORDS = 80
THIN_PAGE_WORDS = 150
SPECIFICITY_LOW = 0.10
SPECIFICITY_TARGET = 0.30


@dataclass
class AnalyzerResult:
    findings: list[Finding] = field(default_factory=list)
    # Category -> {"checks": {name: bool|float}, "applicable": bool, ...}
    score_inputs: dict[str, Any] = field(default_factory=dict)


def _share(n: int, total: int) -> float:
    return n / total if total else 0.0


def _sev_by_share(share: float, high: S = S.MEDIUM, low: S = S.LOW) -> S:
    return high if share > 0.5 else low


# --- entity clarity -----------------------------------------------------------------


def analyze_entity_clarity(ctx: ReadinessContext) -> AnalyzerResult:
    res = AnalyzerResult()
    org = ctx.organization
    props = org.properties if org else {}
    sigs = props.get("_signals", {}) if org else {}
    home = ctx.homepage
    about = ctx.pages_of("about")
    key_pages = [p for p in [home, *about, *ctx.pages_of("contact")] if p]
    key_text = "\n".join(p.text for p in key_pages)
    home_product_text = "\n".join(p.text for p in [home, *ctx.pages_of("product", "service")] if p)

    checks: dict[str, bool] = {}
    ev: dict[str, Any] = {}

    # company name
    name_in_schema = bool(org and sigs.get("name_source") == "schema")
    name_in_title = bool(home and home.title and ctx.project_name.lower() in home.title.lower())
    checks["company_name"] = name_in_schema or name_in_title
    ev["company_name"] = {"schema": name_in_schema, "homepage_title": name_in_title}

    # description
    desc_sources = []
    if org and org.description:
        desc_sources.append("organization_schema")
    if home and home.meta_description and len(home.meta_description.split()) >= 8:
        desc_sources.append("homepage_meta_description")
    if any(p.word_count >= MIN_DESCRIPTION_WORDS for p in about):
        desc_sources.append("about_page")
    checks["organization_description"] = bool(desc_sources)
    ev["organization_description"] = {"sources": desc_sources}

    # products / services
    offering_pages = ctx.pages_of("product", "service")
    offering_schema = any({"Product", "Service"} & p.schema_types for p in ctx.pages)
    offering_headings = any(
        sig.FEATURES_HEADING.search(t)
        or any(w in t.lower() for w in ("product", "service", "solution"))
        for p in ctx.pages
        for _, t in p.headings
    )
    checks["products_or_services"] = bool(offering_pages) or offering_schema or offering_headings
    ev["products_or_services"] = {
        "offering_pages": len(offering_pages),
        "schema": offering_schema,
        "headings": offering_headings,
    }

    # audience
    audience_hits = sig.snippets(sig.AUDIENCE, home_product_text)
    checks["target_audience"] = bool(audience_hits)
    ev["target_audience"] = {"examples": audience_hits}

    # geography
    geo_schema = bool(props.get("address") or props.get("areaServed"))
    geo_text = sig.snippets(sig.GEOGRAPHY, key_text) or sig.snippets(sig.POSTAL_ADDRESS, key_text)
    checks["geographic_coverage"] = geo_schema or bool(geo_text)
    ev["geographic_coverage"] = {"schema": geo_schema, "examples": geo_text}

    # contact
    contact = {
        "contact_page": bool(ctx.pages_of("contact")),
        "schema_contact": bool(
            props.get("telephone") or props.get("email") or props.get("contactPoint")
        ),
        "emails_in_text": sigs.get("text_emails", [])
        or sorted(set(sig.EMAIL.findall(key_text)))[:5],
        "phones_in_text": sigs.get("text_phones", []),
    }
    checks["contact_information"] = any(
        [
            contact["contact_page"],
            contact["schema_contact"],
            contact["emails_in_text"],
            contact["phones_in_text"],
        ]
    )
    ev["contact_information"] = contact

    missing = [k for k, ok in checks.items() if not ok]
    labels = {
        "company_name": (
            "Company name is not stated in a machine-readable way",
            "The organization name was not found in Organization schema, and the homepage title "
            "does not contain the project name. AI systems infer the entity from these places "
            "first.",
            "Add Organization (or LocalBusiness) JSON-LD on the homepage with `name`, `url` and "
            "`sameAs`, and include the company name in the homepage <title>.",
            S.HIGH,
        ),
        "organization_description": (
            "No clear organization description",
            "Neither the Organization schema, the homepage meta description nor an About page "
            "states what the company is and does.",
            "Add a 1–2 sentence `description` to the Organization schema and an About page that "
            "says what the company does, for whom, and since when.",
            S.MEDIUM,
        ),
        "products_or_services": (
            "Products or services are not identifiable",
            "No product/service pages, Product/Service schema, or offering-related headings were "
            "found. Without them the site's offering is unclear to AI systems and readers alike.",
            "Create one page per product or service with a descriptive H1, and mark them up with "
            "Product or Service schema.",
            S.HIGH,
        ),
        "target_audience": (
            "Target audience is not stated explicitly",
            "The homepage and offering pages contain no phrase that names who the product or "
            "service is for (e.g. 'built for small agencies').",
            "Add a short 'Who it's for' section naming the primary customer segments and their "
            "typical situations.",
            S.MEDIUM,
        ),
        "geographic_coverage": (
            "Geographic coverage is not stated",
            "No address, `areaServed`, or phrase such as 'based in', 'serving', or 'worldwide' "
            "was found on the homepage, About or Contact pages.",
            "State where the company is based and which regions it serves, in text and in the "
            "Organization schema (`address`, `areaServed`).",
            S.LOW,
        ),
        "contact_information": (
            "Contact information is not discoverable",
            "No Contact page, schema `telephone`/`email`/`contactPoint`, or visible e-mail/phone "
            "was found on key pages.",
            "Add a Contact page with e-mail and phone in text, and mirror them in Organization "
            "schema `contactPoint`.",
            S.MEDIUM,
        ),
    }
    for key in missing:
        title, desc, rec, sev = labels[key]
        res.findings.append(
            Finding(C.ENTITY_CLARITY, f"entity_{key}_unclear", sev, title, desc, rec, ev[key])
        )
    if not missing:
        res.findings.append(
            Finding(
                C.ENTITY_CLARITY,
                "entity_clarity_complete",
                S.INFO,
                "Entity clarity signals are all present",
                "Company name, description, offering, audience, geography and contact details "
                "were each detected from schema or key pages.",
                "No action needed. Keep these in sync when the company changes.",
                ev,
            )
        )
    res.score_inputs[C.ENTITY_CLARITY.value] = {"applicable": True, "checks": checks}
    return res


# --- product clarity ----------------------------------------------------------------

PRODUCT_ASPECTS = (
    "name",
    "description",
    "features",
    "pricing",
    "use_cases",
    "target_customers",
    "integrations",
)


def _product_aspects(page: PageSnapshot) -> dict[str, bool]:
    heading_text = "\n".join(t for _, t in page.headings)
    text = page.text
    product_entities = [e for e in page.entities if e.entity_type in ("Product", "Service")]
    return {
        "name": bool(page.h1) or any(e.name for e in product_entities),
        "description": page.word_count >= MIN_PRODUCT_WORDS
        or any(e.description for e in product_entities),
        "features": bool(sig.FEATURES_HEADING.search(heading_text)),
        "pricing": bool(sig.PRICING.search(text))
        or any(e.properties.get("offers") for e in product_entities),
        "use_cases": bool(sig.USE_CASES.search(heading_text) or sig.USE_CASES.search(text)),
        "target_customers": bool(sig.AUDIENCE.search(text)),
        "integrations": bool(sig.INTEGRATIONS.search(text)),
    }


def analyze_product_clarity(ctx: ReadinessContext) -> AnalyzerResult:
    res = AnalyzerResult()
    pages = ctx.pages_of("product", "service")
    if not pages:
        res.findings.append(
            Finding(
                C.PRODUCT_CLARITY,
                "product_pages_not_found",
                S.INFO,
                "No product or service pages identified",
                "No page was classified as a product or service page (by path, schema or "
                "headings), so product clarity was not assessed.",
                "If the site sells something, give each offering a dedicated page under "
                "/products/ or /services/ with Product or Service schema.",
                {},
            )
        )
        res.score_inputs[C.PRODUCT_CLARITY.value] = {"applicable": False}
        return res

    per_page = {p: _product_aspects(p) for p in pages}
    coverage = {
        a: _share(sum(1 for v in per_page.values() if v[a]), len(pages)) for a in PRODUCT_ASPECTS
    }
    labels = {
        "name": (
            "Product pages without a clear product name",
            "No H1 and no Product/Service schema name.",
            "Put the product name in the H1 and in Product schema `name`.",
        ),
        "description": (
            "Product pages with little descriptive text",
            f"Fewer than {MIN_PRODUCT_WORDS} words and no schema description.",
            "Add a plain-language paragraph stating what the product is and what problem it "
            "solves.",
        ),
        "features": (
            "Product pages without a features section",
            "No heading mentioning features, capabilities, benefits or how it works.",
            "Add a 'Features' or 'How it works' section with one heading per capability.",
        ),
        "pricing": (
            "Product pages without pricing information",
            "No price, plan, 'starting at' or 'request a quote' phrase was found. Absence may be "
            "intentional; it is recorded as a signal, not a defect.",
            "If prices are public, show them or link to a pricing page; otherwise state how "
            "pricing works (e.g. 'quote-based').",
        ),
        "use_cases": (
            "Product pages without use cases",
            "No 'use cases', 'how teams use', 'helps you' or similar phrasing.",
            "Add 2–4 concrete use cases naming the situation and the outcome.",
        ),
        "target_customers": (
            "Product pages do not clearly identify the target customer",
            "No phrase naming the intended customer (e.g. 'built for agencies', 'for developers').",
            'Add an explicit "Who it\'s for" section describing the primary customer segments '
            "and use cases.",
        ),
        "integrations": (
            "Product pages without integration information",
            "No mention of integrations, 'works with', API or connectors. Not every product "
            "integrates; this is recorded as a signal only.",
            "If integrations exist, list them by name with a short description of each.",
        ),
    }
    for aspect in PRODUCT_ASPECTS:
        lacking = [p.url for p, v in per_page.items() if not v[aspect]]
        if not lacking:
            continue
        title, desc, rec = labels[aspect]
        share = _share(len(lacking), len(pages))
        informational = aspect in ("pricing", "integrations")
        res.findings.append(
            Finding(
                C.PRODUCT_CLARITY,
                f"product_{aspect}_unclear",
                S.INFO if informational else _sev_by_share(share, S.MEDIUM, S.LOW),
                title,
                f"{len(lacking)} of {len(pages)} product/service page(s): {desc}",
                rec,
                {**urls_evidence(lacking), "share": round(share, 2)},
            )
        )
    res.findings.append(
        Finding(
            C.PRODUCT_CLARITY,
            "product_clarity_summary",
            S.INFO,
            "Product clarity coverage",
            f"{len(pages)} product/service page(s) analyzed; share of pages with each aspect "
            "is listed in evidence.",
            "Use the per-aspect observations above to fill the gaps.",
            {"pages": len(pages), "coverage": {k: round(v, 2) for k, v in coverage.items()}},
        )
    )
    res.score_inputs[C.PRODUCT_CLARITY.value] = {
        "applicable": True,
        "pages": len(pages),
        "coverage": coverage,
    }
    return res


# --- authority (author information) ---------------------------------------------------

AUTHOR_ASPECTS = (
    "author",
    "author_bio",
    "organization",
    "credentials",
    "published_date",
    "modified_date",
)


def _author_aspects(page: PageSnapshot, ctx: ReadinessContext) -> dict[str, bool]:
    persons = [e for e in page.entities if e.entity_type == "Person"]
    articles = [
        e
        for e in page.entities
        if e.entity_type in ("Article", "BlogPosting", "NewsArticle", "TechArticle")
    ]
    text = page.text
    author = (
        bool(page.author)
        or bool(persons)
        or bool(sig.BYLINE.search(text))
        or any(a.properties.get("author") for a in articles)
    )
    bio = any(
        p.description or p.properties.get("jobTitle") or p.url or p.same_as for p in persons
    ) or bool(sig.AUTHOR_BIO.search(text))
    organization = any(a.properties.get("publisher") for a in articles) or bool(ctx.organization)
    credentials = any(
        p.properties.get("jobTitle") or p.properties.get("hasCredential") for p in persons
    ) or bool(sig.CREDENTIALS.search(text[:3000]))
    published = (
        bool(page.published_at)
        or any(a.properties.get("datePublished") for a in articles)
        or bool(sig.DATE_TEXT.search(text[:1500]))
    )
    modified = bool(page.modified_at) or any(a.properties.get("dateModified") for a in articles)
    return {
        "author": author,
        "author_bio": bio,
        "organization": organization,
        "credentials": credentials,
        "published_date": published,
        "modified_date": modified,
    }


def analyze_authority(ctx: ReadinessContext) -> AnalyzerResult:
    res = AnalyzerResult()
    pages = ctx.pages_of("article")
    if not pages:
        res.findings.append(
            Finding(
                C.AUTHORITY,
                "article_pages_not_found",
                S.INFO,
                "No article or blog pages identified",
                "No page carries Article/BlogPosting schema, an author, a publication date, or "
                "lives under a blog/news path, so author information was not assessed.",
                "If the site publishes content, mark articles up with Article schema including "
                "`author`, `datePublished` and `publisher`.",
                {},
            )
        )
        res.score_inputs[C.AUTHORITY.value] = {"applicable": False}
        return res
    per_page = {p: _author_aspects(p, ctx) for p in pages}
    coverage = {
        a: _share(sum(1 for v in per_page.values() if v[a]), len(pages)) for a in AUTHOR_ASPECTS
    }
    labels = {
        "author": (
            "Articles without an identifiable author",
            S.MEDIUM,
            "Name the author in a byline and in Article schema `author` (a Person with `name`).",
        ),
        "author_bio": (
            "Articles without an author bio",
            S.LOW,
            "Add a short 'About the author' block (role, expertise, link to profile) and a Person "
            "schema with `jobTitle` and `sameAs`.",
        ),
        "organization": (
            "Articles without a publishing organization",
            S.LOW,
            "Add `publisher` (Organization) to the Article schema.",
        ),
        "credentials": (
            "Authors without stated credentials",
            S.LOW,
            "State the author's role or qualification (e.g. 'Head of Data, 12 years in "
            "analytics').",
        ),
        "published_date": (
            "Articles without a publication date",
            S.MEDIUM,
            "Show the publication date in text and in `datePublished` / article:published_time.",
        ),
        "modified_date": (
            "Articles without a last-updated date",
            S.INFO,
            "Add `dateModified` when articles are revised so freshness is explicit.",
        ),
    }
    for aspect in AUTHOR_ASPECTS:
        lacking = [p.url for p, v in per_page.items() if not v[aspect]]
        if not lacking:
            continue
        title, sev, rec = labels[aspect]
        share = _share(len(lacking), len(pages))
        res.findings.append(
            Finding(
                C.AUTHORITY,
                f"article_{aspect}_missing",
                sev if share > 0.5 or sev == S.INFO else S.LOW,
                title,
                f"{len(lacking)} of {len(pages)} article page(s) lack this signal. Author "
                "identity, credentials and dates are citation-readiness signals that help "
                "readers and AI systems attribute content.",
                rec,
                {**urls_evidence(lacking), "share": round(share, 2)},
            )
        )
    res.score_inputs[C.AUTHORITY.value] = {
        "applicable": True,
        "pages": len(pages),
        "coverage": coverage,
    }
    return res


# --- evidence -------------------------------------------------------------------------

EVIDENCE_KINDS = {
    "statistics": sig.STATISTIC,
    "research": sig.RESEARCH,
    "original_data": sig.ORIGINAL_DATA,
    "citations": sig.CITATION,
    "case_studies": sig.CASE_STUDY,
    "customer_evidence": sig.CUSTOMER_EVIDENCE,
}


def analyze_evidence(ctx: ReadinessContext) -> AnalyzerResult:
    res = AnalyzerResult()
    content_pages = [p for p in ctx.pages if p.word_count >= 50]
    kinds: dict[str, list[str]] = {k: [] for k in EVIDENCE_KINDS}
    kinds["references"] = []
    examples: dict[str, list[str]] = {k: [] for k in kinds}
    for p in content_pages:
        for kind, pattern in EVIDENCE_KINDS.items():
            if pattern.search(p.text):
                kinds[kind].append(p.url)
                if len(examples[kind]) < 3:
                    examples[kind].extend(sig.snippets(pattern, p.text, limit=1))
        if any(not ln.is_nofollow and "social" not in (ln.href or "") for ln in p.external_links):
            kinds["references"].append(p.url)
    if ctx.pages_of("case_study"):
        kinds["case_studies"].extend(
            p.url for p in ctx.pages_of("case_study") if p.url not in kinds["case_studies"]
        )

    present = {k: len(v) for k, v in kinds.items()}
    labels = {
        "statistics": (
            "No statistics or quantified claims found",
            "Add concrete figures (results, sizes, time saved) where claims are made.",
        ),
        "research": (
            "No references to research or studies found",
            "Cite studies, surveys or reports that support key claims, with links.",
        ),
        "original_data": (
            "No original data or first-party research found",
            "Publish findings from your own data (benchmarks, surveys) — a strong "
            "citation-readiness signal.",
        ),
        "citations": (
            "No explicit sources or citations found",
            "Add a 'Sources' section or inline citations to articles.",
        ),
        "references": (
            "No outbound references on content pages",
            "Link to the external sources you rely on; unlinked claims are harder to verify.",
        ),
        "case_studies": (
            "No case studies found",
            "Publish case studies with the customer, problem, approach and measured outcome.",
        ),
        "customer_evidence": (
            "No customer evidence found",
            "Add testimonials, review ratings or named customers where they exist.",
        ),
    }
    for kind, (title, rec) in labels.items():
        if present[kind]:
            continue
        res.findings.append(
            Finding(
                C.EVIDENCE,
                f"evidence_{kind}_absent",
                S.LOW if kind in ("statistics", "customer_evidence", "references") else S.INFO,
                title,
                f"None of {len(content_pages)} content page(s) contains this kind of evidence "
                "(lexical detection).",
                rec,
                {"content_pages": len(content_pages)},
            )
        )
    res.findings.append(
        Finding(
            C.EVIDENCE,
            "evidence_summary",
            S.INFO,
            "Evidence signals detected",
            "Pages per evidence kind (statistics, research, original data, citations, outbound "
            "references, case studies, customer evidence).",
            "Strengthen the kinds with zero or few pages.",
            {"pages_per_kind": present, "examples": {k: v for k, v in examples.items() if v}},
        )
    )
    res.score_inputs[C.EVIDENCE.value] = {
        "applicable": bool(content_pages),
        "checks": {k: bool(v) for k, v in present.items()},
    }
    return res


# --- FAQ --------------------------------------------------------------------------------


def analyze_faq(ctx: ReadinessContext) -> AnalyzerResult:
    res = AnalyzerResult()
    schema_pages = [p.url for p in ctx.pages if "FAQPage" in p.schema_types]
    heading_pages: list[str] = []
    qa_pages: list[dict[str, Any]] = []
    for p in ctx.pages:
        texts = [t for _, t in p.headings]
        questions = [t for t in texts if sig.QUESTION_HEADING.match(t)]
        if any(sig.FAQ_HEADING.search(t) for t in texts) and p.url not in heading_pages:
            heading_pages.append(p.url)
        if len(questions) >= 3:
            qa_pages.append({"url": p.url, "questions": len(questions), "sample": questions[:3]})
    content_without_schema = [
        u for u in {*heading_pages, *(q["url"] for q in qa_pages)} if u not in schema_pages
    ]
    if schema_pages:
        res.findings.append(
            Finding(
                C.FAQ,
                "faq_schema_present",
                S.INFO,
                "FAQPage schema present",
                f"{len(schema_pages)} page(s) declare FAQPage schema.",
                "No action needed; keep questions and answers identical in schema and text.",
                urls_evidence(schema_pages),
            )
        )
    if content_without_schema:
        res.findings.append(
            Finding(
                C.FAQ,
                "faq_content_without_schema",
                S.LOW,
                "FAQ-style content without FAQPage schema",
                f"{len(content_without_schema)} page(s) have FAQ headings or 3+ question "
                "headings but no FAQPage markup.",
                "Add FAQPage JSON-LD whose Question/Answer pairs mirror the visible text.",
                urls_evidence(sorted(content_without_schema)),
            )
        )
    if not schema_pages and not heading_pages and not qa_pages:
        res.findings.append(
            Finding(
                C.FAQ,
                "faq_absent",
                S.LOW,
                "No FAQ content found",
                "No FAQPage schema, FAQ headings or question-and-answer heading structures "
                "were detected. Explicit Q&A is a content-clarity signal that maps directly "
                "to how people ask questions.",
                "Add an FAQ section to key product/service pages answering the 5–10 questions "
                "customers actually ask, and mark it up with FAQPage schema.",
                {},
            )
        )
    if qa_pages:
        res.findings.append(
            Finding(
                C.FAQ,
                "faq_question_structures",
                S.INFO,
                "Question-and-answer structures",
                f"{len(qa_pages)} page(s) use 3+ question-style headings.",
                "No action needed.",
                {"pages": qa_pages[:25], "count": len(qa_pages)},
            )
        )
    res.score_inputs[C.FAQ.value] = {
        "applicable": True,
        "checks": {
            "faq_schema": bool(schema_pages),
            "faq_content": bool(heading_pages or qa_pages),
        },
    }
    return res


# --- comparison -------------------------------------------------------------------------


def analyze_comparison(ctx: ReadinessContext) -> AnalyzerResult:
    res = AnalyzerResult()
    patterns = {
        "vs": r"\b(vs\.?|versus)\b",
        "alternative": r"\balternatives?\b",
        "compare": r"\bcompar(e|ison)s?\b",
        "best": r"\bbest\b",
        "pricing": r"\bpricing\b",
    }
    matched: dict[str, list[str]] = {k: [] for k in patterns}
    for p in ctx.pages_of("comparison"):
        hay = f"{p.title or ''} {p.h1 or ''} {p.path}"
        for key, pat in patterns.items():
            if re.search(pat, hay, re.I):
                matched[key].append(p.url)
    total = len(ctx.pages_of("comparison"))
    if total:
        res.findings.append(
            Finding(
                C.COMPARISON,
                "comparison_pages_present",
                S.INFO,
                "Comparison-style pages present",
                f"{total} page(s) have comparison patterns (vs, alternative, compare, best, "
                "pricing) in their title, H1 or path. Presence is recorded, not judged.",
                "Keep comparisons factual and dated; state the criteria used.",
                {"by_pattern": {k: v[:25] for k, v in matched.items() if v}, "count": total},
            )
        )
    else:
        res.findings.append(
            Finding(
                C.COMPARISON,
                "comparison_pages_absent",
                S.INFO,
                "No comparison-style pages found",
                "No page title, H1 or path matches comparison patterns. This is informational.",
                "Optional: if prospects compare you with alternatives, a factual comparison "
                "page answers that question directly.",
                {},
            )
        )
    res.score_inputs[C.COMPARISON.value] = {
        "applicable": False,
        "informational": True,
        "pages": total,
    }
    return res


# --- content structure / specificity -----------------------------------------------------


def analyze_content_structure(ctx: ReadinessContext) -> AnalyzerResult:
    res = AnalyzerResult()
    product_names = [
        e.name
        for p in ctx.pages
        for e in p.entities
        if e.entity_type in ("Product", "Service") and e.name
    ]
    org_names = [ctx.organization.name] if ctx.organization and ctx.organization.name else []
    org_names.append(ctx.project_name)
    scored: list[tuple[PageSnapshot, sig.SpecificityFacts]] = []
    for p in ctx.pages:
        if p.word_count < 50:
            continue
        scored.append((p, sig.specificity(p.text, list(dict.fromkeys(product_names)), org_names)))
    if not scored:
        res.score_inputs[C.CONTENT_STRUCTURE.value] = {"applicable": False}
        return res

    low = [(p, f) for p, f in scored if p.word_count >= 300 and f.ratio < SPECIFICITY_LOW]
    thin = [
        p for p in ctx.pages_of("product", "service", "article") if p.word_count < THIN_PAGE_WORDS
    ]
    no_headings = [p for p in ctx.pages if p.word_count >= 300 and len(p.headings) < 2]
    if low:
        res.findings.append(
            Finding(
                C.CONTENT_STRUCTURE,
                "content_specificity_low",
                _sev_by_share(_share(len(low), len(scored)), S.MEDIUM, S.LOW),
                "Pages with few specific statements",
                f"{len(low)} page(s) of 300+ words have under {int(SPECIFICITY_LOW * 100)}% of "
                "sentences containing a number, date, product or organization name. Generic "
                "text gives AI systems and readers little to cite.",
                "Replace vague claims with specifics: named products, numbers, dates, "
                "locations and the organizations involved.",
                {
                    "pages": [
                        {
                            "url": p.url,
                            "specific_ratio": round(f.ratio, 2),
                            "sentences": f.sentences,
                        }
                        for p, f in low[:25]
                    ],
                    "count": len(low),
                },
            )
        )
    if thin:
        res.findings.append(
            Finding(
                C.CONTENT_STRUCTURE,
                "content_thin_pages",
                S.LOW,
                "Thin product, service or article pages",
                f"{len(thin)} page(s) have fewer than {THIN_PAGE_WORDS} words of main content.",
                "Expand with what the page is about, for whom, and concrete details.",
                urls_evidence([p.url for p in thin]),
            )
        )
    if no_headings:
        res.findings.append(
            Finding(
                C.CONTENT_STRUCTURE,
                "content_unstructured",
                S.LOW,
                "Long pages without heading structure",
                f"{len(no_headings)} page(s) of 300+ words have fewer than two headings.",
                "Break content into sections with descriptive H2/H3 headings.",
                urls_evidence([p.url for p in no_headings]),
            )
        )
    avg_ratio = sum(f.ratio for _, f in scored) / len(scored)
    totals: Counter[str] = Counter()
    for _, f in scored:
        totals.update(
            {
                "numbers": f.numbers,
                "dates": f.dates,
                "named_entities": f.named_entities,
                "product_mentions": f.product_mentions,
                "organization_mentions": f.organization_mentions,
            }
        )
    res.findings.append(
        Finding(
            C.CONTENT_STRUCTURE,
            "content_specificity_summary",
            S.INFO,
            "Content specificity measurements",
            f"Average share of specific sentences across {len(scored)} page(s): "
            f"{avg_ratio:.0%}. Counts of numbers, dates, named entities, product and "
            "organization mentions are in evidence. These are measurements, not a quality verdict.",
            "Use the low-specificity list to prioritize rewrites.",
            {"pages": len(scored), "avg_specific_ratio": round(avg_ratio, 3), **totals},
        )
    )
    res.score_inputs[C.CONTENT_STRUCTURE.value] = {
        "applicable": True,
        "pages": len(scored),
        "avg_specific_ratio": avg_ratio,
        "specificity_target": SPECIFICITY_TARGET,
        "thin_share": _share(len(thin), max(1, len(ctx.pages_of("product", "service", "article")))),
        "unstructured_share": _share(len(no_headings), len(scored)),
    }
    return res


# --- factual consistency -----------------------------------------------------------------


def analyze_factual_consistency(ctx: ReadinessContext) -> AnalyzerResult:
    res = AnalyzerResult()
    conflicts = ctx.entity_conflicts
    if conflicts:
        res.findings.append(
            Finding(
                C.FACTUAL_CONSISTENCY,
                "entity_facts_inconsistent",
                S.MEDIUM if len(conflicts) > 2 else S.LOW,
                "Entity facts differ between pages",
                f"{len(conflicts)} property value conflict(s) were found between structured-data "
                "declarations of the same entity (see entity consistency). Contradictory facts "
                "reduce entity clarity for any system reading the site.",
                "Decide the correct value for each property listed and use it on every page.",
                {
                    "conflicts": [
                        {
                            "entity_type": c.entity_type,
                            "entity_name": c.entity_name,
                            "property": c.evidence.get("property"),
                            "values": [v.get("value") for v in c.evidence.get("values", [])],
                        }
                        for c in conflicts[:25]
                    ],
                    "count": len(conflicts),
                },
            )
        )
    elif ctx.entities_compared:
        res.findings.append(
            Finding(
                C.FACTUAL_CONSISTENCY,
                "entity_facts_consistent",
                S.INFO,
                "No entity fact conflicts detected",
                f"{ctx.entities_compared} structured-data entities were compared across pages "
                "without contradictory values.",
                "No action needed.",
                {"entities_compared": ctx.entities_compared},
            )
        )
    else:
        res.findings.append(
            Finding(
                C.FACTUAL_CONSISTENCY,
                "entity_facts_not_comparable",
                S.INFO,
                "Not enough structured data to compare facts",
                "No named entities were extracted from structured data, so cross-page "
                "consistency could not be checked.",
                "Add Organization/Product schema so facts become machine-checkable.",
                {},
            )
        )
    res.score_inputs[C.FACTUAL_CONSISTENCY.value] = {
        "applicable": bool(ctx.entities_compared),
        "conflicts": len(conflicts),
        "entities_compared": ctx.entities_compared,
    }
    return res


ANALYZERS = (
    analyze_entity_clarity,
    analyze_product_clarity,
    analyze_authority,
    analyze_evidence,
    analyze_faq,
    analyze_comparison,
    analyze_content_structure,
    analyze_factual_consistency,
)


def run_analyzers(ctx: ReadinessContext) -> tuple[list[Finding], dict[str, Any]]:
    findings: list[Finding] = []
    inputs: dict[str, Any] = {}
    for analyzer in ANALYZERS:
        result = analyzer(ctx)
        findings.extend(result.findings)
        inputs.update(result.score_inputs)
    return findings, inputs
