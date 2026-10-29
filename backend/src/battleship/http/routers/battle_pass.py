"""赛季通行证只读进度、内部开通和奖励领取接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ...services.battle_pass import BattlePassService
from ..deps import require_admin, require_user

router = APIRouter(tags=["battle-pass"])


@router.get("/api/battle-pass")
def get_battle_pass(request: Request, user_id: str = Depends(require_user)):
    return JSONResponse(BattlePassService(request.app.state.database).view(user_id))


@router.post("/api/battle-pass/claim")
async def claim_battle_pass(request: Request, user_id: str = Depends(require_user)):
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - malformed JSON is a normal client error
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        level = int(payload.get("level"))
    except (TypeError, ValueError):
        return JSONResponse({"error": "level_invalid"}, status_code=400)
    ok, reason = BattlePassService(request.app.state.database).claim(
        user_id, level, str(payload.get("track") or "free"),
        season_id=str(payload.get("season_id") or "") or None,
    )
    status = 200 if ok else (400 if reason in {"track_invalid", "level_invalid"} else 409)
    body = {"ok": ok, "reason": reason}
    if ok:
        body["battle_pass"] = BattlePassService(request.app.state.database).view(user_id)
    return JSONResponse(body, status_code=status)


@router.post("/api/admin/battle-pass/grant-premium")
@router.post("/api/battle-pass/unlock")
async def unlock_battle_pass(request: Request, admin_id: str = Depends(require_admin)):
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    target = str(payload.get("user_id") or admin_id)
    season_id = payload.get("season_id")
    ok = BattlePassService(request.app.state.database).unlock_premium(target, season_id)
    return JSONResponse({"ok": ok, "user_id": target}, status_code=200 if ok else 404)


@router.post("/api/admin/battle-pass/seed")
async def seed_battle_pass(request: Request, admin_id: str = Depends(require_admin)):
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    import time
    season_id = str(payload.get("season_id") or "deep-sea-1")
    try:
        starts_at = int(payload.get("starts_at") or time.time())
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "reason": "starts_at_invalid"}, status_code=400)
    result = BattlePassService(request.app.state.database).seed_default(season_id, starts_at)
    return JSONResponse({"ok": True, "admin_id": admin_id, **result})


__all__ = ["router"]
