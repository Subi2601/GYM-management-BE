"""In-process sliding-window limiter for the public (no-login) endpoints.

Single API process, no Redis (not approved) — counts live in memory and reset on restart, which is enough to
stop guessing an ID number from one phone or address.
"""
from __future__ import annotations

import time
from collections import deque
from threading import Lock


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    def _recent(self, key: str, now: float) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= now - self._window:
            hits.popleft()
        return hits

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._recent(key, time.monotonic())) >= self._limit

    def hit(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._recent(key, now).append(now)
            if len(self._hits) > 10_000:   # drop idle keys so memory stays bounded
                self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > now - self._window}

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
