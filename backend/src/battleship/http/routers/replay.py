"""对局回放 HTTP 路由（ticket #18）。

只做协议适配：解析请求 -> 调 services.replays -> 返回**旧形状** JSON
({"success": bool, ...} / {"error": "..."})，因为这是线上录制契约
（DECISIONS D19：已录制路由的错误体保持旧形状）。

回放**只走 HTTP**：本模块不注册、不发送任何 socket 事件。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ...services.replays import (
    read_allow_replay,
    read_replay,
    save_allow_replay,
)
from ..session import read_session, session_user_id

router = APIRouter(tags=["replay"])


def _json(body: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(body, status_code=status)


async def _request_payload(request: Request) -> dict[str, Any] | None:
    """JSON body first, then form body (legacy accepted both)."""
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


@router.get("/api/replay/setting")
def get_replay_setting(request: Request):
    viewer_id = session_user_id(read_session(request))
    if not viewer_id:
        return _json({"success": False, "error": "未登录"}, 401)
    value = read_allow_replay(request.app.state.database, viewer_id)
    if value is None:
        # Unreadable => say "unknown", never lie that replay is allowed.
        return _json({"success": False, "error": "暂时无法读取设置，请稍后重试"}, 503)
    return _json({"success": True, "allow_replay": bool(value)})


@router.post("/api/replay/setting")
async def save_replay_setting(request: Request):
    viewer_id = session_user_id(read_session(request))
    if not viewer_id:
        return _json({"success": False, "error": "未登录"}, 401)

    database = request.app.state.database
    with database.unit_of_work() as uow:
        if uow.users.get(viewer_id) is None:
            return _json({"success": False, "error": "账号不存在"}, 401)

    payload = await _request_payload(request)
    if not isinstance(payload, dict) or "allow_replay" not in payload:
        return _json({"success": False, "error": "请求体必须带 allow_replay"}, 400)

    raw = payload.get("allow_replay")
    if isinstance(raw, bool):
        on = raw
    elif isinstance(raw, (int, str)) and str(raw) in ("0", "1"):
        on = str(raw) == "1"
    elif isinstance(raw, str) and raw.strip().lower() in ("true", "false", "on", "off"):
        on = raw.strip().lower() in ("true", "on")
    else:
        return _json({"success": False, "error": "allow_replay 必须是布尔值"}, 400)

    if not save_allow_replay(database, viewer_id, on):
        return _json({"success": False, "error": "保存失败，请稍后重试"}, 500)
    return _json({"success": True, "allow_replay": on})


@router.get("/api/replay/{match_id}")
def get_match_replay(match_id: str, request: Request):
    viewer_id = session_user_id(read_session(request))
    result = read_replay(request.app.state.database, match_id, viewer_id)
    return JSONResponse(result.body, status_code=result.status)
