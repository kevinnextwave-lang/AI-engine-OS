"""Strict Pydantic schemas. The same models validate deterministic output and
LLM JSON; `extra="forbid"` so free-form keys are rejected."""

import enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Sentiment(enum.StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class RecommendationStrength(enum.StrEnum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    NONE = "none"
    UNKNOWN = "unknown"


class CitationType(enum.StrEnum):
    EXPLICIT_URL = "explicit_url"
    MARKDOWN_LINK = "markdown_link"
    DOMAIN_REFERENCE = "domain_reference"
    SOURCE_LIST = "source_list"
    UNKNOWN = "unknown"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


Position = Annotated[int, Field(ge=1, le=500)]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class Mention(Strict):
    """A brand or competitor mention. `brand_name` is the canonical known name."""

    brand_name: str = Field(min_length=1, max_length=200)
    mention_text: str = Field(min_length=1, max_length=500)
    context: str = Field(default="", max_length=2000)
    position: Position | None = None
    sentiment: Sentiment = Sentiment.UNKNOWN
    recommendation_strength: RecommendationStrength = RecommendationStrength.UNKNOWN
    is_competitor: bool = False
    # Where the judgement came from: "deterministic" | "llm"
    source: str = Field(default="deterministic", pattern=r"^(deterministic|llm)$")


class Claim(Strict):
    subject: str = Field(min_length=1, max_length=200)
    predicate: str = Field(min_length=1, max_length=100)
    object: str = Field(min_length=1, max_length=500)
    confidence: Confidence = 0.5
    context: str = Field(default="", max_length=2000)


class Citation(Strict):
    url: str | None = Field(default=None, max_length=2048)
    domain: str | None = Field(default=None, max_length=253)
    anchor_text: str | None = Field(default=None, max_length=500)
    citation_position: Position | None = None
    citation_type: CitationType = CitationType.UNKNOWN

    @field_validator("domain")
    @classmethod
    def _lower(cls, v: str | None) -> str | None:
        return v.lower() if v else v


class Recommendation(Strict):
    """A named option the answer puts forward, in answer order (known brands only)."""

    name: str = Field(min_length=1, max_length=200)
    position: Position | None = None
    strength: RecommendationStrength = RecommendationStrength.UNKNOWN


class PositionSignals(Strict):
    answer_is_list: bool = False
    list_items: int = 0
    ordered_list: bool = False
    brand_position: Position | None = None
    first_mentioned_brand: str | None = None
    brand_mentioned: bool = False
    competitors_mentioned: list[str] = Field(default_factory=list)


class ParsedResponse(Strict):
    parser_version: str
    mentions: list[Mention] = Field(default_factory=list)
    competitor_mentions: list[Mention] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    # Overall sentiment towards the brand; "unknown" when the brand is absent.
    sentiment: Sentiment = Sentiment.UNKNOWN
    position_signals: PositionSignals = Field(default_factory=PositionSignals)
    stage2_used: bool = False
    stage2_error: str | None = None


# --- LLM output contract (Stage 2) -------------------------------------------------------


class LLMMentionJudgement(Strict):
    brand_name: str = Field(min_length=1, max_length=200)
    sentiment: Sentiment
    recommendation_strength: RecommendationStrength
    position: Position | None = None
    rationale: str = Field(default="", max_length=500)


class LLMClaim(Strict):
    subject: str = Field(min_length=1, max_length=200)
    predicate: str = Field(min_length=1, max_length=100)
    object: str = Field(min_length=1, max_length=500)
    confidence: Confidence = 0.5


class LLMInterpretation(Strict):
    """What the LLM may return. Anything outside this shape is rejected."""

    overall_sentiment: Sentiment = Sentiment.UNKNOWN
    mentions: list[LLMMentionJudgement] = Field(default_factory=list, max_length=50)
    claims: list[LLMClaim] = Field(default_factory=list, max_length=50)
    ranking_is_explicit: bool = False


LLM_JSON_SCHEMA = LLMInterpretation.model_json_schema()
