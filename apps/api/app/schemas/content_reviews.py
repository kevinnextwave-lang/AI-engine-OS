"""Content optimization review responses (Milestone 6D)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.content_reviews import ReviewStatus


class ReviewView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    page_id: uuid.UUID
    agent_run_id: uuid.UUID | None
    score: float
    findings: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    proposed_changes: list[dict[str, Any]]
    confidence: str
    status: ReviewStatus
    analysis_version: str
    analyzed_at: datetime
    created_at: datetime
    updated_at: datetime


class ReviewListItem(BaseModel):
    id: uuid.UUID
    page_id: uuid.UUID
    page_url: str | None
    score: float
    confidence: str
    status: ReviewStatus
    findings_count: int
    changes_count: int
    pending_changes: int
    analyzed_at: datetime


class ReviewListResponse(BaseModel):
    items: list[ReviewListItem]
    total: int
    limit: int
    offset: int


class ReviewUpdateRequest(BaseModel):
    status: ReviewStatus


class ChangeDecisionRequest(BaseModel):
    action: Literal["accept", "edit", "reject"]
    text: str | None = Field(
        default=None,
        max_length=4000,
        description="Required for 'edit': the human-edited replacement text",
    )
