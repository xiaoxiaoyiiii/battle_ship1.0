"""Anti-cheat use case (ticket #16): facts -> verdict -> persistence.

The rules live in `domain.anticheat.rules` (one definition, pure functions).
This service is the only place that:

* assembles facts from a **finished room** (server-side state only -- never the
  client and never by aligning a user id with a socket id, CLAUDE #20);
* exposes the verdict to settlement before the rank hook runs (the
  `blocked` flag on SettlementContext);
* writes the audit rows inside the #9 transaction: `anticheat_flags` for a
  suspicious match and one `match_suspicion` row per account for **every**
  match, including clean 0-score ones (CLAUDE #28: suspicion must survive match
  deletion, so it cannot be derived from `matches`).

A ban level is never stored: `AuthService` recomputes it from these rows plus
the latest admin override on every read (CLAUDE #27).
"""

from __future__ import annotations

import time
from typing import Any

from ..domain.anticheat import rules, suspicion
from ..domain.battle import match_duration_seconds
from ..domain.room import Room
from ..infra.logging import get_logger
from ..repositories import Database, UnitOfWork
from .settlement import SettlementContext, SettlementFacts, SettlementService

logger = get_logger("anticheat")

CLEAN_RESULT: dict[str, Any] = {
    "score": 0,
    "level": "clean",
    "reasons": [],
    "rules": [],
    "blocked": False,
}


