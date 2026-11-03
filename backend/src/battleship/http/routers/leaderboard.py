"""Leaderboards (ticket #16): the wins board and the ranked board.

Both are public reads with the frozen legacy shapes:

* `/api/leaderboard` -> a bare array of accounts that have actually played,
  ordered wins DESC then longest_streak DESC, with name style and level
  projected from the progression module;
* `/api/ranked_leaderboard` -> `{leaderboard, total, constants, my_rank}`; only accounts
  with a `user_rank` row appear (a never-played account must not fill the tail
  with "二级水手Ⅰ 0分"), `position` is the full-server position, and every row's
  rank view comes from `domain.progression.ranks` -- the client never
  recomputes a tier or a label.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ...domain.progression import leveling, profile_spec, ranks
from ...services.progression import ProgressionService
from ..deps import get_current_user_id

router = APIRouter(tags=["leaderboard"])


def _int(raw: str | None, default: int) -> int:
    try:
        return int(raw if raw is not None else default)
    except (TypeError, ValueError):
        return default


@router.get("/api/leaderboard")
def wins_leaderboard(request: Request):
    """Wins board: a bare JSON array, only accounts that have played.

    Legacy shape (api.py `api_leaderboard`): id/username/wins/losses/
    current_streak/longest_streak/avatar plus the batch-projected name_style and
    level. Anonymous is allowed; `limit` is clamped to 1..100.
    """
    limit = max(1, min(_int(request.query_params.get("limit"), 100), 100))
    database = request.app.state.database
    with database.unit_of_work() as uow:
        rows = uow.users.leaderboard(limit)
        ids = [str(row.get("id") or "") for row in rows]
        perks = uow.stats.perks_for(ids)
        xps = uow.stats.xp_for(ids)
        for row in rows:
            user_id = str(row.get("id") or "")
            user_perks = perks.get(user_id, set())
            row["name_style"] = (
                "rainbow" if profile_spec.PERK_RAINBOW_NAME in user_perks else ""
            )
            cap = (
                leveling.LEVEL_101
                if profile_spec.PERK_LEVEL_101 in user_perks
                else leveling.MAX_LEVEL
            )
            row["level"] = leveling.level_view(int(xps.get(user_id, 0)), cap)["level"]
    return JSONResponse(rows)


@router.get("/api/ranked_leaderboard")
def ranked_leaderboard(
    request: Request,
    user_id: str | None = Depends(get_current_user_id),
):
    limit = max(1, min(_int(request.query_params.get("limit"), 100), 200))
    offset = max(0, _int(request.query_params.get("offset"), 0))

    from ...services.ranked_seasons import RankedSeasonService
    return JSONResponse(RankedSeasonService(request.app.state.database).leaderboard(
        request.query_params.get('season_id') or None, limit=limit, offset=offset, user_id=user_id))
