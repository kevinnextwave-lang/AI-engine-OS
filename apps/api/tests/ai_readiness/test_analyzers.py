"""Each analyzer over controlled in-memory pages; scoring transparency."""

import uuid
from datetime import UTC, datetime

from app.ai_readiness.analyzers import (
    analyze_authority,
    analyze_comparison,
    analyze_content_structure,
    analyze_entity_clarity,
    analyze_evidence,
    analyze_factual_consistency,
    analyze_faq,
    analyze_product_clarity,
    run_analyzers,
)
from app.ai_readiness.scoring import METHOD, WEIGHTS, compute_score
from app.ai_readiness.signals import specificity
from app.models.entities import EntityObservation
from app.models.seo import Severity
from tests.ai_readiness.helpers import by_code, codes, context, entity, org_entity, page

LOREM = (
    "We help teams work better together with thoughtful tools and great support. " * 12
).strip()


# --- entity clarity -----------------------------------------------------------------


def test_entity_clarity_detects_all_signals() -> None:
    home = page(
        "/",
        title="Acme – Widgets for agencies",
        description="Acme builds reporting widgets for marketing agencies across Europe.",
        text="Acme is built for marketing agencies. We are based in Paris and serve clients "
        "worldwide. Contact us at hello@acme.com.",
        headings=[(1, "Acme"), (2, "Our products")],
    )
    about = page("/about", text=LOREM)
    org = org_entity(description="Acme makes widgets.", address={"@ref": True}, telephone="+33 1")
    res = analyze_entity_clarity(context([home, about], organization=org))
    assert codes(res.findings) == {"entity_clarity_complete"}
    checks = res.score_inputs["entity_clarity"]["checks"]
    assert all(checks.values()) and len(checks) == 6


def test_entity_clarity_reports_each_missing_signal_with_recommendation() -> None:
    home = page("/", title="Welcome", text="Hello world, nothing specific here.")
    res = analyze_entity_clarity(context([home], organization=None, project_name="Acme"))
    found = codes(res.findings)
    assert found == {
        "entity_company_name_unclear",
        "entity_organization_description_unclear",
        "entity_products_or_services_unclear",
        "entity_target_audience_unclear",
        "entity_geographic_coverage_unclear",
        "entity_contact_information_unclear",
    }
    aud = by_code(res.findings, "entity_target_audience_unclear")
    assert "Who it's for" in aud.recommendation and aud.severity == Severity.MEDIUM
    assert by_code(res.findings, "entity_company_name_unclear").severity == Severity.HIGH
    assert not any(f.description.lower().count("rank") for f in res.findings)


# --- product clarity ----------------------------------------------------------------


def test_product_clarity_aspects_and_target_customer_recommendation() -> None:
    full = page(
        "/products/widget",
        headings=[(1, "Widget"), (2, "Features"), (2, "Use cases")],
        text=(
            "Widget is built for small agencies that report weekly. Plans start at $29 per month. "
            "It integrates with Slack and HubSpot. " + LOREM
        ),
        schema={"Product"},
    )
    bare = page("/products/gadget", headings=[(1, "Gadget")], text=LOREM)
    res = analyze_product_clarity(context([full, bare]))
    cov = res.score_inputs["product_clarity"]["coverage"]
    assert cov["name"] == 1.0 and cov["description"] == 1.0
    assert cov["features"] == cov["pricing"] == cov["use_cases"] == 0.5
    assert cov["target_customers"] == cov["integrations"] == 0.5
    tc = by_code(res.findings, "product_target_customers_unclear")
    assert tc.title == "Product pages do not clearly identify the target customer"
    assert tc.recommendation.startswith('Add an explicit "Who it\'s for" section')
    assert tc.evidence["urls"] == [bare.url]
    # pricing/integrations absence is informational only
    assert by_code(res.findings, "product_pricing_unclear").severity == Severity.INFO
    assert by_code(res.findings, "product_integrations_unclear").severity == Severity.INFO


def test_product_clarity_not_applicable_without_product_pages() -> None:
    res = analyze_product_clarity(context([page("/", text=LOREM)]))
    assert codes(res.findings) == {"product_pages_not_found"}
    assert res.score_inputs["product_clarity"] == {"applicable": False}


# --- authority ------------------------------------------------------------------------


