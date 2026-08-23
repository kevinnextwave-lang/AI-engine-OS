"""Competitive alert responses (Milestone 5F)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.alerts.rules import AlertThresholds
from app.models.alerts import AlertSeverity, AlertStatus, AlertType


class AlertView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    alert_type: AlertType
    competitor_id: uuid.UUID | None
    title: str
    description: str
    evidence: dict[str, Any]
    severity: AlertSeverity
    status: AlertStatus
    detected_at: datetime
    analysis_version: str
    created_at: datetime
    updated_at: datetime


class AlertListResponse(BaseModel):
    items: list[AlertView]
    total: int
    unread: int
    limit: int
    offset: int
    detected_at: datetime | None


class AlertUpdateRequest(BaseModel):
    status: AlertStatus


class AlertDetectRequest(BaseModel):
    window_days: int = Field(default=7, ge=1, le=90)
    thresholds: AlertThresholds | None = Field(
        default=None, description="Overrides; unset fields keep their defaults"
    )


class AlertDetectResponse(BaseModel):
    project_id: uuid.UUID
    window_days: int
    current_responses: int
    previous_responses: int
    alerts_created: int
    alerts_updated: int
    detected_at: datetime
    thresholds: dict[str, Any]
    note: str
