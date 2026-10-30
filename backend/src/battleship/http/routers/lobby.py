"""Lobby HTTP surface needed by ticket #14.

Only the routes this ticket's behaviour depends on: the online counter. The
remaining 48 legacy routes stay with ticket #19. Both routes read the single
presence table the lobby broadcasts from (CLAUDE #17) and share its counters
helper, so the home panel and lobby_state can never disagree.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ...domain.lobby.rules import lobby_counters
from ...infra.logging import get_logger

router = APIRouter(tags=["lobby"], include_in_schema=False)

logger = get_logger("http.lobby")


@router.get("/api/online_count")
def online_count(request: Request):
    presence = request.app.state.presence
    return JSONResponse({"online_count": presence.online_count()})


@router.get("/api/home_stats")
def home_stats(request: Request):
    """Read-only home panel aggregate: online / queue split / joinable rooms.

    Same sources and the same `lobby_counters` helper as lobby_state, and
    deliberately read-only: subscribing to the lobby just to show three numbers
    would add every home-screen visitor to the lobby member list. A failed read
    degrades to nulls (HTTP 200) because a decorative panel must not blank the
    home screen, but the reason is always logged (never a silent null).
    """
    try:
        rooms = request.app.state.rooms
        counters = lobby_counters(
            rooms.get_all_rooms().values(),
            request.app.state.presence.snapshot(),
            rooms.match_queue,
        )
        return JSONResponse({
            "online_count": counters.online_count,
            "queue": counters.queue,
            "lobby_rooms": counters.lobby_rooms,
        })
    except Exception as error:  # noqa: BLE001 - decorative panel must not 500
        logger.exception(
            "home_stats degraded to nulls: %s: %s", type(error).__name__, error
        )
        return JSONResponse({"online_count": None, "queue": None, "lobby_rooms": None})
