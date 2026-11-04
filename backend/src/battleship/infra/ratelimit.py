"""In-process fixed-window rate limiting (legacy 10 requests / 60 seconds).

The old stack kept one counter per (scope, client IP) in a module dict. This is
the same best-effort gate: it is not a distributed limiter and does not survive a
restart, but it preserves the 429 contract for the auth endpoints.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict

DEFAULT_LIMIT = 10
DEFAULT_WINDOW_SECONDS = 60.0


class RateLimiter:
    def __init__(self, *, limit: int = DEFAULT_LIMIT,
                 window_seconds: float = DEFAULT_WINDOW_SECONDS) -> None:
        self.limit = max(1, int(limit))
        self.window = max(0.001, float(window_seconds))
        self._events: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._lock = threading.Lock()
        self._last_sweep = 0.0

    def hit(self, scope: str, key: str) -> bool:
        """Record a request; return True when the caller is over the limit."""
        now = time.monotonic()
        bucket_key = (scope, key)
        with self._lock:
            # L12（issue #32）：桶过去没有整项淘汰，长期运行会按 (scope, 客户端)
            # 无限增长。每个窗口做一次全量清扫，淘汰整个已过期的桶。
            if now - self._last_sweep >= self.window:
                cutoff = now - self.window
                for stale in [k for k, stamps in self._events.items()
                              if not stamps or stamps[-1] <= cutoff]:
                    self._events.pop(stale, None)
                self._last_sweep = now
            bucket = self._events[bucket_key]
            cutoff = now - self.window
            if bucket and bucket[0] <= cutoff:
                bucket[:] = [stamp for stamp in bucket if stamp > cutoff]
            if len(bucket) >= self.limit:
                return True
            bucket.append(now)
            return False

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


def client_key(request) -> str:  # starlette.requests.Request, kept duck-typed
    client = getattr(request, "client", None)
    return str(getattr(client, "host", None) or "unknown")
