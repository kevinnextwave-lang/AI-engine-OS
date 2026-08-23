"""Competitive visibility views: overview, trends, per-prompt and per-engine.
Computed on demand from the same observations as the AI Visibility Score."""

import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.competitive.metrics import (
    BRAND,
    MATERIAL_ADVANTAGE,
    RANKING_MIN_SAMPLE,
    EntityMetrics,
    advantages,
    compute_all,
    data_quality,
    entity_view,
    method_block,
    ranking,
    serialize_date_range,
)
from app.visibility.engine import (
    DEFAULT_WINDOW,
    FLAT_THRESHOLD,
    TREND_BUCKETS,
    WINDOWS,
    in_range,
    utcnow,
    window_bounds,
)
from app.visibility.metrics import MIN_SAMPLE, sufficiency_for
from app.visibility.observations import (
    STRENGTH_RANK,
    ObservationSet,
    ResponseObservation,
    load_observations,
)


def _entity_names(data: ObservationSet) -> list[str]:
    return [BRAND, *data.competitor_names]


def _block(obs: list[ResponseObservation], data: ObservationSet) -> dict[str, Any]:
    rows = compute_all(obs, data.competitor_names)
    return {
        "entities": [r.to_dict() for r in rows],
        "advantages": advantages(rows),
        "ranking": ranking(rows),
        "data_quality": serialize_date_range(data_quality(obs, len(data.competitor_names))),
    }


def _change(cur: EntityMetrics, prev: EntityMetrics) -> dict[str, Any]:
    if cur.score is None or prev.score is None:
        return {"change": None, "trend": "unavailable"}
    change = round(cur.score - prev.score, 1)
    trend = "flat" if abs(change) < FLAT_THRESHOLD else ("up" if change > 0 else "down")
    return {"change": change, "trend": trend}


