"""Consolidate one project-level Organization entity from page-level evidence.

Sources, in priority order: Organization-like schema on the homepage, on an
about/company page, on any other page; then contact details found in the
visible text of the homepage / about / contact pages. Every value records
where it came from; conflicting values are listed, not resolved.
"""

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from app.entities.extraction import ORGANIZATION_TYPES, make_fingerprint
from app.models.entities import Entity

ABOUT_PATHS = ("/about", "/about-us", "/company", "/who-we-are", "/our-story", "/team")
CONTACT_PATHS = ("/contact", "/contact-us", "/impressum", "/imprint", "/legal")

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_PHONE = re.compile(r"(?<![\w/(])\(?\+?\d[\d\s().-]{6,20}\d(?![\w/])")
_IMAGE_EXT = re.compile(r"\.(png|jpe?g|gif|svg|webp)$", re.I)

MERGED_PROPERTIES = (
    "legalName",
    "alternateName",
    "logo",
    "telephone",
    "email",
    "address",
    "foundingDate",
    "founder",
    "numberOfEmployees",
    "areaServed",
    "contactPoint",
    "taxID",
    "vatID",
    "duns",
    "naics",
    "slogan",
)


@dataclass
class PageInfo:
    id: Any
    url: str
    path: str
    clean_text: str | None = None


def page_role(path: str, is_root: bool) -> str | None:
    if is_root:
        return "homepage"
    p = path.rstrip("/") or "/"
    if any(p == a or p.startswith(a + "/") for a in ABOUT_PATHS):
        return "about"
    if any(p == c or p.startswith(c + "/") for c in CONTACT_PATHS):
        return "contact"
    return None


_ROLE_PRIORITY = {"homepage": 0, "about": 1, "contact": 2, None: 3}


def _is_org(entity: Entity) -> bool:
    types = {entity.entity_type, *entity.extra_types}
    return bool(types & ORGANIZATION_TYPES)


def build_project_organization(
    entities: list[Entity],
    pages: dict[Any, PageInfo],
    roles: dict[Any, str | None],
    *,
    project_name: str,
    root_host: str,
) -> dict[str, Any] | None:
    """Returns the fields for a project-scope Entity, or None if there is no evidence at all."""
    candidates = [e for e in entities if e.page_id in pages and _is_org(e)]
    candidates.sort(key=lambda e: (_ROLE_PRIORITY[roles.get(e.page_id)], e.json_path))

    # Prefer the organization that is "this site": its url is on the root host, or it
    # sits on the homepage. Fall back to the most frequently named one.
    def is_self(e: Entity) -> bool:
        host = (urlsplit(e.url).hostname or "").lower() if e.url else ""
        return host.endswith(root_host) if host and root_host else False

    own = [e for e in candidates if is_self(e) or roles.get(e.page_id) == "homepage"]
    pool = own or candidates
    names = Counter(e.fingerprint for e in pool if e.fingerprint)
    primary_fp = names.most_common(1)[0][0] if names else None
    primary = [e for e in pool if e.fingerprint == primary_fp] if primary_fp else pool[:1]

    sources: list[dict[str, Any]] = []
    merged: dict[str, Any] = {}
    conflicts: dict[str, list[dict[str, Any]]] = {}
    same_as: list[str] = []
    identifiers: list[str] = []
    name = description = url = None
    entity_type = "Organization"
    extra_types: list[str] = []

    for e in primary:
        page = pages[e.page_id]
        sources.append(
            {
                "page_url": page.url,
                "role": roles.get(e.page_id),
                "format": e.source_format.value if e.source_format else None,
                "json_path": e.json_path,
                "entity_id": str(e.id),
            }
        )
        if name is None and e.name:
            name = e.name
        if description is None and e.description:
            description = e.description
        if url is None and e.url:
            url = e.url
        if e.entity_type in ORGANIZATION_TYPES and e.entity_type != "Organization":
            if entity_type == "Organization":
                entity_type = e.entity_type
            elif e.entity_type != entity_type and e.entity_type not in extra_types:
                extra_types.append(e.entity_type)
        for s in e.same_as:
            if s not in same_as:
                same_as.append(s)
        for i in e.identifier:
            if i not in identifiers:
                identifiers.append(i)
        for key in MERGED_PROPERTIES:
            value = e.properties.get(key)
            if value in (None, "", [], {}):
                continue
            if key not in merged:
                merged[key] = value
            elif merged[key] != value:
                conflicts.setdefault(
                    key, [{"value": merged[key], "page_url": sources[0]["page_url"]}]
                )
                conflicts[key].append({"value": value, "page_url": page.url})

    # Contact details visible in text on homepage / about / contact pages.
    emails: Counter[str] = Counter()
    phones: Counter[str] = Counter()
    for page_id, role in roles.items():
        if role is None:
            continue
        text = pages[page_id].clean_text or ""
        for m in _EMAIL.findall(text):
            if not _IMAGE_EXT.search(m):
                emails[m.lower()] += 1
        for m in _PHONE.findall(text):
            digits = re.sub(r"\D", "", m)
            if 8 <= len(digits) <= 15 and not re.fullmatch(r"[\d.]+|\d{4}-\d{4}", m):
                phones[" ".join(m.split())] += 1

    signals = {
        "homepage_schema": any(s["role"] == "homepage" for s in sources),
        "about_page": next((pages[pid].url for pid, r in roles.items() if r == "about"), None),
        "contact_page": next((pages[pid].url for pid, r in roles.items() if r == "contact"), None),
        "organization_schema_pages": len({e.page_id for e in candidates}),
        "text_emails": [e for e, _ in emails.most_common(5)],
        "text_phones": [p for p, _ in phones.most_common(5)],
    }

    if not primary and not emails and not phones:
        return None

    if name is None:
        name = project_name
        signals["name_source"] = "project"
    else:
        signals["name_source"] = "schema"
    if url is None and root_host:
        url = f"https://{root_host}/"
        signals["url_source"] = "root_domain"
    else:
        signals["url_source"] = "schema"

    confidence = (
        "high" if signals["homepage_schema"] and same_as else "medium" if primary else "low"
    )
    properties = {
        **merged,
        "_sources": sources,
        "_signals": signals,
        "_conflicts": conflicts,
        "_confidence": confidence,
    }
    return {
        "entity_type": entity_type,
        "extra_types": extra_types,
        "name": name,
        "description": description,
        "url": url,
        "same_as": same_as,
        "identifier": identifiers,
        "properties": properties,
        "fingerprint": make_fingerprint(entity_type, name),
    }
