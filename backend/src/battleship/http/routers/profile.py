"""Legacy profile-card save endpoint (ticket #15).

GET /api/profile is owned by the auth router; this router only adds the POST that
validates the 11 writable fields against the unlock rules. Error shapes are the
frozen legacy shapes (D19), not the structured rewrite envelope.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ...domain.social import guestbook
from ...infra.ratelimit import client_key
from ...services.guestbook import GuestbookService
from ...services.profile import save_profile_card, save_profile_effects
from ..session import read_session, session_user_id

router = APIRouter(tags=["profile"])

# Keep the legacy file formats and size cap while validating bytes and metadata.
AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
AVATAR_MAGIC_TYPES = (
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"GIF87a", "gif", "image/gif"),
    (b"GIF89a", "gif", "image/gif"),
)
MAX_AVATAR_SIZE = 2 * 1024 * 1024
MAX_AVATAR_ALT_LENGTH = 160


async def _payload(request: Request) -> Any:
    try:
        data = await request.json()
    except Exception:
        data = None
    if data is not None:
        return data
    try:
        form = await request.form()
    except Exception:
        return None
    return {key: form.get(key) for key in form.keys()} if form else None


@router.post("/api/profile/card")
async def save_card(request: Request):
    user_id = session_user_id(read_session(request))
    if not user_id:
        return JSONResponse({"success": False, "error": "未登录"}, status_code=401)
    payload = await _payload(request)
    status, body = save_profile_card(request.app.state.database, user_id, payload)
    return JSONResponse(body, status_code=status)


@router.post("/api/profile/effects")
async def save_effects(request: Request):
    """保存不影响旧名片契约的背景、指针特效和称号动效槽位。"""

    user_id = session_user_id(read_session(request))
    if not user_id:
        return JSONResponse({"success": False, "error": "未登录"}, status_code=401)
    payload = await _payload(request)
    status, body = save_profile_effects(request.app.state.database, user_id, payload)
    return JSONResponse(body, status_code=status)


# --------------------------------------------------------------------- helpers


def _legacy(status: int, message: str) -> JSONResponse:
    return JSONResponse({"success": False, "error": message}, status_code=status)


def _target(database, payload: Any) -> tuple[Any | None, JSONResponse | None]:
    """Resolve the target account by username; never silently succeed."""
    try:
        raw = payload.get("username") or ""
    except AttributeError:
        raw = ""
    username = str(raw).strip()
    if not username:
        return None, _legacy(400, "缺少 username 参数")
    with database.unit_of_work() as uow:
        user = uow.users.get_by_username(username)
    if user is None:
        return None, _legacy(404, f"账号不存在：{username}")
    return user, None


def _rate_limited(request: Request, scope: str) -> bool:
    limiter = request.app.state.rate_limiter
    return limiter.hit(scope, client_key(request)) if limiter is not None else False


# ---------------------------------------------------------------- signature


@router.post("/api/profile/signature")
async def update_signature(request: Request):
    user_id = session_user_id(read_session(request))
    if not user_id:
        return JSONResponse({"error": "未登录"}, status_code=401)
    # Legacy contract: form field only. A JSON body reads as "clear signature".
    form = await request.form()
    signature = str(form.get("signature") or "")
    with request.app.state.database.unit_of_work() as uow:
        ok = uow.users.update(user_id, signature=signature)
    return JSONResponse({"success": bool(ok)})


# -------------------------------------------------------------------- avatar


@router.post("/api/profile/avatar")
async def upload_avatar(request: Request):
    user_id = session_user_id(read_session(request))
    if not user_id:
        return JSONResponse({"error": "未登录"}, status_code=401)

    form = await request.form()
    upload = form.get("avatar")
    alt_text = _clean_avatar_alt(form.get("alt_text"))
    action = str(form.get("action") or "").strip().lower()
    remove = str(form.get("remove") or "").strip().lower() in {"1", "true", "yes", "on"}

    # Keep the frozen POST route while allowing the owner to remove an avatar
    # or update its alternative text without re-uploading the image.
    if action in {"delete", "remove"} or remove:
        return _remove_avatar(request, user_id)
    if upload is None:
        if "alt_text" not in form:
            return JSONResponse({"error": "未选择文件"}, status_code=400)
        with request.app.state.database.unit_of_work() as uow:
            user = uow.users.get(user_id)
            if user is None:
                return JSONResponse({"error": "账号不存在"}, status_code=401)
            profile = uow.social.save_profile(user_id, {"avatar_alt": alt_text})
        return JSONResponse({
            "success": True,
            "avatar": str(getattr(user, "avatar", "") or ""),
            "avatar_alt": str(profile.get("avatar_alt") or ""),
        })
    filename = str(getattr(upload, "filename", "") or "")
    if "." not in filename:
        return JSONResponse({"error": "文件类型不支持"}, status_code=400)
    extension = filename.rsplit(".", 1)[1].lower()
    if extension not in AVATAR_EXTENSIONS:
        return JSONResponse({"error": "文件类型不支持"}, status_code=400)

    data = await upload.read(MAX_AVATAR_SIZE + 1)
    if len(data) > MAX_AVATAR_SIZE:
        return JSONResponse({"error": "图片不能超过 2MB"}, status_code=400)
    detected = next((item for item in AVATAR_MAGIC_TYPES if data.startswith(item[0])), None)
    if detected is None:
        return JSONResponse({"error": "文件内容不是有效的图片"}, status_code=400)
    _, detected_extension, detected_mime = detected
    normalized_extension = "jpg" if extension == "jpeg" else extension
    if normalized_extension != detected_extension:
        return JSONResponse({"error": "文件扩展名与图片内容不匹配"}, status_code=400)
    content_type = str(getattr(upload, "content_type", "") or "").lower()
    if content_type and content_type != detected_mime:
        return JSONResponse({"error": "图片类型与文件内容不匹配"}, status_code=400)

    folder = request.app.state.assets.avatars_dir
    folder.mkdir(parents=True, exist_ok=True)
    stored_name = f"{user_id}_avatar.{detected_extension}"
    target = folder / stored_name
    temporary = folder / f".{user_id}_avatar.uploading"
    temporary.write_bytes(data)
    temporary.replace(target)
    avatar_url = f"/static/avatars/{stored_name}"
    with request.app.state.database.unit_of_work() as uow:
        ok = uow.users.update(user_id, avatar=avatar_url)
        profile = uow.social.save_profile(user_id, {"avatar_alt": alt_text})
    if not ok:
        target.unlink(missing_ok=True)
        return JSONResponse({"error": "头像保存失败"}, status_code=500)
    _remove_old_avatar_files(folder, user_id, keep=target)
    return JSONResponse({
        "success": True,
        "avatar": avatar_url,
        "avatar_alt": str(profile.get("avatar_alt") or ""),
    })


def _clean_avatar_alt(value: Any) -> str:
    """Keep alt text short and single-line; it is descriptive user content."""

    text = str(value or "").replace("\r", " ").replace("\n", " ")
    return " ".join(text.split())[:MAX_AVATAR_ALT_LENGTH]


def _remove_old_avatar_files(folder: Path, user_id: str, *, keep: Path | None = None) -> None:
    for candidate in folder.glob(f"{user_id}_avatar.*"):
        if keep is None or candidate != keep:
            candidate.unlink(missing_ok=True)


def _remove_avatar(request: Request, user_id: str) -> JSONResponse:
    folder = request.app.state.assets.avatars_dir
    with request.app.state.database.unit_of_work() as uow:
        user = uow.users.get(user_id)
        if user is None:
            return JSONResponse({"error": "账号不存在"}, status_code=401)
        ok = uow.users.update(user_id, avatar="")
        profile = uow.social.save_profile(user_id, {"avatar_alt": ""})
    if not ok:
        return JSONResponse({"error": "头像删除失败"}, status_code=500)
    _remove_old_avatar_files(folder, user_id)
    return JSONResponse({
        "success": True,
        "avatar": "",
        "avatar_alt": str(profile.get("avatar_alt") or ""),
    })


# --------------------------------------------------------------------- likes


@router.post("/api/profile/like")
async def profile_like(request: Request):
    user_id = session_user_id(read_session(request))
    if not user_id:
        return _legacy(401, "未登录")
    payload = await _payload(request)
    if payload is None:
        return _legacy(400, "请求体必须是 JSON 对象")

    database = request.app.state.database
    target, error = _target(database, payload)
    if error is not None:
        return error
    if str(target.id) == user_id:
        return _legacy(400, "不能给自己点赞或送花")

    kind = str(payload.get("kind") or "").strip()
    if kind not in guestbook.KINDS:
        return _legacy(400, 'kind 必须是 like/flower 之一')
    on = guestbook.reaction_on(payload.get("on", True))

    service = GuestbookService(database)
    service.set_reaction(user_id, str(target.id), kind, on)
    view = service.reaction_view(str(target.id), user_id)
    return JSONResponse({"success": True, **view})


# ----------------------------------------------------------------- guestbook


@router.get("/api/profile/messages")
def profile_messages(request: Request):
    user_id = session_user_id(read_session(request))
    if not user_id:
        return _legacy(401, "未登录")

    database = request.app.state.database
    target, error = _target(database, request.query_params)
    if error is not None:
        return error

    service = GuestbookService(database)
    page = service.page(
        str(target.id),
        user_id,
        limit=guestbook.page_size(request.query_params.get("limit")),
        before_id=guestbook.before_id(request.query_params.get("before_id")),
    )
    return JSONResponse({
        "success": True,
        "messages": page["messages"],
        "has_more": page["has_more"],
        "total": page["total"],
        "guestbook_private": page["guestbook_private"],
        "username": str(target.username or ""),
        "counts": page["counts"],
        "mine": page["mine"],
    })


@router.post("/api/profile/message")
async def post_profile_message(request: Request):
    user_id = session_user_id(read_session(request))
    if not user_id:
        return _legacy(401, "未登录")
    if _rate_limited(request, "profile_message"):
        return _legacy(429, "留言太频繁了，请稍后再试")

    payload = await _payload(request)
    if payload is None:
        return _legacy(400, "请求体必须是 JSON 对象")

    database = request.app.state.database
    target, error = _target(database, payload)
    if error is not None:
        return error
    if str(target.id) == user_id:
        return _legacy(400, "不能给自己留言")

    content = guestbook.clean_content(payload.get("content"))
    problem = guestbook.content_error(content)
    if problem:
        return _legacy(400, problem)

    service = GuestbookService(database)
    if service.count_today(user_id, str(target.id)) >= guestbook.DAILY_LIMIT:
        return _legacy(
            429,
            f"今天给同一个人最多留言 {guestbook.DAILY_LIMIT} 条，明天再来吧",
        )

    session_username = str(read_session(request).get("username") or "")
    with database.unit_of_work() as uow:
        author = uow.users.get(user_id)
    from_name = str(getattr(author, "username", "") or session_username or "匿名")
    created = service.add(str(target.id), user_id, from_name, content)
    if created is None:
        return _legacy(500, "留言失败，请稍后重试")
    return JSONResponse({
        "success": True,
        "message": guestbook.public_message(created, user_id, str(target.id)),
    })


@router.post("/api/profile/message/delete")
async def delete_profile_message(request: Request):
    user_id = session_user_id(read_session(request))
    if not user_id:
        return _legacy(401, "未登录")
    payload = await _payload(request)
    if payload is None:
        return _legacy(400, "请求体必须是 JSON 对象")
    try:
        message_id = int(payload.get("id"))
    except (TypeError, ValueError):
        return _legacy(400, "缺少有效的留言 id")

    status, body = GuestbookService(request.app.state.database).delete(message_id, user_id)
    return JSONResponse(body, status_code=status)
