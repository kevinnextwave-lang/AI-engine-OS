"""Competitor discovery: three sources → scored, de-duplicated candidates.

Nothing here creates a competitor. Candidates are reviewed by a person
(`accept` → competitor via CompetitorService, `reject`). Re-running discovery
updates evidence and confidence of existing candidates but never changes a
reviewed status; rejected names stay rejected.

Confidence (0–1) = weighted sum of
  frequency            0.30  responses mentioning the name, log-scaled (1.0 at ≥ 10)
  relevance            0.20  share of those responses that also mention the brand or a known
                             competitor, blended with the share of commercial prompts
  domain_confidence    0.15  1.0 domain observed in a cited URL, 0.6 AI-provided, 0 none
  competitor_language  0.20  share of observations with direct competitor language
                             ("alternative", "vs", "competitor", …)
  cross_provider       0.15  distinct AI engines that produced it / engines seen in the window
An AI-assisted suggestion alone contributes frequency 0, language 0.5 and its own
stated confidence as relevance, so AI-only candidates stay low/medium until the
stored answers corroborate them. A name seen in a single response with no other
source is not turned into a candidate at all.
"""

import json
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.registry import ProviderRegistry
from app.ai.types import AIRequest
from app.competitors.normalize import is_known_identity, normalize_name
from app.competitors.service import CompetitorInput, CompetitorService
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.logging import get_logger
from app.discovery import DISCOVERY_VERSION
from app.discovery.extract import extract_observations
from app.discovery.schema import AICandidateList
from app.models.competitor import (
    Competitor,
    CompetitorAlias,
    CompetitorConfidence,
    CompetitorProduct,
    CompetitorSource,
)
from app.models.competitor_candidates import CandidateSource, CandidateStatus, CompetitorCandidate
from app.models.domain import Domain
from app.models.entities import Entity
from app.models.intelligence import BrandMention, CompetitorMention
from app.models.project import Project
from app.models.prompts import AiResponse, Prompt, PromptRun, PromptRunStatus
from app.sources.normalize import normalize_hostname

log = get_logger(__name__)

MIN_RESPONSES_FOR_CANDIDATE = 2  # a single mention never becomes a candidate on its own
WEIGHTS = {
    "frequency": 0.30,
    "relevance": 0.20,
    "domain_confidence": 0.15,
    "competitor_language": 0.20,
    "cross_provider": 0.15,
}
FREQUENCY_SATURATION = 10
COMMERCIAL_CATEGORIES = {"comparison", "recommendation", "pricing", "alternative"}
COMMERCIAL_STAGES = {"consideration", "decision", "purchase"}
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class Aggregate:
    name: str
    normalized: str
    responses: set[uuid.UUID] = field(default_factory=set)
    prompts: dict[uuid.UUID, str] = field(default_factory=dict)
    providers: set[str] = field(default_factory=set)
    co_occurring: set[uuid.UUID] = field(default_factory=set)
    commercial_prompts: set[uuid.UUID] = field(default_factory=set)
    language_hits: int = 0
    observations: int = 0
    positions: list[int] = field(default_factory=list)
    domains: set[str] = field(default_factory=set)
    contexts: list[str] = field(default_factory=list)
    ai: dict[str, Any] | None = None
    website_hint: str | None = None


@dataclass
class DiscoveryResult:
    project_id: uuid.UUID
    responses_scanned: int
    observations: int
    candidates_written: int
    candidates_skipped_single_mention: int
    ai_used: bool
    ai_error: str | None
    discovered_at: datetime


