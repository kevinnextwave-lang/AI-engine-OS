"""Finding: the unit of output of every check."""

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.models.seo import ObservationCategory, Severity


@dataclass
class Finding:
    category: ObservationCategory
    code: str
    severity: Severity
    title: str
    description: str
    recommendation: str
    evidence: dict[str, Any] = field(default_factory=dict)
    page_id: uuid.UUID | None = None
    url: str | None = None


def urls_evidence(urls: list[str], limit: int = 25) -> dict[str, Any]:
    """Bounded list of URLs for evidence payloads."""
    return {"urls": urls[:limit], "count": len(urls), "truncated": len(urls) > limit}
