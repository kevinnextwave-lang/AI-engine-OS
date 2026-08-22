import uuid
from dataclasses import dataclass, field
from typing import Any

from app.models.ai_readiness import ReadinessCategory
from app.models.seo import Severity


@dataclass
class Finding:
    category: ReadinessCategory
    code: str
    severity: Severity
    title: str
    description: str
    recommendation: str
    evidence: dict[str, Any] = field(default_factory=dict)
    page_id: uuid.UUID | None = None
    url: str | None = None


def urls_evidence(urls: list[str], limit: int = 25) -> dict[str, Any]:
    return {"urls": urls[:limit], "count": len(urls)}
