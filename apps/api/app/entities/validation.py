"""Structural validation of structured-data blocks.

This validates JSON-LD *shape* (context, types, nesting) — not schema.org
property vocabularies and not search-engine rich-result rules. Nothing here
claims rich-result eligibility.
"""

from dataclasses import dataclass
from typing import Any

from app.models.page_intelligence import StructuredDataFormat

MAX_NESTING_DEPTH = 12
SCHEMA_ORG_CONTEXT_HINTS = ("schema.org",)


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str  # high | medium | low | info
    message: str
    path: str = ""


def _type_values(value: Any) -> list[str] | None:
    """@type as a list of strings, or None when the value has an invalid shape."""
    if isinstance(value, str):
        return [value] if value.strip() else None
    if isinstance(value, list) and value and all(isinstance(v, str) and v.strip() for v in value):
        return list(value)
    return None


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def validate_block(
    fmt: StructuredDataFormat, payload: Any, is_valid: bool, error: str | None
) -> list[Issue]:
    """Issues for one stored block. `is_valid`/`error` come from extraction time
    (e.g. invalid JSON), `payload` is the parsed content when parsing succeeded."""
    if not is_valid:
        text = error or "block could not be parsed"
        code = "invalid_json" if "JSON" in text else "unparseable_block"
        return [Issue(code, "high", f"{fmt.value} block could not be parsed: {text}")]
    if fmt != StructuredDataFormat.JSON_LD:
        return _validate_attribute_items(payload)
    return _validate_jsonld(payload)


def _validate_jsonld(payload: Any) -> list[Issue]:
    issues: list[Issue] = []
    if isinstance(payload, list):
        if not payload:
            return [Issue("empty_block", "low", "JSON-LD block is an empty array")]
        for i, node in enumerate(payload):
            issues.extend(_validate_root(node, f"[{i}]"))
        return issues
    return _validate_root(payload, "")


def _validate_root(node: Any, path: str) -> list[Issue]:
    if not isinstance(node, dict):
        return [
            Issue(
                "invalid_root",
                "high",
                f"Top-level JSON-LD value is {type(node).__name__}, expected an object",
                path,
            )
        ]
    issues: list[Issue] = []
    context = node.get("@context")
    if context is None:
        issues.append(
            Issue("missing_context", "medium", "Node has no @context (schema.org vocabulary)", path)
        )
    elif not _context_is_schema_org(context):
        issues.append(
            Issue(
                "non_schema_org_context",
                "info",
                "@context does not reference schema.org; types may not be understood as "
                "schema.org entities",
                path,
            )
        )
    graph = node.get("@graph")
    if graph is not None:
        if not isinstance(graph, list):
            issues.append(Issue("invalid_graph", "high", "@graph must be an array", path))
        else:
            for i, item in enumerate(graph):
                issues.extend(_validate_node(item, _join(path, f"@graph[{i}]"), 1, root=True))
        # A node that only carries @context + @graph needs no @type itself.
        if set(node) - {"@context", "@graph", "@id"}:
            issues.extend(_validate_node(node, path, 0, root=True, skip_children={"@graph"}))
        return issues
    issues.extend(_validate_node(node, path, 0, root=True))
    return issues


def _context_is_schema_org(context: Any) -> bool:
    if isinstance(context, str):
        return any(h in context for h in SCHEMA_ORG_CONTEXT_HINTS)
    if isinstance(context, dict):
        return (
            any(
                isinstance(v, str) and any(h in v for h in SCHEMA_ORG_CONTEXT_HINTS)
                for v in context.values()
            )
            or "@vocab" in context
        )
    if isinstance(context, list):
        return any(_context_is_schema_org(c) for c in context)
    return False


def _validate_node(
    node: Any,
    path: str,
    depth: int,
    *,
    root: bool = False,
    skip_children: set[str] | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    if depth > MAX_NESTING_DEPTH:
        return [Issue("nesting_too_deep", "low", "Structure nested too deeply", path)]
    if not isinstance(node, dict):
        return [
            Issue(
                "invalid_nested_structure",
                "medium",
                f"Expected an object, found {type(node).__name__}",
                path,
            )
        ]
    keys = set(node) - (skip_children or set())
    if "@type" in node:
        if _type_values(node["@type"]) is None:
            issues.append(
                Issue(
                    "invalid_type_value",
                    "high",
                    "@type must be a non-empty string or array of strings",
                    _join(path, "@type"),
                )
            )
    elif keys - {"@id", "@context", "@value", "@language", "@list", "@set"}:
        # An object with properties but no type: engines cannot classify it.
        # Pure references ({"@id": ...}) and literal wrappers are fine.
        issues.append(
            Issue(
                "missing_type",
                "high" if root else "medium",
                "Object has properties but no @type",
                path,
            )
        )
    for key, value in node.items():
        if key in (skip_children or set()) or key.startswith("@"):
            continue
        child_path = _join(path, key)
        if value is None or value == "" or value == [] or value == {}:
            issues.append(Issue("empty_value", "low", f"Property '{key}' is empty", child_path))
            continue
        if isinstance(value, dict):
            issues.extend(_validate_node(value, child_path, depth + 1))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    issues.extend(_validate_node(item, f"{child_path}[{i}]", depth + 1))
                elif isinstance(item, list):
                    issues.append(
                        Issue(
                            "invalid_nested_structure",
                            "medium",
                            f"Property '{key}' contains a nested array",
                            f"{child_path}[{i}]",
                        )
                    )
    return issues


def _validate_attribute_items(payload: Any) -> list[Issue]:
    """Microdata / RDFa items already arrive normalized; only check for typeless items."""
    issues: list[Issue] = []
    if not isinstance(payload, list):
        return issues
    for i, item in enumerate(payload):
        if isinstance(item, dict) and not item.get("@type"):
            issues.append(
                Issue("missing_type", "medium", "Item declares properties but no type", f"[{i}]")
            )
    return issues