def test_authority_signals_on_articles() -> None:
    now = datetime.now(UTC)
    person = entity("Person", "Jane Doe", jobTitle="Head of Data", same_as=["https://x.com/j"])
    article = entity(
        "Article",
        "Post",
        author={"@ref": True, "name": "Jane Doe"},
        publisher={"@ref": True},
        datePublished="2024-01-01",
        dateModified="2024-02-01",
    )
    complete = page(
        "/blog/post",
        text="By Jane Doe\n" + LOREM,
        author="Jane Doe",
        published=now,
        modified=now,
        schema={"Article"},
        entities=[person, article],
    )
    anonymous = page("/blog/other", text=LOREM, schema={"BlogPosting"})
    res = analyze_authority(context([complete, anonymous]))
    cov = res.score_inputs["authority"]["coverage"]
    assert cov["author"] == 0.5 and cov["published_date"] == 0.5 and cov["credentials"] == 0.5
    assert cov["organization"] == 0.5  # publisher on the first article only, no project org
    missing_author = by_code(res.findings, "article_author_missing")
    assert missing_author.evidence["urls"] == [anonymous.url]
    assert "citation-readiness" in missing_author.description


def test_authority_not_applicable_without_articles() -> None:
    res = analyze_authority(context([page("/", text=LOREM)]))
    assert codes(res.findings) == {"article_pages_not_found"}


# --- evidence ------------------------------------------------------------------------


def test_evidence_kinds_detected() -> None:
    rich = page(
        "/blog/report",
        text=(
            "We surveyed 1,200 customers in 2024. 63% reported faster reporting. According to a "
            "Gartner study, agencies spend 10 hours per week on reports. Sources: [1] Gartner. "
            "Read the Acme case study. Rated 4.8/5 on G2. " + LOREM
        ),
        external_links=2,
    )
    res = analyze_evidence(context([rich]))
    checks = res.score_inputs["evidence"]["checks"]
    assert all(checks.values()), checks
    assert codes(res.findings) == {"evidence_summary"}


def test_evidence_absent_everywhere() -> None:
    res = analyze_evidence(context([page("/", text=LOREM)]))
    assert "evidence_statistics_absent" in codes(res.findings)
    assert by_code(res.findings, "evidence_statistics_absent").severity == Severity.LOW
    assert by_code(res.findings, "evidence_research_absent").severity == Severity.INFO
    assert not any(v for v in res.score_inputs["evidence"]["checks"].values())


# --- faq ------------------------------------------------------------------------------


def test_faq_schema_content_and_structures() -> None:
    with_schema = page(
        "/faq",
        schema={"FAQPage"},
        headings=[(2, "What is Acme?"), (2, "How much does it cost?"), (2, "Is there a trial?")],
    )
    without = page(
        "/help",
        headings=[
            (1, "Frequently asked questions"),
            (2, "Can I cancel?"),
            (2, "Do you offer refunds?"),
            (2, "Where are you based?"),
        ],
    )
    res = analyze_faq(context([with_schema, without]))
    assert codes(res.findings) == {
        "faq_schema_present",
        "faq_content_without_schema",
        "faq_question_structures",
    }
    assert by_code(res.findings, "faq_content_without_schema").evidence["urls"] == [without.url]
    assert res.score_inputs["faq"]["checks"] == {"faq_schema": True, "faq_content": True}
    none = analyze_faq(context([page("/", text=LOREM)]))
    assert codes(none.findings) == {"faq_absent"}


# --- comparison -----------------------------------------------------------------------


def test_comparison_pages_recorded_not_judged() -> None:
    pages = [
        page("/blog/acme-vs-other", title="Acme vs Other"),
        page("/pricing", title="Pricing"),
        page("/blog/best-widgets", title="The best widgets in 2024"),
        page("/blog/plain", title="Plain post"),
    ]
    res = analyze_comparison(context(pages))
    f = by_code(res.findings, "comparison_pages_present")
    assert f.severity == Severity.INFO and f.evidence["count"] == 3
    assert set(f.evidence["by_pattern"]) == {"vs", "pricing", "best"}
    assert res.score_inputs["comparison"]["applicable"] is False
    assert codes(analyze_comparison(context([pages[3]])).findings) == {"comparison_pages_absent"}


# --- content structure / specificity -----------------------------------------------------


def test_specificity_measurement() -> None:
    facts = specificity(
        "Acme launched Widget in March 2021. It processes 2,000 reports per day. "
        "We love making tools. Our team is friendly and nice to everyone.",
        ["Widget"],
        ["Acme"],
    )
    assert facts.sentences == 4 and facts.specific_sentences == 2
    assert facts.numbers >= 1 and facts.dates == 1
    assert facts.product_mentions == 1 and facts.organization_mentions == 1


