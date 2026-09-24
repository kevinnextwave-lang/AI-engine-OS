"""Agent framework responses (Milestone 6A)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.agents import ActionRiskLevel, ActionStatus, AgentRunStatus


class AgentRunRequest(BaseModel):
    objective: str = Field(min_length=3, max_length=2000)


class AgentRunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    agent_name: str
    agent_version: str
    status: AgentRunStatus
    objective: str
    requested_by_user_id: uuid.UUID | None
    started_at: datetime | None
    completed_at: datetime | None
    execution_time_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost: Decimal | None
    error_message: str | None
    result: dict[str, Any] | None
    created_at: datetime


class AgentRunListResponse(BaseModel):
    items: list[AgentRunView]
    total: int
    limit: int
    offset: int


class AgentActionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_run_id: uuid.UUID
    action_type: str
    description: str
    payload: dict[str, Any]
    risk_level: ActionRiskLevel
    approval_required: bool
    status: ActionStatus
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    executed_at: datetime | None
    execution_result: dict[str, Any] | None
    created_at: datetime


class AgentInfo(BaseModel):
    name: str
    version: str
