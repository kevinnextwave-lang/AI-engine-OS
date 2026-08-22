"""Citation gaps (Milestone 4C)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.gaps import GapConfidence, GapStatus, GapType

Priority = Literal["high", "medium", "low"]


class CitationGapView(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    source_domain_id: uuid.UUID
    source_page_id: uuid.UUID | None
    domain: str
    display_name: str
    source_type: str
    gap_type: GapType
    priority: Priority
    brand_citations: int
    competitor_citations: int
    competitors: dict[str, int] = Field(description="Competitor name → citations from this source")
    relevant_response_count: int
    opportunity_score: float = Field(description="Citation Opportunity Score 0–100")
    confidence: GapConfidence
    explanation: str
    status: GapStatus
    note: str | None
    evidence: dict[str, Any] = Field(
        description="Scoring inputs, components, source relevance, top pages"
    )
    analysis_version: str
    analyzed_at: datetime
    created_at: datetime
    updated_at: datetime


class CitationGapListResponse(BaseModel):
    items: list[CitationGapView]
    total: int
    limit: int
    offset: int
    analyzed_at: datetime | None = Field(description="When the project was last analysed")


class CitationGapUpdateRequest(BaseModel):
    status: GapStatus | None = None
    note: str | None = Field(default=None, max_length=2000)


class GapSufficiency(BaseModel):
    eligible_responses: int
    relevant_prompts: int
    sources_observed: int
    window_days: int
    sufficient: bool
    note: str


class CitationGapSummary(BaseModel):
    project_id: uuid.UUID
    analyzed_at: datetime | None
    analysis_version: str
    total: int
    by_gap_type: dict[str, int]
    by_status: dict[str, int]
    by_confidence: dict[str, int]
    by_source_type: dict[str, int]
    by_priority: dict[str, int]
    actionable: int = Field(description="Open gaps with at least low confidence and score ≥ 40")
    top_opportunities: list[CitationGapView]
    competitors_ahead: dict[str, int] = Field(
        description="Competitor → number of sources where it is cited and the brand is not"
    )
    data: GapSufficiency
    method: str


class AnalyzeResponse(BaseModel):
    project_id: uuid.UUID
    window_days: int
    eligible_responses: int
    total_prompts: int
    sources_observed: int
    gaps_written: int
    gaps_removed: int
    analyzed_at: datetime
