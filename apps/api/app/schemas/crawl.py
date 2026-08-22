import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.core.urls import InvalidURLError, normalize_website_url
from app.models.crawl import CrawlStatus, CrawlType, CrawlUrlStatus
from app.schemas.common import APIModel


class CrawlStartRequest(APIModel):
    crawl_type: CrawlType = Field(default=CrawlType.FULL)
    max_pages: int | None = Field(
        default=None, ge=1, le=100_000, description="Defaults to the project/plan limit."
    )
    max_depth: int | None = Field(default=None, ge=0, le=20)
    url: str | None = Field(
        default=None,
        description=(
            "Start URL. Defaults to the project's primary domain. Must be on the "
            "project's domains; for single_page crawls this is the page to fetch."
        ),
    )

    @field_validator("url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return normalize_website_url(value).url
        except InvalidURLError as exc:
            raise ValueError(str(exc)) from exc


class CrawlJobResponse(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    root_url: str
    status: CrawlStatus
    crawl_type: CrawlType
    max_pages: int
    max_depth: int
    pages_discovered: int
    pages_crawled: int
    pages_failed: int
    pages_skipped: int
    duration_seconds: float | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CrawlJobListResponse(APIModel):
    items: list[CrawlJobResponse]
    total: int


class CrawlPageSummary(APIModel):
    id: uuid.UUID
    url: str
    normalized_url: str
    canonical_url: str | None
    http_status: int
    content_type: str
    title: str | None
    meta_description: str | None
    language: str | None
    word_count: int | None
    content_hash: str | None
    is_duplicate_of_id: uuid.UUID | None
    first_crawled_at: datetime
    last_crawled_at: datetime


class CrawlUrlResponse(APIModel):
    id: uuid.UUID
    url: str
    normalized_url: str
    parent_url: str | None
    depth: int
    priority: int
    status: CrawlUrlStatus
    http_status: int | None
    content_type: str | None
    error_message: str | None
    discovered_at: datetime
    crawled_at: datetime | None
    page: CrawlPageSummary | None = None


class CrawlUrlListResponse(APIModel):
    items: list[CrawlUrlResponse]
    total: int
    limit: int
    offset: int
