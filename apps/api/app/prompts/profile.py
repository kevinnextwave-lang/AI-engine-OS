"""Business profile: the inputs prompt generation works from."""

import re
from dataclasses import dataclass, field
from typing import Any

_GENERIC_SUFFIXES = (
    "software",
    "platform",
    "platforms",
    "tool",
    "tools",
    "service",
    "services",
    "app",
    "apps",
    "solution",
    "solutions",
    "agency",
    "agencies",
    "provider",
    "providers",
    "company",
    "companies",
)


def _clean(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for v in values or []:
        s = " ".join(str(v).split()).strip(" .,;")
        if s and s.lower() not in {x.lower() for x in out}:
            out.append(s)
    return out


@dataclass
class BusinessProfile:
    company_name: str
    website: str | None = None
    industry: str | None = None
    products: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    use_cases: list[str] = field(default_factory=list)
    integrations: list[str] = field(default_factory=list)
    target_audience: list[str] = field(default_factory=list)
    competitors: list[str] = field(default_factory=list)
    geographic_market: list[str] = field(default_factory=list)
    language: str = "en"
    country: str | None = None

    def __post_init__(self) -> None:
        self.company_name = " ".join(self.company_name.split())
        self.industry = " ".join(self.industry.split()).strip(" .") if self.industry else None
        for name in (
            "products",
            "services",
            "features",
            "use_cases",
            "integrations",
            "target_audience",
            "competitors",
            "geographic_market",
        ):
            setattr(self, name, _clean(getattr(self, name)))

    # -- derived vocabulary ---------------------------------------------------

    def _seeds(self) -> list[str]:
        seeds: list[str] = []
        if self.industry:
            seeds.append(_smart_lower(self.industry))
        seeds.extend(_smart_lower(s) for s in self.services)
        seeds.extend(_smart_lower(p) for p in self.products if not _looks_like_brand(p))
        return seeds

    @property
    def offerings(self) -> list[str]:
        """Plural/mass category nouns ("accounting software", "accounting platforms")."""
        out: list[str] = []
        for seed in self._seeds():
            for variant in _variants(seed, plural=True):
                if variant not in out:
                    out.append(variant)
        return out[:6]

    @property
    def offerings_singular(self) -> list[str]:
        """Singular forms for "Which X is…" phrasing ("accounting platform")."""
        out: list[str] = []
        for seed in self._seeds():
            for variant in _variants(seed, plural=False):
                if variant not in out:
                    out.append(variant)
        return out[:6]

    @property
    def tasks(self) -> list[str]:
        """Descriptors as verbs' objects: 'automated invoicing' -> 'invoicing'."""
        out: list[str] = []
        for d in self.descriptors:
            t = re.sub(r"^(automated|automatic|automating|managed|manual)\s+", "", d, flags=re.I)
            if t and t not in out:
                out.append(t)
        return out

    @property
    def geo_phrases(self) -> list[str]:
        """Market names with the article they take in a sentence ('the United Kingdom')."""
        return [_with_article(g) for g in self.geographic_market]

    @property
    def primary_offering(self) -> str | None:
        return self.offerings[0] if self.offerings else None

    @property
    def brand_products(self) -> list[str]:
        return [p for p in self.products if _looks_like_brand(p)]

    @property
    def descriptors(self) -> list[str]:
        """Feature-like phrases usable as 'supports X' / 'for X'."""
        return _clean(
            self.features + self.use_cases + [p for p in self.products if not _looks_like_brand(p)]
        )

    def terms(self) -> dict[str, list[str]]:
        """Lower-cased term groups used by the quality scorer."""
        return {
            "offering": [o for o in self.offerings]
            + ([self.industry.lower()] if self.industry else []),
            "audience": [a.lower() for a in self.target_audience],
            "competitor": [c.lower() for c in self.competitors],
            "company": [self.company_name.lower()],
            "product": [p.lower() for p in self.products],
            "descriptor": [d.lower() for d in self.descriptors + self.integrations],
            "geo": [g.lower() for g in self.geographic_market],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "company_name": self.company_name,
            "website": self.website,
            "industry": self.industry,
            "products": self.products,
            "services": self.services,
            "features": self.features,
            "use_cases": self.use_cases,
            "integrations": self.integrations,
            "target_audience": self.target_audience,
            "competitors": self.competitors,
            "geographic_market": self.geographic_market,
            "language": self.language,
            "country": self.country,
        }


def _smart_lower(value: str) -> str:
    """Lower-case ordinary words but keep acronyms ("CRM software")."""
    return " ".join(w if (w.isupper() and len(w) > 1) else w.lower() for w in value.split())


def _looks_like_brand(value: str) -> bool:
    words = value.split()
    return (
        len(words) <= 2
        and any(w[:1].isupper() for w in words)
        and not value.lower().endswith(_GENERIC_SUFFIXES)
    )


_MASS_NOUNS = ("software", "hardware", "equipment", "insurance", "consulting", "hosting", "storage")
_ARTICLE_COUNTRIES = {
    "united kingdom",
    "uk",
    "united states",
    "usa",
    "us",
    "netherlands",
    "philippines",
    "united arab emirates",
    "uae",
    "czech republic",
    "dominican republic",
    "bahamas",
    "maldives",
    "eu",
    "european union",
    "middle east",
    "nordics",
    "dach region",
    "benelux",
}


def _with_article(name: str) -> str:
    return f"the {name}" if name.lower() in _ARTICLE_COUNTRIES else name


_SUFFIX_FAMILIES: tuple[tuple[tuple[str, ...], tuple[tuple[str, str], ...]], ...] = (
    # (suffixes that identify the family, (singular, plural) alternatives)
    (
        (
            "software",
            "platform",
            "platforms",
            "tool",
            "tools",
            "app",
            "apps",
            "solution",
            "solutions",
        ),
        (("software", "software"), ("platform", "platforms"), ("tool", "tools")),
    ),
    (
        ("services", "service", "provider", "providers", "company", "companies", "firm", "firms"),
        (("service", "services"), ("provider", "providers"), ("company", "companies")),
    ),
    (("agency", "agencies"), (("agency", "agencies"), ("service", "services"))),
)


def _variants(seed: str, *, plural: bool) -> list[str]:
    """'accounting software' -> plural ['accounting software', 'accounting platforms',
    'accounting tools'] / singular ['accounting software', 'accounting platform', ...]."""
    seed = re.sub(r"\s+", " ", seed).strip()
    words = seed.split()
    last = words[-1] if words else ""
    for suffixes, alternatives in _SUFFIX_FAMILIES:
        if last in suffixes:
            base = " ".join(words[:-1])
            out: list[str] = []
            for singular, plural_form in alternatives:
                form = plural_form if plural else singular
                phrase = f"{base} {form}".strip()
                if phrase not in out:
                    out.append(phrase)
            return out
    if last in _MASS_NOUNS or not plural:
        return [seed]
    return [seed if last.endswith("s") else seed + "s"]
