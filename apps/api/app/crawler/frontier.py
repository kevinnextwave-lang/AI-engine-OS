"""Priority-aware URL frontier with de-duplication.

Lower number = fetched earlier. Priorities are open-ended so future signals
(high-value pages, staleness, links from important content, prompt
relevance) can slot in without changing the queue.
"""

import enum
import heapq
import itertools
from dataclasses import dataclass


class Priority(enum.IntEnum):
    HOMEPAGE = 0
    SITEMAP = 1
    NAVIGATION = 2
    CONTENT = 3
    # Reserved for later milestones:
    HIGH_VALUE = 1
    STALE = 2
    LOW_VALUE = 5


@dataclass(frozen=True)
class FrontierItem:
    url: str  # normalized
    depth: int
    priority: int
    parent_url: str | None
    source: str  # "seed" | "sitemap" | "link"


class Frontier:
    def __init__(self) -> None:
        self._heap: list[tuple[int, int, int, FrontierItem]] = []
        self._seen: set[str] = set()
        self._counter = itertools.count()

    def __len__(self) -> int:
        return len(self._heap)

    @property
    def seen_count(self) -> int:
        return len(self._seen)

    def has_seen(self, url: str) -> bool:
        return url in self._seen

    def push(self, item: FrontierItem) -> bool:
        """Add a URL once. Returns False if it was already known (duplicate)."""
        if item.url in self._seen:
            return False
        self._seen.add(item.url)
        heapq.heappush(self._heap, (item.priority, item.depth, next(self._counter), item))
        return True

    def pop(self) -> FrontierItem | None:
        if not self._heap:
            return None
        return heapq.heappop(self._heap)[3]
