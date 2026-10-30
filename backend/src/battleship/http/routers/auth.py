"""Login / register / logout and the auth-owned JSON endpoints.

The legacy frontend posts HTML forms to /login and /register and expects a 302
with a flash message in the returned page; it also calls /api/login for a token.
Both shapes are preserved. JSON bodies on /login and /register are accepted for
the new client and produce the structured field+reason errors required by the
rewrite, without adding new route names (the 49-route list is frozen).

CSRF: SameSite=Lax on the signed session cookie is the mitigation, per D13. There
is no token field and no origin check, because the legacy frontend has no token.
"""

from __future__ import annotations

import html
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from ...infra.ratelimit import client_key
from ...services.auth import AuthError, AuthService
from ..deps import get_auth_service, require_user
from ..errors import api_error, from_auth_error
from ..session import (
    SESSION_USERNAME,
    SESSION_USER_ID,
    flash,
    read_session,
    session_user_id,
    write_session,
)

router = APIRouter(tags=["auth"], include_in_schema=False)


# --------------------------------------------------------------------------- helpers


def _limiter(request: Request):
    return request.app.state.rate_limiter


def _rate_limited(request: Request, scope: str) -> bool:
    limiter = _limiter(request)
    return limiter.hit(scope, client_key(request)) if limiter is not None else False


async def _read_payload(request: Request) -> tuple[dict[str, Any], bool, bool]:
    """Return (payload, is_json, malformed_json)."""
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        try:
            data = await request.json()
        except Exception:
            return {}, True, True
        return (data if isinstance(data, dict) else {}), True, False
    try:
        form = await request.form()
    except Exception:
        return {}, False, True
    return {key: form.get(key) for key in form.keys()}, False, False


def _session_payload(identity: dict[str, str]) -> dict[str, str]:
    return {SESSION_USER_ID: str(identity["id"]), SESSION_USERNAME: str(identity["username"])}


def _json_with_session(content: Any, request: Request, data: dict[str, Any],
                       status_code: int = 200) -> JSONResponse:
    response = JSONResponse(content, status_code=status_code)
    write_session(response, request, data)
    return response


def _redirect_with_session(location: str, request: Request,
                           data: dict[str, Any], status_code: int = 302) -> Response:
    """Redirect with the legacy HTML self-redirect body.

    Flask's redirect() answers text/html with a tiny link page; the recorded
    contract stores that content type, so a bare 302 (empty body) is a visible
    difference even though browsers follow the Location header either way.
    """
    escaped = html.escape(location, quote=True)
    body = (
        "<!doctype html><html lang=en><title>Redirecting...</title>"
        f'<h1>Redirecting...</h1><p>You should be redirected automatically to the '
        f'target URL: <a href="{escaped}">{escaped}</a>. If not, click the link.'
    )
    response = HTMLResponse(body, status_code=status_code,
                            headers={"Location": location})
    write_session(response, request, data)
    return response


def _missing_field(name: str, message: str):
    raise api_error(400, "validation_error", message, name)


def _guard_login_fields(username: Any, password: Any) -> None:
    if not str(username or "").strip():
        _missing_field("username", "用户名不能为空")
    if not str(password or ""):
        _missing_field("password", "密码不能为空")


# ------------------------------------------------------------------------ pages


# Phase 5: the deleted panel used to render the HTML login page here. The SPA
# owns the login UI (StartScreen uses the JSON forms), so these frozen entry
# points redirect there; POSTs keep the legacy 302 + flash behaviour below.
@router.get("/login", response_class=RedirectResponse, include_in_schema=False)
def login_page() -> RedirectResponse:
    return RedirectResponse("/", status_code=302)


@router.get("/register", response_class=RedirectResponse, include_in_schema=False)
def register_page() -> RedirectResponse:
    return RedirectResponse("/", status_code=302)


@router.post("/login")
async def login(request: Request, service: AuthService = Depends(get_auth_service)):
    payload, is_json, malformed = await _read_payload(request)
    if _rate_limited(request, "login"):
        if is_json:
            raise api_error(429, "rate_limited", "操作过于频繁，请稍后再试")
        data = read_session(request)
        flash(data, "操作过于频繁，请稍后再试")
        return _redirect_with_session("/login", request, data)

    if malformed:
        raise api_error(400, "validation_error", "请求格式错误")
    username = payload.get("username")
    password = payload.get("password")
    if is_json:
        _guard_login_fields(username, password)
        identity = service.authenticate(username, password)
        if identity is None:
            raise api_error(401, "invalid_credentials", "用户名或密码错误")
        data = _session_payload(identity)
        return _json_with_session({"success": True, "user": identity}, request, data)

    if not str(username or "").strip() or not str(password or ""):
        data = read_session(request)
        flash(data, "用户名和密码不能为空")
        return _redirect_with_session("/login", request, data)
    identity = service.authenticate(username, password)
    if identity is None:
        data = read_session(request)
        flash(data, "用户名或密码错误")
        return _redirect_with_session("/login", request, data)
    data = _session_payload(identity)
    flash(data, "登录成功")
    return _redirect_with_session("/", request, data)


