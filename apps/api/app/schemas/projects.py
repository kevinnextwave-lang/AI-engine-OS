import uuid
from datetime import datetime

from pydantic import Field

from app.models.project import ProjectStatus
from app.schemas.common import APIModel


class ProjectCreateRequest(APIModel):
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    industry: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, min_length=2, max_length=2)


class ProjectUpdateRequest(APIModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    industry: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    status: ProjectStatus | None = None


class ProjectResponse(APIModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    industry: str | None
    country: str | None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
