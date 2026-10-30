"""Public player stats (/user_stats), scoped to the privacy contract.

Ticket #6 owns the privacy semantics exercised here. Rank/level/badge projections
are ticket #15's job; this route already returns the legacy field names and the
server-side history filter so "another user reads the endpoint directly" can be
verified without trusting the frontend.
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