class CompetitiveVisibilityEngine:
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
        current_obs = in_range(data.observations, cur_start, end)
        previous_obs = in_range(data.observations, prev_start, cur_start)
        current = _block(current_obs, data)
        previous_rows = {r.name: r for r in compute_all(previous_obs, data.competitor_names)}
        current_rows = {r.name: r for r in compute_all(current_obs, data.competitor_names)}
        for ent in current["entities"]:
            ent["previous_score"] = previous_rows[ent["name"]].score
            ent.update(_change(current_rows[ent["name"]], previous_rows[ent["name"]]))
        return {
            **method_block(),
            "window": window,
            "generated_at": self._now.isoformat(),
            "period": {"start": cur_start.isoformat(), "end": end.isoformat()},
            "previous_period": {"start": prev_start.isoformat(), "end": cur_start.isoformat()},
            **current,
            "previous_data_quality": serialize_date_range(
                data_quality(previous_obs, len(data.competitor_names))
            ),
            "material_advantage_threshold": MATERIAL_ADVANTAGE,
        }

    async def trends(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Per-window current vs previous score for every entity, plus a bucketed
        series (90 days, weekly) per entity."""
        start = self._now - timedelta(days=2 * WINDOWS["90d"])
        data = await load_observations(self._session, project_id, start=start, end=self._now)
        names = _entity_names(data)
        windows: dict[str, Any] = {}
        for key in WINDOWS:
            prev_start, cur_start, end = window_bounds(key, self._now)
            cur = {
                r.name: r
                for r in compute_all(
                    in_range(data.observations, cur_start, end), data.competitor_names
                )
            }
            prev = {
                r.name: r
                for r in compute_all(
                    in_range(data.observations, prev_start, cur_start), data.competitor_names
                )
            }
            sample = next(iter(cur.values())).sample_size if cur else 0
            windows[key] = {
                "current_sample_size": sample,
                "previous_sample_size": next(iter(prev.values())).sample_size if prev else 0,
                "sufficiency": sufficiency_for(sample),
                "entities": [
                    {
                        "name": n,
                        "is_brand": n == BRAND,
                        "current_score": cur[n].score,
                        "previous_score": prev[n].score,
                        "current_mention_share": cur[n].mention_share,
                        "previous_mention_share": prev[n].mention_share,
                        **_change(cur[n], prev[n]),
                    }
                    for n in names
                ],
                "advantages": advantages(list(cur.values())),
            }
        days, bucket_days = WINDOWS["90d"], TREND_BUCKETS["90d"]
        series: dict[str, list[dict[str, Any]]] = {n: [] for n in names}
        cursor = self._now - timedelta(days=days)
        while cursor < self._now:
            nxt = min(cursor + timedelta(days=bucket_days), self._now)
            bucket = in_range(data.observations, cursor, nxt)
            rows = {r.name: r for r in compute_all(bucket, data.competitor_names)}
            for n in names:
                series[n].append(
                    {
                        "start": cursor.isoformat(),
                        "end": nxt.isoformat(),
                        "score": rows[n].score,
                        "mention_share": rows[n].mention_share,
                        "recommendation_share": rows[n].recommendation_share,
                        "citation_share": rows[n].citation_share,
                        "sample_size": len(bucket),
                        "sufficiency": sufficiency_for(len(bucket)),
                    }
                )
            cursor = nxt
        return {
            **method_block(),
            "generated_at": self._now.isoformat(),
            "windows": windows,
            "series": series,
            "bucket_days": bucket_days,
            "minimum_sample": MIN_SAMPLE,
            "data_quality": serialize_date_range(
                data_quality(
                    in_range(data.observations, self._now - timedelta(days=days), self._now),
                    len(data.competitor_names),
                )
            ),
        }

    async def prompts(self, project_id: uuid.UUID, window: str = DEFAULT_WINDOW) -> dict[str, Any]:
        """Prompt → brand + each competitor: mentioned / recommended / position /
        sentiment / citations / recommendation strength, aggregated over the prompt's
        responses in the window."""
        data, _, cur_start, end = await self._load(project_id, window)
        obs = in_range(data.observations, cur_start, end)
        names = _entity_names(data)
        by_prompt: dict[uuid.UUID, list[ResponseObservation]] = defaultdict(list)
        for o in obs:
            by_prompt[o.prompt_id].append(o)
        out: list[dict[str, Any]] = []
        for pid, rows in by_prompt.items():
            first = rows[0]
            entities = [_prompt_entity(rows, n) for n in names]
            leader = _prompt_leader(entities, len(rows))
            out.append(
                {
                    "prompt_id": str(pid),
                    "text": first.prompt_text,
                    "category": first.category,
                    "funnel_stage": first.funnel_stage,
                    "responses": len(rows),
                    "providers": sorted({o.provider_key for o in rows}),
                    "last_completed_at": max(o.completed_at for o in rows).isoformat(),
                    "sufficiency": sufficiency_for(len(rows)),
                    "entities": entities,
                    "leader": leader,
                    "brand_outperformed_by": [
                        e["name"]
                        for e in entities
                        if not e["is_brand"] and e["mentioned_in"] > entities[0]["mentioned_in"]
                    ],
                }
            )
        out.sort(key=lambda p: (-p["responses"], p["text"]))
        return {
            **method_block(),
            "window": window,
            "period": {"start": cur_start.isoformat(), "end": end.isoformat()},
            "prompts": out,
            "data_quality": serialize_date_range(data_quality(obs, len(data.competitor_names))),
            "note": (
                "Per-prompt rows are small samples: they show counts and the latest "
                "observation, not scores. Only prompts with at least "
                f"{MIN_SAMPLE} responses name a leader."
            ),
        }

    async def engines(self, project_id: uuid.UUID, window: str = DEFAULT_WINDOW) -> dict[str, Any]:
        data, _, cur_start, end = await self._load(project_id, window)
        obs = in_range(data.observations, cur_start, end)
        by_provider: dict[str, list[ResponseObservation]] = defaultdict(list)
        for o in obs:
            by_provider[o.provider_key].append(o)
        providers = []
        for key in sorted(by_provider):
            block = _block(by_provider[key], data)
            providers.append(
                {
                    "provider": key,
                    "models": sorted({o.model_key for o in by_provider[key]}),
                    **block,
                }
            )
        # Where does the brand's gap to its best competitor differ most between engines?
        spread = []
        for p in providers:
            best = p["advantages"][0] if p["advantages"] else None
            spread.append(
                {
                    "provider": p["provider"],
                    "brand_score": next(e["score"] for e in p["entities"] if e["is_brand"]),
                    "top_competitor": best["competitor"] if best else None,
                    "top_competitor_advantage": best["advantage"] if best else None,
                    "sample_size": p["data_quality"]["sample_size"],
                }
            )
        return {
            **method_block(),
            "window": window,
            "period": {"start": cur_start.isoformat(), "end": end.isoformat()},
            "overall": _block(obs, data),
            "providers": providers,
            "engine_spread": spread,
            "ranking_minimum_sample": RANKING_MIN_SAMPLE,
        }


def _prompt_entity(rows: list[ResponseObservation], name: str) -> dict[str, Any]:
    views = [entity_view(o, name) for o in rows]
    mentioned = [v for v in views if v.mentioned]
    positions = [v.position for v in mentioned if v.position is not None]
    latest = entity_view(max(rows, key=lambda o: o.completed_at), name)
    strengths = [v.strength for v in mentioned]
    strongest = max(strengths, key=lambda s: STRENGTH_RANK.get(s, 0), default="unknown")
    return {
        "name": name,
        "is_brand": name == BRAND,
        "mentioned": bool(mentioned),
        "recommended": any(v.recommended for v in views),
        "position": round(sum(positions) / len(positions), 2) if positions else None,
        "sentiment": _dominant_sentiment([v.sentiment for v in mentioned]),
        "citation_count": sum(v.citations for v in views),
        "recommendation_strength": strongest,
        "mentioned_in": len(mentioned),
        "recommended_in": sum(1 for v in views if v.recommended),
        "responses": len(rows),
        "latest": {
            "mentioned": latest.mentioned,
            "recommended": latest.recommended,
            "position": latest.position,
            "sentiment": latest.sentiment,
            "citation_count": latest.citations,
            "recommendation_strength": latest.strength,
        },
    }


def _dominant_sentiment(values: list[str]) -> str:
    known = [v for v in values if v != "unknown"]
    if not known:
        return "unknown"
    counts: dict[str, int] = defaultdict(int)
    for v in known:
        counts[v] += 1
    return max(counts.items(), key=lambda kv: (kv[1], kv[0] == "positive"))[0]


def _prompt_leader(entities: list[dict[str, Any]], responses: int) -> dict[str, Any]:
    if responses < MIN_SAMPLE:
        return {"name": None, "reason": f"fewer than {MIN_SAMPLE} responses"}

    def key(e: dict[str, Any]) -> tuple[int, int, float]:
        return (
            e["mentioned_in"],
            e["recommended_in"],
            -(e["position"] if e["position"] is not None else 99.0),
        )

    best = max(entities, key=key)
    if best["mentioned_in"] == 0:
        return {"name": None, "reason": "nobody mentioned"}
    tied = [e["name"] for e in entities if key(e) == key(best)]
    if len(tied) > 1:
        return {"name": None, "reason": "tie: " + ", ".join(tied)}
    return {"name": best["name"], "reason": None}
