"""Stage 1 + Stage 2 parsing over representative fixtures; strict schema validation."""

import json
import uuid

import pytest

from app.ai.types import AIRequest
from app.intelligence import PARSER_VERSION
from app.intelligence.context import ParseContext, brand_from
from app.intelligence.deterministic import deterministic_parse, parse_structure
from app.intelligence.interpreter import merge, needs_interpretation, parse_llm_json
from app.intelligence.pipeline import parse_response
from app.intelligence.schema import (
    CitationType,
    LLMInterpretation,
    Mention,
    ParsedResponse,
    RecommendationStrength,
    Sentiment,
)
from tests.intelligence import fixtures as fx

QB_ID, XERO_ID = uuid.uuid4(), uuid.uuid4()
CTX = ParseContext(
    project_id=uuid.uuid4(),
    brand=brand_from("Ledgerly", "https://www.ledgerly.example"),
    competitors=[
        brand_from("QuickBooks", "https://quickbooks.intuit.com", QB_ID),
        brand_from("Xero", "https://www.xero.com", XERO_ID),
    ],
)


def by_brand(parsed: ParsedResponse, name: str) -> list[Mention]:
    return [m for m in parsed.mentions + parsed.competitor_mentions if m.brand_name == name]


# --- structure ------------------------------------------------------------------------------


def test_structure_detects_headings_lists_and_source_lists() -> None:
    s = parse_structure(fx.LIST_RECOMMENDATIONS)
    kinds = [(b.kind, b.index) for b in s.blocks]
    assert ("item", 1) in kinds and ("item", 3) in kinds and ("source", 3) in kinds
    assert s.ordered_list and s.list_items == 3 and s.has_source_list
    assert parse_structure(fx.MULTI_COMPETITORS).blocks[0].kind == "heading"
    assert (
        parse_structure(fx.BULLET_LIST).list_items == 3
        and not parse_structure(fx.BULLET_LIST).ordered_list
    )


# --- list recommendations -------------------------------------------------------------------


def test_list_recommendations_positions_and_strengths() -> None:
    p = deterministic_parse(fx.LIST_RECOMMENDATIONS, CTX)
    assert p.parser_version == PARSER_VERSION
    assert p.position_signals.answer_is_list and p.position_signals.ordered_list
    assert p.position_signals.brand_position == 3 and p.position_signals.brand_mentioned
    assert p.position_signals.first_mentioned_brand == "QuickBooks"
    assert p.position_signals.competitors_mentioned == ["QuickBooks", "Xero"]
    assert [(r.name, r.position) for r in p.recommendations] == [
        ("QuickBooks", 1),
        ("Xero", 2),
        ("Ledgerly", 3),
    ]
    qb = by_brand(p, "QuickBooks")[0]
    assert qb.position == 1 and qb.sentiment == Sentiment.MIXED  # popular + expensive
    xero = by_brand(p, "Xero")[0]
    assert xero.recommendation_strength == RecommendationStrength.MODERATE  # "a good option"
    assert all(m.is_competitor for m in p.competitor_mentions) and not any(
        m.is_competitor for m in p.mentions
    )


def test_bullet_list_gives_positions_and_strong_recommendation() -> None:
    p = deterministic_parse(fx.BULLET_LIST, CTX)
    led = by_brand(p, "Ledgerly")[0]
    assert led.position == 1 and led.recommendation_strength == RecommendationStrength.STRONG
    assert led.sentiment == Sentiment.POSITIVE and p.sentiment == Sentiment.POSITIVE
    assert by_brand(p, "Xero")[0].position == 2
    assert p.position_signals.brand_position == 1


# --- prose -----------------------------------------------------------------------------------


def test_prose_never_invents_positions() -> None:
    p = deterministic_parse(fx.PROSE, CTX)
    assert not p.position_signals.answer_is_list
    assert all(m.position is None for m in p.mentions + p.competitor_mentions)
    assert p.position_signals.brand_position is None
    assert all(r.position is None for r in p.recommendations)
    led = by_brand(p, "Ledgerly")[0]
    assert led.recommendation_strength == RecommendationStrength.WEAK  # "one option"
    qb = by_brand(p, "QuickBooks")[0]
    assert qb.sentiment == Sentiment.MIXED  # industry standard + pricey
    assert by_brand(p, "Xero")[0].recommendation_strength == RecommendationStrength.MODERATE


# --- citations ----------------------------------------------------------------------------------


