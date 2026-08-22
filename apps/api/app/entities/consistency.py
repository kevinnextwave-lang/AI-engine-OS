"""Cross-page entity comparison.

Entities that share a fingerprint (type + normalized name) describe the same
real-world thing. When their stated facts differ, we report a *potential*
inconsistency with every observed value and where it came from. We never pick
a winner.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.models.entities import Entity

# Properties that legitimately differ between pages and are not "facts" about the entity.
NON_FACT_PROPERTIES = frozenset(
    {
        "mainEntityOfPage",
        "mainEntity",
        "position",
        "potentialAction",
        "itemListElement",
        "breadcrumb",
        "isPartOf",
        "hasPart",
        "review",
        "reviews",
        "aggregateRating",
        "offers",
        "image",
        "datePublished",
        "dateModified",
        "inLanguage",
        "speakable",
        "publisher",
        "author",
        "about",
    }
)
MAX_GROUP_PAGES = 25


@dataclass
class Observation:
    code: str
    severity: str
    title: str
    description: str
    entity_type: str | None
    entity_name: str | None
    evidence: dict[str, Any] = field(default_factory=dict)


def _comparable(value: Any) -> str | None:
    """A normalized string for comparison, or None when the value isn't a simple fact."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        text = " ".join(value.split()).casefold()
        return text or None
    if isinstance(value, dict):
        if value.get("@ref"):
            name = value.get("name") or value.get("@id") or value.get("url")
            return " ".join(str(name).split()).casefold() if name else None
        # Literal address-like objects: compare their scalar members as a whole.
        parts = [
            f"{k}={_comparable(v)}"
            for k, v in sorted(value.items())
            if not k.startswith("@") and _comparable(v) is not None
        ]
        return ";".join(parts) or None
    if isinstance(value, list):
        items = sorted(c for c in (_comparable(v) for v in value) if c is not None)
        return "|".join(items) or None
    return None


def _display(value: Any) -> Any:
    if isinstance(value, dict) and value.get("@ref"):
        return value.get("name") or value.get("@id") or value.get("url")
    if isinstance(value, str) and len(value) > 300:
        return value[:300] + "…"
    return value


def find_inconsistencies(entities: list[Entity], page_urls: dict[Any, str]) -> list[Observation]:
    groups: dict[str, list[Entity]] = defaultdict(list)
    for e in entities:
        if e.fingerprint and e.page_id is not None:
            groups[e.fingerprint].append(e)

    observations: list[Observation] = []
    for _fingerprint, group in sorted(groups.items()):
        observations.extend(_duplicates(group, page_urls))
        if len({e.page_id for e in group}) < 2:
            continue
        observations.extend(_conflicts(group, page_urls))
    return observations


def _duplicates(group: list[Entity], page_urls: dict[Any, str]) -> list[Observation]:
    per_page: dict[Any, list[Entity]] = defaultdict(list)
    for e in group:
        per_page[e.page_id].append(e)
    out: list[Observation] = []
    for page_id, items in per_page.items():
        if len(items) < 2:
            continue
        sample = items[0]
        out.append(
            Observation(
                "duplicate_entity",
                "low",
                "Same entity declared more than once on a page",
                f"{sample.entity_type} '{sample.name}' appears {len(items)} times in the "
                f"structured data of {page_urls.get(page_id, '?')}. Engines may treat these as "
                "separate entities or ignore the duplicates.",
                sample.entity_type,
                sample.name,
                {
                    "page_url": page_urls.get(page_id),
                    "occurrences": [
                        {
                            "format": e.source_format.value if e.source_format else None,
                            "json_path": e.json_path,
                        }
                        for e in items
                    ],
                    "count": len(items),
                },
            )
        )
    return out


def _conflicts(group: list[Entity], page_urls: dict[Any, str]) -> list[Observation]:
    """One observation per (entity, property) whose values differ across pages."""
    # property -> comparable value -> {display value, pages}
    values: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for e in group:
        facts: dict[str, Any] = {
            k: v for k, v in e.properties.items() if k not in NON_FACT_PROPERTIES
        }
        if e.url:
            facts["url"] = e.url
        if e.same_as:
            facts["sameAs"] = e.same_as
        for key, raw in facts.items():
            comp = _comparable(raw)
            if comp is None:
                continue
            slot = values[key].setdefault(comp, {"value": _display(raw), "pages": []})
            url = page_urls.get(e.page_id)
            if url and url not in slot["pages"] and len(slot["pages"]) < MAX_GROUP_PAGES:
                slot["pages"].append(url)

    sample = group[0]
    out: list[Observation] = []
    for key, variants in sorted(values.items()):
        if len(variants) < 2:
            continue
        if key == "sameAs":
            # Differing profile sets are usually partial, not contradictory.
            code, severity, title = (
                "same_as_inconsistent",
                "info",
                "sameAs profiles differ between pages",
            )
            desc = (
                f"{sample.entity_type} '{sample.name}' lists different sameAs profiles on "
                f"different pages. Merge them into one complete, identical list."
            )
        else:
            code, severity, title = (
                "entity_value_conflict",
                "medium",
                "Potential factual inconsistency",
            )
            desc = (
                f"{sample.entity_type} '{sample.name}' states different values for "
                f"'{key}' on different pages ({len(variants)} variants). One of them may be "
                "outdated; verify which is correct and use it everywhere."
            )
        out.append(
            Observation(
                code,
                severity,
                title,
                desc,
                sample.entity_type,
                sample.name,
                {
                    "property": key,
                    "values": list(variants.values()),
                    "pages_compared": len({e.page_id for e in group}),
                },
            )
        )
    return out
