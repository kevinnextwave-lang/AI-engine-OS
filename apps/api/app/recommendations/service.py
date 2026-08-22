"""Human review of recommendations. Every transition is made by a person;
nothing here triggers any external action."""

import uuid
from datetime import UTC, datetime

from app.core.errors import ConflictError
from app.models.recommendations import TRANSITIONS, Recommendation, RecommendationStatus


def transition(
    rec: Recommendation,
    to: RecommendationStatus,
    *,
    user_id: uuid.UUID,
    note: str | None = None,
) -> Recommendation:
    current = RecommendationStatus(rec.status)
    if to not in TRANSITIONS[current]:
        allowed = ", ".join(sorted(s.value for s in TRANSITIONS[current])) or "none"
        raise ConflictError(
            f"Cannot move a {current.value} recommendation to {to.value} (allowed: {allowed})"
        )
    rec.status = to.value
    rec.reviewed_at = datetime.now(UTC)
    rec.reviewed_by_user_id = user_id
    if note is not None:
        rec.note = note.strip() or None
    return rec
