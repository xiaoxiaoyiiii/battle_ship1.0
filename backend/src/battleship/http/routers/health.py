"""健康检查与指标路由。

L4（issue #32）收敛：健康检查保持匿名（运维探针只看 status），但明细不再携带
磁盘路径；运行指标只对服务端验证的管理员开放。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..deps import require_admin

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
async def metrics(request: Request, actor: str = Depends(require_admin)):
    return request.app.state.metrics.snapshot()
