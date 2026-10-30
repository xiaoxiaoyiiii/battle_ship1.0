"""Pure lobby rules: names, chat text, player status and room visibility.

Ported from the legacy server.py lobby block (2026-09-18). Everything here is a
pure function over plain data so the socket adapter, the HTTP routes and the
tests share exactly one definition of each rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

#: Socket.IO room every lobby subscriber joins.
LOBBY_ROOM = "__lobby__"

#: A single lobby chat line is truncated (the legacy stack never rejects it).
LOBBY_CHAT_MAX_LEN = 120
#: Minimum seconds between two lines from the same connection.
LOBBY_CHAT_MIN_INTERVAL = 1.0
#: How many recent lines a new subscriber receives.
LOBBY_CHAT_BACKLOG = 30
#: Upper bound of the players list inside one lobby_state frame.
LOBBY_MAX_PLAYERS = 200
#: Fallback re-broadcast interval; only emits while somebody is in the lobby.
LOBBY_STATE_TICK_SECONDS = 4.0
#: Display-name length inside the lobby (the room-name limit is separate).
LOBBY_NAME_MAX_LEN = 24

STATUS_MATCHING = "matching"
STATUS_IN_GAME = "in_game"
STATUS_IN_ROOM = "in_room"
STATUS_IDLE = "idle"


def clean_name(name: Any, fallback: str = "游客") -> str:
    """Trim, truncate and fall back for every lobby name source.

    The legacy stack has three name sources (session / find_match payload /
    lobby subscribe payload); they must all be cleaned at the same entry point.
    """
    text = str(name or "").strip()
    if not text:
        return fallback
    return text[:LOBBY_NAME_MAX_LEN]


def chat_text(message: Any) -> str | None:
    """Normalise one public-chat line; None means "drop it silently"."""
    text = str(message or "").strip()[:LOBBY_CHAT_MAX_LEN]
    return text or None


def player_status(sid: str, *, in_game: set[str], in_room: set[str],
                  queued: set[str]) -> str:
    """One of matching / in_game / in_room / idle.

    Order matters: matching wins over in_game (a just-matched player is popped
    from the queue, so both are never true; checking the room first would show
    "idle" for the instant between matching and seating).
    """
    if sid in queued:
        return STATUS_MATCHING
    if sid in in_game:
        return STATUS_IN_GAME
    if sid in in_room:
        return STATUS_IN_ROOM
    return STATUS_IDLE


def room_state(room: Any) -> str:
    state = getattr(room, "state", None)
    return str(getattr(state, "value", state))


def rooms_by_socket(rooms: Iterable[Any]) -> tuple[set[str], set[str]]:
    """Split live socket ids into (really playing, only waiting in a room).

    A waiting host sits in their own room the moment they create it; counting
    that as "in a game" pins every host to "对局中" in the lobby.
    """
    in_game: set[str] = set()
    in_room: set[str] = set()
    for room in rooms:
        state = room_state(room)
        if state == "game_over":
            continue
        bucket = in_room if state == "waiting" else in_game
        for player in getattr(room, "players", {}).values():
            socket_id = getattr(player, "socket_id", None)
            if socket_id:
                bucket.add(socket_id)
    return in_game, in_room


@dataclass(frozen=True)
class LobbyCounters:
    """The home-panel counters, plus the joinable rows they were counted from.

    `lobby_state` and `GET /api/home_stats` both read these numbers; computing
    them here (once, from the same presence snapshot and the same match queue)
    is what keeps the two surfaces from disagreeing.
    """

    online_count: int
    queue: dict[str, int]
    joinable_rooms: list[dict[str, Any]]

    @property
    def lobby_rooms(self) -> int:
        return len(self.joinable_rooms)


def lobby_counters(
    rooms: Iterable[Any],
    presence_rows: dict[str, Any],
    queue: Iterable[Any],
) -> LobbyCounters:
    """Online / queue split / joinable rooms from one presence snapshot."""

    entries = list(queue)
    ranked = sum(1 for entry in entries if entry.get("mode") == "ranked")
    return LobbyCounters(
        online_count=len(presence_rows),
        queue={"casual": len(entries) - ranked, "ranked": ranked},
        joinable_rooms=visible_rooms(rooms, set(presence_rows)),
    )


def visible_rooms(rooms: Iterable[Any], online_sids: set[str]) -> list[dict[str, Any]]:
    """Waiting rooms a player can actually join.

    Rules (docs/LOBBY_2026_09_18.md section 1.4): waiting, not AI, public,
    exactly one seat, and that host's connection is still online. A second room
    from the same host is skipped defensively (one host may only hold one).
    """
    ordered = sorted(
        rooms,
        key=lambda room: getattr(room, "created_at", 0) or 0,
        reverse=True,
    )
    rows: list[dict[str, Any]] = []
    seen_hosts: set[str] = set()
    for room in ordered:
        if room_state(room) != "waiting":
            continue
        if getattr(room, "is_ai_room", False):
            continue
        if not bool(getattr(room, "public", True)):
            continue
        entries = list(getattr(room, "players", {}).items())
        if len(entries) != 1:
            continue
        host_key, host = entries[0]
        socket_id = getattr(host, "socket_id", None)
        if not socket_id or socket_id not in online_sids:
            continue
        if host_key in seen_hosts:
            continue
        seen_hosts.add(host_key)
        host_name = str(getattr(host, "name", "") or "")
        rows.append(
            {
                "room_id": room.id,
                "name": str(getattr(room, "name", "") or "") or f"{host_name}的房间",
                "host": host_name,
                "players": 1,
                "capacity": 2,
                "created_at": int(getattr(room, "created_at", 0) or 0),
            }
        )
    rows.sort(key=lambda row: row["created_at"])
    return rows
