"""指挥官角色系统 HTTP 接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..deps import get_current_user_id

router = APIRouter(tags=["commanders"])


def _service(request: Request):
    svc = getattr(request.app.state, "commanders", None)
    if svc is not None:
        return svc
    from ...services.commanders import CommanderService
    return CommanderService(request.app.state.database)


@router.get("/api/commanders")
def get_commanders(
    request: Request,
    user_id: str | None = Depends(get_current_user_id),
):
    return JSONResponse(_service(request).view(user_id), status_code=200)


@router.post("/api/commanders/unlock")
async def unlock_commander(
    request: Request,
    user_id: str | None = Depends(get_current_user_id),
):
    if not user_id:
        return JSONResponse({"ok": False, "reason": "unauthorized", "message": "请先登录"}, status_code=401)
    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    commander_id = payload.get("commander_id") if isinstance(payload, dict) else None
    if not isinstance(commander_id, str):
        return JSONResponse({"ok": False, "reason": "invalid_commander", "message": "缺少指挥官标识"}, status_code=400)
    res = _service(request).unlock(user_id, commander_id)
    status = 200 if res.get("ok") else {
        "unauthorized": 401,
        "invalid_commander": 400,
        "insufficient_funds": 409,
        "conflict": 409,
    }.get(str(res.get("reason")), 400)
    return JSONResponse(res, status_code=status)


@router.post("/api/commanders/select")
async def select_commander(
    request: Request,
    user_id: str | None = Depends(get_current_user_id),
):
    if not user_id:
        return JSONResponse({"ok": False, "reason": "unauthorized", "message": "请先登录"}, status_code=401)
    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    commander_id = payload.get("commander_id") if isinstance(payload, dict) else None
    if not isinstance(commander_id, str):
        return JSONResponse({"ok": False, "reason": "invalid_commander", "message": "缺少指挥官标识"}, status_code=400)
    res = _service(request).select(user_id, commander_id)
    status = 200 if res.get("ok") else {
        "unauthorized": 401,
        "invalid_commander": 400,
        "not_owned": 409,
    }.get(str(res.get("reason")), 400)
    return JSONResponse(res, status_code=status)


@router.post("/api/commanders/claim")
async def claim_commander_reward(
    request: Request,
    user_id: str | None = Depends(get_current_user_id),
):
    if not user_id:
        return JSONResponse({"ok": False, "reason": "unauthorized", "message": "请先登录"}, status_code=401)
    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        return JSONResponse({"ok": False, "reason": "invalid_payload", "message": "请求参数无效"}, status_code=400)
    commander_id = payload.get("commander_id")
    if not isinstance(commander_id, str):
        return JSONResponse({"ok": False, "reason": "invalid_commander", "message": "缺少指挥官标识"}, status_code=400)
    claim_all = bool(payload.get("claim_all"))
    raw_level = payload.get("level")
    level = int(raw_level) if isinstance(raw_level, int) and not isinstance(raw_level, bool) else None
    res = _service(request).claim(user_id, commander_id, level, claim_all=claim_all)
    status = 200 if res.get("ok") else {
        "unauthorized": 401,
        "invalid_commander": 400,
        "invalid_level": 400,
        "not_owned": 409,
        "level_locked": 409,
    }.get(str(res.get("reason")), 400)
    return JSONResponse(res, status_code=status)


@router.post("/api/commanders/equip")
async def equip_commander_cosmetics(
    request: Request,
    user_id: str | None = Depends(get_current_user_id),
):
    if not user_id:
        return JSONResponse({"ok": False, "reason": "unauthorized", "message": "请先登录"}, status_code=401)
    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        return JSONResponse({"ok": False, "reason": "invalid_payload", "message": "请求参数无效"}, status_code=400)
    commander_id = payload.get("commander_id")
    if not isinstance(commander_id, str):
        return JSONResponse({"ok": False, "reason": "invalid_commander", "message": "缺少指挥官标识"}, status_code=400)
    equipped = payload.get("equipped")
    res = _service(request).equip(user_id, commander_id, equipped if isinstance(equipped, dict) else None)
    status = 200 if res.get("ok") else {
        "unauthorized": 401,
        "invalid_commander": 400,
        "invalid_payload": 400,
        "not_owned": 409,
        "cosmetic_locked": 409,
    }.get(str(res.get("reason")), 400)
    return JSONResponse(res, status_code=status)
