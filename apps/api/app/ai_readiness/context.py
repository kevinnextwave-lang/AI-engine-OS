"""Page snapshots for the readiness analyzers, with a deterministic page-kind
classification (product, service, article, pricing, faq, comparison, ...)."""

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import WebsitePage
from app.models.entities import Entity, EntityObservation, EntityScope
from app.models.page_intelligence import (
    LinkType,
    PageContentMetrics,
    PageHeading,
    PageLink,
    PageMetadata,
    PageStructuredData,
)
from app.models.project import Project

MAX_TEXT_CHARS = 60_000

_COMPARISON_TITLE = re.compile(
    r"\b(vs\.?|versus|alternatives?|compare|comparison|best)\b|\bpricing\b", re.I
)
_COMPARISON_PATH = re.compile(r"/(vs|versus|compare|comparison|alternatives?|best-|pricing)", re.I)


@dataclass(eq=False)
class PageSnapshot:
    id: uuid.UUID
    url: str
    path: str
    title: str | None
    meta_description: str | None
    word_count: int
    text: str
    headings: list[tuple[int, str]]  # (level, text) in document order
    author: str | None
    published_at: Any
    modified_at: Any
    open_graph: dict[str, Any]
    schema_types: set[str]
    entities: list[Entity]
    external_links: list[PageLink]
    depth: int | None = None
    kinds: set[str] = field(default_factory=set)

    @property
    def h1(self) -> str | None:
        return next((t for lvl, t in self.headings if lvl == 1), None)

    def has_kind(self, *kinds: str) -> bool:
        return bool(self.kinds & set(kinds))


@dataclass
class ReadinessContext:
    project_id: uuid.UUID
    project_name: str
    root_host: str
    pages: list[PageSnapshot]
    organization: Entity | None  # project-scope entity from Milestone 2D
    entity_conflicts: list[EntityObservation]
    entities_compared: int

    def pages_of(self, *kinds: str) -> list[PageSnapshot]:
        return [p for p in self.pages if p.has_kind(*kinds)]

    @property
    def homepage(self) -> PageSnapshot | None:
        return next((p for p in self.pages if "home" in p.kinds), None)


# --- classification -------------------------------------------------------------

_KIND_PATHS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "product",
        re.compile(r"^/(products?|solutions?|features?|platform|software|apps?)(/|$)", re.I),
    ),
    ("service", re.compile(r"^/(services?|offerings?|what-we-do|expertise)(/|$)", re.I)),
    ("pricing", re.compile(r"^/(pricing|plans|prices|tarifs?|preise)(/|$)", re.I)),
    (
        "article",
        re.compile(r"^/(blog|news|articles?|insights|resources|guides?|learn|posts?)/.+", re.I),
    ),
    ("about", re.compile(r"^/(about|about-us|company|who-we-are|our-story|team)(/|$)", re.I)),
    ("contact", re.compile(r"^/(contact|contact-us|impressum|imprint)(/|$)", re.I)),
    ("faq", re.compile(r"^/(faq|faqs|help|support|questions)(/|$)", re.I)),
    (
        "case_study",
        re.compile(r"^/(case-stud(y|ies)|customers?|success-stories|clients?)/.+", re.I),
    ),
)
_KIND_SCHEMA = {
    "Product": "product",
    "Service": "service",
    "Article": "article",
    "BlogPosting": "article",
    "NewsArticle": "article",
    "TechArticle": "article",
    "FAQPage": "faq",
    "AboutPage": "about",
    "ContactPage": "contact",
    "Offer": "pricing",
}


