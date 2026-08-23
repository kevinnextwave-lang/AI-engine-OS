"""Competitive insights responses (Milestone 5D)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.insights import InsightConfidence, InsightImpact, InsightType


class InsightView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    competitor_id: uuid.UUID
    insight_type: InsightType
    title: str
    description: str
    evidence: dict[str, Any]
    confidence: InsightConfidence
    impact: InsightImpact
    strength: float = Field(description="0–100 ordering magnitude, not a quality score")
    analysis_version: str
    window_days: int
    analyzed_at: datetime
    created_at: datetime
    updated_at: datetime


class InsightListResponse(BaseModel):
    items: list[InsightView]
    total: int
    limit: int
    offset: int
    analyzed_at: datetime | None
    note: str


class InsightAnalyzeRequest(BaseModel):
    window_days: int = Field(default=90, ge=7, le=365)


class InsightAnalyzeResponse(BaseModel):
    project_id: uuid.UUID
    window_days: int
    eligible_responses: int
    competitors_analyzed: int
    insights_written: int
    insights_removed: int
    analyzed_at: datetime
    note: str
