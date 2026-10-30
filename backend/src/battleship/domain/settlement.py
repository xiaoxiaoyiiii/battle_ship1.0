"""Match settlement facts and the history-mode axis (ticket #9).

Settlement is the single ending funnel: attack wipe, surrender, disconnect
forfeit, magic-card wipe and last-stand all call the same service. This module
holds only pure facts; persistence and the transaction boundary live in
battleship.services.settlement and the repository layer.

Legacy evidence: port map 13-domain-rules section 7; server.py _match_history_mode,
_count_stats_for, _dead_ship_count, _took_any_damage, _match_duration_sec.
"""

from __future__ import annotations

from dataclasses import dataclass

from .battle import dead_ship_count, match_duration_seconds, took_any_damage
from .room import Player, Room

MATCH_HISTORY_MODES: tuple[str, ...] = ("ranked", "casual", "ai", "custom")


def match_history_mode(room: Room | None) -> str | None:
    """This match's history mode, or None when the room is unknown.

    Priority (same as legacy): AI room -> ai; ranked -> ranked; not matchmade
    -> custom; otherwise casual. Unknown must stay None instead of degrading
    into "casual" (the old DB column is nullable for exactly this reason).
    """

    if room is None:
        return None
    if room.is_ai_room:
        return "ai"
    if bool(room.ranked):
        return "ranked"
    if not room.matchmade:
        return "custom"
    return "casual"


@dataclass(frozen=True)
class SettlementFacts:
    """Facts captured once, before any write, for the transaction and hooks."""

    winner_id: str
    loser_id: str
    winner_user_id: str | None
    loser_user_id: str | None
    count_stats: bool
    mode: str | None
    duration_seconds: int
    winner_sunk: int
    loser_sunk: int
    winner_flawless: bool


def settlement_facts(room: Room, winner_id: str, loser_id: str) -> SettlementFacts:
    winner: Player = room.players[winner_id]
    loser: Player = room.players[loser_id]
    return SettlementFacts(
        winner_id=winner_id,
        loser_id=loser_id,
        winner_user_id=getattr(winner, "user_id", None),
        loser_user_id=getattr(loser, "user_id", None),
        # AI matches still write history, but never touch account stats
        # (otherwise beating the computer farms wins/streaks/achievements).
        count_stats=not room.is_ai_room,
        mode=match_history_mode(room),
        duration_seconds=match_duration_seconds(room),
        winner_sunk=dead_ship_count(loser),
        loser_sunk=dead_ship_count(winner),
        winner_flawless=not took_any_damage(winner),
    )
