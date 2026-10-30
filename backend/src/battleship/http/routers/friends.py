"""Friends / direct-message HTTP routes (ticket #14).

The wire shapes are frozen legacy ones (DECISIONS D19): bare {"error": ...} for
401 and {"success": false, "error": ...} for parameter/account failures, and the
friends-specific business rejections stay HTTP 200 with a status/error body.
Only the routes this ticket needs are registered; the full 49-route sweep is
ticket #19.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..session import read_session, session_user_id

router = APIRouter(tags=["friends"], include_in_schema=False)


def _service(request: Request):
    return request.app.state.friends


def _user_id(request: Request) -> str | None:
    return session_user_id(read_session(request))


def _unauthorized() -> JSONResponse:
    # Literal legacy body (D19): no structured error object here.
    return JSONResponse({"error": "未登录"}, status_code=401)


async def _payload(request: Request) -> dict[str, Any]:
    """JSON first, then form, exactly like the legacy _get_json_payload."""
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception:
            return {}
        return body if isinstance(body, dict) else {}
    try:
        form = await request.form()
    except Exception:
        return {}
    return {key: form.get(key) for key in form.keys()}


def _reply(result: tuple[int, dict[str, Any]]) -> JSONResponse:
    status, body = result
    return JSONResponse(body, status_code=status)


@router.get("/api/friends")
async def friends_list(request: Request):
    user_id = _user_id(request)
    if not user_id:
        return _unauthorized()
    return _reply(await _service(request).list_friends(user_id))


@router.post("/api/friends/request")
async def friend_request(request: Request):
    user_id = _user_id(request)
    if not user_id:
        return _unauthorized()
    return _reply(await _service(request).request(user_id, await _payload(request)))


@router.post("/api/friends/respond")
async def friend_respond(request: Request):
    user_id = _user_id(request)
    if not user_id:
        return _unauthorized()
    return _reply(await _service(request).respond(user_id, await _payload(request)))


@router.post("/api/friends/remove")
async def friend_remove(request: Request):
    user_id = _user_id(request)
    if not user_id:
        return _unauthorized()
    return _reply(await _service(request).remove(user_id, await _payload(request)))


@router.post("/api/friends/block")
async def friend_block(request: Request):
    user_id = _user_id(request)
    if not user_id:
        return _unauthorized()
    return _reply(await _service(request).block(user_id, await _payload(request)))


@router.post("/api/friends/invite")
async def friend_invite(request: Request):
    user_id = _user_id(request)
    if not user_id:
        return _unauthorized()
    return _reply(await _service(request).invite(user_id, await _payload(request)))


@router.get("/api/friends/messages")
async def friend_messages(request: Request):
    user_id = _user_id(request)
    if not user_id:
        return _unauthorized()
    params = request.query_params
    return _reply(
        await _service(request).list_messages(
            user_id, params.get("username"), params.get("limit"), params.get("before")
        )
    )


@router.post("/api/friends/messages")
async def friend_message_send(request: Request):
    user_id = _user_id(request)
    if not user_id:
        return _unauthorized()
    return _reply(await _service(request).send_message(user_id, await _payload(request)))


@router.post("/api/friends/messages/read")
async def friend_messages_read(request: Request):
    user_id = _user_id(request)
    if not user_id:
        return _unauthorized()
    return _reply(await _service(request).mark_read(user_id, await _payload(request)))
