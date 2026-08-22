import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.models.ai_readiness import ReadinessCategory
from app.models.seo import AuditStatus, Severity
from app.schemas.common import APIModel

SCORE_NOTE = (
    "AI Readiness Score is an internal product metric computed only from the listed signals. "
    "It is not an industry standard and does not measure or predict AI visibility."
)


class AiReadinessAuditResponse(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: AuditStatus
    pages_analyzed: int
    observation_count: int
    readiness_score: float | None = Field(default=None, description=SCORE_NOTE)
    score_breakdown: dict[str, Any] | None
    summary: dict[str, Any] | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AiReadinessObservationResponse(APIModel):
    id: uuid.UUID
    page_id: uuid.UUID | None
    url: str | None
    category: ReadinessCategory
    code: str
    severity: Severity
    title: str
    description: str
    evidence: dict[str, Any]
    recommendation: str


class AiReadinessAuditDetailResponse(AiReadinessAuditResponse):
    observations: list[AiReadinessObservationResponse]
    observations_total: int
    note: str = SCORE_NOTE


class AiReadinessAuditListResponse(APIModel):
    items: list[AiReadinessAuditResponse]
    total: int