@router.post("/register")
async def register(request: Request, service: AuthService = Depends(get_auth_service)):
    payload, is_json, malformed = await _read_payload(request)
    if _rate_limited(request, "register"):
        if is_json:
            raise api_error(429, "rate_limited", "操作过于频繁，请稍后再试")
        data = read_session(request)
        flash(data, "操作过于频繁，请稍后再试")
        return _redirect_with_session("/register", request, data)

    if malformed:
        raise api_error(400, "validation_error", "请求格式错误")
    username = payload.get("username")
    password = payload.get("password")

    if is_json:
        try:
            identity = service.register(username, password)
        except AuthError as exc:
            raise from_auth_error(exc) from exc
        data = _session_payload(identity)
        return _json_with_session({"success": True, "user": identity}, request, data)

    try:
        identity = service.register(username, password)
    except AuthError as exc:
        data = read_session(request)
        flash(data, exc.message)
        return _redirect_with_session("/register", request, data)
    data = _session_payload(identity)
    flash(data, "注册成功")
    return _redirect_with_session("/", request, data)


@router.get("/logout")
def logout(request: Request) -> Response:
    data = read_session(request)
    data.pop(SESSION_USER_ID, None)
    data.pop(SESSION_USERNAME, None)
    flash(data, "已退出登录")
    return _redirect_with_session("/", request, data)


# ------------------------------------------------------------------------- JSON API


@router.post("/api/login")
async def api_login(request: Request, service: AuthService = Depends(get_auth_service)):
    # Frozen wire shape: the legacy client and the recorded contract expect
    # {"error": "<message>"} with the legacy status codes and messages.
    def legacy(status_code: int, message: str) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status_code)

    if _rate_limited(request, "api_login"):
        return legacy(429, "操作过于频繁，请稍后再试")
    payload, _is_json, malformed = await _read_payload(request)
    if malformed:
        return legacy(400, "请求格式错误")
    username = payload.get("username")
    password = payload.get("password")
    if not username or not password:
        return legacy(400, "用户名或密码不能为空")
    try:
        token = service.issue_token(username, password)
    except AuthError as exc:
        return legacy(exc.status_code, exc.message)
    return JSONResponse({"token": token})


@router.post("/api/change_password")
async def change_password(request: Request,
                          service: AuthService = Depends(get_auth_service)):
    payload, _is_json, malformed = await _read_payload(request)
    user_id = session_user_id(read_session(request))
    if malformed:
        raise api_error(400, "validation_error", "请求格式错误")
    if not user_id:
        return _legacy_error(401, "unauthorized", "未登录", "session")
    if _rate_limited(request, "change_password"):
        return _legacy_error(429, "rate_limited", "操作过于频繁，请稍后再试")
    try:
        service.change_password(user_id, payload.get("old_password"), payload.get("new_password"))
    except AuthError as exc:
        return _legacy_error(exc.status_code, exc.code, exc.message, exc.field)
    return JSONResponse({"success": True, "msg": "密码修改成功"})


def _legacy_error(status_code: int, code: str, message: str,
                  field: str | None = None) -> JSONResponse:
    """Legacy change_password reads success/msg; add the structured error too."""
    error: dict[str, Any] = {"code": code, "message": message}
    if field:
        error["field"] = field
    return JSONResponse(
        {"success": False, "msg": message, "error": error},
        status_code=status_code,
    )


# ---------------------------------------------------------------------------- admin


@router.get("/api/admin/me")
def admin_me(request: Request, service: AuthService = Depends(get_auth_service)):
    user_id = session_user_id(read_session(request))
    return JSONResponse({"success": True, "is_admin": service.is_admin(user_id)})


@router.get("/api/profile")
def profile(request: Request, user_id: str = Depends(require_user)):
    from ...services.profile import build_own_profile

    database = request.app.state.database
    body = build_own_profile(database, user_id)
    if body is None:
        raise api_error(401, "unauthorized", "账号不存在", "session")
    return JSONResponse({"profile": body})
