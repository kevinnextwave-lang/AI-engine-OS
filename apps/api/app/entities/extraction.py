"""Turn a structured-data block into entity records.

Every typed node (root, @graph member, or nested object with @type) becomes an
entity. Nested typed nodes are replaced in their parent's properties by a
compact reference so the parent stays readable and nothing is stored twice.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

KNOWN_TYPES = frozenset(
    {
        "Organization",
        "Person",
        "Product",
        "Service",
        "Article",
        "BlogPosting",
        "NewsArticle",
        "FAQPage",
        "BreadcrumbList",
        "LocalBusiness",
        "WebSite",
        "WebPage",
        "Review",
        "AggregateRating",
        "Offer",
        "Event",
    }
)

# Types we treat as "organization-like" when consolidating the project organization.
ORGANIZATION_TYPES = frozenset(
    {
        "Organization",
        "LocalBusiness",
        "Corporation",
        "Store",
        "Restaurant",
        "MedicalOrganization",
        "EducationalOrganization",
        "NGO",
        "GovernmentOrganization",
        "SportsOrganization",
        "OnlineBusiness",
        "ProfessionalService",
        "FinancialService",
        "LegalService",
        "HomeAndConstructionBusiness",
        "HealthAndBeautyBusiness",
        "FoodEstablishment",
        "LodgingBusiness",
        "AutomotiveBusiness",
        "Dentist",
        "Physician",
        "Hotel",
        "TravelAgency",
        "RealEstateAgent",
        "Brand",
    }
)

CORE_KEYS = frozenset({"@context", "@type", "@id", "name", "description", "url", "sameAs"})
IDENTIFIER_KEYS = ("identifier", "@id", "sku", "gtin", "gtin13", "gtin8", "gtin14", "isbn", "mpn")
MAX_PROPERTY_DEPTH = 6
MAX_PROPERTY_CHARS = 4000
MAX_ENTITIES_PER_BLOCK = 200


@dataclass
class ExtractedEntity:
    entity_type: str
    extra_types: list[str]
    name: str | None
    description: str | None
    url: str | None
    same_as: list[str]
    identifier: list[str]
    properties: dict[str, Any]
    json_path: str
    is_known_type: bool
    fingerprint: str | None = None
    children: list[str] = field(default_factory=list)  # json paths of nested entities


def short_type(value: str) -> str:
    value = value.strip()
    return value.rsplit("/", 1)[-1].rsplit("#", 1)[-1].rsplit(":", 1)[-1] or value


_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = _PUNCT.sub(" ", text.lower())
    text = _WS.sub(" ", text).strip()
    for suffix in (" inc", " llc", " ltd", " gmbh", " sa", " sas", " bv", " plc", " co"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


def make_fingerprint(entity_type: str, name: str | None) -> str | None:
    if not name:
        return None
    norm = normalize_name(name)
    return f"{entity_type}|{norm}" if norm else None


def _first_str(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        for v in value:
            if isinstance(v, str) and v.strip():
                return v.strip()
    if isinstance(value, dict):
        # {"@value": "..."} or a localized/nested object with a name
        for key in ("@value", "name", "@id", "url"):
            if isinstance(value.get(key), str):
                return value[key].strip() or None
    return None


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        out: list[str] = []
        for v in value:
            s = _first_str(v)
            if s:
                out.append(s)
        return list(dict.fromkeys(out))
    s = _first_str(value)
    return [s] if s else []


def _identifiers(node: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in IDENTIFIER_KEYS:
        value = node.get(key)
        if value is None:
            continue
        if isinstance(value, dict) and value.get("@type") == "PropertyValue":
            prop = _first_str(value.get("propertyID")) or "id"
            val = _first_str(value.get("value"))
            if val:
                ids.append(f"{prop}:{val}")
            continue
        if isinstance(value, list):
            for v in value:
                if isinstance(v, dict) and v.get("@type") == "PropertyValue":
                    prop = _first_str(v.get("propertyID")) or "id"
                    val = _first_str(v.get("value"))
                    if val:
                        ids.append(f"{prop}:{val}")
                else:
                    s = _first_str(v)
                    if s:
                        ids.append(s if key in ("identifier", "@id") else f"{key}:{s}")
            continue
        s = _first_str(value)
        if s:
            ids.append(s if key in ("identifier", "@id") else f"{key}:{s}")
    return list(dict.fromkeys(ids))


def _types(node: dict[str, Any]) -> list[str]:
    t = node.get("@type")
    if isinstance(t, str):
        return [short_type(t)] if t.strip() else []
    if isinstance(t, list):
        return [short_type(x) for x in t if isinstance(x, str) and x.strip()]
    return []


def _reference(node: dict[str, Any]) -> dict[str, Any]:
    ref: dict[str, Any] = {"@ref": True}
    types = _types(node)
    if types:
        ref["@type"] = types[0]
    for key in ("name", "@id", "url"):
        s = _first_str(node.get(key))
        if s:
            ref[key] = s
    return ref


def _truncate(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_PROPERTY_CHARS:
        return value[:MAX_PROPERTY_CHARS] + "…"
    return value


def extract_entities(payload: Any) -> list[ExtractedEntity]:
    """All typed nodes in a block (JSON-LD document or normalized microdata/RDFa items)."""
    entities: list[ExtractedEntity] = []

    def walk(node: Any, path: str, depth: int) -> Any:
        """Returns the value to keep in the parent's properties."""
        if len(entities) >= MAX_ENTITIES_PER_BLOCK or depth > MAX_PROPERTY_DEPTH:
            return _reference(node) if isinstance(node, dict) else _truncate(node)
        if isinstance(node, list):
            return [walk(item, f"{path}[{i}]", depth) for i, item in enumerate(node)]
        if not isinstance(node, dict):
            return _truncate(node)
        types = _types(node)
        if not types:
            # Untyped object (context wrapper, literal, reference): keep walking for
            # typed children (e.g. {"@context": ..., "@graph": [...]}).
            return {k: walk(v, f"{path}.{k}" if path else k, depth + 1) for k, v in node.items()}
        properties: dict[str, Any] = {}
        children: list[str] = []
        for key, value in node.items():
            if key in CORE_KEYS:
                continue
            child_path = f"{path}.{key}" if path else key
            kept = walk(value, child_path, depth + 1)
            properties[key] = kept
            if isinstance(value, dict) and _types(value):
                children.append(child_path)
            elif isinstance(value, list):
                children.extend(
                    f"{child_path}[{i}]"
                    for i, v in enumerate(value)
                    if isinstance(v, dict) and _types(v)
                )
        name = _first_str(node.get("name")) or _first_str(node.get("headline"))
        entity = ExtractedEntity(
            entity_type=types[0],
            extra_types=types[1:],
            name=name,
            description=_first_str(node.get("description")),
            url=_first_str(node.get("url")),
            same_as=_str_list(node.get("sameAs")),
            identifier=_identifiers(node),
            properties=properties,
            json_path=path,
            is_known_type=types[0] in KNOWN_TYPES,
            fingerprint=make_fingerprint(types[0], name),
            children=children,
        )
        entities.append(entity)
        return _reference(node)

    walk(payload, "", 0)
    return entities
