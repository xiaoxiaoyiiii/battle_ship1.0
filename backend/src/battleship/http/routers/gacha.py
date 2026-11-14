"""卡池状态、抽卡与碎片兑换。"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ...services.gacha import SkinHttpError
from ..deps import require_user
from ..errors import api_error

router = APIRouter(tags=["gacha"])


def _service(request: Request):
    return request.app.state.gacha


def _raise(exc: SkinHttpError):
    raise api_error(exc.status_code, exc.code, exc.message, exc.field)


@router.get("/api/shop/gacha")
def get_gacha(request: Request, user_id: str = Depends(require_user)):
    try:
        body = _service(request).view(user_id)
    except SkinHttpError as exc:
        _raise(exc)
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.post("/api/shop/gacha/pull")
async def pull_gacha(request: Request, user_id: str = Depends(require_user)):
    try:
        data = await request.json()
    except ValueError:
        data = None
    try:
        body = _service(request).pull(user_id, data)
    except SkinHttpError as exc:
        _raise(exc)
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.post("/api/shop/gacha/exchange")
async def exchange_gacha(request: Request, user_id: str = Depends(require_user)):
    try:
        data = await request.json()
    except ValueError:
        data = None
    try:
        body = _service(request).exchange(user_id, data)
    except SkinHttpError as exc:
        _raise(exc)
    return JSONResponse(body, headers={"Cache-Control": "no-store"})
