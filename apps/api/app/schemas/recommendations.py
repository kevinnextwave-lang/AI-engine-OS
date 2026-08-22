"""Recommendations (Milestone 4E)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.recommendations import (
    RecommendationPriority,
    RecommendationStatus,
    RecommendationType,
)


class RecommendationExplanation(BaseModel):
    observed: str = Field(description="1. What did we observe?")
    why_it_matters: str = Field(description="2. Why does it matter?")
    investigate: str = Field(description="3. What could the customer investigate?")
    evidence_summary: str = Field(description="4. What evidence supports it?")
    confidence_statement: str = Field(description="5. How confident are we?")


class RecommendationView(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    recommendation_type: RecommendationType
    title: str
    description: str
    explanation: RecommendationExplanation
    evidence: dict[str, Any]
    priority: RecommendationPriority
    opportunity_score: float
    confidence: str
    status: RecommendationStatus
    note: str | None
    citation_gap_id: uuid.UUID | None
    source_key: str
    generator_version: str
    generated_at: datetime
    reviewed_at: datetime | None
    reviewed_by_user_id: uuid.UUID | None
    allowed_transitions: list[RecommendationStatus] = Field(
        description="Statuses a reviewer may move this recommendation to"
    )
    created_at: datetime
    updated_at: datetime


class RecommendationListResponse(BaseModel):
    items: list[RecommendationView]
    total: int
    limit: int
    offset: int
    generated_at: datetime | None


class RecommendationSummary(BaseModel):
    project_id: uuid.UUID
    total: int
    by_status: dict[str, int]
    by_priority: dict[str, int]
    by_type: dict[str, int]
    awaiting_review: int = Field(description="new + reviewing")
    generated_at: datetime | None
    generator_version: str
    note: str


class ReviewRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class RecommendationUpdateRequest(BaseModel):
    status: RecommendationStatus | None = None
    note: str | None = Field(default=None, max_length=2000)


class GenerateResponse(BaseModel):
    project_id: uuid.UUID
    generated: int
    removed: int
    skipped_insufficient: int
    research_considered: bool = Field(
        description="Whether 'create original research' was warranted"
    )
    research_reasons: list[str] = Field(
        description="Why research was not recommended, if it was not"
    )
    generated_at: datetime
