"""AgentContext: targeted retrieval, never the whole database.

Each agent declares a `ContextSpec` — which categories it needs and how many
rows of each. The builder fetches only that, as compact dicts, through the same
capped queries the tool registry uses. Anything the agent needs beyond its
declared context it must fetch through tools at run time.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools import MAX_LIMIT, ToolBox
from app.models.project import Project


@dataclass(frozen=True)
class ContextSpec:
    """Row budgets per category; 0 = the category is not retrieved at all."""

    observations: int = 0  # recent AI responses
    recommendations: int = 0
    prompts: int = 0
    competitors: int = 0
    citations: int = 0
    pages: int = 0

    def clamped(self) -> "ContextSpec":
        return ContextSpec(**{k: min(v, MAX_LIMIT) for k, v in self.__dict__.items()})


@dataclass
class AgentContext:
    organization_id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID | None
    objective: str
    observations: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    prompts: list[dict[str, Any]] = field(default_factory=list)
    competitors: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    pages: list[dict[str, Any]] = field(default_factory=list)
    project: dict[str, Any] = field(default_factory=dict)
    tools: ToolBox | None = None

    def summary(self) -> dict[str, int]:
        return {
            "observations": len(self.observations),
            "recommendations": len(self.recommendations),
            "prompts": len(self.prompts),
            "competitors": len(self.competitors),
            "citations": len(self.citations),
            "pages": len(self.pages),
        }


async def build_context(
    session: AsyncSession,
    project: Project,
    *,
    objective: str,
    user_id: uuid.UUID | None,
    spec: ContextSpec,
) -> AgentContext:
    spec = spec.clamped()
    box = ToolBox(session, project)
    ctx = AgentContext(
        organization_id=project.organization_id,
        project_id=project.id,
        user_id=user_id,
        objective=objective,
        project=await box.call("get_project"),
        tools=box,
    )
    if spec.observations:
        ctx.observations = await box.call("get_ai_responses", limit=spec.observations)
    if spec.recommendations:
        ctx.recommendations = await box.call("get_recommendations", limit=spec.recommendations)
    if spec.prompts:
        ctx.prompts = await box.call("get_prompts", limit=spec.prompts)
    if spec.competitors:
        ctx.competitors = await box.call("get_competitors", limit=spec.competitors)
    if spec.citations:
        ctx.citations = await box.call("get_citations", limit=spec.citations)
    if spec.pages:
        ctx.pages = await box.call("get_pages", limit=spec.pages)
    return ctx
