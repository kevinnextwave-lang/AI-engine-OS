"""Per-host politeness: concurrency cap plus minimum spacing between requests.

In-process (one crawl job runs inside one worker process). A Redis-backed
variant can replace this when several workers crawl the same host.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field


@dataclass
class HostPolicy:
    concurrency: int = 2
    requests_per_second: float = 2.0
    min_delay_seconds: float = 0.0

    @property
    def interval(self) -> float:
        by_rps = 1.0 / self.requests_per_second if self.requests_per_second > 0 else 0.0
        return max(by_rps, self.min_delay_seconds)


@dataclass
class _HostState:
    semaphore: asyncio.Semaphore
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    next_allowed_at: float = 0.0


class HostRateLimiter:
    def __init__(
        self,
        policy: HostPolicy,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._policy = policy
        self._hosts: dict[str, _HostState] = {}
        self._clock = clock
        self._sleep = sleep

    def policy_for(self, host: str) -> HostPolicy:
        return self._policy

    def _state(self, host: str) -> _HostState:
        state = self._hosts.get(host)
        if state is None:
            state = _HostState(semaphore=asyncio.Semaphore(self.policy_for(host).concurrency))
            self._hosts[host] = state
        return state

    def set_delay(self, host: str, seconds: float) -> None:
        """Honour robots.txt crawl-delay for a host (never below the global spacing)."""
        state = self._state(host)
        state.next_allowed_at = max(state.next_allowed_at, self._clock() + seconds)

    async def acquire(self, host: str) -> None:
        state = self._state(host)
        await state.semaphore.acquire()
        try:
            async with state.lock:
                now = self._clock()
                wait = state.next_allowed_at - now
                state.next_allowed_at = (
                    max(now, state.next_allowed_at) + self.policy_for(host).interval
                )
            if wait > 0:
                await self._sleep(wait)
        except BaseException:
            state.semaphore.release()
            raise

    def release(self, host: str) -> None:
        self._state(host).semaphore.release()
