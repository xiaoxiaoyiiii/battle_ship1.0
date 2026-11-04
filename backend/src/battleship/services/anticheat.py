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

import hashlib
import json
import time
from collections import Counter
from typing import Any

from ..domain.anticheat import rules, suspicion
from ..domain.battle import dead_ship_count, match_duration_seconds
from ..domain.room import Room
from ..infra.logging import get_logger
from ..repositories import Database, UnitOfWork
from ..repositories.anticheat_history import AnticheatHistoryRepository
from .settlement import SettlementContext, SettlementFacts, SettlementService

logger = get_logger("anticheat")

CLEAN_RESULT: dict[str, Any] = {
    "score": 0,
    "level": "clean",
    "reasons": [],
    "rules": [],
    "blocked": False,
}


def _position_signature(cells: Any) -> str | None:
    """仅在内存比较布局指纹；审计、日志和客户端不获得坐标。"""
    if not isinstance(cells, list) or not cells:
        return None
    points = []
    for cell in cells:
        if not isinstance(cell, dict):
            return None
        x, y = cell.get("x"), cell.get("y")
        if type(x) is not int or type(y) is not int or not (0 <= x < 6 and 0 <= y < 6):
            return None
        points.append((x, y))
    return hashlib.sha256(json.dumps(sorted(set(points))).encode("utf-8")).hexdigest()


def _initial_layout(payload: dict[str, Any], side: str) -> str | None:
    """读取首次完整布船；末局、截断前未记录或未知格式不猜测。"""
    if payload.get("version") == 2 or "initial_state" in payload:
        frame = payload.get("initial_state") or {}
        frames = [frame]
        for event in (payload.get("events") or [])[:16000]:
            if isinstance(event, dict) and event.get("type") == "state":
                frame = {**frame, **(event.get("patch") or {})}
                frames.append(frame)
        for frame in frames:
            if frame.get("context", {}).get("state") not in ("rock_paper_scissors", "attacking"):
                continue
            boards = frame.get("boards") or {}
            if all((boards.get(label) or {}).get("fleet") for label in ("p1", "p2")):
                return _position_signature(boards[side]["fleet"])
        return None
    if payload.get("version") == 1:
        fleets: dict[str, Any] = {}
        for row in (payload.get("ships") or [])[:2000]:
            if not isinstance(row, dict):
                continue
            fleets.update({key: row[key] for key in ("p1", "p2") if key in row})
            if fleets.get("p1") and fleets.get("p2"):
                return _position_signature(fleets[side])
    return None


