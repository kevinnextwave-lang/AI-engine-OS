"""Configurable source registry: known domains per category plus the pattern
and keyword lists the classifier uses as evidence.

Bundled defaults live in `registry.json`; `SOURCE_REGISTRY_PATH` may point at a
JSON file whose lists are merged on top (added, never removed). Loaded once
per process (`get_registry()`); `SourceRegistry.from_dict` for tests."""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.models.sources import DomainType

_BUNDLED = Path(__file__).with_name("registry.json")

# registry key → domain type the membership is evidence for
CATEGORY_LISTS: dict[str, DomainType] = {
    "known_review_domains": DomainType.REVIEW,
    "known_social_domains": DomainType.SOCIAL,
    "known_community_domains": DomainType.COMMUNITY,
    "known_forum_domains": DomainType.FORUM,
    "known_media_domains": DomainType.MEDIA,
    "known_directory_domains": DomainType.DIRECTORY,
    "known_research_domains": DomainType.RESEARCH,
    "known_blog_platforms": DomainType.BLOG,
}


@dataclass(frozen=True)
class SourceRegistry:
    version: str
    lists: dict[str, frozenset[str]]  # CATEGORY_LISTS keys + known_authority_domains
    government_suffixes: tuple[str, ...]
    education_suffixes: tuple[str, ...]
    hostname_patterns: dict[str, tuple[str, ...]] = field(default_factory=dict)
    path_patterns: dict[str, tuple[str, ...]] = field(default_factory=dict)
    title_keywords: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceRegistry":
        lists = {
            key: frozenset(h.lower().removeprefix("www.") for h in data.get(key, []))
            for key in [*CATEGORY_LISTS, "known_authority_domains"]
        }
        return cls(
            version=str(data.get("version", "custom")),
            lists=lists,
            government_suffixes=tuple(data.get("government_suffixes", [])),
            education_suffixes=tuple(data.get("education_suffixes", [])),
            hostname_patterns={k: tuple(v) for k, v in data.get("hostname_patterns", {}).items()},
            path_patterns={k: tuple(v) for k, v in data.get("path_patterns", {}).items()},
            title_keywords={
                k: tuple(w.lower() for w in v) for k, v in data.get("title_keywords", {}).items()
            },
        )

    @classmethod
    def load(cls, override_path: str | None = None) -> "SourceRegistry":
        data: dict[str, Any] = json.loads(_BUNDLED.read_text())
        if override_path:
            extra: dict[str, Any] = json.loads(Path(override_path).read_text())
            for key, value in extra.items():
                if isinstance(value, list) and isinstance(data.get(key), list):
                    data[key] = [*data[key], *value]
                elif isinstance(value, dict) and isinstance(data.get(key), dict):
                    for k, v in value.items():
                        data[key][k] = [*data[key].get(k, []), *v]
                else:
                    data[key] = value
        return cls.from_dict(data)

    # -- lookups ------------------------------------------------------------------

    def list_match(self, host: str, key: str) -> str | None:
        """The registry entry `host` equals or is a subdomain of, for one list."""
        entries = self.lists.get(key, frozenset())
        parts = host.split(".")
        for i in range(len(parts) - 1):
            candidate = ".".join(parts[i:])
            if candidate in entries:
                return candidate
        return None

    def category_matches(self, host: str) -> list[tuple[DomainType, str, str]]:
        """(domain type, matched entry, list key) for every category list that matches."""
        out = []
        for key, dtype in CATEGORY_LISTS.items():
            hit = self.list_match(host, key)
            if hit:
                out.append((dtype, hit, key))
        return out

    def is_authority(self, host: str) -> bool:
        return self.list_match(host, "known_authority_domains") is not None

    def suffix_match(self, host: str, suffixes: tuple[str, ...]) -> str | None:
        for suffix in suffixes:
            if host.endswith(suffix) or host == suffix.lstrip("."):
                return suffix
        return None


@lru_cache(maxsize=1)
def get_registry() -> SourceRegistry:
    return SourceRegistry.load(get_settings().source_registry_path)
