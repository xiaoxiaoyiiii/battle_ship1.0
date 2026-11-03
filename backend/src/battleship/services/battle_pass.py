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
    MATCH_COMPLETION_XP,
    MATCH_WIN_XP,
    WEEKLY_MATCH_XP_CAP,
)
from ..domain.tasks import TASKS, periods
from ..domain.shop import owned_cosmetics, storage_kind
from ..domain.tide_ash import (
    CURRENCY, DAILY_MATCH_CAP, DUPLICATE_TIDE, FREE_GAP_TIDE, PREMIUM_GAP_TIDE,
    MATCH_COMPLETION_TIDE, MATCH_WIN_TIDE, TASK_TIDE, capped_grant,
)
from ..domain.room import Room
from ..repositories import Database, UnitOfWork
from .progression import ProgressionService

DEFAULT_REWARDS: dict[tuple[int, str], tuple[str, str]] = {
    (level, track): (CURRENCY, f"{CURRENCY}:{amount}")
    for level in range(1, 51)
    for track, amount in (("free", FREE_GAP_TIDE), ("premium", PREMIUM_GAP_TIDE))
}
DEFAULT_REWARDS.update({
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
    (45, "premium"): ("frame", "star_compass"),
    (50, "premium"): ("title", "season_deep_1"),
})


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
            if not user_id or not uow.users.get(user_id):
                return {"ok": False, "reason": "unauthorized", "season": None,
                        "state": "closed", "levels": [], "progress": None,
                        "challenges": [], "claims": [],
                        "wallet": {"currency": CURRENCY, "balance": 0,
                                   "daily_match_granted": 0, "daily_cap": DAILY_MATCH_CAP}}
            from .daily_challenge import release_pending_xp
            release_pending_xp(uow, user_id, now)
            # 补发与当前展示季分开，避免新季开启后旧季奖励失去领取入口。
            auto_granted = set()
            for closed in uow.battle_pass.closed_seasons_for_user(user_id, now):
                previous = _config(closed)
                self._auto_grant_closed(
                    uow, user_id, previous, uow.battle_pass.progress(user_id, previous.id, now=now),
                    uow.battle_pass.levels(previous.id), now,
                )
                auto_granted.add(previous.id)
            window = periods(now)["daily"]
            wallet = {
                "currency": CURRENCY, "balance": uow.tide_ash.balance(user_id),
                "daily_match_granted": uow.tide_ash.granted_between(
                    user_id, "match_tide", window["next_reset_at"] - 86400, window["next_reset_at"],
                ), "daily_cap": DAILY_MATCH_CAP,
            }
            season = uow.battle_pass.current_season(now) or uow.battle_pass.latest_season()
            if season is None:
                return {"season": None, "state": "closed", "levels": [],
                        "progress": None, "challenges": [], "claims": [], "wallet": wallet}
            config = _config(season)
            state = season_state(now, config)
            progress = uow.battle_pass.progress(user_id, config.id, now=now)
            levels = uow.battle_pass.levels(config.id)
            if state == "closed" and config.id not in auto_granted:
                self._auto_grant_closed(uow, user_id, config, progress, levels, now)
                wallet["balance"] = uow.tide_ash.balance(user_id)
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
                "wallet": wallet,
            }

    @staticmethod
    def _auto_grant_closed(uow: UnitOfWork, user_id: str, config: SeasonConfig,
                           progress: dict[str, Any], levels: list[dict[str, Any]], now: int) -> None:
        """领取期结束后懒触发补发；唯一键保证重复访问不会重复授予。"""
        reached = current_level(progress["xp"], config)
        premium = bool(progress.get("premium_unlocked"))
        uow.tide_ash.lock(user_id, now=now)
        owned = owned_cosmetics(ProgressionService().unlock_stats(uow, user_id))
        for row in levels:
            level = int(row["level"])
            if level > reached:
                break
            tracks = ["free"] + (["premium"] if premium else [])
            for track in tracks:
                kind = row.get(f"{track}_kind")
                reward_id = row.get(f"{track}_reward_id")
                if kind and reward_id:
                    BattlePassService._claim_reward(
                        user_id, config.id, level, track, str(kind), str(reward_id),
                        uow, now, owned=owned,
                    )

    @staticmethod
    def _claim_reward(user_id: str, season_id: str, level: int, track: str,
                      kind: str, reward_id: str, uow: UnitOfWork, now: int,
                      *, owned: set[tuple[str, str]] | None = None) -> tuple[bool, int]:
        """领取标记、外观及徽记同事务；过期补发也复用此入口。"""
        uow.tide_ash.lock(user_id, now=now)
        if owned is None:
            owned = owned_cosmetics(ProgressionService().unlock_stats(uow, user_id))
        currency = kind in {CURRENCY, "currency"}
        reward_kind = storage_kind(kind)
        duplicate = not currency and (reward_kind, reward_id) in owned
        grant_key = f"{user_id}:{season_id}:{level}:{track}"
        inserted = uow.battle_pass.claim_once(
            user_id, season_id, level, track, reward_kind, reward_id, grant_key,
            now=now, grant_cosmetic=not currency and not duplicate,
        )
        if not inserted:
            return False, 0
        if currency or duplicate:
            amount = int(reward_id.removeprefix(f"{CURRENCY}:")) if currency else DUPLICATE_TIDE
            if amount <= 0:
                raise ValueError("通行证徽记奖励必须为正数")
            uow.tide_ash.apply_once(user_id, "pass_reward" if currency else "pass_duplicate",
                                    grant_key, amount, now=now)
        else:
            owned.add((reward_kind, reward_id))
        return True, DUPLICATE_TIDE if duplicate else 0

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
        config = SeasonConfig(season_id, starts_at, ends_at, claim_ends_at, 50, 18_000, 2)
        with self.database.unit_of_work() as uow:
            existing = uow.battle_pass.get_season(season_id)
            if existing and int(existing["rules_version"]) != config.rules_version:
                raise ValueError("season_rules_conflict")
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
                "levels": config.level_cap, "total_xp": config.total_xp,
                "rules_version": config.rules_version}

    def claim(self, user_id: str, level: int, track: str,
              *, season_id: str | None = None, now: int | None = None) -> tuple[bool, str]:
        """保留既有调用方的二元返回值。"""
        result = self.claim_with_details(user_id, level, track, season_id=season_id, now=now)
        return bool(result["ok"]), str(result["reason"])

    def claim_with_details(self, user_id: str, level: int, track: str,
                           *, season_id: str | None = None, now: int | None = None) -> dict[str, Any]:
        now = int(time.time()) if now is None else int(now)
        if track not in {"free", "premium"}:
            return {"ok": False, "reason": "track_invalid"}
        with self.database.unit_of_work() as uow:
            if not user_id or not uow.users.get(user_id):
                return {"ok": False, "reason": "unauthorized"}
            season = uow.battle_pass.get_season(season_id) if season_id else uow.battle_pass.current_season(now)
            if season is None:
                return {"ok": False, "reason": "season_unavailable"}
            config = _config(season)
            state = season_state(now, config)
            if state not in {"active", "claim_only"}:
                return {"ok": False, "reason": "claim_closed" if state == "closed" else "season_unavailable"}
            level = int(level)
            if level < 1 or level > config.level_cap:
                return {"ok": False, "reason": "level_invalid"}
            progress = uow.battle_pass.progress(user_id, config.id, now=now)
            if current_level(progress["xp"], config) < level:
                return {"ok": False, "reason": "level_locked"}
            if track == "premium" and not progress["premium_unlocked"]:
                return {"ok": False, "reason": "premium_locked"}
            level_rows = {int(row["level"]): row for row in uow.battle_pass.levels(config.id)}
            reward = level_rows.get(level)
            if reward is None:
                return {"ok": False, "reason": "reward_unavailable"}
            kind = reward.get(f"{track}_kind")
            reward_id = reward.get(f"{track}_reward_id")
            if not kind or not reward_id:
                return {"ok": False, "reason": "reward_unavailable"}
            claimed, converted = self._claim_reward(
                user_id, config.id, level, track, str(kind), str(reward_id), uow, now,
            )
            return {"ok": True, "reason": "claimed" if claimed else "already_claimed",
                    "converted_to_tide_ash": converted}

    # ------------------------------------------------------------------ settlement

    def settlement_hook(self, room: Room, uow: UnitOfWork, context: Any) -> None:
        """在同一结算事务写入真人排位/休闲的赛季经验。"""
        facts = context.facts
        users = [facts.winner_user_id, facts.loser_user_id]
        seats = [facts.winner_id, facts.loser_id]
        if (facts.mode not in {"ranked", "casual"} or room.is_ai_room
                or not context.match_id or not all(users) or len(set(users)) != 2
                or any(not uow.users.get(uid) for uid in users)
                or any(seat.startswith("ai-") or seat not in room.players
                       or not room.players[seat].registered
                       or room.players[seat].user_id != uid for seat, uid in zip(seats, users))):
            return
        now = int(context.timestamp)
        season = uow.battle_pass.current_season(now)
        config = _config(season) if season else None
        active = config is not None and season_state(now, config) == "active"
        windows = periods(now)
        for uid in users:
            uow.tide_ash.lock(uid, now=now)
            for period, window in windows.items() if active else ():
                totals = uow.tasks.totals(uid, window["start"], window["end"])
                completed = sum(
                    int(totals.get(metric, 0)) >= int(target)
                    for metric, _title, _desc, target in TASKS[period]
                )
                xp = task_reward_xp(period, completed)
                if xp:
                    added = uow.battle_pass.add_event_once(
                        uid, config.id, f"{period}_tasks", window["start"], xp,
                        now=now,
                    )
                    if added:
                        uow.tide_ash.apply_once(uid, f"{period}_task_tide", window["start"],
                                                TASK_TIDE[period], now=now)

            is_win = uid == facts.winner_user_id
            new_match = False
            if active:
                week = windows["weekly"]["next_reset_at"]
                granted = uow.battle_pass.match_xp_total(uid, week - 7 * 86400, week)
                xp = capped_grant(MATCH_COMPLETION_XP + (MATCH_WIN_XP if is_win else 0),
                                  granted, WEEKLY_MATCH_XP_CAP)
                new_match = uow.battle_pass.add_event_once(
                    uid, config.id, "match_xp", str(context.match_id), xp, now=now,
                )

            day = windows["daily"]["next_reset_at"]
            granted = uow.tide_ash.granted_between(uid, "match_tide", day - 86400, day)
            tide = capped_grant(MATCH_COMPLETION_TIDE + (MATCH_WIN_TIDE if is_win else 0),
                                granted, DAILY_MATCH_CAP)
            uow.tide_ash.apply_once(uid, "match_tide", str(context.match_id), tide, now=now)
            if not new_match:
                continue

            # 只有首次记账的有效比赛推进挑战，结算重入不会重复累计。
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