def classify(page: PageSnapshot, root_host: str) -> set[str]:
    kinds: set[str] = set()
    host = (urlsplit(page.url).hostname or "").lower().removeprefix("www.")
    if page.path in ("", "/") and host == root_host:
        kinds.add("home")
    for kind, pattern in _KIND_PATHS:
        if pattern.search(page.path):
            kinds.add(kind)
    for schema_type, kind in _KIND_SCHEMA.items():
        if schema_type in page.schema_types:
            kinds.add(kind)
    title = f"{page.title or ''} {page.h1 or ''}"
    if _COMPARISON_TITLE.search(title) or _COMPARISON_PATH.search(page.path):
        kinds.add("comparison")
    if page.author or page.published_at:
        kinds.add("article")
    return kinds


# --- loading --------------------------------------------------------------------


async def build_context(
    session: AsyncSession, project: Project, root_host: str
) -> ReadinessContext:
    pid = project.id
    pages = list(
        (
            await session.scalars(
                select(WebsitePage).where(
                    WebsitePage.project_id == pid, WebsitePage.http_status == 200
                )
            )
        ).all()
    )
    ids = [p.id for p in pages]
    meta = {
        m.page_id: m
        for m in (
            await session.scalars(select(PageMetadata).where(PageMetadata.project_id == pid))
        ).all()
    }
    metrics = {
        m.page_id: m
        for m in (
            await session.scalars(
                select(PageContentMetrics).where(PageContentMetrics.project_id == pid)
            )
        ).all()
    }
    headings: dict[uuid.UUID, list[tuple[int, str]]] = defaultdict(list)
    for h in (
        await session.scalars(
            select(PageHeading)
            .where(PageHeading.project_id == pid)
            .order_by(PageHeading.page_id, PageHeading.position)
        )
    ).all():
        headings[h.page_id].append((h.level, h.text))
    schema_types: dict[uuid.UUID, set[str]] = defaultdict(set)
    for sd in (
        await session.scalars(
            select(PageStructuredData).where(PageStructuredData.project_id == pid)
        )
    ).all():
        schema_types[sd.page_id].update(sd.schema_types)
    entities: dict[uuid.UUID, list[Entity]] = defaultdict(list)
    organization: Entity | None = None
    for e in (await session.scalars(select(Entity).where(Entity.project_id == pid))).all():
        if e.scope == EntityScope.PROJECT:
            organization = e
        elif e.page_id is not None:
            entities[e.page_id].append(e)
    external: dict[uuid.UUID, list[PageLink]] = defaultdict(list)
    for link in (
        await session.scalars(
            select(PageLink).where(
                PageLink.project_id == pid, PageLink.link_type == LinkType.EXTERNAL
            )
        )
    ).all():
        external[link.page_id].append(link)
    conflicts = list(
        (
            await session.scalars(
                select(EntityObservation).where(
                    EntityObservation.project_id == pid,
                    EntityObservation.code == "entity_value_conflict",
                )
            )
        ).all()
    )
    compared = sum(1 for group in entities.values() for e in group if e.fingerprint)

    snapshots: list[PageSnapshot] = []
    for p in pages:
        m = meta.get(p.id)
        c = metrics.get(p.id)
        snap = PageSnapshot(
            id=p.id,
            url=p.normalized_url,
            path=urlsplit(p.normalized_url).path or "/",
            title=p.title,
            meta_description=p.meta_description,
            word_count=(c.word_count if c else p.word_count) or 0,
            text=(c.clean_text if c and c.clean_text else "")[:MAX_TEXT_CHARS],
            headings=headings.get(p.id, []),
            author=m.author if m else None,
            published_at=m.published_at if m else None,
            modified_at=m.modified_at if m else None,
            open_graph=m.open_graph if m else {},
            schema_types=schema_types.get(p.id, set()),
            entities=entities.get(p.id, []),
            external_links=external.get(p.id, []),
        )
        snap.kinds = classify(snap, root_host)
        snapshots.append(snap)
    _ = ids
    return ReadinessContext(
        project_id=pid,
        project_name=project.name,
        root_host=root_host,
        pages=snapshots,
        organization=organization,
        entity_conflicts=conflicts,
        entities_compared=compared,
    )
