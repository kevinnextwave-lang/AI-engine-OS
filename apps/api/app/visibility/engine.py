"""AI Visibility Engine: time windows, comparisons, trends and breakdowns.

Everything here is computed on demand from stored observations; nothing is
persisted, so a parser or methodology change is reflected immediately and
consistently across periods. See docs/ai-visibility-score.md.
"""

import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.visibility import METHOD
from app.visibility.metrics import (
    MIN_SAMPLE,
    VisibilityMetrics,
    competitor_table,
    compute,
    sufficiency_for,
)
from app.visibility.observations import ObservationSet, ResponseObservation, load_observations

WINDOWS = {"7d": 7, "30d": 30, "90d": 90}
DEFAULT_WINDOW: Literal["30d"] = "30d"
TREND_BUCKETS = {"7d": 1, "30d": 1, "90d": 7}  # bucket width in days for the series
# A change smaller than this (in score points) is reported as "flat".
FLAT_THRESHOLD = 2.0


def utcnow() -> datetime:
    return datetime.now(UTC)


def window_bounds(window: str, now: datetime) -> tuple[datetime, datetime, datetime]:
    """(previous_start, current_start, end) for a window key."""
    days = WINDOWS[window]
    current_start = now - timedelta(days=days)
    return current_start - timedelta(days=days), current_start, now


def in_range(
    obs: Iterable[ResponseObservation], start: datetime, end: datetime
) -> list[ResponseObservation]:
    return [o for o in obs if start <= o.completed_at < end]


def compare(current: VisibilityMetrics, previous: VisibilityMetrics) -> dict[str, Any]:
    """Change between two periods. Unavailable when either score is withheld."""
    if current.score is None or previous.score is None:
        reason = (
            "insufficient data in the current period"
            if current.score is None
            else ("insufficient data in the previous period")
        )
        return {"change": None, "trend": "unavailable", "reason": reason}
    change = round(current.score - previous.score, 1)
    if abs(change) < FLAT_THRESHOLD:
        trend = "flat"
    else:
        trend = "up" if change > 0 else "down"
    return {"change": change, "trend": trend, "reason": None}


def _period(metrics: VisibilityMetrics, start: datetime, end: datetime) -> dict[str, Any]:
    return {
        **metrics.to_dict(),
        "period": {"start": start.isoformat(), "end": end.isoformat()},
    }


