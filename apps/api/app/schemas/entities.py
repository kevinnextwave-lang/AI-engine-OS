import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.models.entities import EntityScope
from app.models.page_intelligence import StructuredDataFormat
from app.schemas.common import APIModel


class EntityLinkResponse(APIModel):
    url: str
    platform: str
    is_authoritative: bool


class EntityResponse(APIModel):
    id: uuid.UUID
    project_id: uuid.UUID
    page_id: uuid.UUID | None
    page_url: str | None = None
    scope: EntityScope
    source_format: StructuredDataFormat | None
    entity_type: str
    extra_types: list[str]
    name: str | None
    description: str | None
    url: str | None
    same_as: list[str]
    identifier: list[str]
    properties: dict[str, Any]
    json_path: str
    is_known_type: bool
    links: list[EntityLinkResponse] = Field(default_factory=list)
    created_at: datetime


class EntityListResponse(APIModel):
    items: list[EntityResponse]
    total: int
    limit: int
    offset: int
    organization: EntityResponse | None = Field(
        default=None, description="The consolidated project-level organization entity, if any."
    )
    analyzed_at: datetime | None


class SchemaIssueResponse(APIModel):
    id: uuid.UUID
    page_id: uuid.UUID
    page_url: str | None = None
    structured_data_id: uuid.UUID | None
    format: StructuredDataFormat
    block_position: int
    code: str
    severity: str
    message: str
    json_path: str


class SchemaBlockResponse(APIModel):
    id: uuid.UUID
    format: StructuredDataFormat
    position: int
    schema_types: list[str]
    is_valid: bool
    error: str | None
    payload: dict[str, Any] | list[Any] | None
    issues: list[SchemaIssueResponse]
    entities: list[EntityResponse]


class PageSchemaResponse(APIModel):
    page_id: uuid.UUID
    url: str
    blocks: list[SchemaBlockResponse]
    analyzed_at: datetime | None


class ProjectSchemaSummary(APIModel):
    pages_crawled: int
    pages_with_structured_data: int
    pages_without_structured_data: int
    blocks_total: int
    blocks_invalid: int
    formats: dict[str, int]
    schema_types: dict[str, int] = Field(description="Pages per schema.org type")
    entity_types: dict[str, int] = Field(description="Extracted entities per type")
    known_types_present: list[str]
    known_types_absent: list[str] = Field(
        description="Common schema types not found. Absence is informational only; not "
        "every site needs every type."
    )
    issues_by_code: dict[str, int]


class ProjectSchemaResponse(APIModel):
    summary: ProjectSchemaSummary
    issues: list[SchemaIssueResponse]
    analyzed_at: datetime | None
    note: str = (
        "Validation covers JSON-LD/Microdata/RDFa structure only. It does not assess "
        "search-engine rich-result eligibility."
    )


class EntityObservationResponse(APIModel):
    id: uuid.UUID
    code: str
    severity: str
    title: str
    description: str
    entity_type: str | None
    entity_name: str | None
    evidence: dict[str, Any]
    created_at: datetime


class EntityConsistencyResponse(APIModel):
    items: list[EntityObservationResponse]
    total: int
    entities_compared: int
    analyzed_at: datetime | None
    note: str = (
        "Inconsistencies list every observed value with its source pages; no value is "
        "assumed to be the correct one."
    )


class EntityAnalysisStartResponse(APIModel):
    project_id: uuid.UUID
    queued: bool
