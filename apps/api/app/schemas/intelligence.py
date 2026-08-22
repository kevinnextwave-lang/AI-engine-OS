import uuid
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, Field

from app.schemas.common import APIModel


class MentionView(APIModel):
    id: uuid.UUID
    brand_name: str
    mention_text: str
    position: int | None
    sentiment: str
    recommendation_strength: str
    context: str
    source: str
    parser_version: str


class CompetitorMentionView(MentionView):
    brand_name: str = Field(validation_alias=AliasChoices("competitor_name", "brand_name"))
    competitor_id: uuid.UUID | None


class ClaimView(APIModel):
    id: uuid.UUID
    subject: str
    predicate: str
    object: str
    confidence: float
    context: str
    parser_version: str


class CitationView(APIModel):
    id: uuid.UUID
    url: str | None
    domain: str | None
    anchor_text: str | None
    citation_position: int | None
    citation_type: str
    parser_version: str


class ResponseIntelligenceView(APIModel):
    prompt_run_id: uuid.UUID
    ai_response_id: uuid.UUID
    parser_version: str | None
    parsed_at: datetime | None
    summary: dict[str, Any] | None
    mentions: list[MentionView]
    competitor_mentions: list[CompetitorMentionView]
    claims: list[ClaimView]
    citations: list[CitationView]


class ReprocessResponse(APIModel):
    reprocessed: int
    parser_version: str
