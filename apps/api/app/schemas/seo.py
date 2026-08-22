import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.models.seo import AuditStatus, ObservationCategory, ObservationStatus, Severity
from app.schemas.common import APIModel


class SeoAuditStartRequest(APIModel):
    crawl_job_id: uuid.UUID | None = Field(
        default=None,
        description="Crawl to analyze. Defaults to the project's most recent finished crawl.",
    )


class SeoAuditResponse(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    crawl_job_id: uuid.UUID
    status: AuditStatus
    pages_analyzed: int
    observation_count: int
    health_score: float | None = Field(
        default=None,
        description=(
            "Technical SEO Health Score, 0-100. Preliminary, computed only from this "
            "audit's observations; see docs/technical-seo-health-score.md."
        ),
    )
    score_breakdown: dict[str, Any] | None
    summary: dict[str, Any] | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SeoAuditListResponse(APIModel):
    items: list[SeoAuditResponse]
    total: int


class SeoObservationResponse(APIModel):
    id: uuid.UUID
    audit_id: uuid.UUID
    project_id: uuid.UUID
    page_id: uuid.UUID | None
    url: str | None
    category: ObservationCategory
    code: str
    severity: Severity
    title: str
    description: str
    evidence: dict[str, Any]
    recommendation: str
    status: ObservationStatus
    status_note: str | None
    status_changed_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class SeoObservationListResponse(APIModel):
    items: list[SeoObservationResponse]
    total: int
    limit: int
    offset: int


class SeoObservationUpdateRequest(APIModel):
    status: ObservationStatus
    note: str | None = Field(default=None, max_length=1000)
