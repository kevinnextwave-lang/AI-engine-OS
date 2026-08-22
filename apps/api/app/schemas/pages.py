import uuid
from datetime import datetime
from typing import Any

from app.models.page_intelligence import LinkStatus, LinkType
from app.schemas.common import APIModel


class PageSummary(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    url: str
    normalized_url: str
    pathname: str | None = None
    canonical_url: str | None
    http_status: int
    content_type: str
    title: str | None
    meta_description: str | None
    language: str | None
    word_count: int | None
    is_duplicate_of_id: uuid.UUID | None
    first_crawled_at: datetime
    last_crawled_at: datetime


class PageListResponse(APIModel):
    items: list[PageSummary]
    total: int
    limit: int
    offset: int


class HeadingResponse(APIModel):
    level: int
    position: int
    parent_position: int | None
    text: str


class LinkResponse(APIModel):
    id: uuid.UUID
    href: str
    normalized_url: str | None
    anchor_text: str
    link_type: LinkType
    status: LinkStatus
    target_page_id: uuid.UUID | None
    target_http_status: int | None
    is_nofollow: bool
    is_sponsored: bool
    is_ugc: bool
    in_navigation: bool
    position: int


class LinkListResponse(APIModel):
    items: list[LinkResponse]
    total: int
    limit: int
    offset: int


class ImageResponse(APIModel):
    src: str
    alt: str | None
    title: str | None
    width: int | None
    height: int | None
    loading: str | None
    position: int


class MetadataResponse(APIModel):
    pathname: str
    robots: str | None
    viewport: str | None
    author: str | None
    charset: str | None
    published_at: datetime | None
    modified_at: datetime | None
    html_lang: str | None
    language: str | None
    language_source: str | None
    language_confidence: float | None
    open_graph: dict[str, Any]
    twitter: dict[str, Any]
    other: dict[str, Any]


class ContentMetricsResponse(APIModel):
    word_count: int
    character_count: int
    paragraph_count: int
    sentence_count: int
    reading_time_seconds: int
    text_to_html_ratio: float
    html_bytes: int
    heading_count: int
    h1_count: int
    link_count: int
    internal_link_count: int
    external_link_count: int
    image_count: int
    images_missing_alt: int
    heading_observations: dict[str, Any]


class PageDetailResponse(PageSummary):
    html_hash: str | None
    content_hash: str | None
    metadata: MetadataResponse | None
    content: ContentMetricsResponse | None
    headings: list[HeadingResponse]
    images: list[ImageResponse]
    link_counts: dict[str, int]
    clean_text: str | None
