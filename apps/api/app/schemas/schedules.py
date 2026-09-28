"""Recurring collection schedule schemas."""

import uuid
from datetime import datetime

from pydantic import Field

from app.models.prompt_schedule import ScheduleCadence
from app.schemas.common import APIModel


class ScheduleUpsertRequest(APIModel):
    cadence: ScheduleCadence
    hour_utc: int = Field(ge=0, le=23, description="UTC hour the collection starts.")
    weekday: int | None = Field(
        default=None, ge=0, le=6, description="0=Monday … 6=Sunday; required for weekly."
    )
    providers: list[str] = Field(min_length=1, max_length=10)
    models: dict[str, str] | None = Field(
        default=None, description="Optional provider_key -> model_key overrides."
    )
    is_active: bool = True


class ScheduleResponse(APIModel):
    id: uuid.UUID
    prompt_set_id: uuid.UUID
    cadence: ScheduleCadence
    hour_utc: int
    weekday: int | None
    providers: list[str]
    models: dict[str, str] | None
    is_active: bool
    next_run_at: datetime
    last_run_at: datetime | None
    last_batch_id: uuid.UUID | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
