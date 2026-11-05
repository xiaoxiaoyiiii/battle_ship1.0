"""公开玩家资料入口 /user_stats，服务端按隐私约定裁剪。

资料保留兼容字段名；战绩、常用卡、历史摘要与 rank_info 的权限过滤
均在服务端执行，直接请求接口也不能绕过前端隐藏设置。
段位、等级和徽章等投影由成长服务提供。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ...services.profile import public_stats
from ..session import read_session, session_user_id

router = APIRouter(tags=["stats"])


def _limit(raw: str | None) -> int:
    try:
        value = int(raw or 20)
    except (TypeError, ValueError):
        value = 20
    return max(1, min(value, 100))


@router.get("/user_stats")
def user_stats(request: Request):
    database = request.app.state.database
    viewer_id = session_user_id(read_session(request))
    username = request.query_params.get("username")

    with database.unit_of_work() as uow:
        if username:
            user = uow.users.get_by_username(username)
        else:
            if not viewer_id:
                return JSONResponse({"error": "未登录"}, status_code=401)
            user = uow.users.get(viewer_id)

    if user is None:
        # Legacy behavior: missing username is not a 404 (guests polling an
        # opponent should not produce console errors).
        return JSONResponse({"stats": None, "history": []})

    stats, history = public_stats(database, user, viewer_id, _limit(request.query_params.get("limit")))
    return JSONResponse({"stats": stats, "history": history})


@router.get("/api/card_usage")
def card_usage(request: Request):
    """Public lifetime card-use map (catalogue "how popular is this card")."""
    database = request.app.state.database
    with database.unit_of_work() as uow:
        usage = uow.stats.all_card_usage()
    return JSONResponse({"usage": usage, "total": sum(usage.values())})