def _recorded_attacks(room: Room) -> tuple[dict[str, int], set[str]] | None:
    """有界读取已录下的出手增量；重置前命中只能作已证实的下界。"""
    state = getattr(room, "_viewing_recording", None)
    if not isinstance(state, dict) or state.get("truncated"):
        return None
    events = state.get("events") or []
    if len(events) > 16000:
        return None
    frame = state.get("initial_state")
    if not isinstance(frame, dict):
        return None
    order = list(room.players)
    totals = {pid: 0 for pid in order}
    shooters: set[str] = set()
    previous: dict[str, Counter] = {pid: Counter() for pid in order}

    def capture(boards: dict[str, Any]) -> None:
        for index, pid in enumerate(order[:2]):
            # 回放棋盘存入射炮击，必须反向映射为对手打出的真实座位。
            board = boards.get(f"p{2-index}") or {}
            shots = board.get("shots")
            if not isinstance(shots, list) or len(shots) > 2000:
                raise ValueError("出手记录不完整")
            current = Counter((cell["x"], cell["y"], bool(cell.get("hit"))) for cell in shots)
            additions = current - previous[pid]
            totals[pid] += sum(count for (_, _, hit), count in additions.items() if hit)
            if current:
                shooters.add(pid)
            previous[pid] = current

    try:
        capture(frame.get("boards") or {})
        for event in events:
            if event.get("type") != "state":
                continue
            frame = {**frame, **(event.get("patch") or {})}
            capture(frame.get("boards") or {})
        # 当前动作可能尚未提交观看帧，收上最后一份服务端标记。
        boards = {}
        for index, pid in enumerate(order[:2]):
            boards[f"p{2-index}"] = {"shots": [
                {"x": attack.x, "y": attack.y, "hit": attack.hit}
                for attack in room.players[pid].attacks
            ]}
        capture(boards)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    return totals, shooters


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

            logged = {pid: [] for pid in room.players}
            for entry in room.game_logs:
                detail = entry.get("detail") or {}
                pid = detail.get("attacker")
                if entry.get("type") == "attack" and pid in logged:
                    logged[pid].append(detail)

            def hits(pid: str, player: Any) -> int:
                # 重部署会清棋盘标记；完整炮击日志保存此前的实际出手。
                rows = logged.get(pid, [])
                targets = {(row.get("target", {}).get("x"), row.get("target", {}).get("y"), bool(row.get("hit")))
                           for row in rows}
                return sum(bool(row.get("hit")) for row in rows) + sum(
                    bool(attack.hit) for attack in (getattr(player, "attacks", None) or ())
                    if (attack.x, attack.y, bool(attack.hit)) not in targets
                )

            winner_hits, loser_hits = hits(winner_id, winner), hits(loser_id, loser)
            recording = getattr(room, "_viewing_recording", None)
            reconstructed = _recorded_attacks(room)
            reset = bool((room.replay or {}).get("board_resets") or room.polar_reversal_applied)
            truncated = bool(isinstance(recording, dict) and recording.get("truncated"))
            shooters = {pid for pid, player in room.players.items() if player.attacks or logged[pid]}
            if reconstructed is not None:
                recovered, recorded_shooters = reconstructed
                winner_hits = max(winner_hits, recovered.get(winner_id, 0))
                loser_hits = max(loser_hits, recovered.get(loser_id, 0))
                shooters.update(recorded_shooters)
            # 清盘前没有完整证据，零只能表示未知；已见命中保留为下界。
            if truncated or (reset and reconstructed is None):
                winner_hits = loser_hits = None
            elif reset or reconstructed is None:
                winner_hits = winner_hits or None
                loser_hits = loser_hits or None
            facts["attack_history_complete"] = reconstructed is not None and not reset and not truncated
            facts["hits_are_lower_bounds"] = reset or reconstructed is None
            raw_round = getattr(room, "round", None)
            facts["rounds"] = int(raw_round) if raw_round is not None else -1
            facts["attacker_total_hits"] = winner_hits
            facts["defender_total_hits"] = loser_hits
            facts["loser_total_hits"] = loser_hits

            # 出手包含未命中；身份保持房间座位键，不与账号或Socket混用。
            facts["attackers"] = [pid for pid in room.players if pid in shooters]
            facts["max_hits"] = max((value for value in (winner_hits, loser_hits) if value is not None), default=None)

            winner_ships = len(getattr(winner, "ships", None) or ()) if winner else 0
            loser_ships = len(getattr(loser, "ships", None) or ()) if loser else 0
            facts["foe_ships"] = loser_ships
            facts["total_ships"] = winner_ships + loser_ships
            facts["sunk"] = dead_ship_count(loser) if loser else None
            facts["battle_started"] = bool(room.match_started_at and winner_ships and loser_ships)
            facts["duration_sec"] = match_duration_seconds(room)
            facts["ended_by"] = getattr(room, "game_over_reason", None)
            facts.update(foe_position_signature=None, past_signatures=None,
                         opponent_gaps_sec=None, opponent_total_games=None,
                         opponent_wins=None, opponent_losses=None,
                         since_last_match_sec=None, ranked_win_streak=None)
            order = list(room.players)
            if loser_id in order:
                side = f"p{order.index(loser_id) + 1}"
                if isinstance(recording, dict):
                    facts["foe_position_signature"] = _initial_layout(recording, side)
        except Exception:
            pass
        return facts

    def _history_facts(self, room: Room, winner_id: str, loser_id: str) -> dict[str, Any]:
        winner, loser = room.players.get(winner_id), room.players.get(loser_id)
        uid = getattr(winner, "user_id", None)
        foe = getattr(loser, "user_id", None)
        if not self.database or not uid:
            return {}
        now = int(time.time())
        with self.database.unit_of_work() as uow:
            history = AnticheatHistoryRepository(uow.session)
            recent = history.recent(uid, before=now, exclude_match_id=room.match_id)
            rows = []
            for row in recent:
                # 取消局不参与；未知旧局截断连续历史，不能越过未知败局推断。
                if row["rewards_eligible"] is None:
                    break
                if row["rewards_eligible"] is True:
                    rows.append(row)
            recordings = history.replays([row["id"] for row in rows])
        result: dict[str, Any] = {}
        if rows and room.match_started_at:
            gap = int(room.match_started_at) - int(rows[0]["timestamp"])
            result["since_last_match_sec"] = gap if gap >= 0 else None
        if foe and foe != uid:
            pairs = [row for row in rows if {row["winner_id"], row["loser_id"]} == {uid, foe}]
            times = [now, *[int(row["timestamp"]) for row in pairs]]
            if pairs:
                result.update(
                    opponent_gaps_sec=[a-b for a, b in zip(times, times[1:]) if a >= b],
                    opponent_total_games=len(pairs)+1,
                    opponent_wins=sum(row["winner_id"] == uid for row in pairs)+1,
                    opponent_losses=sum(row["loser_id"] == uid for row in pairs),
                )
        if room.ranked and rows:
            streak = 1
            for row in rows:
                if row["mode"] is None:
                    # 旧数据的模式未知，不能越过它声称连续排位获胜。
                    break
                if row["mode"] != "ranked":
                    continue
                if row["winner_id"] != uid:
                    break
                streak += 1
            result["ranked_win_streak"] = streak
        signatures = []
        by_id = {row["id"]: row for row in rows}
        for match_id, payload in recordings:
            row = by_id[match_id]
            opponent = row["loser_id"] if row["winner_id"] == uid else row["winner_id"]
            side = (payload.get("seats") or {}).get(opponent)
            if side in ("p1", "p2"):
                signature = _initial_layout(payload, side)
                if signature:
                    signatures.append(signature)
        result["past_signatures"] = signatures or None
        return result

    def evaluate_room(self, room: Room, winner_id: str, loser_id: str) -> dict[str, Any]:
        """Evaluate one finished match. Fails open, but always logs the failure."""
        try:
            facts = self.facts_from_room(room, winner_id, loser_id)
            try:
                facts.update(self._history_facts(room, winner_id, loser_id))
            except Exception as error:
                logger.warning("反作弊历史暂不可读，仅使用本局事实", exc_info=error)
            return rules.evaluate(facts)
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