class VisibilityEngine:
    def __init__(self, session: AsyncSession, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utcnow()

    async def _load(
        self, project_id: uuid.UUID, window: str
    ) -> tuple[ObservationSet, datetime, datetime, datetime]:
        prev_start, cur_start, end = window_bounds(window, self._now)
        data = await load_observations(self._session, project_id, start=prev_start, end=end)
        return data, prev_start, cur_start, end

    async def overview(self, project_id: uuid.UUID, window: str = DEFAULT_WINDOW) -> dict[str, Any]:
        data, prev_start, cur_start, end = await self._load(project_id, window)
        current = compute(in_range(data.observations, cur_start, end), data.competitor_names)
        previous = compute(
            in_range(data.observations, prev_start, cur_start), data.competitor_names
        )
        return {
            "method": METHOD,
            "window": window,
            "generated_at": self._now.isoformat(),
            "current": _period(current, cur_start, end),
            "previous": _period(previous, prev_start, cur_start),
            **compare(current, previous),
            "competitors_configured": len(data.competitor_names),
        }

    async def trends(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Per-window summary (current vs previous) plus a bucketed series over 90 days."""
        start = self._now - timedelta(days=2 * WINDOWS["90d"])
        data = await load_observations(self._session, project_id, start=start, end=self._now)
        windows: dict[str, Any] = {}
        for key in WINDOWS:
            prev_start, cur_start, end = window_bounds(key, self._now)
            current = compute(in_range(data.observations, cur_start, end), data.competitor_names)
            previous = compute(
                in_range(data.observations, prev_start, cur_start), data.competitor_names
            )
            windows[key] = {
                "current_score": current.score,
                "previous_score": previous.score,
                "current_sample_size": current.sample_size,
                "previous_sample_size": previous.sample_size,
                "sufficiency": current.sufficiency,
                **compare(current, previous),
            }
        days, bucket = WINDOWS["90d"], TREND_BUCKETS["90d"]
        series = self._series(data, days=days, bucket_days=bucket)
        by_provider = {
            key: self._series(
                ObservationSet(
                    [o for o in data.observations if o.provider_key == key],
                    data.competitor_names,
                    data.brand_domains,
                ),
                days=days,
                bucket_days=bucket,
            )
            for key in sorted({o.provider_key for o in data.observations})
        }
        return {
            "method": METHOD,
            "generated_at": self._now.isoformat(),
            "windows": windows,
            "series": series,
            "series_by_provider": by_provider,
            "series_by_competitor": self._competitor_series(data, days=days, bucket_days=bucket),
            "minimum_sample": MIN_SAMPLE,
        }

    def _competitor_series(
        self, data: ObservationSet, *, days: int, bucket_days: int
    ) -> dict[str, list[dict[str, Any]]]:
        """Mention rate per bucket for the brand and each configured competitor.
        Rates follow the same sufficiency rounding as everything else."""
        end = self._now
        start = end - timedelta(days=days)
        names = ["brand", *data.competitor_names]
        out: dict[str, list[dict[str, Any]]] = {n: [] for n in names}
        cursor = start
        while cursor < end:
            nxt = min(cursor + timedelta(days=bucket_days), end)
            bucket = in_range(data.observations, cursor, nxt)
            n = len(bucket)
            rows = {
                r["name"]: r
                for r in competitor_table(
                    ObservationSet(bucket, data.competitor_names, data.brand_domains)
                )
            }
            for name in names:
                out[name].append(
                    {
                        "start": cursor.isoformat(),
                        "end": nxt.isoformat(),
                        "mention_rate": rows[name]["mention_rate"],
                        "sample_size": n,
                        "sufficiency": sufficiency_for(n),
                    }
                )
            cursor = nxt
        return out

    def _series(self, data: ObservationSet, *, days: int, bucket_days: int) -> list[dict[str, Any]]:
        end = self._now
        start = end - timedelta(days=days)
        points: list[dict[str, Any]] = []
        cursor = start
        while cursor < end:
            nxt = min(cursor + timedelta(days=bucket_days), end)
            bucket = in_range(data.observations, cursor, nxt)
            m = compute(bucket, data.competitor_names)
            points.append(
                {
                    "start": cursor.isoformat(),
                    "end": nxt.isoformat(),
                    "score": m.score,
                    "mention_rate": m.mention_rate,
                    "recommendation_rate": m.recommendation_rate,
                    "citation_rate": m.citation_rate,
                    "sample_size": m.sample_size,
                    "sufficiency": m.sufficiency,
                }
            )
            cursor = nxt
        return points

    async def by_engine(
        self, project_id: uuid.UUID, window: str = DEFAULT_WINDOW
    ) -> dict[str, Any]:
        data, _, cur_start, end = await self._load(project_id, window)
        obs = in_range(data.observations, cur_start, end)
        providers = _group(obs, lambda o: o.provider_key, data.competitor_names)
        models = _group(obs, lambda o: (o.provider_key, o.model_key), data.competitor_names)
        return {
            "method": METHOD,
            "window": window,
            "period": {"start": cur_start.isoformat(), "end": end.isoformat()},
            "overall": compute(obs, data.competitor_names).to_dict(),
            "providers": [{"provider": key, **m.to_dict()} for key, m in sorted(providers.items())],
            "models": [
                {"provider": key[0], "model": key[1], **m.to_dict()}
                for key, m in sorted(models.items())
            ],
        }

    async def by_prompt(
        self, project_id: uuid.UUID, window: str = DEFAULT_WINDOW
    ) -> dict[str, Any]:
        data, _, cur_start, end = await self._load(project_id, window)
        obs = in_range(data.observations, cur_start, end)
        prompts = _group(obs, lambda o: o.prompt_id, data.competitor_names)
        texts = {o.prompt_id: o for o in obs}
        last_run: dict[uuid.UUID, str] = {}
        for o in obs:
            prev = last_run.get(o.prompt_id)
            if prev is None or o.completed_at.isoformat() > prev:
                last_run[o.prompt_id] = o.completed_at.isoformat()
        categories = _group(obs, lambda o: o.category, data.competitor_names)
        stages = _group(obs, lambda o: o.funnel_stage, data.competitor_names)
        return {
            "method": METHOD,
            "window": window,
            "period": {"start": cur_start.isoformat(), "end": end.isoformat()},
            "prompts": [
                {
                    "prompt_id": str(pid),
                    "text": texts[pid].prompt_text,
                    "category": texts[pid].category,
                    "funnel_stage": texts[pid].funnel_stage,
                    "last_completed_at": last_run.get(pid),
                    **_prompt_summary(m),
                }
                for pid, m in prompts.items()
            ],
            "categories": [{"category": k, **m.to_dict()} for k, m in sorted(categories.items())],
            "funnel_stages": [
                {"funnel_stage": k, **m.to_dict()} for k, m in sorted(stages.items())
            ],
        }

    async def competitors(
        self, project_id: uuid.UUID, window: str = DEFAULT_WINDOW
    ) -> dict[str, Any]:
        data, _, cur_start, end = await self._load(project_id, window)
        obs = in_range(data.observations, cur_start, end)
        metrics = compute(obs, data.competitor_names)
        return {
            "method": METHOD,
            "window": window,
            "period": {"start": cur_start.isoformat(), "end": end.isoformat()},
            "competitors_configured": len(data.competitor_names),
            "competitive_score": next(
                c.value for c in metrics.components if c.key == "competitive_score"
            ),
            "data_quality": metrics.to_dict()["data_quality"],
            "rows": competitor_table(
                ObservationSet(obs, data.competitor_names, data.brand_domains)
            ),
            "note": (
                "Share of voice counts responses mentioning each name; only configured "
                "competitors are compared. Unconfigured brands never lower the score."
            ),
        }


def _group(
    obs: list[ResponseObservation],
    key: Callable[[ResponseObservation], Any],
    competitors: list[str],
) -> dict[Any, VisibilityMetrics]:
    groups: dict[Any, list[ResponseObservation]] = defaultdict(list)
    for o in obs:
        groups[key(o)].append(o)
    return {k: compute(v, competitors) for k, v in groups.items()}


def _prompt_summary(m: VisibilityMetrics) -> dict[str, Any]:
    """Per-prompt rows are usually tiny samples: expose counts, not precise scores."""
    return {
        "sample_size": m.sample_size,
        "sufficiency": m.sufficiency,
        "score": m.score,
        "mentions": sum(m.sentiment.values()),
        "mention_rate": m.mention_rate,
        "recommendation_rate": m.recommendation_rate,
        "average_position": m.average_position,
        "citation_rate": m.citation_rate,
        "sentiment": m.sentiment,
        "providers": len(m.providers),
    }