class CompetitorDiscoveryService:
    def __init__(
        self,
        session: AsyncSession,
        registry: ProviderRegistry | None = None,
        *,
        now: datetime | None = None,
    ) -> None:
        self._session = session
        self._registry = registry
        self._now = now or datetime.now(UTC)

    # -- orchestration -------------------------------------------------------------------

    async def discover(
        self, project_id: uuid.UUID, *, window_days: int = 90, use_ai: bool = True
    ) -> DiscoveryResult:
        project = await self._session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        excluded, known = await self._known_identities(project)
        aggregates: dict[str, Aggregate] = {}

        scanned, observations = await self._from_responses(
            project, excluded, aggregates, window_days=window_days
        )
        await self._from_website(project, excluded, aggregates)
        ai_error: str | None = None
        ai_used = False
        if use_ai:
            ai_used, ai_error = await self._from_ai(project, known, excluded, aggregates)

        providers_seen = await self._providers_seen(project_id, window_days)
        written = skipped = 0
        for agg in aggregates.values():
            if len(agg.responses) < MIN_RESPONSES_FOR_CANDIDATE and agg.ai is None:
                skipped += 1
                continue
            await self._upsert(project, agg, providers_seen)
            written += 1
        await self._session.flush()
        log.info(
            "competitor_discovery_done",
            project_id=str(project_id),
            responses=scanned,
            observations=observations,
            candidates=written,
            skipped_single=skipped,
            ai_used=ai_used,
            ai_error=ai_error,
        )
        return DiscoveryResult(
            project_id, scanned, observations, written, skipped, ai_used, ai_error, self._now
        )

    # -- identities to exclude -------------------------------------------------------------

    async def _known_identities(self, project: Project) -> tuple[frozenset[str], list[str]]:
        """Normalised names that are NOT candidates (brand, own domains, configured
        competitors with aliases/products/domains) and the display names of known competitors."""
        names: set[str] = {normalize_name(project.name)}
        known: list[str] = []
        for (host,) in (
            await self._session.execute(
                select(Domain.hostname).where(Domain.project_id == project.id)
            )
        ).all():
            stem = (normalize_hostname(host) or host).split(".")[0]
            names.add(normalize_name(stem))
        comps = (
            await self._session.scalars(
                select(Competitor).where(Competitor.project_id == project.id)
            )
        ).all()
        for c in comps:
            names.add(c.normalized_name)
            names.add(normalize_name(c.normalized_domain.split(".")[0]))
            known.append(c.name)
        comp_ids = [c.id for c in comps]
        if comp_ids:
            for (alias,) in (
                await self._session.execute(
                    select(CompetitorAlias.normalized_alias).where(
                        CompetitorAlias.competitor_id.in_(comp_ids)
                    )
                )
            ).all():
                names.add(alias)
            for (prod,) in (
                await self._session.execute(
                    select(CompetitorProduct.normalized_name).where(
                        CompetitorProduct.competitor_id.in_(comp_ids)
                    )
                )
            ).all():
                names.add(prod)
        return frozenset(n for n in names if n), known

    # -- source 1: stored AI responses ----------------------------------------------------------

    async def _from_responses(
        self,
        project: Project,
        excluded: frozenset[str],
        aggregates: dict[str, Aggregate],
        *,
        window_days: int,
    ) -> tuple[int, int]:
        start = self._now - timedelta(days=window_days)
        rows = (
            await self._session.execute(
                select(AiResponse, PromptRun, Prompt)
                .join(PromptRun, PromptRun.id == AiResponse.prompt_run_id)
                .join(Prompt, Prompt.id == PromptRun.prompt_id)
                .where(
                    PromptRun.project_id == project.id,
                    PromptRun.status == PromptRunStatus.COMPLETED,
                    AiResponse.parser_version.is_not(None),
                    PromptRun.completed_at >= start,
                )
            )
        ).all()
        if not rows:
            return 0, 0
        response_ids = [r.id for r, _, _ in rows]
        mentioned: set[uuid.UUID] = set()
        for (rid,) in (
            await self._session.execute(
                select(BrandMention.ai_response_id).where(
                    BrandMention.ai_response_id.in_(response_ids)
                )
            )
        ).all():
            mentioned.add(rid)
        for (rid,) in (
            await self._session.execute(
                select(CompetitorMention.ai_response_id).where(
                    CompetitorMention.ai_response_id.in_(response_ids)
                )
            )
        ).all():
            mentioned.add(rid)

        observations = 0
        for response, run, prompt in rows:
            commercial = (
                prompt.category.value in COMMERCIAL_CATEGORIES
                or prompt.funnel_stage.value in COMMERCIAL_STAGES
            )
            for obs in extract_observations(response.response_text or "", excluded):
                observations += 1
                key = normalize_name(obs.name)
                agg = aggregates.setdefault(key, Aggregate(name=obs.name, normalized=key))
                agg.responses.add(response.id)
                agg.prompts[prompt.id] = prompt.text
                if run.provider_key:
                    agg.providers.add(run.provider_key)
                if response.id in mentioned:
                    agg.co_occurring.add(response.id)
                if commercial:
                    agg.commercial_prompts.add(prompt.id)
                agg.observations += 1
                agg.language_hits += int(obs.competitor_language)
                if obs.position is not None:
                    agg.positions.append(obs.position)
                agg.domains |= obs.domains
                if len(agg.contexts) < 3 and obs.context:
                    agg.contexts.append(obs.context)
        return len(rows), observations

    # -- source 2: website intelligence -----------------------------------------------------------

    async def _from_website(
        self, project: Project, excluded: frozenset[str], aggregates: dict[str, Aggregate]
    ) -> None:
        """Organisations the crawler found on the customer's own site (e.g. "alternatives"
        comparison pages, schema.org `competitor`/`sameAs` style references) are weak hints;
        they enrich aggregates and become website-sourced candidates only when they also
        appear elsewhere."""
        rows = (
            await self._session.scalars(
                select(Entity).where(
                    Entity.project_id == project.id,
                    or_(Entity.entity_type == "Organization", Entity.entity_type == "Brand"),
                )
            )
        ).all()
        for entity in rows:
            name = (entity.name or "").strip()
            key = normalize_name(name)
            if not key or is_known_identity(key, excluded):
                continue
            agg = aggregates.get(key)
            if agg is None:
                continue  # alone, a mention on the customer's own site is not evidence
            agg.website_hint = f"also referenced on the project website as {entity.entity_type}"

    # -- source 3: AI-assisted ------------------------------------------------------------------

    def _ai_prompt(self, project: Project, known: list[str]) -> str:
        profile = {
            "brand": project.name,
            "description": project.description,
            "industry": project.industry,
            "country": project.country,
            "known_competitors": known[:20],
        }
        return (
            "You identify direct competitors and commonly recommended alternatives for a company. "
            "Return ONLY a JSON object with this exact shape and nothing else:\n"
            '{"candidates": [{"name": "Company or product", "domain": "example.com or null", '
            '"reason": "one sentence", "confidence": 0.0-1.0, '
            '"category": "short category or null"}]}\n'
            "Rules: at most 15 candidates; do not include the brand itself or the known "
            "competitors; only include companies you are confident exist; use null when unsure "
            "of the domain.\n\nCompany profile:\n" + json.dumps(profile, ensure_ascii=False)
        )

    async def _from_ai(
        self,
        project: Project,
        known: list[str],
        excluded: frozenset[str],
        aggregates: dict[str, Aggregate],
    ) -> tuple[bool, str | None]:
        registry = self._registry or ProviderRegistry()
        provider_key = next((k for k in registry.known_keys if registry.is_configured(k)), None)
        if provider_key is None:
            return False, "no AI provider configured"
        provider = registry.get(provider_key)
        model = registry.default_model(provider_key) or ""
        response = await provider.generate(
            AIRequest(
                model=model,
                prompt=self._ai_prompt(project, known),
                system_prompt="You are a precise market analyst. Output strict JSON only.",
                temperature=0.0,
                max_tokens=1500,
                metadata={"purpose": "competitor_discovery", "project_id": str(project.id)},
            )
        )
        if not response.succeeded:
            return (
                True,
                f"{provider_key}: {response.error.category.value if response.error else 'error'}",
            )
        text = response.response_text.strip()
        match = _JSON_BLOCK.search(text)
        if match is None:
            return True, "AI answer contained no JSON object"
        try:
            parsed = AICandidateList.model_validate_json(match.group(0))
        except ValidationError as exc:
            log.warning("competitor_discovery_ai_invalid", errors=exc.error_count())
            return True, f"AI answer failed validation ({exc.error_count()} errors)"
        for item in parsed.candidates:
            key = normalize_name(item.name)
            if not key or is_known_identity(key, excluded):
                continue
            agg = aggregates.setdefault(key, Aggregate(name=item.name, normalized=key))
            agg.ai = {
                "provider": provider_key,
                "model": response.model,
                "reason": item.reason,
                "confidence": item.confidence,
                "domain": item.domain,
                "category": item.category,
            }
            if item.domain:
                agg.domains.add(item.domain)
        return True, None

    # -- scoring + persistence ------------------------------------------------------------------

    async def _providers_seen(self, project_id: uuid.UUID, window_days: int) -> set[str]:
        start = self._now - timedelta(days=window_days)
        rows = (
            await self._session.execute(
                select(PromptRun.provider_key)
                .where(
                    PromptRun.project_id == project_id,
                    PromptRun.status == PromptRunStatus.COMPLETED,
                    PromptRun.completed_at >= start,
                )
                .distinct()
            )
        ).all()
        return {p for (p,) in rows if p}

    @staticmethod
    def score(agg: Aggregate, providers_seen: set[str]) -> dict[str, Any]:
        n = len(agg.responses)
        frequency = min(1.0, math.log10(n + 1) / math.log10(FREQUENCY_SATURATION + 1)) if n else 0.0
        if n:
            co = len(agg.co_occurring) / n
            commercial = len(agg.commercial_prompts) / max(1, len(agg.prompts))
            relevance = 0.6 * co + 0.4 * commercial
        else:
            relevance = float(agg.ai["confidence"]) * 0.5 if agg.ai else 0.0
        # `agg.domains` only holds hosts the extractor already matched to the name
        # (full name or first-word stem), e.g. zoho.com for "Zoho Books".
        observed_domain = bool(agg.domains)
        domain_conf = 1.0 if observed_domain else (0.6 if agg.ai and agg.ai.get("domain") else 0.0)
        if agg.observations:
            language = agg.language_hits / agg.observations
        else:
            language = 0.5 if agg.ai else 0.0
        cross = len(agg.providers) / len(providers_seen) if providers_seen else 0.0
        components = {
            "frequency": round(frequency, 3),
            "relevance": round(relevance, 3),
            "domain_confidence": round(domain_conf, 3),
            "competitor_language": round(language, 3),
            "cross_provider": round(cross, 3),
        }
        total = round(sum(WEIGHTS[k] * v for k, v in components.items()), 3)
        label = "high" if total >= 0.7 else "medium" if total >= 0.4 else "low"
        return {"score": total, "label": label, "components": components, "weights": WEIGHTS}

    def _reason(self, agg: Aggregate, scored: dict[str, Any]) -> str:
        parts = []
        n = len(agg.responses)
        if n:
            parts.append(f"Appeared in {n} relevant AI response{'s' if n != 1 else ''}")
            if agg.language_hits:
                parts.append(
                    f"named with competitor/alternative language {agg.language_hits} time"
                    f"{'s' if agg.language_hits != 1 else ''}"
                )
            if agg.co_occurring:
                parts.append(
                    f"alongside the brand or a known competitor in {len(agg.co_occurring)}"
                )
        if agg.ai:
            parts.append(f"suggested by {agg.ai['provider']}: {agg.ai['reason']}")
        if agg.website_hint:
            parts.append(agg.website_hint)
        return "; ".join(parts) + "."

    async def _upsert(self, project: Project, agg: Aggregate, providers_seen: set[str]) -> None:
        scored = self.score(agg, providers_seen)
        sources = []
        if agg.responses:
            sources.append(CandidateSource.AI_RESPONSES.value)
        if agg.website_hint:
            sources.append(CandidateSource.WEBSITE_INTELLIGENCE.value)
        if agg.ai:
            sources.append(CandidateSource.AI_ASSISTED.value)
        source = CandidateSource.COMBINED.value if len(sources) > 1 else sources[0]
        # Prefer a host containing the whole name (quickbooks.intuit.com for
        # "QuickBooks"), then any stem-matched host (zoho.com for "Zoho Books"),
        # then the AI-provided domain.
        observed = sorted(agg.domains)
        domain = (
            next(
                (d for d in observed if agg.normalized in d.replace("-", "").replace(".", "")),
                None,
            )
            or (observed[0] if observed else None)
            or (agg.ai.get("domain") if agg.ai else None)
        )
        evidence = {
            "responses": len(agg.responses),
            "observations": agg.observations,
            "prompts": [
                {"prompt_id": str(pid), "text": text}
                for pid, text in list(agg.prompts.items())[:10]
            ],
            "prompt_count": len(agg.prompts),
            "co_occurring_responses": len(agg.co_occurring),
            "commercial_prompts": len(agg.commercial_prompts),
            "providers": sorted(agg.providers),
            "providers_seen": sorted(providers_seen),
            "competitor_language_hits": agg.language_hits,
            "average_position": round(sum(agg.positions) / len(agg.positions), 2)
            if agg.positions
            else None,
            "domains_observed": sorted(agg.domains),
            "examples": agg.contexts,
            "ai": agg.ai,
            "website": agg.website_hint,
            "sources": sources,
            "confidence": scored,
            "discovery_version": DISCOVERY_VERSION,
        }
        row = (
            await self._session.scalars(
                select(CompetitorCandidate).where(
                    CompetitorCandidate.project_id == project.id,
                    CompetitorCandidate.normalized_name == agg.normalized,
                )
            )
        ).first()
        if row is None:
            row = CompetitorCandidate(
                project_id=project.id,
                name=agg.name,
                normalized_name=agg.normalized,
                discovery_version=DISCOVERY_VERSION,
                discovered_at=self._now,
            )
            self._session.add(row)
        row.domain = domain
        row.reason = self._reason(agg, scored)
        row.evidence = evidence
        row.confidence = float(scored["score"])
        row.confidence_label = str(scored["label"])
        row.source = source
        row.discovery_version = DISCOVERY_VERSION
        row.discovered_at = self._now

    # -- review ---------------------------------------------------------------------------

    async def accept(
        self,
        candidate: CompetitorCandidate,
        *,
        user_id: uuid.UUID,
        website_url: str | None = None,
        name: str | None = None,
    ) -> Competitor:
        if candidate.status == CandidateStatus.ACCEPTED.value:
            raise ConflictError("Candidate already accepted")
        url = website_url or (f"https://{candidate.domain}" if candidate.domain else None)
        if not url:
            raise ValidationAppError(
                "This candidate has no known domain; provide website_url to accept it"
            )
        competitor = await CompetitorService(self._session).create(
            candidate.project_id,
            CompetitorInput(
                name=(name or candidate.name).strip(),
                website_url=url,
                description=candidate.reason,
                source=CompetitorSource.DISCOVERED,
                confidence=CompetitorConfidence(candidate.confidence_label),
            ),
        )
        candidate.status = CandidateStatus.ACCEPTED.value
        candidate.competitor_id = competitor.id
        candidate.reviewed_at = self._now
        candidate.reviewed_by_user_id = user_id
        await self._session.flush()
        return competitor

    async def reject(self, candidate: CompetitorCandidate, *, user_id: uuid.UUID) -> None:
        if candidate.status == CandidateStatus.ACCEPTED.value:
            raise ConflictError("An accepted candidate cannot be rejected; remove the competitor")
        candidate.status = CandidateStatus.REJECTED.value
        candidate.reviewed_at = self._now
        candidate.reviewed_by_user_id = user_id
        await self._session.flush()
