import uuid
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class KnownBrand:
    name: str
    aliases: tuple[str, ...] = ()
    competitor_id: uuid.UUID | None = None  # None for the project's own brand

    @property
    def is_competitor(self) -> bool:
        return self.competitor_id is not None

    def all_names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass
class ParseContext:
    project_id: uuid.UUID
    brand: KnownBrand
    competitors: list[KnownBrand] = field(default_factory=list)
    # Hosts considered "own" (brand) for domain-based mention detection.
    brand_domains: tuple[str, ...] = ()

    @property
    def all_brands(self) -> list[KnownBrand]:
        return [self.brand, *self.competitors]


def host_stem(url_or_host: str) -> str | None:
    """'https://www.xero.com/uk/' -> 'xero'."""
    host = urlsplit(url_or_host if "//" in url_or_host else f"//{url_or_host}").hostname or ""
    host = host.lower().removeprefix("www.")
    if not host or "." not in host:
        return None
    return host.split(".")[0]


def brand_from(
    name: str, website: str | None, competitor_id: uuid.UUID | None = None
) -> KnownBrand:
    aliases: list[str] = []
    stem = host_stem(website) if website else None
    if stem and stem.lower() != name.lower() and len(stem) >= 3:
        aliases.append(stem)
    host = (urlsplit(website).hostname or "").lower().removeprefix("www.") if website else ""
    if host:
        aliases.append(host)
    return KnownBrand(name=name, aliases=tuple(aliases), competitor_id=competitor_id)