class AnticheatService:
    def __init__(self, database: Database | None = None) -> None:
        self.database = database

    # --------------------------------------------------------------- wiring

    def register(self, settlement: SettlementService) -> None:
        """Must run before the progression hook: it supplies `blocked`."""
        settlement.add_pre_hook(self.collect_pre_facts)
        settlement.add_hook(self.apply_settlement)

    # ---------------------------------------------------------------- facts

    @staticmethod
    def facts_from_room(room: Room, winner_id: str, loser_id: str) -> dict[str, Any]:
        """Facts available from the room, mirroring the legacy assembly.

        Everything here is server-side match state. Missing values stay missing
        (the rules treat them as "unknown"), and any failure yields an empty dict
        so the verdict degrades to "clean" instead of breaking settlement.
        """
        facts: dict[str, Any] = {}
        try:
            winner = room.players.get(winner_id)
            loser = room.players.get(loser_id)

            def hits(player: Any) -> int:
                if player is None:
                    return 0
                total = 0
                for ship in getattr(player, "ships", None) or ():
                    total += len(getattr(ship, "hits", None) or ())
                return total

            winner_hits, loser_hits = hits(winner), hits(loser)
            facts["rounds"] = max(0, int(getattr(room, "round", 0) or 0))
            facts["attacker_total_hits"] = winner_hits
            facts["defender_total_hits"] = loser_hits
            facts["loser_total_hits"] = loser_hits

            # Shape feature, independent of id alignment: how many sides landed
            # a hit, and the largest single-side hit count.
            shooters = (1 if winner_hits > 0 else 0) + (1 if loser_hits > 0 else 0)
            facts["attackers"] = ["a"] * shooters if shooters else []
            facts["max_hits"] = max(winner_hits, loser_hits)

            winner_ships = len(getattr(winner, "ships", None) or ()) if winner else 0
            loser_ships = len(getattr(loser, "ships", None) or ()) if loser else 0
            facts["foe_ships"] = loser_ships
            facts["total_ships"] = winner_ships + loser_ships
            facts["duration_sec"] = match_duration_seconds(room)
            facts["ended_by"] = getattr(room, "game_over_reason", None) or "attacks"
        except Exception:
            pass
        return facts

    def evaluate_room(self, room: Room, winner_id: str, loser_id: str) -> dict[str, Any]:
        """Evaluate one finished match. Fails open, but always logs the failure."""
        try:
            return rules.evaluate(self.facts_from_room(room, winner_id, loser_id))
        except Exception as error:  # noqa: BLE001 - settlement must never break
            logger.error(
                "anti-cheat evaluation failed; treating match as clean",
                extra={"room_id": getattr(room, "id", None), "error_type": type(error).__name__},
                exc_info=error,
            )
            return dict(CLEAN_RESULT)

    # ------------------------------------------------------------- hooks

    def collect_pre_facts(self, room: Room, facts: SettlementFacts) -> dict[str, Any]:
        """Read-only veto input: computed before the transaction and the rank hook."""
        if not facts.count_stats:
            return {"anticheat": None, "anticheat_blocked": False}
        try:
            result = self.evaluate_room(room, facts.winner_id, facts.loser_id)
        except Exception as error:  # noqa: BLE001 - double fail-open guard
            logger.error(
                "anti-cheat pre-hook failed; treating match as clean",
                extra={"room_id": getattr(room, "id", None), "error_type": type(error).__name__},
                exc_info=error,
            )
            result = dict(CLEAN_RESULT)
        return {"anticheat": result, "anticheat_blocked": bool(result.get("blocked"))}

    def apply_settlement(self, room: Room, uow: UnitOfWork,
                         context: SettlementContext) -> None:
        facts = context.facts
        if not facts.count_stats:
            return
        result = (context.pre or {}).get("anticheat")
        if not isinstance(result, dict):
            return

        score = int(result.get("score") or 0)
        level = str(result.get("level") or "clean")
        if level != "clean":
            uow.stats.record_anticheat_flag(
                context.match_id,
                rule=",".join(result.get("rules") or [])[:400],
                severity=level[:32],
                detail=rules.explain(result)[:2000],
                created_at=context.timestamp,
            )

        # Both participants, every match (clean 0 included). The composite key
        # is the legacy '{match_id}:{user_id}' primary key; using the bare
        # match_id would make the second participant overwrite the first.
        for user_id in {facts.winner_user_id, facts.loser_user_id}:
            if not user_id:
                continue
            uow.stats.record_suspicion(
                match_id=f"{context.match_id}:{user_id}",
                user_id=user_id,
                score=score,
                level=level,
                created_at=context.timestamp,
            )

    # ------------------------------------------------------------- admin

    def report_for(self, user_id: str) -> dict[str, Any] | None:
        """Current suspicion report (derived level + audit facts)."""
        if not self.database or not user_id:
            return None
        with self.database.unit_of_work() as uow:
            user = uow.users.get(user_id)
            if user is None:
                return None
            rows = uow.stats.list_suspicions(user_id, limit=500)
            override = uow.stats.latest_override(user_id)
        now = time.time()
        matches = [
            {
                "score": row.get("score"),
                "age_days": suspicion.match_age_days(row.get("created_at"), now),
            }
            for row in rows
        ]
        return suspicion.build_report(
            user_id, matches, override=override,
            username=str(getattr(user, "username", "") or ""),
        )

    def override_history(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        if not self.database or not user_id:
            return []
        with self.database.unit_of_work() as uow:
            return uow.stats.list_overrides(user_id, limit=limit)

    def player_report(self, user_id: str) -> dict[str, Any]:
        """Full admin dossier: derived report + stats + flags + audit history."""
        with self.database.unit_of_work() as uow:
            user = uow.users.get(user_id)
            rows = uow.stats.list_suspicions(user_id, limit=2000)
            flags = uow.stats.list_anticheat_flags(500)
            overrides = uow.stats.list_overrides(user_id, limit=50)
            rank = uow.stats.get_rank(user_id)
        now = time.time()
        matches = [
            {
                "score": row.get("score"),
                "age_days": suspicion.match_age_days(row.get("created_at"), now),
            }
            for row in rows
        ]
        report = suspicion.build_report(
            user_id,
            matches,
            override=overrides[0] if overrides else None,
            username=str(getattr(user, "username", "") or "(已删除)"),
        )
        wins = int(getattr(user, "wins", 0) or 0)
        losses = int(getattr(user, "losses", 0) or 0)
        report["stats"] = {
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / (wins + losses), 3) if (wins + losses) else 0.0,
            "rank_points": int(rank.get("points") or 0),
            "ranked_wins": int(rank.get("ranked_wins") or 0),
            "ranked_losses": int(rank.get("ranked_losses") or 0),
        }
        match_ids = {
            str(row.get("match_id") or "").split(":", 1)[0] for row in rows
        }
        report["flagged_matches"] = [
            dict(flag) for flag in flags if str(flag.get("match_id")) in match_ids
        ][:100]
        report["override_history"] = [
            {
                "level": row.get("level"),
                "cleared": bool(row.get("cleared")),
                "reason": row.get("reason"),
                "actor": row.get("actor"),
                "created_at": row.get("created_at"),
            }
            for row in overrides
        ]
        return report

    def suspicion_overview(self, limit: int = 200) -> dict[str, Any]:
        """Admin list: raw totals -> one derived report per account."""
        if not self.database:
            return {"players": [], "total": 0,
                    "levels": {}, "thresholds": {}}
        with self.database.unit_of_work() as uow:
            totals = uow.stats.all_suspicion_totals(limit)
        players: list[dict[str, Any]] = []
        for row in totals:
            user_id = row.get("user_id")
            if not user_id:
                continue
            report = self.report_for(str(user_id))
            if report is not None:
                players.append(report)
        players.sort(key=lambda item: item.get("suspicion") or 0, reverse=True)
        return {
            "players": players,
            "total": len(totals),
            "levels": {str(level): name for level, name in suspicion.LEVEL_NAMES.items()},
            "thresholds": {
                str(level): threshold
                for threshold, level in suspicion.LEVEL_THRESHOLDS
            },
        }

    def set_override(self, user_id: str, *, actor: str, level: int | None = None,
                     cleared: bool = False, reason: str = "") -> dict[str, Any]:
        """Persist an explicit admin decision (append-only audit).

        This is the only stored ban input besides the scores themselves; the
        effective level is still recomputed (CLAUDE #27). Validation mirrors the
        legacy route so callers cannot store an out-of-range level.
        """
        if not user_id:
            raise ValueError("缺少用户 ID")
        if not cleared:
            if level is None:
                raise ValueError("必须给 cleared 或 level")
            try:
                level = int(level)
            except (TypeError, ValueError) as error:
                raise ValueError("level 必须是整数") from error
            if not (suspicion.LEVEL_NONE <= level <= suspicion.LEVEL_NO_ROOM):
                raise ValueError(f"level 必须在 0~{suspicion.LEVEL_NO_ROOM} 之间")
        if self.database is None:
            raise RuntimeError("anti-cheat override needs a database")
        with self.database.unit_of_work() as uow:
            # Validate before writing: a missing account must not leave an
            # orphan override row behind (the legacy route checked the user
            # report after the write; the transaction makes the check cheap).
            if uow.users.get(user_id) is None:
                raise ValueError("用户不存在")
            uow.stats.record_override(
                user_id=user_id,
                level=None if cleared else level,
                cleared=1 if cleared else 0,
                reason=str(reason or "")[:500],
                actor=str(actor or "")[:64],
                created_at=int(time.time()),
            )
        report = self.player_report(user_id)
        if report is None:
            raise ValueError("用户不存在")
        return report
