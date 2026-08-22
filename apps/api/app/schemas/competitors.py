"""Competitor intelligence (Milestone 5A)."""

import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.core.urls import InvalidURLError, normalize_website_url
from app.models.competitor import (
    CompetitorConfidence,
    CompetitorDomainType,
    CompetitorSource,
    CompetitorStatus,
)
from app.schemas.common import APIModel


def _validate_url(value: str) -> str:
    try:
        return normalize_website_url(value).url
    except InvalidURLError as exc:
        raise ValueError(str(exc)) from exc


class CompetitorAliasView(APIModel):
    id: uuid.UUID
    alias: str
    normalized_alias: str
    created_at: datetime


class CompetitorDomainView(APIModel):
    id: uuid.UUID
    domain: str
    domain_type: CompetitorDomainType
    is_primary: bool
    created_at: datetime


class CompetitorProductView(APIModel):
    id: uuid.UUID
    name: str
    description: str | None
    url: str | None
    created_at: datetime
    updated_at: datetime


class CompetitorResponse(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    domain: str = Field(validation_alias="hostname", description="Primary domain as entered")
    normalized_domain: str
    website_url: str
    hostname: str = Field(description="Same as `domain`; kept for older clients")
    description: str | None
    source: CompetitorSource
    status: CompetitorStatus
    confidence: CompetitorConfidence
    aliases: list[CompetitorAliasView] = Field(default_factory=list)
    domains: list[CompetitorDomainView] = Field(default_factory=list)
    products: list[CompetitorProductView] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CompetitorCreateRequest(APIModel):
    name: str = Field(min_length=1, max_length=200, examples=["Rival Inc"])
    website_url: str = Field(examples=["https://rival.io"])
    description: str | None = Field(default=None, max_length=2000)
    source: CompetitorSource = CompetitorSource.MANUAL
    status: CompetitorStatus = CompetitorStatus.ACTIVE
    confidence: CompetitorConfidence = CompetitorConfidence.HIGH
    aliases: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("website_url")
    @classmethod
    def _url(cls, value: str) -> str:
        return _validate_url(value)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("aliases")
    @classmethod
    def _aliases(cls, value: list[str]) -> list[str]:
        cleaned = [a.strip() for a in value if a and a.strip()]
        if any(len(a) > 200 for a in cleaned):
            raise ValueError("aliases must be at most 200 characters")
        return cleaned


class CompetitorUpdateRequest(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    website_url: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    status: CompetitorStatus | None = None
    confidence: CompetitorConfidence | None = None

    @field_validator("website_url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        return _validate_url(value) if value is not None else None


class AliasCreateRequest(APIModel):
    alias: str = Field(min_length=1, max_length=200, examples=["QBO", "QuickBooks Online"])


class DomainCreateRequest(APIModel):
    domain: str = Field(min_length=1, max_length=253, examples=["community.rival.io"])
    domain_type: CompetitorDomainType = CompetitorDomainType.OTHER
    is_primary: bool = False


class ProductCreateRequest(APIModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    url: str | None = None


class ProductUpdateRequest(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    url: str | None = None
