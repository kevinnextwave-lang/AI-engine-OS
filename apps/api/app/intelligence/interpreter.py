"""Stage 2 — AI-assisted interpretation, used only when Stage 1 leaves
judgements unknown (prose answers, ambiguous or hedged mentions).

The LLM must answer with JSON matching `LLMInterpretation`. Its output is
validated with Pydantic and then *merged* under strict rules: it may set
sentiment / recommendation strength / position for brands Stage 1 already
found, and add claims about known brands. It can never introduce new brands,
citations, or touch application state directly.
"""

import json
import re
from typing import Protocol

from pydantic import ValidationError

from app.ai.types import AIRequest
from app.intelligence.context import ParseContext
from app.intelligence.schema import (
    LLM_JSON_SCHEMA,
    Claim,
    LLMInterpretation,
    LLMMentionJudgement,
    ParsedResponse,
    RecommendationStrength,
    Sentiment,
)

MAX_RESPONSE_CHARS = 12_000
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I | re.M)


class Interpreter(Protocol):
    """Anything that turns a request into raw text (an AIProvider, or a test stub)."""

    async def interpret(self, request: AIRequest) -> str | None: ...


class ProviderInterpreter:
    """Adapts an `AIProvider` from the registry to the Interpreter protocol."""

    def __init__(self, provider, model: str) -> None:  # type: ignore[no-untyped-def]
        self._provider = provider
        self._model = model

    async def interpret(self, request: AIRequest) -> str | None:
        request.model = self._model
        response = await self._provider.generate(request)
        return response.response_text if response.succeeded else None


def needs_interpretation(parsed: ParsedResponse) -> bool:
    """True when Stage 1 could not settle sentiment/strength for some mention,
    or the answer is prose with mentions (no list positions)."""
    all_mentions = parsed.mentions + parsed.competitor_mentions
    if not all_mentions:
        return False
    unsettled = any(
        m.recommendation_strength == RecommendationStrength.UNKNOWN
        or m.sentiment in (Sentiment.UNKNOWN, Sentiment.NEUTRAL)
        for m in all_mentions
    )
    prose = not parsed.position_signals.answer_is_list
    return unsettled or prose


def build_request(text: str, ctx: ParseContext) -> AIRequest:
    names = ", ".join(b.name for b in ctx.all_brands)
    system = (
        "You analyze an AI assistant's answer about software products. Respond with JSON only, "
        "no prose, matching exactly this JSON schema:\n"
        + json.dumps(LLM_JSON_SCHEMA)
        + "\nRules: only judge the brands listed; never add other brands; set position only "
        "when the answer explicitly ranks options (else null); sentiment is about how the "
        "answer portrays the brand, and an absent brand must not appear at all."
    )
    prompt = f"Known brands: {names}\n\nANSWER:\n{text[:MAX_RESPONSE_CHARS]}"
    return AIRequest(
        model="", prompt=prompt, system_prompt=system, temperature=0.0, max_tokens=1500
    )


def parse_llm_json(raw: str) -> LLMInterpretation:
    """Strict parse; raises ValueError on malformed or off-schema output."""
    cleaned = _FENCE.sub("", raw.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError("top-level JSON must be an object")
    try:
        return LLMInterpretation.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"schema violation: {exc.errors()[0]['msg']}") from exc


def merge(parsed: ParsedResponse, llm: LLMInterpretation, ctx: ParseContext) -> ParsedResponse:
    """Apply validated LLM judgements to mentions Stage 1 found. Unknown brands
    and judgements for brands that are not present are ignored."""
    known = {b.name.lower(): b.name for b in ctx.all_brands}
    present = {m.brand_name for m in parsed.mentions + parsed.competitor_mentions}
    by_brand: dict[str, LLMMentionJudgement] = {}
    for j in llm.mentions:
        canonical = known.get(j.brand_name.lower())
        if canonical and canonical in present:
            by_brand[canonical] = j
    updated = parsed.model_copy(deep=True)
    for m in updated.mentions + updated.competitor_mentions:
        judged = by_brand.get(m.brand_name)
        if judged is None:
            continue
        j = judged
        if (
            m.sentiment in (Sentiment.UNKNOWN, Sentiment.NEUTRAL)
            and j.sentiment != Sentiment.UNKNOWN
        ):
            m.sentiment = j.sentiment
            m.source = "llm"
        if (
            m.recommendation_strength == RecommendationStrength.UNKNOWN
            and j.recommendation_strength != RecommendationStrength.UNKNOWN
        ):
            m.recommendation_strength = j.recommendation_strength
            m.source = "llm"
        # Positions only when the model says the ranking is explicit and Stage 1 had none.
        if m.position is None and llm.ranking_is_explicit and j.position is not None:
            m.position = j.position
            m.source = "llm"
    for r in updated.recommendations:
        judged = by_brand.get(r.name)
        if judged is None:
            continue
        j = judged
        if (
            r.strength == RecommendationStrength.UNKNOWN
            and j.recommendation_strength != RecommendationStrength.UNKNOWN
        ):
            r.strength = j.recommendation_strength
        if r.position is None and llm.ranking_is_explicit and j.position is not None:
            r.position = j.position
    existing = {(c.subject.lower(), c.predicate.lower(), c.object.lower()) for c in updated.claims}
    for c in llm.claims:
        subject = known.get(c.subject.lower())
        key = (c.subject.lower(), c.predicate.lower(), c.object.lower())
        if subject and key not in existing:
            updated.claims.append(
                Claim(
                    subject=subject,
                    predicate=c.predicate,
                    object=c.object,
                    confidence=min(c.confidence, 0.9),
                    context="",
                )
            )
    brand_mentions = updated.mentions
    if (
        brand_mentions
        and llm.overall_sentiment != Sentiment.UNKNOWN
        and updated.sentiment in (Sentiment.UNKNOWN, Sentiment.NEUTRAL)
    ):
        updated.sentiment = llm.overall_sentiment
    positions = [m.position for m in updated.mentions if m.position is not None]
    updated.position_signals.brand_position = min(positions) if positions else None
    updated.stage2_used = True
    return updated
