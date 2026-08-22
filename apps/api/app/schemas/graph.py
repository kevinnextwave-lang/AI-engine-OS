"""AI Search Graph responses (Milestone 4D)."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

NodeType = Literal[
    "project",
    "brand",
    "competitor",
    "prompt",
    "response",
    "model",
    "source_domain",
    "source_page",
    "claim",
]
EdgeType = Literal[
    "has_prompt",
    "tracks",
    "produces",
    "mentions",
    "cites",
    "claims",
    "associated_with",
    "competes_with",
    "belongs_to",
]


class GraphNode(BaseModel):
    id: str = Field(description="`<type>:<uuid-or-key>`")
    type: NodeType
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    type: EdgeType
    weight: int = Field(description="Number of underlying observations")
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphWindow(BaseModel):
    start: datetime
    end: datetime


class GraphStatistics(BaseModel):
    responses: int
    prompts: int
    models: int
    brand_mentions: int
    competitor_mentions: int
    claims: int
    citations: int
    source_domains: int
    source_pages: int
    brand_citations: int = Field(description="Citations related to the brand")
    competitor_citations: int = Field(description="Citations related to a configured competitor")
    provider: str | None = Field(default=None, description="AI provider filter applied, if any")
    competitors_configured: int
    nodes_returned: int
    edges_returned: int
    truncated: bool = Field(description="True when top-N limits cut the graph")


class GraphOverview(BaseModel):
    version: str
    project_id: uuid.UUID
    window: GraphWindow
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    statistics: GraphStatistics


class SourceNode(BaseModel):
    source_domain_id: uuid.UUID
    domain: str
    display_name: str
    source_type: str
    citations: int
    responses: int
    prompts: int
    brand_citations: int
    competitor_citations: int
    competitors: dict[str, int]
    first_cited_at: datetime | None
    last_cited_at: datetime | None
    # view-specific
    competitor_share: float | None = Field(
        default=None, description="competitor citations / citations (competitor + gap views)"
    )
    brand_ratio: float | None = Field(
        default=None, description="brand citations / competitor citations (gap view)"
    )
    previous_citations: int | None = Field(default=None, description="rising view")
    growth: float | None = Field(
        default=None, description="rising view: (current − previous) / max(previous, 1)"
    )
    top_pages: list[dict[str, Any]] = Field(default_factory=list)


class GraphSourcesResponse(BaseModel):
    version: str
    project_id: uuid.UUID
    window: GraphWindow
    view: Literal["top", "competitor", "gap", "rising"]
    items: list[SourceNode]
    total: int
    limit: int
    offset: int


class CompetitorNode(BaseModel):
    competitor_id: uuid.UUID | None
    name: str
    is_brand: bool
    mentions: int
    responses_mentioning: int
    citations: int
    co_mentions_with_brand: int
    top_sources: list[dict[str, Any]]


class GraphCompetitorsResponse(BaseModel):
    version: str
    project_id: uuid.UUID
    window: GraphWindow
    items: list[CompetitorNode]
    edges: list[GraphEdge] = Field(
        description="competes_with edges (brand ↔ competitor co-mentions)"
    )
    total: int
    limit: int
    offset: int


class PromptNode(BaseModel):
    prompt_id: uuid.UUID
    text: str
    category: str
    funnel_stage: str
    responses: int
    brand_mentions: int
    competitor_mentions: int
    competitor_citations: int
    brand_citations: int
    citations: int
    competitors: dict[str, int]
    top_sources: list[dict[str, Any]]


class GraphPromptsResponse(BaseModel):
    version: str
    project_id: uuid.UUID
    window: GraphWindow
    items: list[PromptNode]
    total: int
    limit: int
    offset: int


class ClaimNode(BaseModel):
    subject: str
    predicate: str
    object: str
    occurrences: int
    responses: int
    prompts: int
    avg_confidence: float
    associated_with: Literal["brand", "competitor", "other"]
    entity_name: str | None
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    examples: list[str] = Field(default_factory=list)


class GraphClaimsResponse(BaseModel):
    version: str
    project_id: uuid.UUID
    window: GraphWindow
    items: list[ClaimNode]
    total: int
    limit: int
    offset: int
