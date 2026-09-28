"""Share link schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import APIModel


class ShareLinkCreateRequest(APIModel):
    label: str | None = Field(default=None, max_length=100)


class ShareLinkResponse(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    label: str | None
    revoked_at: datetime | None
    last_accessed_at: datetime | None
    created_at: datetime


class ShareLinkCreatedResponse(ShareLinkResponse):
    """Returned once, at creation: the only time the raw token exists."""

    token: str
    url_path: str


class PublicReportResponse(APIModel):
    project_name: str
    window: str
    generated_at: str
    overview: dict[str, Any]
    engines: list[dict[str, Any]]
    series: list[dict[str, Any]]
