"""Fixed-window rate limiting backed by Redis.

Falls back to an in-process store when Redis is unavailable (tests / local dev)
so the API never hard-fails because of the limiter. In production, Redis is
expected to be present.
"""

import time
from typing import Protocol

from redis.asyncio import Redis

from app.core.logging import get_logger

log = get_logger(__name__)


class RateLimiter(Protocol):
    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Record a hit. Returns True if allowed, False if the limit is exceeded."""
        ...


class RedisRateLimiter:
    def __init__(self, redis: Redis, fallback: "InMemoryRateLimiter | None" = None) -> None:
        self._redis = redis
        # A Redis blip must not fail OPEN (that's exactly when an attack is
        # cheapest) and must not fail the API CLOSED either: degrade to the
        # per-process store, which still bounds abuse per replica.
        self._fallback = fallback or InMemoryRateLimiter()

    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        window = int(time.time() // window_seconds)
        redis_key = f"rl:{key}:{window}"
        try:
            pipe = self._redis.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, window_seconds)
            count, _ = await pipe.execute()
        except Exception as exc:  # noqa: BLE001 — limiter must never take the API down
            log.warning("rate_limiter_redis_degraded_to_memory", error=type(exc).__name__)
            return await self._fallback.hit(key, limit, window_seconds)
        return int(count) <= limit


class InMemoryRateLimiter:
    def __init__(self) -> None:
        # key -> (count, window_expires_at_epoch_seconds)
        self._hits: dict[str, tuple[int, float]] = {}

    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        window = int(now // window_seconds)
        k = f"{key}:{window}"
        count, expires = self._hits.get(k, (0, (window + 1) * window_seconds))
        count += 1
        self._hits[k] = (count, expires)
        if len(self._hits) > 50_000:
            # Expired windows never get read again; drop them (by each entry's
            # OWN expiry, so rules with different window sizes are untouched)
            # so a long-lived process without Redis cannot grow this dict
            # without bound.
            self._hits = {kk: v for kk, v in self._hits.items() if v[1] > now}
        return count <= limit

    def reset(self) -> None:
        self._hits.clear()
