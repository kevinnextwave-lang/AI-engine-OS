"""Generation, deduplication, categorization and scoring — pure functions."""

from collections import Counter

from app.models.prompts import FunnelStage, PromptCategory, PromptIntent
from app.prompts.classify import classify
from app.prompts.generator import generate_candidates
from app.prompts.normalize import is_near_duplicate, normalize_text, similarity
from app.prompts.profile import BusinessProfile
from app.prompts.quality import WEIGHTS, priority_for, score_prompt

PROFILE = BusinessProfile(
    "Ledgerly",
    website="https://ledgerly.example",
    industry="Accounting software",
    products=["Ledgerly"],
    features=["automated invoicing", "expense tracking"],
    integrations=["Stripe", "Shopify"],
    target_audience=["small businesses", "startups"],
    competitors=["QuickBooks", "Xero"],
    geographic_market=["United Kingdom"],
)


# --- profile vocabulary ----------------------------------------------------------


def test_profile_derives_buyer_vocabulary() -> None:
    assert PROFILE.offerings[:3] == [
        "accounting software",
        "accounting platforms",
        "accounting tools",
    ]
    assert PROFILE.offerings_singular[1] == "accounting platform"
    assert PROFILE.brand_products == ["Ledgerly"]
    assert PROFILE.tasks == ["invoicing", "expense tracking"]
    assert PROFILE.geo_phrases == ["the United Kingdom"]
    agency = BusinessProfile("Pixel", services=["Web design agency"], geographic_market=["Berlin"])
    assert agency.offerings == ["web design agencies", "web design services"]
    assert agency.geo_phrases == ["Berlin"]


# --- generation -------------------------------------------------------------------


def test_generation_is_realistic_diverse_and_deterministic() -> None:
    cands = generate_candidates(PROFILE, max_total=60)
    texts = [c.text for c in cands]
    assert len(cands) == 60
    # every category represented, none dominating
    counts = Counter(c.category for c in cands)
    assert set(counts) == set(PromptCategory)
    assert max(counts.values()) <= 8
    # all funnel stages represented
    assert {c.funnel_stage for c in cands} == set(FunnelStage)
    # realistic natural-language questions from the spec's examples family
    assert "What are the best accounting software for small businesses?" in texts
    assert "What are the best alternatives to QuickBooks?" in texts
    assert "Which accounting platforms integrate with Shopify?" in texts
    assert "What accounting software support automated invoicing?" in texts
    # natural language, no keyword stuffing: every prompt is a sentence with a verb-ish length
    assert all(5 <= len(t.split()) <= 20 for t in texts)
    assert all(t[0].isupper() and t.endswith("?") for t in texts)
    # no exact or near duplicates
    norms = [normalize_text(t) for t in texts]
    assert len(set(norms)) == len(norms)
    for i, a in enumerate(texts):
        for b in texts[i + 1 :]:
            assert not is_near_duplicate(a, b), (a, b)
    # deterministic
    assert [c.text for c in generate_candidates(PROFILE, max_total=60)] == texts


def test_generation_skips_templates_without_inputs() -> None:
    minimal = BusinessProfile("Acme", industry="CRM software")
    cands = generate_candidates(minimal)
    texts = " ".join(c.text for c in cands)
    assert cands and "{" not in texts
    assert not any(
        c.category in (PromptCategory.COMPARISON, PromptCategory.ALTERNATIVE, PromptCategory.LOCAL)
        for c in cands
    )
    assert any("CRM software" in c.text for c in cands)


def test_generation_respects_category_filter_and_existing_prompts() -> None:
    only = generate_candidates(
        PROFILE, categories=[PromptCategory.PRICING, PromptCategory.COMPARISON]
    )
    assert {c.category for c in only} == {PromptCategory.PRICING, PromptCategory.COMPARISON}
    existing = ["What are the best accounting software for small businesses?"]
    again = generate_candidates(PROFILE, existing_texts=existing)
    assert existing[0] not in [c.text for c in again]
    assert all(not is_near_duplicate(c.text, existing[0]) for c in again)


# --- dedup -------------------------------------------------------------------------


def test_normalization_and_near_duplicates() -> None:
    assert (
        normalize_text("  What's the BEST  accounting software?? ")
        == "what s the best accounting software"
    )
    assert normalize_text("Café") == "cafe"
    assert is_near_duplicate(
        "Best accounting software for startups",
        "What is the best accounting software for startups?",
    )
    assert is_near_duplicate(
        "Best accounting platforms for startups?", "best accounting platform for startup"
    )
    assert not is_near_duplicate(
        "Best accounting software for startups", "How much does Xero cost per month?"
    )
    assert (
        similarity("a b c", "a b c") == 1.0
        and 0 < similarity("accounting software startups", "accounting software agencies") < 1
    )


