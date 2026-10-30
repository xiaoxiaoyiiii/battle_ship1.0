"""HTTP 契约的通用模型（健康检查 / 指标 / 结构化错误）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthCheck(BaseModel):
    name: str
    status: Literal["ok", "error"]
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: str = "battleship-backend"
    version: str
    uptime_seconds: float
    checks: list[HealthCheck]


class LatencyStats(BaseModel):
    count: int = 0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    max_ms: float = 0.0


class MetricsResponse(BaseModel):
    uptime_seconds: float
    started_at: str
    counters: dict[str, int] = Field(default_factory=dict)
    gauges: dict[str, int] = Field(default_factory=dict)
    latency_ms: dict[str, LatencyStats] = Field(default_factory=dict)
    error_rate: float = 0.0


class ErrorDetail(BaseModel):
    code: str
    message: str
    field: str | None = None
    context: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
