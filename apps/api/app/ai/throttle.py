"""Per-provider request throttling for workers.

A fixed-window counter keyed by provider (Redis in production, in-memory for
tests/dev). `acquire()` returns 0 when a call may proceed now, otherwise the
number of seconds to wait — the Celery task re-schedules itself instead of
sleeping on a worker slot.
"""

import time
from typing import Protocol

from redis.asyncio import Redis


class ProviderThrottle(Protocol):
    async def acquire(self, provider_key: str, limit_per_minute: int) -> float: ...


class RedisProviderThrottle:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def acquire(self, provider_key: str, limit_per_minute: int) -> float:
        if limit_per_minute <= 0:
            return 0.0
        window = int(time.time() // 60)
        key = f"ai:throttle:{provider_key}:{window}"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, 120)
        if count <= limit_per_minute:
            return 0.0
        await self._redis.decr(key)
        return float(60 - (time.time() % 60)) + 0.5


class InMemoryProviderThrottle:
    def __init__(self) -> None:
        self._counts: dict[tuple[str, int], int] = {}

    async def acquire(self, provider_key: str, limit_per_minute: int) -> float:
        if limit_per_minute <= 0:
            return 0.0
        window = int(time.time() // 60)
        key = (provider_key, window)
        if self._counts.get(key, 0) >= limit_per_minute:
            return float(60 - (time.time() % 60)) + 0.5
        self._counts[key] = self._counts.get(key, 0) + 1
        return 0.0

    def reset(self) -> None:
        self._counts.clear()


def backoff_seconds(attempt: int, *, base: float, cap: float) -> float:
    """Exponential backoff for retry N (1-based): base × 2^(N−1), capped."""
    return float(min(cap, base * (2 ** max(0, attempt - 1))))
