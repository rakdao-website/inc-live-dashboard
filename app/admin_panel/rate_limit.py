"""Sliding-window limiter for login attempts, per client IP and per username.

Held in process memory: it resets on restart and is per worker. Run a single
worker, or move this to Redis/the database before scaling out.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.config import settings


class LoginRateLimiter:
    def __init__(self):
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        window = settings.admin_login_window_seconds
        bucket = self._failures[key]
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        return bucket

    def retry_after(self, *keys: str) -> int:
        """Seconds until a blocked key may try again, or 0 if none is blocked."""
        now = time.monotonic()
        wait = 0
        with self._lock:
            for key in keys:
                bucket = self._prune(key, now)
                if len(bucket) >= settings.admin_login_max_attempts:
                    wait = max(wait, int(settings.admin_login_window_seconds - (now - bucket[0])) + 1)
        return wait

    def record_failure(self, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key in keys:
                self._prune(key, now).append(now)

    def reset(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._failures.clear()


login_limiter = LoginRateLimiter()
