"""进程内关键指标：连接/房间/在线数、事件延迟、错误率。

不引入 Prometheus 依赖：`/metrics` 直接输出 JSON，部署侧要接监控再包一层即可。
指标只增不降（除 gauge），未来服务通过 `set_gauge` 填 rooms / online_players。
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

_MAX_SAMPLES = 1024


class _LatencyWindow:
    def __init__(self, max_samples: int = _MAX_SAMPLES) -> None:
        self._samples: deque[float] = deque(maxlen=max_samples)
        self._lock = threading.Lock()

    def add(self, value_ms: float) -> None:
        with self._lock:
            self._samples.append(float(value_ms))

    def stats(self) -> dict[str, float | int]:
        with self._lock:
            values = sorted(self._samples)
        count = len(values)
        if not values:
            return {"count": 0, "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}

        def percentile(p: float) -> float:
            index = max(0, min(count - 1, math.ceil(p * count) - 1))
            return round(values[index], 3)

        return {
            "count": count,
            "p50_ms": percentile(0.50),
            "p95_ms": percentile(0.95),
            "max_ms": round(values[-1], 3),
        }


class MetricsRegistry:
    def __init__(self, *, started_at: datetime | None = None) -> None:
        self.started_at = started_at or datetime.now(timezone.utc)
        self._started_monotonic = time.monotonic()
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {
            "http_requests_total": 0,
            "http_errors_total": 0,
            "socket_events_total": 0,
            "socket_errors_total": 0,
        }
        self._gauges: dict[str, int] = {
            "connections": 0,
            "rooms": 0,
            "online_players": 0,
        }
        self._latency: dict[str, _LatencyWindow] = {
            "http_request_ms": _LatencyWindow(),
            "socket_event_ms": _LatencyWindow(),
        }

    def increment(self, name: str, amount: int = 1) -> int:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount
            return self._counters[name]

    def set_gauge(self, name: str, value: int) -> None:
        with self._lock:
            self._gauges[name] = int(value)

    def connection_opened(self) -> None:
        with self._lock:
            self._gauges["connections"] = self._gauges.get("connections", 0) + 1
            self._gauges["online_players"] = self._gauges.get("online_players", 0) + 1

    def connection_closed(self) -> None:
        with self._lock:
            self._gauges["connections"] = max(0, self._gauges.get("connections", 0) - 1)
            self._gauges["online_players"] = max(0, self._gauges.get("online_players", 0) - 1)

    def record_http(self, status_code: int, duration_ms: float) -> None:
        self.increment("http_requests_total")
        if status_code >= 500:
            self.increment("http_errors_total")
        self._latency["http_request_ms"].add(duration_ms)

    def record_socket_event(self, event: str, duration_ms: float, *, error: bool = False) -> None:
        self.increment("socket_events_total")
        if error:
            self.increment("socket_errors_total")
        self._latency["socket_event_ms"].add(duration_ms)

    @property
    def uptime_seconds(self) -> float:
        return round(time.monotonic() - self._started_monotonic, 3)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
        latency = {name: window.stats() for name, window in self._latency.items()}
        total = counters["http_requests_total"] + counters["socket_events_total"]
        errors = counters["http_errors_total"] + counters["socket_errors_total"]
        return {
            "uptime_seconds": self.uptime_seconds,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "counters": counters,
            "gauges": gauges,
            "latency_ms": latency,
            "error_rate": round(errors / total, 4) if total else 0.0,
        }
