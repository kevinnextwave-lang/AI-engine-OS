"""Content brief responses (Milestone 6C)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.content_briefs import ContentBriefStatus, ContentType


class ContentBriefView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    agent_run_id: uuid.UUID | None
    source_key: str
    title: str
    content_type: ContentType
    target_prompt_ids: list[uuid.UUID]
    competitor_ids: list[uuid.UUID]
    objective: str
    search_intent: str
    audience: str
    differentiation: str
    outline: dict[str, Any]
    information_requirements: list[str]
    evidence_requirements: dict[str, Any]
    citation_opportunities: list[dict[str, Any]]
    entity_requirements: list[str]
    internal_link_recommendations: list[dict[str, Any]]
    confidence: str
    status: ContentBriefStatus
    created_at: datetime
    updated_at: datetime


class ContentBriefListResponse(BaseModel):
    items: list[ContentBriefView]
    total: int
    limit: int
    offset: int


class ContentBriefUpdateRequest(BaseModel):
    status: ContentBriefStatus | None = None
    title: str | None = Field(default=None, min_length=3, max_length=300)
    audience: str | None = Field(default=None, max_length=2000)