def test_markdown_links_urls_and_domain_references() -> None:
    p = deterministic_parse(fx.MARKDOWN_CITATIONS, CTX)
    by_type = {c.citation_type: c for c in p.citations}
    assert by_type[CitationType.MARKDOWN_LINK].domain in {"ledgerly.example", "g2.com"}
    md = [c for c in p.citations if c.citation_type == CitationType.MARKDOWN_LINK]
    assert {c.anchor_text for c in md} == {"pricing page", "G2"}
    assert by_type[CitationType.EXPLICIT_URL].url == "https://example.org/accounting-tools-2025"
    assert (
        by_type[CitationType.DOMAIN_REFERENCE].domain == "capterra.com"
        and by_type[CitationType.DOMAIN_REFERENCE].url is None
    )
    assert all(c.citation_position is None for c in p.citations)


def test_source_list_citations_have_positions() -> None:
    p = deterministic_parse(fx.LIST_RECOMMENDATIONS, CTX)
    sources = [c for c in p.citations if c.citation_type == CitationType.SOURCE_LIST]
    assert [(c.citation_position, c.domain) for c in sources] == [
        (1, "xero.com"),
        (2, "quickbooks.intuit.com"),
        (3, "g2.com"),
    ]
    assert (
        sources[0].anchor_text == "Xero pricing"
        and sources[0].url == "https://www.xero.com/pricing"
    )
    assert sources[2].url is None


# --- multiple competitors / ambiguous / negative / no brand ---------------------------------


def test_multiple_competitors_and_in_passing_brand_mention() -> None:
    p = deterministic_parse(fx.MULTI_COMPETITORS, CTX)
    assert p.position_signals.competitors_mentioned == ["QuickBooks", "Xero"]
    assert by_brand(p, "QuickBooks")[0].position == 1 and by_brand(p, "Xero")[0].position == 2
    # Ledgerly appears only in prose, in passing → mentioned but unranked
    led = by_brand(p, "Ledgerly")
    assert led and all(m.position is None for m in led)
    assert p.position_signals.brand_position is None and p.position_signals.brand_mentioned
    # Competitors named mid-sentence (not as the item subject) get no position for that mention
    passing = [m for m in by_brand(p, "Xero") if "integrate with Ledgerly" in m.context]
    assert passing and passing[0].position is None
    claims = {(c.subject, c.predicate.split()[0]) for c in p.claims}
    assert ("Xero", "integrate") in claims or ("QuickBooks", "integrate") in claims


def test_ambiguous_mention_is_left_unknown_for_stage_two() -> None:
    p = deterministic_parse(fx.AMBIGUOUS, CTX)
    led = by_brand(p, "Ledgerly")[0]
    assert led.recommendation_strength in (
        RecommendationStrength.UNKNOWN,
        RecommendationStrength.MODERATE,
    )
    assert led.position is None
    assert needs_interpretation(p)


def test_negative_mention() -> None:
    p = deterministic_parse(fx.NEGATIVE, CTX)
    led = by_brand(p, "Ledgerly")[0]
    assert (
        led.sentiment == Sentiment.NEGATIVE
        and led.recommendation_strength == RecommendationStrength.NONE
    )
    assert p.sentiment == Sentiment.NEGATIVE
    assert any(
        c.subject == "Ledgerly" and c.predicate == "lacks" and "payroll" in c.object
        for c in p.claims
    )


def test_no_brand_mention_is_unknown_not_negative() -> None:
    p = deterministic_parse(fx.NO_BRAND, CTX)
    assert p.mentions == [] and p.competitor_mentions == []
    assert p.sentiment == Sentiment.UNKNOWN
    assert p.position_signals.brand_mentioned is False and p.position_signals.brand_position is None
    assert p.recommendations == [] and not needs_interpretation(p)
    empty = deterministic_parse(fx.EMPTY, CTX)
    assert empty.sentiment == Sentiment.UNKNOWN and empty.citations == []


def test_brand_aliases_from_domain_are_detected() -> None:
    p = deterministic_parse("Try ledgerly.example for invoicing; it is great.", CTX)
    assert by_brand(p, "Ledgerly") and by_brand(p, "Ledgerly")[0].mention_text == "ledgerly.example"


# --- stage 2: strict schema -----------------------------------------------------------------


