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

    database = request.app.state.database
    service = ProgressionService(database)
    with database.unit_of_work() as uow:
        rows = uow.stats.rank_leaderboard(limit=limit, offset=offset)
        # Ticket #43: the viewer's full-server position (1-based); 0 means the
        # account has no rank row yet, which the contract reports as null.
        my_rank = (uow.stats.rank_position(user_id) or None) if user_id else None
        briefs = uow.users.list_by_ids(
            [str(row.get("user_id") or "") for row in rows]
        )
        total = uow.stats.count_rank_at_least(0)
        # One pool query for the page, not one per captain row.
        pool_map: dict[str, int | None] = {}
        pool_size: int | None = None
        if any(int(row.get("points") or 0) >= ranks.CAPTAIN_FLOOR for row in rows):
            for entry in uow.stats.captains_ordered(limit=500):
                pool_map[str(entry.get("user_id"))] = entry.get("pool_position")
            pool_size = uow.stats.count_rank_at_least(ranks.CAPTAIN_FLOOR)

        leaderboard = []
        for index, row in enumerate(rows):
            user_id = str(row.get("user_id") or "")
            user = briefs.get(user_id)
            position = offset + index + 1
            captain_pool_rank = pool_map.get(user_id)
            is_admiral = ranks.is_admiral(row, captain_pool_rank, pool_size)
            entry = {
                "user_id": user_id,
                "username": str(getattr(user, "username", "") or ""),
                "avatar": str(getattr(user, "avatar", "") or ""),
                "points": int(row.get("points") or 0),
                "ranked_wins": int(row.get("ranked_wins") or 0),
                "ranked_losses": int(row.get("ranked_losses") or 0),
                "position": position,
            }
            entry.update(
                service.rank_view_for(
                    uow, user_id, server_rank=position,
                    captain_pool_rank=captain_pool_rank,
                    is_admiral=is_admiral,
                )
            )
            leaderboard.append(entry)

    return JSONResponse({
        "leaderboard": leaderboard,
        "total": int(total),
        "constants": ranks.constants(),
        "my_rank": my_rank,
    })
