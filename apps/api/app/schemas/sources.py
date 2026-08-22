"""Source profile (Milestone 4B)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SourceClassificationView(BaseModel):
    type: str
    confidence: float | None = Field(description="Combined evidence score of the chosen type")
    probabilities: dict[str, float]
    authority: bool
    threshold: float
    evidence: list[dict[str, Any]]
    classified_at: datetime | None


class SourceRelevanceView(BaseModel):
    name: str
    score: float
    scope: str
    components: dict[str, dict[str, float]]
    note: str


class CitedPageView(BaseModel):
    id: uuid.UUID
    url: str
    title: str | None
    citation_count: int
    last_seen_at: datetime


class CitedEntityView(BaseModel):
    name: str
    citations: int


class SourceDomainProfile(BaseModel):
    id: uuid.UUID
    domain: str
    display_name: str
    type: str
    classification: SourceClassificationView
    citation_count: int = Field(description="Citations across the projects you can access")
    global_citation_count: int = Field(description="Citations across all projects (count only)")
    projects_observed: int = Field(description="Your projects in which this source was cited")
    global_projects_observed: int
    pages_cited: int
    pages: list[CitedPageView]
    brands_cited: list[CitedEntityView]
    competitors_cited: list[CitedEntityView]
    first_seen_at: datetime
    last_seen_at: datetime
    relevance: SourceRelevanceView
