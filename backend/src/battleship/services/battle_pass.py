"""赛季通行证服务：规则、幂等事件与结算钩子集中在这里。"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from ..domain.battle_pass import (
    SeasonConfig,
    current_level,
    level_xp,
    season_challenges,
    season_state,
    task_reward_xp,
)
from ..domain.tasks import TASKS, periods
from ..domain.room import Room
from ..repositories import Database, UnitOfWork

DEFAULT_REWARDS: dict[tuple[int, str], tuple[str, str]] = {
    (1, "free"): ("title", "rookie"),
    (5, "free"): ("card_bg", "graphite"),
    (10, "free"): ("frame", "silver"),
    (15, "free"): ("title", "sailor"),
    (20, "free"): ("card_bg", "dusk"),
    (25, "free"): ("frame", "aurora"),
    (30, "free"): ("title", "cardmaster"),
    (35, "free"): ("card_bg", "storm"),
    (40, "free"): ("frame", "golden_wheel"),
    (45, "free"): ("title", "hunter"),
    (5, "premium"): ("frame", "season_tide_ring"),
    (10, "premium"): ("card_bg", "abyss"),
    (15, "premium"): ("title", "deep_navigator"),
    (20, "premium"): ("frame", "mithril_ring"),
    (25, "premium"): ("card_bg", "starfield"),
    (30, "premium"): ("title", "iron_soul"),
    (35, "premium"): ("frame", "king_aura"),
    (40, "premium"): ("card_bg", "molten_gold"),
    (45, "premium"): ("title", "season_deep_1"),
    (50, "premium"): ("title", "season_deep_1"),
}


def _config(row: dict[str, Any]) -> SeasonConfig:
    return SeasonConfig(
        id=str(row["id"]), starts_at=int(row["starts_at"]),
        ends_at=int(row["ends_at"]), claim_ends_at=int(row["claim_ends_at"]),
        level_cap=int(row["level_cap"]), total_xp=int(row["total_xp"]),
        rules_version=int(row["rules_version"]),
    )


class BattlePassService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def view(self, user_id: str, *, now: int | None = None) -> dict[str, Any]:
        now = int(time.time()) if now is None else int(now)
        with self.database.unit_of_work() as uow:
            season = uow.battle_pass.current_season(now) or uow.battle_pass.latest_season()
            if season is None:
                return {"season": None, "state": "closed", "levels": [],
                        "progress": None, "challenges": [], "claims": []}
            config = _config(season)
            state = season_state(now, config)
            progress = uow.battle_pass.progress(user_id, config.id, now=now)
            levels = uow.battle_pass.levels(config.id)
            if state == "closed":
                self._auto_grant_closed(uow, user_id, config, progress, levels, now)
            challenges = season_challenges(config.id)
            by_id = {row["challenge_id"]: row for row in uow.battle_pass.challenge_progress(user_id, config.id)}
            for item in challenges:
                row = by_id.get(item["id"])
                item["current"] = min(int(item["target"]), int(row["progress"] if row else 0))
                item["completed"] = bool(row and row.get("completed_at"))
            return {
                "season": season,
                "state": state,
                "levels": levels,
                "progress": progress | {
                    "level": current_level(progress["xp"], config),
                    "total_xp": config.total_xp,
                    "level_cap": config.level_cap,
                },
                "challenges": challenges,
                "claims": uow.battle_pass.claims(user_id, config.id),
            }

    @staticmethod
    def _auto_grant_closed(uow: UnitOfWork, user_id: str, config: SeasonConfig,
                           progress: dict[str, Any], levels: list[dict[str, Any]], now: int) -> None:
        """领取期结束后懒触发补发；唯一键保证重复访问不会重复授予。"""
        reached = current_level(progress["xp"], config)
        premium = bool(progress.get("premium_unlocked"))
        for row in levels:
            level = int(row["level"])
            if level > reached:
                break
            tracks = ["free"] + (["premium"] if premium else [])
            for track in tracks:
                kind = row.get(f"{track}_kind")
                reward_id = row.get(f"{track}_reward_id")
                if kind and reward_id:
                    uow.battle_pass.claim_once(
                        user_id, config.id, level, track, str(kind), str(reward_id),
                        f"{user_id}:{config.id}:{level}:{track}", now=now,
                    )

    def unlock_premium(self, user_id: str, season_id: str | None = None,
                       *, now: int | None = None) -> bool:
        now = int(time.time()) if now is None else int(now)
        with self.database.unit_of_work() as uow:
            season = uow.battle_pass.get_season(season_id) if season_id else uow.battle_pass.current_season(now)
            if season is None:
                return False
            return uow.battle_pass.unlock_premium(user_id, str(season["id"]), now=now)

    def seed_default(self, season_id: str, starts_at: int, *, now: int | None = None) -> dict[str, Any]:
        """由受控运维入口创建一套 8 周、50 级的首季目录。"""
        starts_at = int(starts_at)
        ends_at = starts_at + 8 * 7 * 24 * 3600
        claim_ends_at = ends_at + 14 * 24 * 3600
        config = SeasonConfig(season_id, starts_at, ends_at, claim_ends_at, 50, 20_000, 1)
        with self.database.unit_of_work() as uow:
            uow.battle_pass.upsert_season(config, status="active", now=now)
            for level in range(1, config.level_cap + 1):
                free = DEFAULT_REWARDS.get((level, "free"))
                premium = DEFAULT_REWARDS.get((level, "premium"))
                uow.battle_pass.seed_level(
                    config.id, level, int(level_xp(level, config)),
                    free[0] if free else None, free[1] if free else None,
                    premium[0] if premium else None, premium[1] if premium else None,
                )
        return {"season_id": config.id, "starts_at": starts_at,
                "ends_at": ends_at, "claim_ends_at": claim_ends_at,
                "levels": config.level_cap}

    def claim(self, user_id: str, level: int, track: str,
              *, season_id: str | None = None, now: int | None = None) -> tuple[bool, str]:
        now = int(time.time()) if now is None else int(now)
        if track not in {"free", "premium"}:
            return False, "track_invalid"
        with self.database.unit_of_work() as uow:
            season = uow.battle_pass.get_season(season_id) if season_id else uow.battle_pass.current_season(now)
            if season is None:
                return False, "season_unavailable"
            config = _config(season)
            if season_state(now, config) == "closed":
                return False, "claim_closed"
            level = int(level)
            if level < 1 or level > config.level_cap:
                return False, "level_invalid"
            progress = uow.battle_pass.progress(user_id, config.id, now=now)
            if current_level(progress["xp"], config) < level:
                return False, "level_locked"
            if track == "premium" and not progress["premium_unlocked"]:
                return False, "premium_locked"
            level_rows = {int(row["level"]): row for row in uow.battle_pass.levels(config.id)}
            reward = level_rows.get(level)
            if reward is None:
                return False, "reward_unavailable"
            kind = reward.get(f"{track}_kind")
            reward_id = reward.get(f"{track}_reward_id")
            if not kind or not reward_id:
                return False, "reward_unavailable"
            grant_key = f"{user_id}:{config.id}:{level}:{track}"
            claimed = uow.battle_pass.claim_once(
                user_id, config.id, level, track, str(kind), str(reward_id), grant_key,
                now=now,
            )
            # Repeated clicks are a successful idempotent read of the original
            # grant, rather than a transient conflict for the caller.
            return True, "claimed" if claimed else "already_claimed"

    # ------------------------------------------------------------------ settlement

    def settlement_hook(self, room: Room, uow: UnitOfWork, context: Any) -> None:
        """在同一结算事务写入真人排位/休闲的赛季经验。"""
        facts = context.facts
        if facts.mode not in {"ranked", "casual"}:
            return
        now = int(context.timestamp)
        season = uow.battle_pass.current_season(now)
        if season is None:
            return
        config = _config(season)
        users = [facts.winner_user_id, facts.loser_user_id]
        users = [uid for uid in users if uid and uow.users.get(uid)]
        windows = periods(now)
        for uid in users:
            # Daily/weekly XP is granted once when at least two tasks in the
            # corresponding window become complete. The source id makes this
            # safe when the settlement callback is retried.
            for period, window in windows.items():
                totals = uow.tasks.totals(uid, window["start"], window["end"])
                completed = sum(
                    int(totals.get(metric, 0)) >= int(target)
                    for metric, _title, _desc, target in TASKS[period]
                )
                xp = task_reward_xp(period, completed)
                if xp:
                    uow.battle_pass.add_event_once(
                        uid, config.id, f"{period}_tasks", window["start"], xp,
                        now=now,
                    )

            # Challenges deliberately use only counters already authoritative
            # in the settlement transaction. AI/custom/test rooms never reach
            # this hook, so they cannot advance a challenge or award XP.
            cards = sum(int(v or 0) for v in room.task_card_uses.get(uid, {}).values())
            metrics = {"matches": 1, "wins": 1 if uid == facts.winner_user_id else 0,
                       "cards": cards}
            for challenge in season_challenges(config.id):
                delta = metrics.get(str(challenge["metric"]), 0)
                if not delta:
                    continue
                progress, completed = uow.battle_pass.add_challenge_progress(
                    uid, config.id, str(challenge["id"]), delta,
                    int(challenge["target"]), now=now,
                )
                if completed:
                    payload = json.dumps({"progress": progress, "target": challenge["target"]}, sort_keys=True)
                    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                    uow.battle_pass.add_event_once(
                        uid, config.id, "challenge", str(challenge["id"]),
                        int(challenge["xp"]), payload_hash=payload_hash, now=now,
                    )


__all__ = ["BattlePassService"]
