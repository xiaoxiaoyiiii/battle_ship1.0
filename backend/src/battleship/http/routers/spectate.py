"""HTTP surface for the per-account spectate switch (ticket #17).

Frozen legacy shapes (port map 11 sections 19/20, DECISIONS D19):

* GET  /api/spectate/setting -> 200 {success, allow_spectate}
                               401 {success:false, error:"未登录"}
                               503 {success:false, error:"暂时无法读取设置，请稍后重试"}
* POST /api/spectate/setting -> 200 {success, allow_spectate}
                               400 missing field / bad type (with a reason)
                               401 not logged in / account missing
                               500 write failed

The switch is deliberately NOT part of the profile-card save: that route has
"whole row, missing keys reset to defaults" semantics, so folding this column
into it would silently turn the switch back on every time the card is saved.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..session import read_session, session_user_id

router = APIRouter(tags=["spectate"], include_in_schema=False)

NOT_LOGGED_IN = {"success": False, "error": "未登录"}


def _legacy(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"success": False, "error": message}, status_code=status_code)


def _coerce_bool(raw: Any) -> bool | None:
    """Legacy conversion table; None means "invalid" (never a silent default)."""

    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return None if str(raw) not in ("0", "1") else str(raw) == "1"
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in ("0", "1"):
            return text == "1"
        if text in ("true", "on"):
            return True
        if text in ("false", "off"):
            return False
    return None


async def _read_payload(request: Request) -> Any:
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        try:
            return await request.json()
        except Exception:  # noqa: BLE001 - malformed JSON is a 400 below
            return None
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001
        return None
    return {key: form.get(key) for key in form.keys()} if form else None


@router.get("/api/spectate/setting")
def get_spectate_setting(request: Request):
    user_id = session_user_id(read_session(request))
    if not user_id:
        return JSONResponse(NOT_LOGGED_IN, status_code=401)
    value = request.app.state.spectators.get_setting(user_id)
    if value is None:
        # Unknown must say so; reporting "allowed" would be a privacy lie.
        return _legacy(503, "暂时无法读取设置，请稍后重试")
    return JSONResponse({"success": True, "allow_spectate": bool(value)})


@router.post("/api/spectate/setting")
async def save_spectate_setting(request: Request):
    user_id = session_user_id(read_session(request))
    if not user_id:
        return JSONResponse(NOT_LOGGED_IN, status_code=401)
    spectators = request.app.state.spectators
    if not spectators.has_account(user_id):
        return _legacy(401, "账号不存在")

    payload = await _read_payload(request)
    if not isinstance(payload, dict) or "allow_spectate" not in payload:
        return _legacy(400, "请求体必须带 allow_spectate")
    allow = _coerce_bool(payload.get("allow_spectate"))
    if allow is None:
        return _legacy(400, "allow_spectate 必须是布尔值")
    if not spectators.set_setting(user_id, allow):
        return _legacy(500, "保存失败，请稍后重试")
    return JSONResponse({"success": True, "allow_spectate": allow})
