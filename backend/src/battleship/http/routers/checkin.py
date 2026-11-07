"""每日签到。日期只由服务端沪时决定，请求体里的日期一律不读。"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..deps import require_user
from ..errors import api_error

router = APIRouter(tags=["checkin"])


def _service(request: Request):
    return request.app.state.checkin


@router.get("/api/checkin")
def get_checkin(request: Request, user_id: str = Depends(require_user)):
    body = _service(request).view(user_id)
    if body is None:
        raise api_error(401, "unauthorized", "未登录", "session")
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.post("/api/checkin")
def post_checkin(request: Request, user_id: str = Depends(require_user)):
    body = _service(request).claim(user_id)
    if body is None:
        raise api_error(401, "unauthorized", "未登录", "session")
    return JSONResponse(body, headers={"Cache-Control": "no-store"})
