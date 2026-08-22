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


class CitationRelationshipView(BaseModel):
    entity_name: str
    relationship: str
    confidence: float


class CitationListItem(BaseModel):
    id: uuid.UUID
    url: str | None
    domain: str | None
    source_domain_id: uuid.UUID | None
    source_page_id: uuid.UUID | None
    source_type: str | None
    anchor_text: str | None
    citation_type: str
    citation_position: int | None
    cited_at: datetime | None = Field(description="When the AI response completed")
    prompt_id: uuid.UUID
    prompt: str
    prompt_run_id: uuid.UUID
    provider_key: str | None
    model_key: str | None
    relationships: list[CitationRelationshipView]


class CitationListResponse(BaseModel):
    items: list[CitationListItem]
    total: int
    limit: int
    offset: int
