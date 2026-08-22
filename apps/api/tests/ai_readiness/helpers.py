"""In-memory ReadinessContext builders (no DB)."""

import uuid
from typing import Any

from app.ai_readiness.context import PageSnapshot, ReadinessContext, classify
from app.ai_readiness.findings import Finding
from app.models.entities import Entity, EntityObservation, EntityScope
from app.models.page_intelligence import LinkStatus, LinkType, PageLink

ROOT = "https://www.acme.com/"
HOST = "www.acme.com"


def entity(entity_type: str, name: str | None, **props: Any) -> Entity:
    return Entity(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        scope=EntityScope.PAGE,
        entity_type=entity_type,
        extra_types=[],
        name=name,
        description=props.pop("description", None),
        url=props.pop("url", None),
        same_as=props.pop("same_as", []),
        identifier=[],
        properties=props,
        json_path="",
        fingerprint=f"{entity_type}|{name.lower()}" if name else None,
    )


def page(
    path: str,
    *,
    title: str | None = "Acme page",
    text: str = "",
    headings: list[tuple[int, str]] | None = None,
    description: str | None = None,
    author: str | None = None,
    published: Any = None,
    modified: Any = None,
    schema: set[str] | None = None,
    entities: list[Entity] | None = None,
    external_links: int = 0,
    word_count: int | None = None,
) -> PageSnapshot:
    url = ROOT + path.lstrip("/")
    links = [
        PageLink(
            page_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            href=f"https://source{i}.example/study",
            normalized_url=f"https://source{i}.example/study",
            anchor_text="source",
            link_type=LinkType.EXTERNAL,
            status=LinkStatus.UNKNOWN,
            position=i,
        )
        for i in range(external_links)
    ]
    snap = PageSnapshot(
        id=uuid.uuid4(),
        url=url,
        path="/" + path.lstrip("/"),
        title=title,
        meta_description=description,
        word_count=word_count if word_count is not None else len(text.split()),
        text=text,
        headings=headings or [],
        author=author,
        published_at=published,
        modified_at=modified,
        open_graph={},
        schema_types=schema or set(),
        entities=entities or [],
        external_links=links,
    )
    snap.kinds = classify(snap, HOST[4:])
    return snap


def org_entity(**props: Any) -> Entity:
    e = entity("Organization", props.pop("name", "Acme"), **props)
    e.scope = EntityScope.PROJECT
    e.page_id = None
    e.properties.setdefault(
        "_signals", {"name_source": "schema", "text_emails": [], "text_phones": []}
    )
    return e


def context(
    pages: list[PageSnapshot],
    *,
    organization: Entity | None = None,
    conflicts: list[EntityObservation] | None = None,
    compared: int | None = None,
    project_name: str = "Acme",
) -> ReadinessContext:
    return ReadinessContext(
        project_id=uuid.uuid4(),
        project_name=project_name,
        root_host="acme.com",
        pages=pages,
        organization=organization,
        entity_conflicts=conflicts or [],
        entities_compared=compared
        if compared is not None
        else sum(1 for p in pages for e in p.entities if e.fingerprint),
    )


def codes(findings: list[Finding]) -> set[str]:
    return {f.code for f in findings}


def by_code(findings: list[Finding], code: str) -> Finding:
    return next(f for f in findings if f.code == code)
