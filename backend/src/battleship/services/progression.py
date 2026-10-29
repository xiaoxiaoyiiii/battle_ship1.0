"""Progression use cases: rank / level / badges / looks (ticket #15).

Rules are single-sourced in battleship.domain.progression; this module only
assembles database facts, writes settlement outcomes through the #5 UnitOfWork and
produces the wire payloads the legacy server emitted. No SQL lives here.

Settlement wiring is deliberately two hooks:

* a read-only pre-hook captures the **pre-match** streak/tier facts before the
  core settlement rows are written (legacy ordering: reading after the write
  silently turns "first win" into a 1-win streak);
* the regular hook runs inside the #9 transaction and writes XP, rank points and
  badge unlocks. Its frames are returned on SettlementResult so BattleService can
  preserve the legacy order (xp/badges before game_over, rank_changed after).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..domain.progression import achievements, leveling, profile_spec, ranks
from ..domain.room import Room
from ..repositories import Database, UnitOfWork
from .settlement import SettlementContext, SettlementFacts, SettlementService

_CARD_DATA = Path(__file__).resolve().parents[1] / "domain" / "magic" / "data" / "magic_card.json"


@lru_cache(maxsize=1)
def card_speeds() -> dict[str, int]:
    """Card name -> speed, read from the frozen card table (not a second rule)."""

    try:
        data = json.loads(_CARD_DATA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    speeds: dict[str, int] = {}
    for card in data if isinstance(data, list) else ():
        if isinstance(card, dict) and card.get("name"):
            try:
                speeds[str(card["name"])] = int(card.get("speed") or 0)
            except (TypeError, ValueError):
                speeds[str(card["name"])] = 0
    return speeds


class ProgressionService:
    def __init__(self, database: Database | None = None) -> None:
        self.database = database

    # --------------------------------------------------------------- wiring

    def register(self, settlement: SettlementService) -> None:
        settlement.add_pre_hook(self.collect_pre_facts)
        settlement.add_hook(self.apply_settlement)

    # ---------------------------------------------------------- settlement

    def collect_pre_facts(self, room: Room, facts: SettlementFacts) -> dict[str, Any]:
        """Read-only: pre-match streak and tier facts (must run before writes)."""

        ctx: dict[str, Any] = {
            "win_streak_before": 0,
            "winner_loss_streak_before": 0,
            "lose_streak_before": 0,
            "winner_tier": 0,
            "loser_tier": 0,
            "seconds": int(facts.duration_seconds or 0),
            "rounds": max(0, int(getattr(room, "round", 0) or 0)),
        }
        if self.database is None or not facts.count_stats:
            return ctx
        with self.database.unit_of_work() as uow:
            winner = uow.users.get(facts.winner_user_id)
            if winner is not None:
                ctx["win_streak_before"] = max(0, int(winner.current_streak or 0))
            ctx["winner_loss_streak_before"] = uow.matches.consecutive_losses(
                facts.winner_user_id
            )
            ctx["lose_streak_before"] = uow.matches.consecutive_losses(
                facts.loser_user_id
            )
            ctx["winner_tier"] = self._tier_of(uow, facts.winner_user_id)
            ctx["loser_tier"] = self._tier_of(uow, facts.loser_user_id)
        return ctx

    def apply_settlement(self, room: Room, uow: UnitOfWork,
                         context: SettlementContext) -> None:
        facts = context.facts
        if not facts.count_stats:
            return

        winner_socket = self._socket_id(room, facts.winner_id)
        loser_socket = self._socket_id(room, facts.loser_id)
        # Legacy order: badges are granted before XP (both before game_over).
        for player_id, user_id, socket_id in (
            (facts.winner_id, facts.winner_user_id, winner_socket),
            (facts.loser_id, facts.loser_user_id, loser_socket),
        ):
            if user_id:
                self._grant_badges(
                    uow, context, room, player_id, user_id, socket_id
                )

        if facts.winner_user_id:
            self._grant_xp(
                uow, context, facts.winner_user_id, winner_socket,
                win=True, sunk=facts.winner_sunk, flawless=facts.winner_flawless,
                fast=0 < int(facts.duration_seconds or 0) <= 180,
            )
        if facts.loser_user_id:
            self._grant_xp(
                uow, context, facts.loser_user_id, loser_socket,
                win=False, sunk=facts.loser_sunk, flawless=False, fast=False,
            )

        # Ticket #16 fills the missing gate: an anti-cheat-blocked match still
        # settles wins/XP/badges, but must never move rank points (legacy
        # _finalize_match checked ac_result.blocked around _settle_ranked_match).
        if (
            bool(getattr(room, "ranked", False))
            and bool(getattr(room, "match_started_at", None))
            and not bool(getattr(context, "blocked", False))
        ):
            self._settle_rank(uow, context, room, facts)

    @staticmethod
    def _socket_id(room: Room, player_id: str) -> str | None:
        player = room.players.get(player_id)
        return getattr(player, "socket_id", None) if player is not None else None

    @staticmethod
    def _player_name(room: Room, player_id: str) -> str:
        player = room.players.get(player_id)
        return (getattr(player, "name", None) or "玩家") if player else "玩家"

    def _grant_xp(self, uow: UnitOfWork, context: SettlementContext, user_id: str,
                  socket_id: str | None, *, win: bool, sunk: int, flawless: bool,
                  fast: bool) -> None:
        cap = self.level_cap(uow, user_id)
        before = uow.stats.get_xp(user_id)
        delta = leveling.match_xp(win, sunk=sunk, flawless=flawless, fast=fast)
        after = uow.stats.add_xp(user_id, delta, now=context.timestamp)
        if not socket_id:
            return
        context.events.append({
            "phase": "before",
            "event": "xp_gained",
            "to": socket_id,
            "data": {
                "player_id": self._player_id_for_user(context, user_id),
                "delta": int(max(0, after - before)),
                "xp_before": int(before),
                "xp_after": int(after),
                "win": bool(win),
                "breakdown": leveling.xp_breakdown(
                    win, sunk=sunk, flawless=flawless, fast=fast
                ),
                "before": leveling.level_view(before, cap),
                "after": leveling.level_view(after, cap),
                "segments": leveling.segments(before, after, cap),
            },
        })

    @staticmethod
    def _player_id_for_user(context: SettlementContext, user_id: str) -> str:
        facts = context.facts
        if user_id == facts.winner_user_id:
            return facts.winner_id
        if user_id == facts.loser_user_id:
            return facts.loser_id
        return user_id

    def _grant_badges(self, uow: UnitOfWork, context: SettlementContext, room: Room,
                      player_id: str, user_id: str, socket_id: str | None) -> None:
        stats = self.achievement_stats(uow, user_id)
        already = {row["badge_id"] for row in uow.stats.list_achievements(user_id)}
        candidates = achievements.evaluate(stats)
        granted: list[str] = []
        for badge in achievements.BADGES:
            badge_id = badge["id"]
            if badge_id in already or badge_id not in candidates:
                continue
            if uow.stats.unlock_achievement(
                user_id, badge_id, unlocked_at=context.timestamp
            ):
                granted.append(badge_id)
        if not granted:
            return
        items = [item for item in (achievements.details(bid) for bid in granted) if item]
        names = "、".join(achievements.name_of(bid) or bid for bid in granted)
        context.events.append({
            "phase": "before",
            "event": "message",
            "room": room.id,
            "data": {
                "text": f"{self._player_name(room, player_id)} 解锁了新徽章：{names}"
            },
        })
        if socket_id and items:
            context.events.append({
                "phase": "before",
                "event": "achievements_unlocked",
                "to": socket_id,
                "data": {"items": items, "count": len(items)},
            })

    def _settle_rank(self, uow: UnitOfWork, context: SettlementContext, room: Room,
                     facts: SettlementFacts) -> None:
        pre = context.pre or {}
        seconds = int(pre.get("seconds", facts.duration_seconds) or 0)
        rounds = max(0, int(pre.get("rounds", getattr(room, "round", 0)) or 0))
        tiers = {
            facts.winner_id: int(pre.get("winner_tier") or 0),
            facts.loser_id: int(pre.get("loser_tier") or 0),
        }

        rows: list[dict[str, Any]] = []
        for player_id, is_winner in ((facts.winner_id, True), (facts.loser_id, False)):
            player = room.players.get(player_id)
            user_id = getattr(player, "user_id", None) if player else None
            if not user_id:
                continue
            foe_id = facts.loser_id if is_winner else facts.winner_id
            sunk = facts.winner_sunk if is_winner else facts.loser_sunk
            lost = facts.loser_sunk if is_winner else facts.winner_sunk
            factors = {
                "win_streak": (
                    max(0, int(pre.get("win_streak_before") or 0)) + 1
                ) if is_winner else 0,
                "lose_streak": (
                    max(0, int(pre.get("lose_streak_before") or 0)) + 1
                ) if not is_winner else 0,
                "loss_streak_broken": (
                    max(0, int(pre.get("winner_loss_streak_before") or 0))
                ) if is_winner else 0,
                "seconds": seconds,
                "rounds": rounds,
                "sunk": sunk,
                "lost": lost,
                "my_tier": tiers.get(player_id, 0),
                "opp_tier": tiers.get(foe_id, 0),
            }
            base, bonuses, total = ranks.points_breakdown(bool(is_winner), **factors)
            before_row = uow.stats.get_rank(user_id)
            before_points = int(before_row.get("points") or 0)
            _predicted, clamped = ranks.apply_delta(before_points, int(total))
            uow.stats.add_rank_points(user_id, int(total), now=context.timestamp)
            # Legacy reads the "before" server rank *after* this seat's write
            # (server.py:5229 then :5237), so the first ranked match shows 1/2
            # instead of 0/0. Keep the same order; before_points is still the
            # pre-match value used by the view.
            before_server_rank = uow.stats.rank_position(user_id)
            rows.append({
                "player": player,
                "player_id": player_id,
                "uid": user_id,
                "is_winner": bool(is_winner),
                "clamped": bool(clamped),
                "before_points": before_points,
                "before_admiral": bool(before_row.get("is_admiral")),
                "before_server_rank": before_server_rank,
                "base": int(base),
                "bonuses": bonuses,
                "breakdown_total": int(total),
            })

        if not rows:
            return

        pool_size = uow.stats.count_rank_at_least(ranks.CAPTAIN_FLOOR)
        pool_positions = {
            str(item.get("user_id")): item.get("pool_position")
            for item in uow.stats.captains_ordered(limit=500)
        }

        for row in rows:
            uid = row["uid"]
            pool_position = pool_positions.get(str(uid))
            after_row = uow.stats.get_rank(uid)
            after_points = int(after_row.get("points") or 0)
            ok, admiral_reason = ranks.can_promote_to_admiral(
                after_points, pool_position, pool_size
            )
            admiral_promoted = bool(ok) and not row["before_admiral"]
            admiral_demoted = bool(row["before_admiral"]) and not ok
            if ok:
                uow.stats.add_rank_points(uid, 0, is_admiral=True,
                                          now=context.timestamp)
            elif row["before_admiral"] and not ranks.ADMIRAL_STICKY:
                uow.stats.add_rank_points(uid, 0, is_admiral=False,
                                          now=context.timestamp)

            final_row = uow.stats.get_rank(uid)
            after_points = int(final_row.get("points") or 0)
            after_admiral = bool(final_row.get("is_admiral"))
            server_rank = uow.stats.rank_position(uid)
            summary = ranks.solve_delta(row["before_points"], after_points)
            before_view = ranks.rank_view(
                row["before_points"], is_admiral=row["before_admiral"],
                server_rank=row["before_server_rank"],
                captain_pool_rank=pool_position,
            )
            after_view = ranks.rank_view(
                after_points, is_admiral=after_admiral,
                server_rank=server_rank, captain_pool_rank=pool_position,
            )
            socket_id = getattr(row["player"], "socket_id", None)
            if not socket_id:
                continue
            context.events.append({
                "phase": "after",
                "event": "rank_changed",
                "to": socket_id,
                "data": {
                    "role": "winner" if row["is_winner"] else "loser",
                    "delta": int(after_points - row["before_points"]),
                    "clamped": row["clamped"],
                    "points_before": int(row["before_points"]),
                    "points_after": int(after_points),
                    "before": before_view,
                    "after": after_view,
                    "promoted": bool(summary["promoted"]),
                    "demoted": bool(summary["demoted"]),
                    "tier_up": bool(summary["tier_up"]),
                    "tier_down": bool(summary["tier_down"]),
                    "admiral_promoted": admiral_promoted,
                    "admiral_demoted": admiral_demoted,
                    "admiral_reason": admiral_reason,
                    "base": int(row["base"]),
                    "bonuses": [dict(item) for item in row["bonuses"]],
                    "breakdown_total": int(row["breakdown_total"]),
                    "segments": ranks.segments(
                        row["before_points"], after_points
                    ),
                },
            })

    # ------------------------------------------------------------- projections

    @staticmethod
    def _tier_of(uow: UnitOfWork, user_id: str | None) -> int:
        if not user_id:
            return 0
        return ranks.points_tier_index(uow.stats.get_rank(user_id).get("points") or 0)

    def unlock_stats(self, uow: UnitOfWork, user_id: str,
                     user: Any = None) -> dict[str, Any]:
        """Inputs for profile_spec unlock checks (one assembly point)."""

        user = user if user is not None else uow.users.get(user_id)
        stats: dict[str, Any] = {
            key: getattr(user, key, None)
            for key in ("wins", "losses", "longest_streak", "current_streak", "created_at")
        }
        stats["card_uses_total"] = uow.stats.card_uses_total(user_id)
        stats["rank_tier"] = self._tier_of(uow, user_id)
        stats["battle_pass_rewards"] = {
            f"{kind}:{reward_id}"
            for kind, reward_id in uow.battle_pass.cosmetic_rewards(user_id)
        }
        if profile_spec.PERK_UNLOCK_ALL in uow.stats.list_perks(user_id):
            stats[profile_spec.UNLOCK_ALL_FLAG] = True
        return stats

    def achievement_stats(self, uow: UnitOfWork, user_id: str,
                          user: Any = None, rank: Any = None) -> dict[str, Any]:
        """The single assembly used by settlement and by both profile views."""

        user = user if user is not None else uow.users.get(user_id)
        stats: dict[str, Any] = {
            key: getattr(user, key, None)
            for key in ("wins", "losses", "longest_streak", "created_at")
        }
        counters = uow.stats.get_counters(user_id)
        stats.update({
            "matches_played": counters.get("matches_played"),
            "sunk_total": counters.get("sunk_total"),
            "flawless_wins": counters.get("flawless_wins"),
            "fastest_win_sec": counters.get("fastest_win_sec"),
            "card_uses_total": uow.stats.card_uses_total(user_id),
            "distinct_cards": uow.stats.distinct_cards_used(user_id),
            "rank": rank if rank is not None else uow.users.wins_rank(user_id),
        })
        return stats

    def badge_view(self, uow: UnitOfWork, user_id: str, user: Any = None,
                   rank: Any = None, *, unlocked_only: bool = False
                   ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        stats = self.achievement_stats(uow, user_id, user=user, rank=rank)
        unlocked = {
            row["badge_id"]: row["unlocked_at"]
            for row in uow.stats.list_achievements(user_id)
        }
        items = achievements.catalog(stats, unlocked)
        count = achievements.count_unlocked(items)
        if unlocked_only:
            items = achievements.unlocked_only(items)
        return items, count

    def level_cap(self, uow: UnitOfWork, user_id: str | None) -> int:
        if not user_id:
            return leveling.MAX_LEVEL
        perks = uow.stats.list_perks(user_id)
        return leveling.LEVEL_101 if profile_spec.PERK_LEVEL_101 in perks else leveling.MAX_LEVEL

    def level_view_for(self, uow: UnitOfWork, user_id: str, xp: int | None = None) -> dict[str, Any]:
        if xp is None:
            xp = uow.stats.get_xp(user_id)
        return leveling.level_view(xp, self.level_cap(uow, user_id))

    def rank_view_for(self, uow: UnitOfWork, user_id: str,
                      server_rank: int | None = None,
                      captain_pool_rank: int | None = None,
                      is_admiral: bool | None = None) -> dict[str, Any]:
        row = uow.stats.get_rank(user_id)
        points = ranks.normalize_points(row.get("points"))
        if server_rank is None:
            server_rank = uow.stats.rank_position(user_id) or None
        if captain_pool_rank is None and points >= ranks.CAPTAIN_FLOOR:
            for entry in uow.stats.captains_ordered(limit=500):
                if str(entry.get("user_id")) == str(user_id):
                    captain_pool_rank = entry.get("pool_position")
                    break
        if is_admiral is None:
            if points < ranks.CAPTAIN_FLOOR:
                is_admiral = False
            else:
                pool_size = uow.stats.count_rank_at_least(ranks.CAPTAIN_FLOOR)
                is_admiral = bool(ranks.is_admiral(row, captain_pool_rank, pool_size))
        return ranks.rank_view(
            points, is_admiral=bool(is_admiral), server_rank=server_rank,
            captain_pool_rank=captain_pool_rank,
        )

    def name_style(self, uow: UnitOfWork, user_id: str | None) -> str:
        if not user_id:
            return ""
        return "rainbow" if profile_spec.PERK_RAINBOW_NAME in uow.stats.list_perks(user_id) else ""

    def fav_cards(self, uow: UnitOfWork, user_id: str, limit: int = 3) -> list[dict[str, Any]]:
        speeds = card_speeds()
        result = []
        for row in uow.stats.top_user_cards(user_id, limit):
            name = str(row.get("card_name") or "")
            result.append({
                "name": name,
                "speed": speeds.get(name, 0),
                "uses": int(row.get("uses") or 0),
            })
        return result

    def unlock_catalog(self, uow: UnitOfWork, user_id: str, user: Any = None) -> dict[str, Any]:
        return profile_spec.catalog(self.unlock_stats(uow, user_id, user=user))
