"""Per-seat AI difficulty resolution (single implementation).

Ticket #13 lesson #35: the room-level `ai_difficulty` is only the **default**.
Self-play measurement seats two AIs in one room, so every "is this seat the
master?" judgement must be able to answer **per seat** — otherwise the opponent
silently inherits the master card pool and the measured match is "master vs
master" (50% by construction).

`room.ai_difficulty_by_player` is the per-seat override the self-play driver
fills in. Both `is_master` and `difficulty_of` read it, and nothing else in the
backend may re-implement that lookup.
"""

from __future__ import annotations

from typing import Any

from ..room import AI_DIFFICULTIES

DEFAULT_DIFFICULTY = "normal"
AI_SEAT_PREFIX = "ai-"


def difficulty_of(room: Any, player_id: str | None) -> str:
    """The difficulty this **seat** actually plays at.

    Room-level `ai_difficulty` is the default (the only truth in a normal AI
    room); `ai_difficulty_by_player` overrides it seat by seat. Unknown or
    malformed values degrade to `normal` instead of leaking an invalid tier.
    """

    by_player = getattr(room, "ai_difficulty_by_player", None)
    key = str(player_id) if player_id is not None else None
    if key and isinstance(by_player, dict) and key in by_player:
        value = str(by_player.get(key) or DEFAULT_DIFFICULTY)
        return value if value in AI_DIFFICULTIES else DEFAULT_DIFFICULTY
    value = str(getattr(room, "ai_difficulty", DEFAULT_DIFFICULTY) or DEFAULT_DIFFICULTY)
    return value if value in AI_DIFFICULTIES else DEFAULT_DIFFICULTY


def is_master(room: Any, player_id: str | None) -> bool:
    """Whether **this seat** is the master tier (never "does the room have one")."""

    return difficulty_of(room, player_id) == "master"


def is_ai_seat(player_id: str | None) -> bool:
    """Whether this player id is a computer seat (`ai-<room_id>`)."""

    return str(player_id or "").startswith(AI_SEAT_PREFIX)


def ai_seat_id(room: Any) -> str | None:
    """The room's computer seat id, if any (legacy `_ai_player_id`)."""

    for player_id in getattr(room, "players", {}) or {}:
        if is_ai_seat(player_id):
            return str(player_id)
    return None


__all__ = [
    "AI_SEAT_PREFIX",
    "DEFAULT_DIFFICULTY",
    "ai_seat_id",
    "difficulty_of",
    "is_ai_seat",
    "is_master",
]
