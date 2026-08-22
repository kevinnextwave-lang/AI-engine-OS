import uuid
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, Field

from app.models.prompts import (
    FunnelStage,
    PromptCategory,
    PromptIntent,
    PromptRunStatus,
    PromptSetStatus,
    PromptSource,
)
from app.schemas.common import APIModel


class PromptSetCreateRequest(APIModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    category: PromptCategory | None = None
    status: PromptSetStatus = PromptSetStatus.ACTIVE


class PromptSetResponse(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    category: PromptCategory | None
    status: PromptSetStatus
    prompt_count: int = 0
    active_prompt_count: int = 0
    last_generated_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PromptSetListResponse(APIModel):
    items: list[PromptSetResponse]
    total: int


class BusinessProfileInput(APIModel):
    """Overrides for the generation profile. Anything omitted is derived from the
    project (name, primary domain, industry, country, competitors, crawled entities)."""

    company_name: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=2048)
    industry: str | None = Field(default=None, max_length=200)
    products: list[str] = Field(default_factory=list, max_length=25)
    services: list[str] = Field(default_factory=list, max_length=25)
    features: list[str] = Field(default_factory=list, max_length=25)
    use_cases: list[str] = Field(default_factory=list, max_length=25)
    integrations: list[str] = Field(default_factory=list, max_length=25)
    target_audience: list[str] = Field(default_factory=list, max_length=25)
    competitors: list[str] = Field(default_factory=list, max_length=25)
    geographic_market: list[str] = Field(default_factory=list, max_length=25)
    language: str | None = Field(default=None, max_length=10)
    country: str | None = Field(default=None, min_length=2, max_length=2)


class PromptGenerateRequest(APIModel):
    profile: BusinessProfileInput = Field(default_factory=BusinessProfileInput)
    categories: list[PromptCategory] | None = Field(
        default=None, description="Restrict generation to these categories (default: all)."
    )
    max_prompts: int = Field(default=40, ge=1, le=200)
    max_per_category: int = Field(default=8, ge=1, le=50)


class PromptCreateRequest(APIModel):
    text: str = Field(min_length=5, max_length=500)
    category: PromptCategory | None = Field(
        default=None, description="Inferred from the text when omitted."
    )
    intent: PromptIntent | None = None
    funnel_stage: FunnelStage | None = None
    language: str | None = Field(default=None, max_length=10)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    priority: int | None = Field(default=None, ge=1, le=5)
    is_active: bool = True


class PromptUpdateRequest(APIModel):
    text: str | None = Field(default=None, min_length=5, max_length=500)
    category: PromptCategory | None = None
    intent: PromptIntent | None = None
    funnel_stage: FunnelStage | None = None
    language: str | None = Field(default=None, max_length=10)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    priority: int | None = Field(default=None, ge=1, le=5)
    is_active: bool | None = None


class PromptRunSummary(APIModel):
    id: uuid.UUID
    status: PromptRunStatus
    provider_key: str | None
    model_key: str | None
    started_at: datetime | None
    completed_at: datetime | None


class PromptResponse(APIModel):
    """Table-ready row: prompt + classification + priority + status + last run + visibility."""

    id: uuid.UUID
    prompt_set_id: uuid.UUID
    project_id: uuid.UUID
    prompt: str = Field(validation_alias=AliasChoices("text", "prompt"))
    category: PromptCategory
    intent: PromptIntent
    funnel_stage: FunnelStage
    language: str
    country: str | None
    priority: int
    status: str = Field(default="active", description="active | inactive")
    is_active: bool
    source: PromptSource
    quality_score: float | None
    quality_breakdown: dict[str, Any] | None
    last_run: PromptRunSummary | None = None
    visibility_result: dict[str, Any] | None = Field(
        default=None, description="Visibility of the latest completed run, when available."
    )
    created_at: datetime
    updated_at: datetime


class PromptListResponse(APIModel):
    items: list[PromptResponse]
    total: int
    limit: int
    offset: int


class PromptGenerateResponse(APIModel):
    prompt_set_id: uuid.UUID
    generated: int
    skipped_duplicates: int
    profile: dict[str, Any]
    items: list[PromptResponse]
