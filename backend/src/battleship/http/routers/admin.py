"""Anti-cheat administration routes (port map note 11 section 1.7).

The legacy screens read `{"success": bool, ...}` and `{"success": false,
"error": "<message>"}`; that body shape is frozen (D19). The gate is the same
single source of truth as every other admin check -- `AuthService.is_admin`
over `DEBUG_ADMIN_USER_IDS`, where an empty allowlist means nobody.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ...services.anticheat import AnticheatService
from ..session import read_session, session_user_id

router = APIRouter(tags=["admin"], include_in_schema=False)


def _legacy(status: int, message: str) -> JSONResponse:
    return JSONResponse({"success": False, "error": message}, status_code=status)


def _admin_guard(request: Request) -> tuple[str | None, JSONResponse | None]:
    user_id = session_user_id(read_session(request))
    if not user_id:
        return None, _legacy(401, "未登录")
    if not request.app.state.auth.is_admin(user_id):
        # Empty DEBUG_ADMIN_USER_IDS means nobody, never "empty means allow".
        return None, _legacy(403, "无权访问")
    return user_id, None


async def _payload(request: Request) -> Any:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001 - wrong content type / empty body
        data = None
    if isinstance(data, dict):
        return data
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001
        return None
    return dict(form) if form else None


def _service(request: Request) -> AnticheatService:
    return AnticheatService(request.app.state.database)


@router.get("/api/admin/suspicion")
def admin_suspicion_list(request: Request):
    _actor, error = _admin_guard(request)
    if error is not None:
        return error
    try:
        limit = int(request.query_params.get("limit") or 200)
    except (TypeError, ValueError):
        limit = 200
    limit = max(1, min(limit, 2000))
    return JSONResponse({"success": True, **_service(request).suspicion_overview(limit)})


@router.get("/api/admin/player/{uid}")
def admin_player_detail(uid: str, request: Request):
    _actor, error = _admin_guard(request)
    if error is not None:
        return error
    if not uid:
        return _legacy(400, "缺少用户 ID")
    return JSONResponse({"success": True, "player": _service(request).player_report(uid)})


@router.post("/api/admin/player/{uid}/override")
async def admin_player_override(uid: str, request: Request):
    actor, error = _admin_guard(request)
    if error is not None:
        return error
    if not uid:
        return _legacy(400, "缺少用户 ID")
    payload = await _payload(request)
    if not isinstance(payload, dict):
        return _legacy(400, "请求体必须是 JSON 对象")

    cleared = bool(payload.get("cleared"))
    level = payload.get("level")
    reason = str(payload.get("reason") or "").strip()[:500]
    try:
        report = _service(request).set_override(
            uid, actor=str(actor), level=level, cleared=cleared, reason=reason
        )
    except ValueError as exc:
        return _legacy(400, str(exc))
    return JSONResponse({"success": True, "player": report})


@router.get("/api/admin/player/{uid}/history")
def admin_player_history(uid: str, request: Request):
    _actor, error = _admin_guard(request)
    if error is not None:
        return error
    rows = _service(request).override_history(uid, limit=100)
    return JSONResponse({
        "success": True,
        "history": [
            {
                "level": row.get("level"),
                "cleared": bool(row.get("cleared")),
                "reason": row.get("reason"),
                "actor": row.get("actor"),
                "created_at": row.get("created_at"),
            }
            for row in rows
        ],
    })
