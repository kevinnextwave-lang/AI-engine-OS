"""Competitor discovery candidates (Milestone 5B)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.core.urls import InvalidURLError, normalize_website_url
from app.models.competitor_candidates import CandidateSource, CandidateStatus


class CandidateView(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    domain: str | None
    reason: str
    evidence: dict[str, Any]
    confidence: float = Field(description="0–1")
    confidence_label: str
    source: CandidateSource
    status: CandidateStatus
    competitor_id: uuid.UUID | None
    discovery_version: str
    discovered_at: datetime
    reviewed_at: datetime | None
    reviewed_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class CandidateListResponse(BaseModel):
    items: list[CandidateView]
    total: int
    limit: int
    offset: int
    discovered_at: datetime | None


class DiscoverRequest(BaseModel):
    window_days: int = Field(default=90, ge=7, le=365)
    use_ai: bool = Field(default=True, description="Also ask the configured AI provider")


class DiscoverResponse(BaseModel):
    project_id: uuid.UUID
    responses_scanned: int
    observations: int
    candidates_written: int
    candidates_skipped_single_mention: int = Field(
        description="Names seen in only one response and by no other source — never promoted"
    )
    ai_used: bool
    ai_error: str | None
    discovered_at: datetime
    note: str


class AcceptRequest(BaseModel):
    website_url: str | None = Field(
        default=None, description="Required when the candidate has no known domain"
    )
    name: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("website_url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return normalize_website_url(value).url
        except InvalidURLError as exc:
            raise ValueError(str(exc)) from exc
