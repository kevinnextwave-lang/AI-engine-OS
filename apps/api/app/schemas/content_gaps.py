"""Content gap responses (Milestone 5E)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.content_gaps import ContentGapType
from app.models.gaps import GapConfidence, GapStatus


class ContentGapView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    prompt_id: uuid.UUID | None
    topic: str
    gap_type: ContentGapType
    competitor_evidence: dict[str, Any]
    customer_coverage: dict[str, Any]
    opportunity_score: float = Field(description="0–100; scoring components in evidence")
    confidence: GapConfidence
    status: GapStatus
    note: str | None
    analysis_version: str
    window_days: int
    analyzed_at: datetime
    created_at: datetime
    updated_at: datetime


class ContentGapListResponse(BaseModel):
    items: list[ContentGapView]
    total: int
    limit: int
    offset: int
    analyzed_at: datetime | None
    note: str


class ContentGapUpdateRequest(BaseModel):
    status: GapStatus | None = None
    note: str | None = Field(default=None, max_length=2000)


class ContentGapAnalyzeRequest(BaseModel):
    window_days: int = Field(default=90, ge=7, le=365)


class ContentGapAnalyzeResponse(BaseModel):
    project_id: uuid.UUID
    window_days: int
    eligible_responses: int
    topics_analyzed: int
    pages_considered: int
    gaps_written: int
    gaps_removed: int
    analyzed_at: datetime
    note: str
