import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.core.urls import InvalidURLError, normalize_website_url
from app.models.project import ProjectStatus
from app.schemas.common import APIModel

# -- shared validators ------------------------------------------------------


def _validate_url(value: str) -> str:
    try:
        return normalize_website_url(value).url
    except InvalidURLError as exc:
        raise ValueError(str(exc)) from exc


def _country(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().upper()
    if len(value) != 2 or not value.isalpha():
        raise ValueError("country must be an ISO 3166-1 alpha-2 code, e.g. US")
    return value


# -- domains ----------------------------------------------------------------


class DomainCreateRequest(APIModel):
    url: str = Field(
        description="Website URL. Scheme optional; normalized to https and lowercase host.",
        examples=["https://www.acme.com", "acme.com/pricing"],
    )
    is_primary: bool = Field(
        default=False, description="Make this the project's primary domain (at most one)."
    )

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        return _validate_url(value)


class DomainResponse(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    url: str
    hostname: str
    is_primary: bool
    verified: bool
    created_at: datetime
    updated_at: datetime


# -- competitors ------------------------------------------------------------


class CompetitorCreateRequest(APIModel):
    name: str = Field(min_length=1, max_length=200, examples=["Rival Inc"])
    website_url: str = Field(examples=["https://rival.io"])

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


class CompetitorResponse(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    website_url: str
    hostname: str
    created_at: datetime
    updated_at: datetime


# -- projects ---------------------------------------------------------------


class ProjectCreateRequest(APIModel):
    name: str = Field(min_length=2, max_length=200, examples=["Acme Brand"])
    website_url: str = Field(
        description="Primary website. Becomes the project's primary domain.",
        examples=["https://www.acme.com"],
    )
    organization_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Organization to create the project in. Optional when you belong to exactly "
            "one organization. Membership is always verified server-side."
        ),
    )
    description: str | None = Field(default=None, max_length=2000)
    industry: str | None = Field(default=None, max_length=100, examples=["SaaS"])
    country: str | None = Field(default=None, examples=["US"])

    @field_validator("website_url")
    @classmethod
    def _url(cls, value: str) -> str:
        return _validate_url(value)

    @field_validator("country")
    @classmethod
    def _country_code(cls, value: str | None) -> str | None:
        return _country(value)


class ProjectUpdateRequest(APIModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    industry: str | None = Field(default=None, max_length=100)
    country: str | None = None
    status: ProjectStatus | None = None

    @field_validator("country")
    @classmethod
    def _country_code(cls, value: str | None) -> str | None:
        return _country(value)


class ProjectResponse(APIModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    industry: str | None
    country: str | None
    status: ProjectStatus
    primary_domain: DomainResponse | None = None
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(APIModel):
    items: list[ProjectResponse]
    total: int
