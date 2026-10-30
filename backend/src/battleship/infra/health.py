"""健康检查聚合器。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..contracts.export_schema import schema_hash
from ..contracts.http_models import HealthCheck, HealthResponse
from .db import check_database

if TYPE_CHECKING:
    from .config import Settings
    from .metrics import MetricsRegistry


class HealthService:
    def __init__(
        self,
        settings: "Settings",
        metrics: "MetricsRegistry",
        *,
        version: str,
        socketio_ready: bool = True,
    ) -> None:
        self.settings = settings
        self.metrics = metrics
        self.version = version
        self.socketio_ready = socketio_ready

    def snapshot(self) -> dict:
        checks: list[HealthCheck] = [
            HealthCheck(name="config", status="ok", detail="环境变量已校验"),
            HealthCheck(name="socketio", status="ok" if self.socketio_ready else "error",
                        detail="ASGI 适配层已挂载" if self.socketio_ready else "Socket.IO 未就绪"),
        ]

        db_ok, db_detail = check_database(self.settings)
        checks.append(HealthCheck(name="database", status="ok" if db_ok else "error", detail=db_detail))

        try:
            checks.append(HealthCheck(name="contracts", status="ok", detail=schema_hash()[:12]))
        except Exception as exc:
            checks.append(HealthCheck(name="contracts", status="error", detail=str(exc)))

        status = "ok" if all(check.status == "ok" for check in checks) else "degraded"
        response = HealthResponse(
            status=status,
            version=self.version,
            uptime_seconds=self.metrics.uptime_seconds,
            checks=checks,
        )
        return response.model_dump(mode="json")

    @property
    def healthy(self) -> bool:
        return self.snapshot()["status"] == "ok"