def test_content_structure_flags_generic_thin_and_unstructured_pages() -> None:
    generic = page(
        "/blog/generic", text=LOREM * 4, headings=[(1, "Hi")]
    )  # ~500 words, no specifics
    thin = page("/products/thin", text="Short.", headings=[(1, "Thin")])
    res = analyze_content_structure(context([generic, thin]))
    assert codes(res.findings) == {
        "content_specificity_low",
        "content_thin_pages",
        "content_unstructured",
        "content_specificity_summary",
    }
    assert by_code(res.findings, "content_thin_pages").evidence["urls"] == [thin.url]
    assert (
        by_code(res.findings, "content_specificity_low").evidence["pages"][0]["url"] == generic.url
    )
    assert (
        "not a quality verdict" in by_code(res.findings, "content_specificity_summary").description
    )


# --- factual consistency -------------------------------------------------------------------


def test_factual_consistency_uses_entity_conflicts() -> None:
    conflict = EntityObservation(
        project_id=uuid.uuid4(),
        code="entity_value_conflict",
        severity="medium",
        title="t",
        description="d",
        entity_type="Organization",
        entity_name="Acme",
        evidence={"property": "foundingDate", "values": [{"value": "2018"}, {"value": "2019"}]},
    )
    res = analyze_factual_consistency(context([page("/")], conflicts=[conflict], compared=4))
    f = by_code(res.findings, "entity_facts_inconsistent")
    assert f.evidence["conflicts"][0]["values"] == ["2018", "2019"]
    assert (
        analyze_factual_consistency(context([page("/")], compared=4)).findings[0].code
        == "entity_facts_consistent"
    )
    assert (
        analyze_factual_consistency(context([page("/")], compared=0)).findings[0].code
        == "entity_facts_not_comparable"
    )


# --- scoring ----------------------------------------------------------------------------------


def test_score_is_weighted_transparent_and_redistributes_inapplicable_weight() -> None:
    inputs = {
        "entity_clarity": {"applicable": True, "checks": {"a": True, "b": False}},
        "faq": {"applicable": True, "checks": {"faq_schema": False, "faq_content": True}},
        "product_clarity": {"applicable": False},
        "authority": {"applicable": False},
        "evidence": {"applicable": False},
        "content_structure": {"applicable": False},
        "factual_consistency": {"applicable": False},
        "comparison": {"applicable": False, "informational": True, "pages": 2},
    }
    result = compute_score(inputs)
    # (0.5×25 + 0.5×5) / 30 = 0.5
    assert result.score == 50.0
    assert result.breakdown["method"] == METHOD and result.breakdown["weights"] == WEIGHTS
    assert result.breakdown["applicable_weight"] == 30.0
    assert (
        result.breakdown["categories"]["entity_clarity"]["how"] == "1 of 2 entity signals present"
    )
    assert result.breakdown["categories"]["comparison"]["weight"] == 0.0
    assert "Not an industry standard" in result.breakdown["note"]


def test_full_run_on_strong_site_scores_high_and_never_claims_ranking() -> None:
    now = datetime.now(UTC)
    org = org_entity(description="Acme makes widgets.", address={"@ref": True}, telephone="+33 1")
    home = page(
        "/",
        title="Acme – Widgets",
        description="Acme builds reporting widgets for agencies, trusted by 500 teams.",
        text="Acme is built for marketing agencies. Based in Paris, serving clients "
        "worldwide. Email hello@acme.com. Rated 4.8/5 on G2.",
        headings=[(1, "Acme"), (2, "Products")],
    )
    product = page(
        "/products/widget",
        headings=[
            (1, "Widget"),
            (2, "Features"),
            (2, "Use cases"),
            (2, "What is Widget?"),
            (2, "How does pricing work?"),
            (2, "Can I cancel?"),
        ],
        text="Widget is built for small agencies. Plans start at $29 per month. Integrates "
        "with Slack. In 2024, 1,200 customers saved 10 hours per week. " + LOREM,
        schema={"Product", "FAQPage"},
        entities=[entity("Product", "Widget")],
    )
    person = entity("Person", "Jane Doe", jobTitle="Head of Data")
    article = page(
        "/blog/report",
        text="By Jane Doe\nWe surveyed 1,200 customers in 2024; 63% reported faster reporting. "
        "Sources: [1]. See the Acme case study. " + LOREM,
        author="Jane Doe",
        published=now,
        modified=now,
        schema={"Article"},
        entities=[
            person,
            entity("Article", "Report", publisher={"@ref": True}, dateModified="2024-01-01"),
        ],
        external_links=1,
    )
    findings, inputs = run_analyzers(
        context([home, product, article], organization=org, compared=3)
    )
    score = compute_score(inputs)
    assert score.score >= 75, score.breakdown
    text = " ".join(f.title + f.description + f.recommendation for f in findings).lower()
    assert "rank you higher" not in text and "will rank" not in text
