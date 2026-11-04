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
    # 人机任务仍可结算，账号统计另由 count_stats 保持原有模式边界。
    rewards_eligible: bool = False


def match_rewards_eligible(room: Room) -> bool:
    """正式开战且双方确已布船，才产生普通对局收益。"""
    if not room.match_started_at or len(room.players) != 2:
        return False
    # 此标记在双方初次布船完成时冻结，合法清盘、重摆不会抹掉参战事实。
    # 没有冻结标记的既有调用方可由棋盘或死亡舰记录证明双方已布船。
    return bool(room.ban_initial_placement_complete) or all(
        player.ships or player.sunken_ships or player.permanently_destroyed_ships
        for player in room.players.values()
    )


def settlement_facts(room: Room, winner_id: str, loser_id: str) -> SettlementFacts:
    winner: Player = room.players[winner_id]
    loser: Player = room.players[loser_id]
    rewards_eligible = match_rewards_eligible(room)
    return SettlementFacts(
        winner_id=winner_id,
        loser_id=loser_id,
        winner_user_id=getattr(winner, "user_id", None),
        loser_user_id=getattr(loser, "user_id", None),
        # AI matches still write history, but never touch account stats
        # (otherwise beating the computer farms wins/streaks/achievements).
        count_stats=rewards_eligible and not room.is_ai_room,
        mode=match_history_mode(room),
        duration_seconds=match_duration_seconds(room),
        winner_sunk=dead_ship_count(loser),
        loser_sunk=dead_ship_count(winner),
        winner_flawless=not took_any_damage(winner),
        rewards_eligible=rewards_eligible,
    )
