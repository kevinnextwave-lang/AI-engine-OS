"""Graph query service: answers the AI Search Graph questions with SQL.

Every query is scoped to one project (tenancy is enforced by the caller's
project access; this service never reads across projects) and to a time
window on `prompt_runs.completed_at`. Everything is top-N / paginated — the
full graph is never materialised.

Questions answered (see docs/ai-search-graph.md):
  Q1 sources(view="top")        most frequently cited sources
  Q2 sources(view="competitor") sources frequently associated with competitors
  Q3 sources(view="gap")        sources citing competitors but rarely the brand
  Q4 prompts()                  prompts producing the most competitor citations
  Q5 sources(view="rising")     sources becoming more important over time
  Q6 claims()                   claims repeatedly associated with competitors
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import Integer, Select, cast, distinct, false, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph import GRAPH_VERSION
from app.models.competitor import Competitor
from app.models.intelligence import (
    BrandMention,
    CompetitorMention,
    ResponseCitation,
    ResponseClaim,
)
from app.models.project import Project
from app.models.prompts import AiResponse, Prompt, PromptRun, PromptRunStatus
from app.models.sources import CitationEntity, CitationRelationship, SourceDomain, SourcePage

DEFAULT_WINDOW_DAYS = 90
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
SourceView = Literal["top", "competitor", "gap", "rising"]


@dataclass(frozen=True)
class Window:
    """Time window on prompt_runs.completed_at, optionally restricted to one AI provider."""

    start: datetime
    end: datetime
    provider: str | None = None

    @classmethod
    def default(cls, now: datetime | None = None) -> "Window":
        end = now or datetime.now(UTC)
        return cls(end - timedelta(days=DEFAULT_WINDOW_DAYS), end)

    @property
    def previous(self) -> "Window":
        return Window(self.start - (self.end - self.start), self.start, self.provider)


def node_id(kind: str, key: Any) -> str:
    return f"{kind}:{key}"


class GraphQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- building blocks ---------------------------------------------------------------

    def _responses(self, project_id: uuid.UUID, w: Window) -> Any:
        """Eligible responses (completed, parsed) in the window, with prompt and model."""
        stmt = (
            select(
                AiResponse.id.label("response_id"),
                PromptRun.prompt_id.label("prompt_id"),
                PromptRun.provider_key.label("provider_key"),
                PromptRun.model_key.label("model_key"),
                PromptRun.completed_at.label("completed_at"),
            )
            .join(PromptRun, PromptRun.id == AiResponse.prompt_run_id)
            .where(
                PromptRun.project_id == project_id,
                PromptRun.status == PromptRunStatus.COMPLETED,
                AiResponse.parser_version.is_not(None),
                PromptRun.completed_at >= w.start,
                PromptRun.completed_at < w.end,
            )
        )
        if w.provider:
            stmt = stmt.where(PromptRun.provider_key == w.provider)
        return stmt.subquery("responses")

    def _relationships(self, project_id: uuid.UUID) -> Any:
        return (
            select(
                CitationEntity.citation_id.label("cid"),
                func.bool_or(CitationEntity.relationship == CitationRelationship.BRAND.value).label(
                    "is_brand"
                ),
                func.bool_or(
                    CitationEntity.relationship == CitationRelationship.COMPETITOR.value
                ).label("is_competitor"),
            )
            .where(CitationEntity.project_id == project_id)
            .group_by(CitationEntity.citation_id)
            .subquery("rel")
        )

    def _citations(self, project_id: uuid.UUID, w: Window) -> Any:
        """Citations of eligible responses, flagged with brand/competitor relationships."""
        responses = self._responses(project_id, w)
        rel = self._relationships(project_id)
        return (
            select(
                ResponseCitation.id.label("cid"),
                ResponseCitation.source_domain_id.label("domain_id"),
                ResponseCitation.source_page_id.label("page_id"),
                ResponseCitation.created_at.label("cited_at"),
                responses.c.response_id,
                responses.c.prompt_id,
                func.coalesce(rel.c.is_brand, False).label("is_brand"),
                func.coalesce(rel.c.is_competitor, False).label("is_competitor"),
            )
            .join(responses, responses.c.response_id == ResponseCitation.ai_response_id)
            .outerjoin(rel, rel.c.cid == ResponseCitation.id)
            .where(
                ResponseCitation.project_id == project_id,
                ResponseCitation.source_domain_id.is_not(None),
            )
        ).subquery("cites")

    async def _competitor_counts_by_domain(
        self, cites: Any, domain_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, int]]:
        if not domain_ids:
            return {}
        rows = (
            await self._session.execute(
                select(cites.c.domain_id, CitationEntity.entity_name, func.count())
                .join(CitationEntity, CitationEntity.citation_id == cites.c.cid)
                .where(
                    CitationEntity.relationship == CitationRelationship.COMPETITOR.value,
                    cites.c.domain_id.in_(domain_ids),
                )
                .group_by(cites.c.domain_id, CitationEntity.entity_name)
            )
        ).all()
        out: dict[uuid.UUID, dict[str, int]] = {}
        for domain_id, name, n in rows:
            out.setdefault(domain_id, {})[name] = int(n)
        return out

    async def _top_pages_by_domain(
        self, cites: Any, domain_ids: list[uuid.UUID], per_domain: int = 3
    ) -> dict[uuid.UUID, list[dict[str, Any]]]:
        if not domain_ids:
            return {}
        rows = (
            await self._session.execute(
                select(cites.c.domain_id, SourcePage.id, SourcePage.url, func.count().label("n"))
                .join(SourcePage, SourcePage.id == cites.c.page_id)
                .where(cites.c.domain_id.in_(domain_ids))
                .group_by(cites.c.domain_id, SourcePage.id, SourcePage.url)
                .order_by(func.count().desc())
            )
        ).all()
        out: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for domain_id, page_id, url, n in rows:
            bucket = out.setdefault(domain_id, [])
            if len(bucket) < per_domain:
                bucket.append({"source_page_id": str(page_id), "url": url, "citations": int(n)})
        return out

    # -- Q1/Q2/Q3/Q5: sources -----------------------------------------------------------------

    async def sources(
        self,
        project_id: uuid.UUID,
        w: Window,
        *,
        view: SourceView = "top",
        source_type: str | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        cites = self._citations(project_id, w)
        agg = (
            select(
                cites.c.domain_id,
                func.count().label("citations"),
                func.count(distinct(cites.c.response_id)).label("responses"),
                func.count(distinct(cites.c.prompt_id)).label("prompts"),
                func.sum(cast(cites.c.is_brand, Integer)).label("brand"),
                func.sum(cast(cites.c.is_competitor, Integer)).label("competitor"),
                func.min(cites.c.cited_at).label("first"),
                func.max(cites.c.cited_at).label("last"),
            )
            .group_by(cites.c.domain_id)
            .subquery("agg")
        )
        stmt: Select[Any] = select(agg, SourceDomain).join(
            SourceDomain, SourceDomain.id == agg.c.domain_id
        )
        if source_type:
            stmt = stmt.where(SourceDomain.domain_type == source_type)

        previous: dict[uuid.UUID, int] = {}
        if view == "competitor":
            stmt = stmt.where(agg.c.competitor > 0).order_by(
                agg.c.competitor.desc(), agg.c.citations.desc()
            )
        elif view == "gap":
            # competitors cited at least 3 times and at least 3× more often than the brand
            stmt = stmt.where(agg.c.competitor >= 3, agg.c.competitor >= 3 * agg.c.brand).order_by(
                (agg.c.competitor - agg.c.brand).desc(), agg.c.citations.desc()
            )
        elif view == "rising":
            prev_cites = self._citations(project_id, w.previous)
            prev_rows = (
                await self._session.execute(
                    select(prev_cites.c.domain_id, func.count()).group_by(prev_cites.c.domain_id)
                )
            ).all()
            previous = {d: int(n) for d, n in prev_rows}
            stmt = stmt.order_by(agg.c.citations.desc())
        else:
            stmt = stmt.order_by(agg.c.citations.desc(), agg.c.responses.desc())

        total = await self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        if view == "rising":
            # growth needs the previous window; rank in Python over a bounded candidate set
            rows = (await self._session.execute(stmt.limit(MAX_LIMIT * 2))).all()
            scored: list[tuple[float, int, Any, int]] = []
            for row in rows:
                cur = int(row.citations)
                prev = previous.get(row.domain_id, 0)
                if cur < 3 or cur <= prev:
                    continue
                scored.append(((cur - prev) / max(prev, 1), cur, row, prev))
            scored.sort(key=lambda t: (-t[0], -t[1]))
            total = len(scored)
            page = scored[offset : offset + limit]
            rows = [t[2] for t in page]
            growth = {t[2].domain_id: (t[0], t[3]) for t in page}
        else:
            rows = (await self._session.execute(stmt.limit(limit).offset(offset))).all()
            growth = {}

        ids = [r.domain_id for r in rows]
        comps = await self._competitor_counts_by_domain(cites, ids)
        pages = await self._top_pages_by_domain(cites, ids)
        items = []
        for r in rows:
            d: SourceDomain = r[len(agg.c)]  # the SourceDomain entity follows the agg columns
            citations = int(r.citations)
            brand, competitor = int(r.brand or 0), int(r.competitor or 0)
            item: dict[str, Any] = {
                "source_domain_id": d.id,
                "domain": d.normalized_hostname,
                "display_name": d.display_name,
                "source_type": d.domain_type,
                "citations": citations,
                "responses": int(r.responses),
                "prompts": int(r.prompts),
                "brand_citations": brand,
                "competitor_citations": competitor,
                "competitors": comps.get(r.domain_id, {}),
                "first_cited_at": r.first,
                "last_cited_at": r.last,
                "top_pages": pages.get(r.domain_id, []),
            }
            if view in ("competitor", "gap"):
                item["competitor_share"] = round(competitor / citations, 3) if citations else None
            if view == "gap":
                item["brand_ratio"] = round(brand / competitor, 3) if competitor else None
            if view == "rising":
                g, prev = growth[r.domain_id]
                item["growth"] = round(g, 3)
                item["previous_citations"] = prev
            items.append(item)
        return items, int(total)

    # -- competitors (and the competes_with edges) --------------------------------------------

    async def competitors(
        self, project_id: uuid.UUID, w: Window, *, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
        project = await self._session.get(Project, project_id)
        brand_name = project.name if project else "brand"
        responses = self._responses(project_id, w)
        cites = self._citations(project_id, w)

        brand_resp = (
            select(distinct(BrandMention.ai_response_id).label("rid"))
            .join(responses, responses.c.response_id == BrandMention.ai_response_id)
            .where(BrandMention.project_id == project_id)
            .subquery("brand_resp")
        )
        brand_mentions = (
            await self._session.execute(
                select(func.count(), func.count(distinct(BrandMention.ai_response_id)))
                .join(responses, responses.c.response_id == BrandMention.ai_response_id)
                .where(BrandMention.project_id == project_id)
            )
        ).one()
        brand_citations = (
            await self._session.scalar(
                select(func.count()).select_from(cites).where(cites.c.is_brand.is_(True))
            )
            or 0
        )

        comp_rows = (
            await self._session.execute(
                select(
                    CompetitorMention.competitor_name,
                    CompetitorMention.competitor_id,
                    func.count().label("mentions"),
                    func.count(distinct(CompetitorMention.ai_response_id)).label("responses"),
                    func.count(distinct(brand_resp.c.rid)).label("co"),
                )
                .join(responses, responses.c.response_id == CompetitorMention.ai_response_id)
                .outerjoin(brand_resp, brand_resp.c.rid == CompetitorMention.ai_response_id)
                .where(CompetitorMention.project_id == project_id)
                .group_by(CompetitorMention.competitor_name, CompetitorMention.competitor_id)
                .order_by(func.count().desc())
            )
        ).all()
        configured = {
            c.name: c
            for c in (
                await self._session.scalars(
                    select(Competitor).where(Competitor.project_id == project_id)
                )
            ).all()
        }
        cite_rows = (
            await self._session.execute(
                select(CitationEntity.entity_name, func.count())
                .join(cites, cites.c.cid == CitationEntity.citation_id)
                .where(CitationEntity.relationship == CitationRelationship.COMPETITOR.value)
                .group_by(CitationEntity.entity_name)
            )
        ).all()
        comp_citations = {name: int(n) for name, n in cite_rows}
        top_sources = await self._top_sources_by_entity(
            cites, CitationRelationship.COMPETITOR.value
        )
        brand_sources = await self._top_sources_by_entity(cites, CitationRelationship.BRAND.value)

        items: list[dict[str, Any]] = [
            {
                "competitor_id": None,
                "name": brand_name,
                "is_brand": True,
                "mentions": int(brand_mentions[0]),
                "responses_mentioning": int(brand_mentions[1]),
                "citations": int(brand_citations),
                "co_mentions_with_brand": int(brand_mentions[1]),
                "top_sources": brand_sources.get(brand_name, []),
            }
        ]
        edges: list[dict[str, Any]] = []
        seen = set()
        for name, raw_cid, mentions, resp, co in comp_rows:
            seen.add(name)
            cid = raw_cid or (configured[name].id if name in configured else None)
            items.append(
                {
                    "competitor_id": cid,
                    "name": name,
                    "is_brand": False,
                    "mentions": int(mentions),
                    "responses_mentioning": int(resp),
                    "citations": comp_citations.get(name, 0),
                    "co_mentions_with_brand": int(co),
                    "top_sources": top_sources.get(name, []),
                }
            )
            if int(co) > 0:
                edges.append(
                    {
                        "source": node_id("brand", project_id),
                        "target": node_id("competitor", cid or name),
                        "type": "competes_with",
                        "weight": int(co),
                        "properties": {"basis": "responses mentioning both"},
                    }
                )
        for name, c in configured.items():  # configured but never mentioned in the window
            if name not in seen:
                items.append(
                    {
                        "competitor_id": c.id,
                        "name": name,
                        "is_brand": False,
                        "mentions": 0,
                        "responses_mentioning": 0,
                        "citations": comp_citations.get(name, 0),
                        "co_mentions_with_brand": 0,
                        "top_sources": top_sources.get(name, []),
                    }
                )
        total = len(items)
        return items[offset : offset + limit], edges, total

    async def _top_sources_by_entity(
        self, cites: Any, relationship: str, per_entity: int = 5
    ) -> dict[str, list[dict[str, Any]]]:
        rows = (
            await self._session.execute(
                select(
                    CitationEntity.entity_name,
                    SourceDomain.id,
                    SourceDomain.normalized_hostname,
                    func.count().label("n"),
                )
                .join(cites, cites.c.cid == CitationEntity.citation_id)
                .join(SourceDomain, SourceDomain.id == cites.c.domain_id)
                .where(CitationEntity.relationship == relationship)
                .group_by(
                    CitationEntity.entity_name, SourceDomain.id, SourceDomain.normalized_hostname
                )
                .order_by(func.count().desc())
            )
        ).all()
        out: dict[str, list[dict[str, Any]]] = {}
        for name, did, host, n in rows:
            bucket = out.setdefault(name, [])
            if len(bucket) < per_entity:
                bucket.append({"source_domain_id": str(did), "domain": host, "citations": int(n)})
        return out

    # -- Q4: prompts ----------------------------------------------------------------------------

    async def prompts(
        self, project_id: uuid.UUID, w: Window, *, limit: int = DEFAULT_LIMIT, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        responses = self._responses(project_id, w)
        cites = self._citations(project_id, w)
        resp_per_prompt = (
            select(responses.c.prompt_id, func.count().label("responses"))
            .group_by(responses.c.prompt_id)
            .subquery("rpp")
        )
        cite_per_prompt = (
            select(
                cites.c.prompt_id,
                func.count().label("citations"),
                func.sum(cast(cites.c.is_brand, Integer)).label("brand_citations"),
                func.sum(cast(cites.c.is_competitor, Integer)).label("competitor_citations"),
            )
            .group_by(cites.c.prompt_id)
            .subquery("cpp")
        )
        bm = (
            select(responses.c.prompt_id, func.count().label("n"))
            .join(BrandMention, BrandMention.ai_response_id == responses.c.response_id)
            .group_by(responses.c.prompt_id)
            .subquery("bm")
        )
        cm = (
            select(responses.c.prompt_id, func.count().label("n"))
            .join(CompetitorMention, CompetitorMention.ai_response_id == responses.c.response_id)
            .group_by(responses.c.prompt_id)
            .subquery("cm")
        )
        stmt = (
            select(
                Prompt,
                resp_per_prompt.c.responses,
                func.coalesce(cite_per_prompt.c.citations, 0).label("citations"),
                func.coalesce(cite_per_prompt.c.brand_citations, 0).label("brand_citations"),
                func.coalesce(cite_per_prompt.c.competitor_citations, 0).label(
                    "competitor_citations"
                ),
                func.coalesce(bm.c.n, 0).label("brand_mentions"),
                func.coalesce(cm.c.n, 0).label("competitor_mentions"),
            )
            .join(resp_per_prompt, resp_per_prompt.c.prompt_id == Prompt.id)
            .outerjoin(cite_per_prompt, cite_per_prompt.c.prompt_id == Prompt.id)
            .outerjoin(bm, bm.c.prompt_id == Prompt.id)
            .outerjoin(cm, cm.c.prompt_id == Prompt.id)
            .where(Prompt.project_id == project_id)
            .order_by(
                func.coalesce(cite_per_prompt.c.competitor_citations, 0).desc(),
                func.coalesce(cm.c.n, 0).desc(),
                resp_per_prompt.c.responses.desc(),
            )
        )
        total = await self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = (await self._session.execute(stmt.limit(limit).offset(offset))).all()
        prompt_ids = [r[0].id for r in rows]
        comp_rows = (
            await self._session.execute(
                select(cites.c.prompt_id, CitationEntity.entity_name, func.count())
                .join(CitationEntity, CitationEntity.citation_id == cites.c.cid)
                .where(
                    CitationEntity.relationship == CitationRelationship.COMPETITOR.value,
                    cites.c.prompt_id.in_(prompt_ids) if prompt_ids else false(),
                )
                .group_by(cites.c.prompt_id, CitationEntity.entity_name)
            )
        ).all()
        comps: dict[uuid.UUID, dict[str, int]] = {}
        for pid, name, n in comp_rows:
            comps.setdefault(pid, {})[name] = int(n)
        src_rows = (
            await self._session.execute(
                select(
                    cites.c.prompt_id,
                    SourceDomain.id,
                    SourceDomain.normalized_hostname,
                    func.count(),
                )
                .join(SourceDomain, SourceDomain.id == cites.c.domain_id)
                .where(cites.c.prompt_id.in_(prompt_ids) if prompt_ids else false())
                .group_by(cites.c.prompt_id, SourceDomain.id, SourceDomain.normalized_hostname)
                .order_by(func.count().desc())
            )
        ).all()
        srcs: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for pid, did, host, n in src_rows:
            bucket = srcs.setdefault(pid, [])
            if len(bucket) < 5:
                bucket.append({"source_domain_id": str(did), "domain": host, "citations": int(n)})
        items = [
            {
                "prompt_id": p.id,
                "text": p.text,
                "category": p.category.value,
                "funnel_stage": p.funnel_stage.value,
                "responses": int(r.responses),
                "brand_mentions": int(r.brand_mentions),
                "competitor_mentions": int(r.competitor_mentions),
                "competitor_citations": int(r.competitor_citations),
                "brand_citations": int(r.brand_citations),
                "citations": int(r.citations),
                "competitors": comps.get(p.id, {}),
                "top_sources": srcs.get(p.id, []),
            }
            for r in rows
            for p in [r[0]]
        ]
        return items, int(total)

    # -- Q6: claims -----------------------------------------------------------------------------

    async def claims(
        self,
        project_id: uuid.UUID,
        w: Window,
        *,
        associated_with: Literal["brand", "competitor", "other"] | None = None,
        min_occurrences: int = 2,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        project = await self._session.get(Project, project_id)
        brand_name = (project.name if project else "").lower()
        competitor_names = {
            c.name.lower(): c.name
            for c in (
                await self._session.scalars(
                    select(Competitor).where(Competitor.project_id == project_id)
                )
            ).all()
        }
        responses = self._responses(project_id, w)
        subject = func.lower(func.trim(ResponseClaim.subject))
        predicate = func.lower(func.trim(ResponseClaim.predicate))
        obj = func.lower(func.trim(ResponseClaim.object))
        stmt = (
            select(
                subject.label("subject"),
                predicate.label("predicate"),
                obj.label("object"),
                func.count().label("occurrences"),
                func.count(distinct(ResponseClaim.ai_response_id)).label("responses"),
                func.count(distinct(responses.c.prompt_id)).label("prompts"),
                func.avg(ResponseClaim.confidence).label("avg_confidence"),
                func.min(ResponseClaim.created_at).label("first"),
                func.max(ResponseClaim.created_at).label("last"),
                func.min(ResponseClaim.context).label("example"),
            )
            .join(responses, responses.c.response_id == ResponseClaim.ai_response_id)
            .where(ResponseClaim.project_id == project_id)
            .group_by(subject, predicate, obj)
            .having(func.count() >= min_occurrences)
        )
        if associated_with == "brand":
            stmt = stmt.where(subject == brand_name)
        elif associated_with == "competitor":
            stmt = stmt.where(subject.in_(list(competitor_names)) if competitor_names else false())
        elif associated_with == "other":
            stmt = stmt.where(subject != brand_name, subject.not_in(list(competitor_names)))
        stmt = stmt.order_by(func.count().desc(), func.max(ResponseClaim.created_at).desc())
        total = await self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = (await self._session.execute(stmt.limit(limit).offset(offset))).all()
        items = []
        for r in rows:
            if r.subject == brand_name:
                assoc, entity = "brand", project.name if project else None
            elif r.subject in competitor_names:
                assoc, entity = "competitor", competitor_names[r.subject]
            else:
                assoc, entity = "other", None
            items.append(
                {
                    "subject": r.subject,
                    "predicate": r.predicate,
                    "object": r.object,
                    "occurrences": int(r.occurrences),
                    "responses": int(r.responses),
                    "prompts": int(r.prompts),
                    "avg_confidence": round(float(r.avg_confidence or 0), 3),
                    "associated_with": assoc,
                    "entity_name": entity,
                    "first_seen_at": r.first,
                    "last_seen_at": r.last,
                    "examples": [r.example] if r.example else [],
                }
            )
        return items, int(total)

    # -- overview: bounded subgraph -----------------------------------------------------------

    async def overview(
        self,
        project_id: uuid.UUID,
        w: Window,
        *,
        top_sources: int = DEFAULT_LIMIT,
        top_prompts: int = DEFAULT_LIMIT,
        top_claims: int = 10,
        source_type: str | None = None,
    ) -> dict[str, Any]:
        project = await self._session.get(Project, project_id)
        if project is None:
            raise ValueError("project not found")
        responses = self._responses(project_id, w)
        cites = self._citations(project_id, w)

        stats_row = (
            await self._session.execute(
                select(
                    func.count(),
                    func.count(distinct(responses.c.prompt_id)),
                    func.count(
                        distinct(func.concat(responses.c.provider_key, "/", responses.c.model_key))
                    ),
                ).select_from(responses)
            )
        ).one()
        counts = {
            "brand_mentions": await self._count_joined(BrandMention, responses, project_id),
            "competitor_mentions": await self._count_joined(
                CompetitorMention, responses, project_id
            ),
            "claims": await self._count_joined(ResponseClaim, responses, project_id),
        }
        cite_stats = (
            await self._session.execute(
                select(
                    func.count(),
                    func.count(distinct(cites.c.domain_id)),
                    func.count(distinct(cites.c.page_id)),
                    func.coalesce(func.sum(cast(cites.c.is_brand, Integer)), 0),
                    func.coalesce(func.sum(cast(cites.c.is_competitor, Integer)), 0),
                ).select_from(cites)
            )
        ).one()

        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []

        def add_node(kind: str, key: Any, label: str, **props: Any) -> str:
            nid = node_id(kind, key)
            nodes.setdefault(nid, {"id": nid, "type": kind, "label": label, "properties": props})
            return nid

        def add_edge(src: str, dst: str, kind: str, weight: int = 1, **props: Any) -> None:
            edges.append(
                {"source": src, "target": dst, "type": kind, "weight": weight, "properties": props}
            )

        pnode = add_node("project", project.id, project.name)
        bnode = add_node("brand", project.id, project.name)
        add_edge(pnode, bnode, "tracks")
        competitors, comp_edges, _ = await self.competitors(project_id, w, limit=MAX_LIMIT)
        comp_nodes: dict[str, str] = {}
        for c in competitors:
            if c["is_brand"]:
                nodes[bnode]["properties"].update(
                    mentions=c["mentions"],
                    responses_mentioning=c["responses_mentioning"],
                    citations=c["citations"],
                )
                continue
            cid = add_node(
                "competitor",
                c["competitor_id"] or c["name"],
                c["name"],
                mentions=c["mentions"],
                responses_mentioning=c["responses_mentioning"],
                citations=c["citations"],
                configured=c["competitor_id"] is not None,
            )
            comp_nodes[c["name"]] = cid
            if c["competitor_id"] is not None:
                add_edge(pnode, cid, "tracks")
        for e in comp_edges:
            target = e["target"]
            if target not in nodes:  # unconfigured competitor keyed by name
                continue
            add_edge(bnode, target, "competes_with", e["weight"], **e["properties"])

        prompts, prompts_total = await self.prompts(project_id, w, limit=top_prompts)
        prompt_nodes: dict[uuid.UUID, str] = {}
        for p in prompts:
            pid = add_node(
                "prompt",
                p["prompt_id"],
                p["text"],
                category=p["category"],
                funnel_stage=p["funnel_stage"],
                responses=p["responses"],
                citations=p["citations"],
            )
            prompt_nodes[p["prompt_id"]] = pid
            add_edge(pnode, pid, "has_prompt")
            if p["brand_mentions"]:
                add_edge(pid, bnode, "mentions", p["brand_mentions"], via="responses")
            for name, n in p["competitors"].items():
                if name in comp_nodes:
                    add_edge(pid, comp_nodes[name], "cites", n, via="competitor citations")

        sources, sources_total = await self.sources(
            project_id, w, view="top", limit=top_sources, source_type=source_type
        )
        source_nodes: dict[uuid.UUID, str] = {}
        for s in sources:
            sid = add_node(
                "source_domain",
                s["source_domain_id"],
                s["domain"],
                source_type=s["source_type"],
                citations=s["citations"],
                responses=s["responses"],
            )
            source_nodes[s["source_domain_id"]] = sid
            if s["brand_citations"]:
                add_edge(bnode, sid, "associated_with", s["brand_citations"], relationship="brand")
            for name, n in s["competitors"].items():
                if name in comp_nodes:
                    add_edge(comp_nodes[name], sid, "associated_with", n, relationship="competitor")
        # prompt → source "cites" edges, only between nodes already in the subgraph
        if prompt_nodes and source_nodes:
            ps_rows = (
                await self._session.execute(
                    select(cites.c.prompt_id, cites.c.domain_id, func.count())
                    .where(
                        cites.c.prompt_id.in_(list(prompt_nodes)),
                        cites.c.domain_id.in_(list(source_nodes)),
                    )
                    .group_by(cites.c.prompt_id, cites.c.domain_id)
                )
            ).all()
            for pid, did, n in ps_rows:
                add_edge(prompt_nodes[pid], source_nodes[did], "cites", int(n))

        claims, _ = await self.claims(project_id, w, limit=top_claims)
        for c in claims:
            key = f"{c['subject']}|{c['predicate']}|{c['object']}"
            cid = add_node(
                "claim",
                key,
                f"{c['subject']} {c['predicate']} {c['object']}",
                occurrences=c["occurrences"],
                associated_with=c["associated_with"],
            )
            if c["associated_with"] == "brand":
                add_edge(bnode, cid, "claims", c["occurrences"])
            elif c["associated_with"] == "competitor" and c["entity_name"] in comp_nodes:
                add_edge(comp_nodes[c["entity_name"]], cid, "claims", c["occurrences"])

        truncated = prompts_total > len(prompts) or sources_total > len(sources)
        return {
            "version": GRAPH_VERSION,
            "project_id": project_id,
            "window": {"start": w.start, "end": w.end},
            "nodes": list(nodes.values()),
            "edges": edges,
            "statistics": {
                "responses": int(stats_row[0]),
                "prompts": int(stats_row[1]),
                "models": int(stats_row[2]),
                **counts,
                "citations": int(cite_stats[0]),
                "source_domains": int(cite_stats[1]),
                "source_pages": int(cite_stats[2]),
                "brand_citations": int(cite_stats[3]),
                "competitor_citations": int(cite_stats[4]),
                "provider": w.provider,
                "competitors_configured": sum(1 for c in competitors if c["competitor_id"]),
                "nodes_returned": len(nodes),
                "edges_returned": len(edges),
                "truncated": truncated,
            },
        }

    async def _count_joined(self, model: Any, responses: Any, project_id: uuid.UUID) -> int:
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(model)
                .join(responses, responses.c.response_id == model.ai_response_id)
                .where(model.project_id == project_id)
            )
            or 0
        )
