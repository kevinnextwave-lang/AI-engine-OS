"""Seed parsed observations directly (no providers, no parser) for visibility tests."""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intelligence import BrandMention, CompetitorMention, ResponseCitation
from app.models.prompts import (
    AiResponse,
    FunnelStage,
    Prompt,
    PromptCategory,
    PromptIntent,
    PromptRun,
    PromptRunStatus,
    PromptSet,
    PromptSource,
)
from app.prompts.normalize import normalize_text
from tests.conftest import auth_header
from tests.test_authz import org_id_for, signup
from tests.test_projects_api import create_project

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
PV = "response-parser/v1"


class Seeder:
    def __init__(self, session: AsyncSession, project_id: uuid.UUID) -> None:
        self.session = session
        self.project_id = project_id
        self.prompt_set: PromptSet | None = None
        self.prompts: dict[str, Prompt] = {}

    async def prompt(
        self,
        text: str,
        *,
        category: PromptCategory = PromptCategory.COMPARISON,
        funnel_stage: FunnelStage = FunnelStage.CONSIDERATION,
    ) -> Prompt:
        if text in self.prompts:
            return self.prompts[text]
        if self.prompt_set is None:
            self.prompt_set = PromptSet(project_id=self.project_id, name="Seeded")
            self.session.add(self.prompt_set)
            await self.session.flush()
        p = Prompt(
            prompt_set_id=self.prompt_set.id,
            project_id=self.project_id,
            text=text,
            normalized_text=normalize_text(text),
            category=category,
            intent=PromptIntent.COMMERCIAL,
            funnel_stage=funnel_stage,
            source=PromptSource.MANUAL,
        )
        self.session.add(p)
        await self.session.flush()
        self.prompts[text] = p
        return p

    async def observation(
        self,
        *,
        prompt: str = "best accounting tools for startups",
        provider: str = "openai",
        model: str = "gpt-4o-mini",
        days_ago: float = 1,
        mentioned: bool = True,
        position: int | None = None,
        sentiment: str = "positive",
        strength: str = "strong",
        cited: bool = False,
        competitors: list[tuple[str, int | None, str, str]] | None = None,
        competitor_cited: list[str] | None = None,
        parsed: bool = True,
        category: PromptCategory = PromptCategory.COMPARISON,
        funnel_stage: FunnelStage = FunnelStage.CONSIDERATION,
    ) -> PromptRun:
        """One completed+parsed run. competitors: (name, position, sentiment, strength);
        competitor_cited: names whose own site (www.{name}.com) is cited in the response."""
        p = await self.prompt(prompt, category=category, funnel_stage=funnel_stage)
        when = NOW - timedelta(days=days_ago)
        run = PromptRun(
            prompt_id=p.id,
            project_id=self.project_id,
            status=PromptRunStatus.COMPLETED,
            provider_key=provider,
            model_key=model,
            attempts=1,
            started_at=when,
            completed_at=when,
        )
        self.session.add(run)
        await self.session.flush()
        resp = AiResponse(
            prompt_run_id=run.id,
            response_text="seeded",
            parser_version=PV if parsed else None,
            parsed_at=when if parsed else None,
        )
        self.session.add(resp)
        await self.session.flush()
        if mentioned:
            self.session.add(
                BrandMention(
                    ai_response_id=resp.id,
                    project_id=self.project_id,
                    brand_name="Ledgerly",
                    mention_text="Ledgerly",
                    position=position,
                    sentiment=sentiment,
                    recommendation_strength=strength,
                    parser_version=PV,
                )
            )
        if cited:
            self.session.add(
                ResponseCitation(
                    ai_response_id=resp.id,
                    project_id=self.project_id,
                    url="https://www.ledgerly.example/pricing",
                    domain="www.ledgerly.example",
                    citation_type="url",
                    parser_version=PV,
                )
            )
        for name in competitor_cited or []:
            self.session.add(
                ResponseCitation(
                    ai_response_id=resp.id,
                    project_id=self.project_id,
                    url=f"https://www.{name.lower()}.com/pricing",
                    domain=f"www.{name.lower()}.com",
                    citation_type="url",
                    parser_version=PV,
                )
            )
        for name, cpos, csent, cstr in competitors or []:
            self.session.add(
                CompetitorMention(
                    ai_response_id=resp.id,
                    project_id=self.project_id,
                    competitor_name=name,
                    mention_text=name,
                    position=cpos,
                    sentiment=csent,
                    recommendation_strength=cstr,
                    parser_version=PV,
                )
            )
        await self.session.flush()
        return run


async def project_with_competitors(
    client: AsyncClient, *, competitors: tuple[str, ...] = ("QuickBooks", "Xero")
) -> tuple[dict[str, str], str, str]:
    """Returns (headers, org_id, project_id)."""
    owner = await signup(client, org="Vis Org")
    h = auth_header(owner["access_token"])
    org = await org_id_for(client, owner["access_token"])
    pid = (
        await create_project(client, h, name="Ledgerly", website_url="https://www.ledgerly.example")
    )["id"]
    for name in competitors:
        r = await client.post(
            f"/api/v1/projects/{pid}/competitors",
            json={"name": name, "website_url": f"https://www.{name.lower()}.com"},
            headers=h,
        )
        assert r.status_code == 201, r.text
    return h, org, pid
