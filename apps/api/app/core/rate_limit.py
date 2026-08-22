"""Fixed-window rate limiting backed by Redis.

Falls back to an in-process store when Redis is unavailable (tests / local dev)
so the API never hard-fails because of the limiter. In production, Redis is
expected to be present.
"""

import time
from collections import defaultdict
from typing import Protocol

from redis.asyncio import Redis

from app.core.logging import get_logger

log = get_logger(__name__)


class RateLimiter(Protocol):
    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Record a hit. Returns True if allowed, False if the limit is exceeded."""
        ...


class RedisRateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        window = int(time.time() // window_seconds)
        redis_key = f"rl:{key}:{window}"
        try:
            pipe = self._redis.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, window_seconds)
            count, _ = await pipe.execute()
        except Exception as exc:  # noqa: BLE001 — limiter must never take the API down
            log.warning("rate_limiter_redis_unavailable", error=type(exc).__name__)
            return True
        return int(count) <= limit


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, int] = defaultdict(int)

    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        window = int(time.time() // window_seconds)
        k = f"{key}:{window}"
        self._hits[k] += 1
        return self._hits[k] <= limit

    def reset(self) -> None:
        self._hits.clear()
