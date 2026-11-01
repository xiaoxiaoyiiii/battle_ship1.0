"""潮汐徽记商店的只读目录与幂等购买接口。"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ...services.shop import ShopService
from ..deps import get_current_user_id

router = APIRouter(tags=["shop"])


@router.get("/api/shop")
def get_shop(request: Request, user_id: str | None = Depends(get_current_user_id)):
    result = ShopService(request.app.state.database).view(user_id or "")
    return JSONResponse(result, status_code=200 if result["ok"] else 401)


@router.post("/api/shop/purchase")
async def purchase_shop(request: Request, user_id: str | None = Depends(get_current_user_id)):
    if not user_id:
        return JSONResponse({"ok": False, "reason": "unauthorized"}, status_code=401)
    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    item_id = payload.get("item_id") if isinstance(payload, dict) else None
    if not isinstance(item_id, str):
        return JSONResponse({"ok": False, "reason": "item_unavailable"}, status_code=400)
    result = ShopService(request.app.state.database).purchase(user_id, item_id)
    status = 200 if result["ok"] else {
        "unauthorized": 401, "item_unavailable": 400,
        "insufficient_funds": 409, "already_owned": 409,
    }[result["reason"]]
    return JSONResponse(result, status_code=status)