# --- classification ---------------------------------------------------------------


def test_categorization_rules() -> None:
    cases = {
        "What are the best accounting platforms for small businesses?": (
            PromptCategory.RECOMMENDATION,
            PromptIntent.COMMERCIAL,
            FunnelStage.CONSIDERATION,
        ),
        "What are the best alternatives to QuickBooks?": (
            PromptCategory.ALTERNATIVE,
            PromptIntent.COMMERCIAL,
            FunnelStage.CONSIDERATION,
        ),
        "Which accounting platforms integrate with Stripe?": (
            PromptCategory.PRODUCT,
            PromptIntent.COMMERCIAL,
            FunnelStage.CONSIDERATION,
        ),
        "How much does Xero cost per month?": (
            PromptCategory.PRICING,
            PromptIntent.TRANSACTIONAL,
            FunnelStage.DECISION,
        ),
        "Xero vs QuickBooks for freelancers": (
            PromptCategory.COMPARISON,
            PromptIntent.COMMERCIAL,
            FunnelStage.CONSIDERATION,
        ),
        "Accounting firms near me in Paris": (
            PromptCategory.LOCAL,
            PromptIntent.COMMERCIAL,
            FunnelStage.DECISION,
        ),
        "How do I automate invoice reminders?": (
            PromptCategory.PROBLEM_SOLUTION,
            PromptIntent.INFORMATIONAL,
            FunnelStage.AWARENESS,
        ),
        "How do I cancel my QuickBooks subscription?": (
            PromptCategory.PROBLEM_SOLUTION,
            PromptIntent.INFORMATIONAL,
            FunnelStage.RETENTION,
        ),
        "Where do I sign up for a free trial of Ledgerly?": (
            PromptCategory.TRANSACTIONAL,
            PromptIntent.TRANSACTIONAL,
            FunnelStage.PURCHASE,
        ),
        "What are the trends in the accounting industry?": (
            PromptCategory.INDUSTRY,
            PromptIntent.INFORMATIONAL,
            FunnelStage.AWARENESS,
        ),
        "What is double-entry bookkeeping?": (
            PromptCategory.DISCOVERY,
            PromptIntent.INFORMATIONAL,
            FunnelStage.AWARENESS,
        ),
        "Ledgerly login page": (
            PromptCategory.DISCOVERY,
            PromptIntent.NAVIGATIONAL,
            FunnelStage.AWARENESS,
        ),
    }
    for text, (cat, intent, stage) in cases.items():
        c = classify(text)
        assert (c.category, c.intent, c.funnel_stage) == (cat, intent, stage), text


# --- quality scoring -----------------------------------------------------------------


def test_quality_score_rewards_specific_commercial_relevant_prompts() -> None:
    others = ["What is accounting software and how does it work?"]
    strong = score_prompt(
        "Ledgerly vs QuickBooks: which is better for small businesses in the United Kingdom?",
        PromptCategory.COMPARISON,
        PROFILE,
        others,
    )
    generic = score_prompt("What is software?", PromptCategory.DISCOVERY, PROFILE, others)
    assert strong.score > 80 > generic.score
    assert strong.priority == 1 and generic.priority >= 4
    bd = strong.breakdown
    assert bd["method"] == "prompt-quality-score/v1" and bd["weights"] == WEIGHTS
    assert bd["components"]["geographic_relevance"] == 1.0
    assert bd["signals"]["named_entity"] and bd["signals"]["qualifier"]
    assert generic.breakdown["components"]["relevance"] == 0.0


def test_quality_uniqueness_penalizes_near_copies_and_geo_is_optional() -> None:
    text = "What are the best accounting software for startups?"
    alone = score_prompt(text, PromptCategory.RECOMMENDATION, PROFILE, [])
    crowded = score_prompt(
        text,
        PromptCategory.RECOMMENDATION,
        PROFILE,
        ["What is the best accounting software for a startup?"],
    )
    assert (
        crowded.breakdown["components"]["uniqueness"] < alone.breakdown["components"]["uniqueness"]
    )
    assert crowded.score < alone.score
    no_geo = BusinessProfile("Ledgerly", industry="Accounting software")
    assert (
        score_prompt(text, PromptCategory.RECOMMENDATION, no_geo, []).breakdown["components"][
            "geographic_relevance"
        ]
        is None
    )
    assert [priority_for(s) for s in (90, 70, 55, 40, 10)] == [1, 2, 3, 4, 5]