def test_llm_json_strict_validation() -> None:
    good = {
        "overall_sentiment": "positive",
        "mentions": [
            {
                "brand_name": "Ledgerly",
                "sentiment": "positive",
                "recommendation_strength": "moderate",
                "position": None,
            }
        ],
        "claims": [],
        "ranking_is_explicit": False,
    }
    assert isinstance(parse_llm_json(json.dumps(good)), LLMInterpretation)
    assert (
        parse_llm_json("```json\n" + json.dumps(good) + "\n```").mentions[0].brand_name
        == "Ledgerly"
    )
    for bad in (
        "not json at all",
        "[]",
        json.dumps({**good, "extra_field": 1}),
        json.dumps({**good, "overall_sentiment": "ecstatic"}),
        json.dumps(
            {
                **good,
                "mentions": [
                    {
                        "brand_name": "Ledgerly",
                        "sentiment": "positive",
                        "recommendation_strength": "huge",
                    }
                ],
            }
        ),
        json.dumps(
            {
                **good,
                "mentions": [
                    {
                        "brand_name": "Ledgerly",
                        "sentiment": "positive",
                        "recommendation_strength": "weak",
                        "position": 0,
                    }
                ],
            }
        ),
        json.dumps({**good, "claims": [{"subject": "", "predicate": "is", "object": "x"}]}),
    ):
        with pytest.raises(ValueError):
            parse_llm_json(bad)


def test_merge_only_refines_known_present_brands() -> None:
    parsed = deterministic_parse(fx.AMBIGUOUS, CTX)
    llm = LLMInterpretation(
        overall_sentiment=Sentiment.NEUTRAL,
        mentions=[
            {
                "brand_name": "ledgerly",
                "sentiment": "positive",
                "recommendation_strength": "weak",
                "position": 1,
            },
            {
                "brand_name": "FreshBooks",
                "sentiment": "positive",
                "recommendation_strength": "strong",
                "position": 2,
            },
            {
                "brand_name": "QuickBooks",
                "sentiment": "negative",
                "recommendation_strength": "none",
            },  # not present in text
        ],
        claims=[
            {
                "subject": "Ledgerly",
                "predicate": "depends on",
                "object": "how much automation you want",
                "confidence": 0.95,
            }
        ],
        ranking_is_explicit=False,
    )
    merged = merge(parsed, llm, CTX)
    led = by_brand(merged, "Ledgerly")[0]
    assert led.sentiment == Sentiment.POSITIVE and led.source == "llm"
    assert led.position is None  # ranking not explicit → no invented rank
    assert not by_brand(merged, "FreshBooks") and not by_brand(merged, "QuickBooks")
    assert any(
        c.subject == "Ledgerly" and c.predicate == "depends on" and c.confidence == 0.9
        for c in merged.claims
    )
    assert merged.stage2_used and merged.parser_version == PARSER_VERSION
    # deterministic judgements are not overridden
    strong = deterministic_parse(fx.BULLET_LIST, CTX)
    kept = merge(
        strong,
        LLMInterpretation(
            mentions=[
                {
                    "brand_name": "Ledgerly",
                    "sentiment": "negative",
                    "recommendation_strength": "none",
                }
            ]
        ),
        CTX,
    )
    assert by_brand(kept, "Ledgerly")[0].recommendation_strength == RecommendationStrength.STRONG


class StubInterpreter:
    def __init__(self, raw: str | None) -> None:
        self.raw = raw
        self.requests: list[AIRequest] = []

    async def interpret(self, request: AIRequest) -> str | None:
        self.requests.append(request)
        return self.raw


async def test_pipeline_uses_stage_two_only_when_needed_and_survives_malformed_output() -> None:
    stub = StubInterpreter(
        json.dumps(
            {
                "overall_sentiment": "positive",
                "mentions": [
                    {
                        "brand_name": "Ledgerly",
                        "sentiment": "positive",
                        "recommendation_strength": "moderate",
                    }
                ],
                "claims": [],
                "ranking_is_explicit": False,
            }
        )
    )
    p = await parse_response(fx.AMBIGUOUS, CTX, stub)
    assert p.stage2_used and len(stub.requests) == 1
    assert "Known brands: Ledgerly, QuickBooks, Xero" in stub.requests[0].prompt
    assert by_brand(p, "Ledgerly")[0].sentiment == Sentiment.POSITIVE

    untouched = StubInterpreter("{}")
    p = await parse_response(fx.NO_BRAND, CTX, untouched)
    assert not p.stage2_used and untouched.requests == []

    broken = StubInterpreter("Sure! Here is my analysis: Ledgerly is great.")
    p = await parse_response(fx.AMBIGUOUS, CTX, broken)
    assert not p.stage2_used and p.stage2_error is not None and "invalid JSON" in p.stage2_error
    assert by_brand(p, "Ledgerly")  # deterministic results kept

    off_schema = StubInterpreter(json.dumps({"overall_sentiment": "positive", "surprise": True}))
    p = await parse_response(fx.AMBIGUOUS, CTX, off_schema)
    assert p.stage2_error is not None and "schema violation" in p.stage2_error

    silent = StubInterpreter(None)
    p = await parse_response(fx.AMBIGUOUS, CTX, silent)
    assert p.stage2_error == "interpreter returned no output"
