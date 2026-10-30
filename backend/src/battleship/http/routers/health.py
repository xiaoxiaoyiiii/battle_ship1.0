"""健康检查与指标路由。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health")
@router.get("/healthz")
@router.get("/api/health")
async def health(request: Request):
    payload = request.app.state.health.snapshot()
    status_code = 200 if payload["status"] == "ok" else 503
    return JSONResponse(payload, status_code=status_code)


@router.get("/metrics")
@router.get("/api/metrics")
async def metrics(request: Request):
    return request.app.state.metrics.snapshot()
