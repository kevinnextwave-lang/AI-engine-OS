"""Prompt sets, prompts and deterministic generation for a project."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.models.entities import Entity, EntityScope
from app.models.project import Project
from app.models.prompts import (
    FunnelStage,
    Prompt,
    PromptCategory,
    PromptSet,
    PromptSetStatus,
    PromptSource,
)
from app.prompts.classify import classify
from app.prompts.generator import generate_candidates
from app.prompts.normalize import is_near_duplicate, normalize_text
from app.prompts.profile import BusinessProfile
from app.prompts.quality import priority_for, score_prompt
from app.repositories.projects import CompetitorRepository, DomainRepository
from app.repositories.prompts import PromptRepository, PromptSetRepository
from app.schemas.prompts import (
    BusinessProfileInput,
    PromptCreateRequest,
    PromptResponse,
    PromptRunSummary,
    PromptSetCreateRequest,
    PromptSetResponse,
    PromptUpdateRequest,
)

log = get_logger(__name__)


class PromptService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._sets = PromptSetRepository(session)
        self._prompts = PromptRepository(session)

    # -- prompt sets ---------------------------------------------------------------

    async def create_set(self, project: Project, body: PromptSetCreateRequest) -> PromptSet:
        prompt_set = PromptSet(
            project_id=project.id,
            name=body.name,
            description=body.description,
            category=body.category,
            status=body.status,
        )
        await self._sets.add(prompt_set)
        await self._session.commit()
        await self._session.refresh(prompt_set)
        return prompt_set

    async def list_sets(
        self, project: Project, *, status: PromptSetStatus | None, limit: int, offset: int
    ) -> tuple[list[PromptSetResponse], int]:
        sets, total = await self._sets.list_for_project(
            project.id, status=status, limit=limit, offset=offset
        )
        counts = await self._sets.prompt_counts([s.id for s in sets])
        items = []
        for s in sets:
            item = PromptSetResponse.model_validate(s)
            item.prompt_count, item.active_prompt_count = counts.get(s.id, (0, 0))
            items.append(item)
        return items, total

    async def set_response(self, prompt_set: PromptSet) -> PromptSetResponse:
        item = PromptSetResponse.model_validate(prompt_set)
        item.prompt_count, item.active_prompt_count = (
            await self._sets.prompt_counts([prompt_set.id])
        ).get(prompt_set.id, (0, 0))
        return item

    # -- profile ------------------------------------------------------------------------

    async def build_profile(
        self, project: Project, overrides: BusinessProfileInput
    ) -> BusinessProfile:
        """Project data first, explicit overrides win. Crawled entities contribute
        product/service names when the caller gives none."""
        domains = await DomainRepository(self._session).list_for_project(project.id)
        primary = next((d for d in domains if d.is_primary), domains[0] if domains else None)
        competitors = [
            c.name for c in await CompetitorRepository(self._session).list_for_project(project.id)
        ]
        products: list[str] = list(overrides.products)
        services: list[str] = list(overrides.services)
        if not products and not services:
            entities = (
                await self._session.scalars(
                    select(Entity).where(
                        Entity.project_id == project.id,
                        Entity.scope == EntityScope.PAGE,
                        Entity.entity_type.in_(["Product", "Service"]),
                        Entity.name.is_not(None),
                    )
                )
            ).all()
            for e in entities:
                target = products if e.entity_type == "Product" else services
                if e.name and e.name not in target:
                    target.append(e.name)
        return BusinessProfile(
            company_name=overrides.company_name or project.name,
            website=overrides.website or (primary.url if primary else None),
            industry=overrides.industry or project.industry,
            products=products[:10],
            services=services[:10],
            features=overrides.features,
            use_cases=overrides.use_cases,
            integrations=overrides.integrations,
            target_audience=overrides.target_audience,
            competitors=overrides.competitors or competitors,
            geographic_market=overrides.geographic_market,
            language=overrides.language or "en",
            country=overrides.country or project.country,
        )

    # -- generation ---------------------------------------------------------------------

    async def generate(
        self,
        prompt_set: PromptSet,
        project: Project,
        overrides: BusinessProfileInput,
        *,
        categories: list[PromptCategory] | None,
        max_prompts: int,
        max_per_category: int,
    ) -> tuple[list[Prompt], int, BusinessProfile]:
        if prompt_set.status == PromptSetStatus.ARCHIVED:
            raise ConflictError("Prompt set is archived")
        profile = await self.build_profile(project, overrides)
        if not profile.offerings and not profile.company_name:
            raise ValidationAppError("Profile needs at least an industry, product or service")
        existing = await self._prompts.texts_for_set(prompt_set.id)
        candidates = generate_candidates(
            profile,
            max_total=max_prompts,
            max_per_category=max_per_category,
            categories=categories,
            existing_texts=existing,
        )
        all_texts = existing + [c.text for c in candidates]
        created: list[Prompt] = []
        for c in candidates:
            quality = score_prompt(c.text, c.category, profile, all_texts)
            created.append(
                Prompt(
                    prompt_set_id=prompt_set.id,
                    project_id=project.id,
                    text=c.text,
                    normalized_text=normalize_text(c.text),
                    category=c.category,
                    intent=c.intent,
                    funnel_stage=c.funnel_stage,
                    language=profile.language,
                    country=profile.country,
                    priority=quality.priority,
                    is_active=True,
                    source=PromptSource.GENERATED,
                    quality_score=quality.score,
                    quality_breakdown=quality.breakdown,
                    metadata_={"template": c.template},
                )
            )
        await self._prompts.add_all(created)
        prompt_set.generation_profile = profile.to_dict()
        prompt_set.last_generated_at = datetime.now(UTC)
        await self._session.commit()
        for p in created:
            await self._session.refresh(p)
        log.info(
            "prompts_generated",
            prompt_set_id=str(prompt_set.id),
            project_id=str(project.id),
            generated=len(created),
            existing=len(existing),
        )
        return created, 0, profile

    # -- prompts ------------------------------------------------------------------------

    async def create_prompt(self, prompt_set: PromptSet, body: PromptCreateRequest) -> Prompt:
        if prompt_set.status == PromptSetStatus.ARCHIVED:
            raise ConflictError("Prompt set is archived")
        text = " ".join(body.text.split())
        norm = normalize_text(text)
        if await self._prompts.normalized_exists(prompt_set.id, norm):
            raise ConflictError("An identical prompt already exists in this set")
        near = [
            t
            for t in await self._prompts.texts_for_set(prompt_set.id)
            if is_near_duplicate(text, t)
        ]
        if near:
            raise ConflictError(
                "A near-duplicate prompt already exists in this set",
                details=[{"loc": ["body", "text"], "msg": f"Similar to: {near[0]}"}],
            )
        inferred = classify(text)
        category = body.category or inferred.category
        profile = self._profile_from_set(prompt_set)
        quality = (
            score_prompt(text, category, profile, await self._prompts.texts_for_set(prompt_set.id))
            if profile
            else None
        )
        prompt = Prompt(
            prompt_set_id=prompt_set.id,
            project_id=prompt_set.project_id,
            text=text,
            normalized_text=norm,
            category=category,
            intent=body.intent or inferred.intent,
            funnel_stage=body.funnel_stage or inferred.funnel_stage,
            language=body.language or (profile.language if profile else "en"),
            country=body.country or (profile.country if profile else None),
            priority=body.priority or (quality.priority if quality else 3),
            is_active=body.is_active,
            source=PromptSource.MANUAL,
            quality_score=quality.score if quality else None,
            quality_breakdown=quality.breakdown if quality else None,
        )
        await self._prompts.add_all([prompt])
        await self._session.commit()
        await self._session.refresh(prompt)
        return prompt

    async def update_prompt(self, prompt: Prompt, body: PromptUpdateRequest) -> Prompt:
        data = body.model_dump(exclude_unset=True)
        if "text" in data and data["text"] is not None:
            text = " ".join(data["text"].split())
            norm = normalize_text(text)
            if norm != prompt.normalized_text and await self._prompts.normalized_exists(
                prompt.prompt_set_id, norm
            ):
                raise ConflictError("An identical prompt already exists in this set")
            prompt.text = text
            prompt.normalized_text = norm
            inferred = classify(text)
            if "category" not in data:
                prompt.category = inferred.category
            if "intent" not in data:
                prompt.intent = inferred.intent
            if "funnel_stage" not in data:
                prompt.funnel_stage = inferred.funnel_stage
        for field in (
            "category",
            "intent",
            "funnel_stage",
            "language",
            "country",
            "priority",
            "is_active",
        ):
            if field in data and data[field] is not None:
                setattr(prompt, field, data[field])
        if "text" in data or "category" in data:
            prompt_set = await self._sets.get(prompt.prompt_set_id)
            profile = self._profile_from_set(prompt_set) if prompt_set else None
            if profile:
                others = [
                    t
                    for t in await self._prompts.texts_for_set(prompt.prompt_set_id)
                    if t != prompt.text
                ]
                quality = score_prompt(prompt.text, prompt.category, profile, others)
                prompt.quality_score = quality.score
                prompt.quality_breakdown = quality.breakdown
                if "priority" not in data:
                    prompt.priority = priority_for(quality.score)
        await self._session.commit()
        await self._session.refresh(prompt)
        return prompt

    async def delete_prompt(self, prompt: Prompt) -> None:
        await self._prompts.delete(prompt)
        await self._session.commit()

    async def list_prompts(
        self,
        prompt_set: PromptSet,
        *,
        category: PromptCategory | None,
        funnel_stage: FunnelStage | None,
        is_active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[list[PromptResponse], int]:
        rows, total = await self._prompts.list_for_set(
            prompt_set.id,
            category=category,
            funnel_stage=funnel_stage,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )
        return await self.responses(rows), total

    async def responses(self, prompts: list[Prompt]) -> list[PromptResponse]:
        ids = [p.id for p in prompts]
        latest = await self._prompts.latest_runs(ids)
        completed = await self._prompts.latest_completed_runs(ids)
        out: list[PromptResponse] = []
        for p in prompts:
            item = PromptResponse.model_validate(p, from_attributes=True)
            item.status = "active" if p.is_active else "inactive"
            run = latest.get(p.id)
            item.last_run = PromptRunSummary.model_validate(run) if run else None
            done = completed.get(p.id)
            item.visibility_result = done.visibility if done else None
            out.append(item)
        return out

    async def get_set_for_project(
        self, project_id: uuid.UUID, prompt_set_id: uuid.UUID
    ) -> PromptSet:
        prompt_set = await self._sets.get(prompt_set_id)
        if prompt_set is None or prompt_set.project_id != project_id:
            raise NotFoundError("Prompt set not found")
        return prompt_set

    @staticmethod
    def _profile_from_set(prompt_set: PromptSet) -> BusinessProfile | None:
        data = prompt_set.generation_profile
        if not data or not data.get("company_name"):
            return None
        return BusinessProfile(
            **{k: v for k, v in data.items() if k in BusinessProfile.__dataclass_fields__}
        )
