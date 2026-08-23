"""Entity optimization review responses (Milestone 6E)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.entity_reviews import ReviewStatus


class EntityReviewView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    entity_id: uuid.UUID | None
    agent_run_id: uuid.UUID | None
    review_key: str
    entity_type: str
    findings: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    confidence: str
    status: ReviewStatus
    analysis_version: str
    analyzed_at: datetime
    created_at: datetime
    updated_at: datetime


class EntityReviewListResponse(BaseModel):
    items: list[EntityReviewView]
    total: int
    limit: int
    offset: int


class EntityReviewUpdateRequest(BaseModel):
    status: ReviewStatus
