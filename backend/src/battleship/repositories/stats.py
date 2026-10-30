"""Progress/stats tables: card usage, counters, achievements, xp, rank, perks, anticheat.

Persistence only. Business policy (when to award xp, replay retention, suspicion
thresholds) belongs in services/domain and is intentionally not implemented here.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..domain.progression.ranks import CAPTAIN_FLOOR
from .mapping import instance_dict
from .models import (
    AnticheatFlag,
    AnticheatOverride,
    CardUsage,
    MatchSuspicion,
    User,
    UserAchievement,
    UserCardUsage,
    UserCounters,
    UserPerk,
    UserRank,
    UserXp,
)

COUNTER_ADD_FIELDS = ("sunk_total", "matches_played", "flawless_wins")
COUNTER_FIELDS = ("sunk_total", "matches_played", "flawless_wins", "fastest_win_sec")


def _limit(value: int, maximum: int = 100) -> int:
    return min(max(1, int(value)), maximum)


def _now() -> int:
    return int(time.time())


class StatsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------ card usage

    def increment_card_usage(self, card_name: str, *, delta: int = 1, now: int | None = None) -> None:
        now = _now() if now is None else now
        statement = sqlite_insert(CardUsage).values(
            card_name=card_name, uses=delta, updated_at=now
        )
        statement = statement.on_conflict_do_update(
            index_elements=["card_name"],
            set_={
                "uses": CardUsage.uses + statement.excluded.uses,
                "updated_at": statement.excluded.updated_at,
            },
        )
        self.session.execute(statement)

    def card_uses(self, card_name: str) -> int:
        return int(
            self.session.scalar(
                select(CardUsage.uses).where(CardUsage.card_name == card_name)
            )
            or 0
        )

    def all_card_usage(self) -> dict[str, int]:
        """Every card's lifetime use count, as the legacy /api/card_usage map."""
        statement = select(CardUsage.card_name, CardUsage.uses)
        return {
            str(name): int(uses or 0)
            for name, uses in self.session.execute(statement)
        }

    def top_cards(self, limit: int = 10) -> list[dict[str, Any]]:
        statement = (
            select(CardUsage.card_name, CardUsage.uses, CardUsage.updated_at)
            .order_by(CardUsage.uses.desc(), CardUsage.card_name)
            .limit(_limit(limit))
        )
        return [dict(row._mapping) for row in self.session.execute(statement)]

    def increment_user_card_usage(
        self, user_id: str, card_name: str, *, delta: int = 1, now: int | None = None
    ) -> None:
        now = _now() if now is None else now
        statement = sqlite_insert(UserCardUsage).values(
            user_id=user_id, card_name=card_name, uses=delta, updated_at=now
        )
        statement = statement.on_conflict_do_update(
            index_elements=["user_id", "card_name"],
            set_={
                "uses": UserCardUsage.uses + statement.excluded.uses,
                "updated_at": statement.excluded.updated_at,
            },
        )
        self.session.execute(statement)

    def user_card_uses(self, user_id: str, card_name: str) -> int:
        return int(
            self.session.scalar(
                select(UserCardUsage.uses).where(
                    UserCardUsage.user_id == user_id,
                    UserCardUsage.card_name == card_name,
                )
            )
            or 0
        )

    def top_user_cards(self, user_id: str, limit: int = 3) -> list[dict[str, Any]]:
        statement = (
            select(UserCardUsage.card_name, UserCardUsage.uses, UserCardUsage.updated_at)
            .where(UserCardUsage.user_id == user_id)
            .order_by(UserCardUsage.uses.desc(), UserCardUsage.card_name)
            .limit(_limit(limit))
        )
        return [dict(row._mapping) for row in self.session.execute(statement)]

    def card_uses_total(self, user_id: str) -> int:
        """Sum of all card uses (the legacy cardmaster threshold input)."""

        statement = select(func.coalesce(func.sum(UserCardUsage.uses), 0)).where(
            UserCardUsage.user_id == user_id
        )
        return int(self.session.scalar(statement) or 0)

    def distinct_cards_used(self, user_id: str) -> int:
        statement = select(func.count(func.distinct(UserCardUsage.card_name))).where(
            UserCardUsage.user_id == user_id
        )
        return int(self.session.scalar(statement) or 0)

    # -------------------------------------------------------------- counters

    def get_counters(self, user_id: str) -> dict[str, Any]:
        counters = self.session.get(UserCounters, user_id)
        if counters is None:
            return {
                "user_id": user_id,
                "sunk_total": 0,
                "matches_played": 0,
                "flawless_wins": 0,
                "fastest_win_sec": 0,
                "updated_at": 0,
            }
        data = instance_dict(counters)
        for field in COUNTER_FIELDS:
            data[field] = max(0, int(data.get(field) or 0))
        data["updated_at"] = int(data.get("updated_at") or 0)
        return data

    def bump_counters(self, user_id: str, *, now: int | None = None, **deltas: int) -> dict[str, Any]:
        """Add counts; fastest_win_sec keeps the smallest non-zero value (legacy rule)."""
        unknown = set(deltas) - set(COUNTER_FIELDS)
        if unknown:
            raise ValueError(f"unknown user_counters columns: {sorted(unknown)}")
        now = _now() if now is None else now
        values = {field: 0 for field in COUNTER_ADD_FIELDS}
        insert_values = {"user_id": user_id, "updated_at": now, **values}
        set_values: dict[str, Any] = {"updated_at": now}

        for field in COUNTER_ADD_FIELDS:
            raw = deltas.get(field)
            if raw is None:
                continue
            value = max(0, int(raw))
            insert_values[field] = value
            set_values[field] = getattr(UserCounters, field) + value

        fastest = deltas.get("fastest_win_sec")
        if fastest is not None:
            candidate = int(fastest)
            if candidate > 0:
                insert_values["fastest_win_sec"] = candidate
                current = UserCounters.fastest_win_sec
                set_values["fastest_win_sec"] = case(
                    (func.coalesce(current, 0) == 0, candidate),
                    else_=func.min(current, candidate),
                )

        statement = sqlite_insert(UserCounters).values(**insert_values)
        statement = statement.on_conflict_do_update(
            index_elements=["user_id"], set_=set_values
        )
        self.session.execute(statement)
        self.session.flush()
        return self.get_counters(user_id)

    # ---------------------------------------------------------- achievements

    def unlock_achievement(self, user_id: str, badge_id: str, *, unlocked_at: int) -> bool:
        statement = sqlite_insert(UserAchievement).values(
            user_id=user_id, badge_id=badge_id, unlocked_at=unlocked_at
        )
        statement = statement.on_conflict_do_nothing(
            index_elements=["user_id", "badge_id"]
        )
        result = self.session.execute(statement)
        return bool(result.rowcount)

    def list_achievements(self, user_id: str) -> list[dict[str, Any]]:
        statement = (
            select(UserAchievement.badge_id, UserAchievement.unlocked_at)
            .where(UserAchievement.user_id == user_id)
            .order_by(UserAchievement.unlocked_at, UserAchievement.badge_id)
        )
        return [dict(row._mapping) for row in self.session.execute(statement)]

    # -------------------------------------------------------------------- xp

    def get_xp(self, user_id: str) -> int:
        return int(self.session.scalar(select(UserXp.xp).where(UserXp.user_id == user_id)) or 0)

    def add_xp(self, user_id: str, delta: int, *, now: int | None = None) -> int:
        """XP only grows: a non-positive delta returns the current value."""
        now = _now() if now is None else now
        amount = int(delta)
        if amount <= 0:
            return self.get_xp(user_id)
        statement = sqlite_insert(UserXp).values(
            user_id=user_id, xp=amount, updated_at=now
        )
        statement = statement.on_conflict_do_update(
            index_elements=["user_id"],
            set_={"xp": UserXp.xp + statement.excluded.xp, "updated_at": now},
        )
        self.session.execute(statement)
        self.session.flush()
        return self.get_xp(user_id)

    def xp_for(self, user_ids: list[str]) -> dict[str, int]:
        """Bulk XP lookup for a leaderboard page (one query, not one per row)."""
        ids = [str(user_id) for user_id in user_ids if user_id]
        if not ids:
            return {}
        statement = select(UserXp.user_id, UserXp.xp).where(UserXp.user_id.in_(ids))
        return {
            str(user_id): int(xp or 0)
            for user_id, xp in self.session.execute(statement)
        }

    def perks_for(self, user_ids: list[str]) -> dict[str, set[str]]:
        """Bulk perk lookup for a leaderboard page."""
        ids = [str(user_id) for user_id in user_ids if user_id]
        if not ids:
            return {}
        statement = select(UserPerk.user_id, UserPerk.perk).where(
            UserPerk.user_id.in_(ids)
        )
        result: dict[str, set[str]] = {}
        for user_id, perk in self.session.execute(statement):
            result.setdefault(str(user_id), set()).add(str(perk))
        return result

    # ------------------------------------------------------------------ perks

    def grant_perk(self, user_id: str, perk: str, *, granted_at: int) -> bool:
        statement = sqlite_insert(UserPerk).values(
            user_id=user_id, perk=perk, granted_at=granted_at
        )
        statement = statement.on_conflict_do_nothing(index_elements=["user_id", "perk"])
        result = self.session.execute(statement)
        return bool(result.rowcount)

    def list_perks(self, user_id: str) -> list[str]:
        statement = (
            select(UserPerk.perk)
            .where(UserPerk.user_id == user_id)
            .order_by(UserPerk.granted_at, UserPerk.perk)
        )
        return list(self.session.scalars(statement))

    # ------------------------------------------------------------------- rank

    def get_rank(self, user_id: str) -> dict[str, Any]:
        rank = self.session.get(UserRank, user_id)
        if rank is None:
            return {
                "user_id": user_id,
                "points": 0,
                "is_admiral": 0,
                "ranked_wins": 0,
                "ranked_losses": 0,
                "updated_at": 0,
            }
        data = instance_dict(rank)
        for field in ("points", "is_admiral", "ranked_wins", "ranked_losses"):
            data[field] = max(0, int(data.get(field) or 0))
        data["updated_at"] = int(data.get("updated_at") or 0)
        return data

    def add_rank_points(
        self,
        user_id: str,
        delta: int,
        *,
        is_admiral: bool | None = None,
        now: int | None = None,
    ) -> dict[str, Any]:
        """Floor points at zero; a positive/negative delta counts as a win/loss."""
        now = _now() if now is None else now
        change = int(delta)
        won = 1 if change > 0 else 0
        lost = 1 if change < 0 else 0
        insert_values = {
            "user_id": user_id,
            "points": max(0, change),
            "is_admiral": 1 if is_admiral else 0,
            "ranked_wins": won,
            "ranked_losses": lost,
            "updated_at": now,
        }
        set_values: dict[str, Any] = {
            "points": func.max(0, UserRank.points + change),
            "ranked_wins": UserRank.ranked_wins + won,
            "ranked_losses": UserRank.ranked_losses + lost,
            "updated_at": now,
        }
        if is_admiral is not None:
            set_values["is_admiral"] = 1 if is_admiral else 0
        statement = sqlite_insert(UserRank).values(**insert_values)
        statement = statement.on_conflict_do_update(
            index_elements=["user_id"], set_=set_values
        )
        self.session.execute(statement)
        self.session.flush()
        return self.get_rank(user_id)

    def rank_leaderboard(self, limit: int = 10, offset: int = 0) -> list[dict[str, Any]]:
        safe_offset = max(0, int(offset))
        statement = (
            select(
                UserRank.user_id,
                UserRank.points,
                UserRank.is_admiral,
                UserRank.ranked_wins,
                UserRank.ranked_losses,
                UserRank.updated_at,
            )
            .order_by(
                UserRank.points.desc(),
                func.coalesce(UserRank.updated_at, 0),
                UserRank.user_id,
            )
            .offset(safe_offset)
            .limit(_limit(limit))
        )
        return [dict(row._mapping) for row in self.session.execute(statement)]

    def count_rank_at_least(self, points: int) -> int:
        statement = select(func.count()).select_from(UserRank).where(
            UserRank.points >= max(0, int(points))
        )
        return int(self.session.scalar(statement) or 0)

    def captains_ordered(self, limit: int = 500) -> list[dict[str, Any]]:
        """Captain-pool rows ordered like the leaderboard, each with pool_position."""

        safe_limit = min(max(1, int(limit)), 500)
        statement = (
            select(
                UserRank.user_id,
                UserRank.points,
                UserRank.is_admiral,
                UserRank.ranked_wins,
                UserRank.ranked_losses,
                UserRank.updated_at,
            )
            .where(UserRank.points >= int(CAPTAIN_FLOOR))
            .order_by(
                UserRank.points.desc(),
                func.coalesce(UserRank.updated_at, 0),
                UserRank.user_id,
            )
            .limit(safe_limit)
        )
        rows = [dict(row._mapping) for row in self.session.execute(statement)]
        for position, row in enumerate(rows, start=1):
            row["pool_position"] = position
        return rows

    def rank_position(self, user_id: str) -> int:
        """Full-server rank position by points (1-based); 0 when no row exists."""

        row = self.session.execute(
            select(UserRank.points, UserRank.updated_at, UserRank.user_id).where(
                UserRank.user_id == user_id
            )
        ).first()
        if row is None:
            return 0
        points, updated_at, uid = int(row.points or 0), int(row.updated_at or 0), str(row.user_id)
        ahead = self.session.scalar(
            select(func.count())
            .select_from(UserRank)
            .where(
                (UserRank.points > points)
                | (
                    (UserRank.points == points)
                    & (
                        (func.coalesce(UserRank.updated_at, 0) < updated_at)
                        | (
                            (func.coalesce(UserRank.updated_at, 0) == updated_at)
                            & (UserRank.user_id < uid)
                        )
                    )
                )
            )
        )
        return int(ahead or 0) + 1

    # ------------------------------------------------------------- anticheat

    def record_anticheat_flag(
        self,
        match_id: str,
        *,
        rule: str,
        severity: str,
        detail: str,
        created_at: int,
    ) -> None:
        values = {
            "match_id": match_id,
            "rule": rule,
            "severity": severity,
            "detail": detail,
            "created_at": created_at,
        }
        statement = sqlite_insert(AnticheatFlag).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["match_id"],
            set_={key: statement.excluded[key] for key in values if key != "match_id"},
        )
        self.session.execute(statement)

    def get_anticheat_flag(self, match_id: str) -> dict[str, Any] | None:
        flag = self.session.get(AnticheatFlag, match_id)
        return instance_dict(flag) if flag is not None else None

    def record_suspicion(
        self,
        *,
        match_id: str,
        user_id: str,
        score: int,
        level: str | None,
        created_at: int,
    ) -> None:
        values = {
            "match_id": match_id,
            "user_id": user_id,
            "score": score,
            "level": level,
            "created_at": created_at,
        }
        statement = sqlite_insert(MatchSuspicion).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=["match_id"],
            set_={key: statement.excluded[key] for key in values if key != "match_id"},
        )
        self.session.execute(statement)

    def all_suspicion_totals(self, limit: int = 2000) -> list[dict[str, Any]]:
        """Server-wide raw suspicion sums, ordered by total (admin list input).

        The score is deliberately NOT decayed here: decay depends on "now" and
        stays in `domain.anticheat.suspicion.accumulate` (the admin route calls
        `build_report` per account with the live age).
        """
        safe_limit = max(1, min(int(limit), 10000))
        statement = (
            select(
                MatchSuspicion.user_id.label("user_id"),
                User.username.label("username"),
                func.sum(MatchSuspicion.score).label("total"),
                func.count().label("matches"),
            )
            .select_from(MatchSuspicion)
            .outerjoin(User, User.id == MatchSuspicion.user_id)
            .group_by(MatchSuspicion.user_id)
            .order_by(func.sum(MatchSuspicion.score).desc())
            .limit(safe_limit)
        )
        return [dict(row._mapping) for row in self.session.execute(statement)]

    def list_anticheat_flags(self, limit: int = 200) -> list[dict[str, Any]]:
        """Recent suspicious-match flags, newest first (admin detail input)."""
        safe_limit = max(1, min(int(limit), 2000))
        statement = (
            select(
                AnticheatFlag.match_id,
                AnticheatFlag.rule,
                AnticheatFlag.severity,
                AnticheatFlag.detail,
                AnticheatFlag.created_at,
            )
            .order_by(AnticheatFlag.created_at.desc())
            .limit(safe_limit)
        )
        return [dict(row._mapping) for row in self.session.execute(statement)]

    def list_suspicions(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        statement = (
            select(
                MatchSuspicion.match_id,
                MatchSuspicion.user_id,
                MatchSuspicion.score,
                MatchSuspicion.level,
                MatchSuspicion.created_at,
            )
            .where(MatchSuspicion.user_id == user_id)
            .order_by(MatchSuspicion.created_at.desc())
            # Legacy reads up to 500 rows for accumulation; the default 100 cap
            # would silently shrink every banned account's score.
            .limit(_limit(limit, 500))
        )
        return [dict(row._mapping) for row in self.session.execute(statement)]

    def record_override(
        self,
        *,
        user_id: str,
        level: int | None,
        cleared: int,
        reason: str,
        actor: str,
        created_at: int,
    ) -> int:
        override = AnticheatOverride(
            user_id=user_id,
            level=level,
            cleared=cleared,
            reason=reason,
            actor=actor,
            created_at=created_at,
        )
        self.session.add(override)
        self.session.flush()
        return int(override.id)

    def list_overrides(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Append-only admin audit history, newest first."""
        statement = (
            select(AnticheatOverride)
            .where(AnticheatOverride.user_id == user_id)
            .order_by(AnticheatOverride.id.desc())
            .limit(_limit(limit, 500))
        )
        return [instance_dict(row) for row in self.session.scalars(statement)]

    def latest_override(self, user_id: str) -> dict[str, Any] | None:
        statement = (
            select(AnticheatOverride)
            .where(AnticheatOverride.user_id == user_id)
            .order_by(AnticheatOverride.id.desc())
            .limit(1)
        )
        override = self.session.scalar(statement)
        return instance_dict(override) if override is not None else None