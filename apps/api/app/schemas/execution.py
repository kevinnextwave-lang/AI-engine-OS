import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.models.prompts import BatchStatus, ExecutionPriority, PromptRunStatus
from app.schemas.common import APIModel


class RunPromptSetRequest(APIModel):
    providers: list[str] = Field(
        min_length=1, max_length=10, description="Provider keys, e.g. ['openai', 'google']."
    )
    models: dict[str, str] | None = Field(
        default=None,
        description=(
            "Optional provider_key -> model_key; defaults to each provider's default model."
        ),
    )
    priority: ExecutionPriority = ExecutionPriority.NORMAL
    prompt_ids: list[uuid.UUID] | None = Field(
        default=None, description="Restrict to these prompts (must be active members of the set)."
    )


class BatchResponse(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    prompt_set_id: uuid.UUID
    status: BatchStatus
    priority: ExecutionPriority
    targets: list[dict[str, Any]]
    total_runs: int
    completed_runs: int
    failed_runs: int
    cancelled_runs: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    usage: dict[str, Any] | None = None


class BatchListResponse(APIModel):
    items: list[BatchResponse]
    total: int


class AiResponseView(APIModel):
    response_text: str
    finish_reason: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    latency_ms: int | None
    provider_request_id: str | None
    raw_metadata: dict[str, Any]


class PromptRunResponse(APIModel):
    id: uuid.UUID
    prompt_id: uuid.UUID
    batch_id: uuid.UUID | None
    provider_key: str | None
    model_key: str | None
    status: PromptRunStatus
    attempts: int
    latency_ms: int | None
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    response: AiResponseView | None = None


class PromptRunListResponse(APIModel):
    items: list[PromptRunResponse]
    total: int
    limit: int
    offset: int
