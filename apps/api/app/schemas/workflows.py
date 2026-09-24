"""Agent workflow responses (Milestone 6F)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.workflows import WorkflowStatus, WorkflowStepStatus


class WorkflowCreateRequest(BaseModel):
    workflow_type: str = Field(default="full_optimization", max_length=60)
    objective: str = Field(min_length=3, max_length=2000)


class WorkflowStepView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_name: str
    sequence: int
    status: WorkflowStepStatus
    agent_run_id: uuid.UUID | None
    input_context: dict[str, Any]
    output_summary: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class WorkflowView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    workflow_type: str
    status: WorkflowStatus
    current_step: int
    objective: str
    hold_reason: str | None
    error_message: str | None
    action_plan: list[dict[str, Any]] | None
    steps: list[WorkflowStepView]
    created_at: datetime
    updated_at: datetime


class WorkflowListItem(BaseModel):
    id: uuid.UUID
    workflow_type: str
    status: WorkflowStatus
    current_step: int
    objective: str
    steps_total: int
    steps_completed: int
    created_at: datetime


class WorkflowListResponse(BaseModel):
    items: list[WorkflowListItem]
    total: int
    limit: int
    offset: int
