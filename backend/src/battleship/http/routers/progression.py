"""Achievement catalog and public rank constants (ticket #15)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ...domain.progression import ranks
from ...services.progression import ProgressionService
from ..session import read_session, session_user_id

router = APIRouter(tags=["progression"])


@router.get("/api/achievements")
def achievements_catalog(request: Request):
    database = request.app.state.database
    user_id = session_user_id(read_session(request))
    if not user_id:
        return JSONResponse({"error": "未登录"}, status_code=401)
    with database.unit_of_work() as uow:
        user = uow.users.get(user_id)
        if user is None:
            return JSONResponse({"error": "账号不存在"}, status_code=401)
        items, count = ProgressionService(database).badge_view(
            uow, user_id, user=user
        )
    return JSONResponse({"achievements": items, "badge_count": count})


@router.get("/api/rank_constants")
def rank_constants():
    # Public and read-only: the help page must open for anonymous visitors.
    # On failure return the legacy empty shell (HTTP 200), never a 500 and never
    # invented numbers.
    try:
        data = ranks.constants()
    except Exception:  # noqa: BLE001 - display-only endpoint must not 500
        return JSONResponse({"error": "段位规则暂不可用", "scoring": {}})
    if not isinstance(data, dict):
        return JSONResponse({"error": "段位规则暂不可用", "scoring": {}})
    return JSONResponse(data)
