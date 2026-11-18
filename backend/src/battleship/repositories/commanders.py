"""指挥官角色系统仓储：所有读写在调用方 UoW 事务内完成。"""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..domain.commanders import DEFAULT_EQUIPPED, clamp_xp, level_for_xp
from .models import (
    CommanderXpEvent,
    UserCommanderClaim,
    UserCommanderOwned,
    UserCommanderSelection,
    UserCosmeticReward,
)


def _decode_equipped(raw: str | None) -> dict[str, str]:
    merged = dict(DEFAULT_EQUIPPED)
    if not raw:
        return merged
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            for k, v in parsed.items():
                if isinstance(k, str) and isinstance(v, str) and k in merged:
                    merged[k] = v
    except (ValueError, TypeError):
        pass
    return merged


class CommanderRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_owned(self, user_id: str) -> dict[str, dict[str, Any]]:
        rows = self.session.scalars(
            select(UserCommanderOwned).where(UserCommanderOwned.user_id == user_id)
        )
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            result[str(row.commander_id)] = {
                "commander_id": str(row.commander_id),
                "unlock_source": str(row.unlock_source),
                "cost_paid": int(row.cost_paid or 0),
                "xp": clamp_xp(int(row.xp or 0)),
                "level": level_for_xp(int(row.xp or 0)),
                "equipped": _decode_equipped(row.equipped_json),
                "unlocked_at": int(row.unlocked_at),
                "updated_at": int(row.updated_at),
            }
        return result

    def get_owned(self, user_id: str, commander_id: str) -> UserCommanderOwned | None:
        return self.session.get(UserCommanderOwned, (user_id, commander_id))

    def unlock_once(
        self,
        user_id: str,
        commander_id: str,
        *,
        unlock_source: str,
        cost_paid: int,
        now: int | None = None,
    ) -> bool:
        ts = int(time.time()) if now is None else int(now)
        stmt = (
            sqlite_insert(UserCommanderOwned)
            .values(
                user_id=user_id,
                commander_id=commander_id,
                unlock_source=unlock_source,
                cost_paid=max(0, int(cost_paid)),
                xp=0,
                level=1,
                equipped_json=json.dumps(dict(DEFAULT_EQUIPPED), ensure_ascii=False),
                unlocked_at=ts,
                updated_at=ts,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "commander_id"])
        )
        result = self.session.execute(stmt)
        self.session.flush()
        return bool(result.rowcount)

    def get_selection(self, user_id: str) -> dict[str, Any] | None:
        row = self.session.get(UserCommanderSelection, user_id)
        if row is None:
            return None
        return {
            "user_id": str(row.user_id),
            "selected_commander_id": str(row.selected_commander_id),
            "free_claimed": bool(row.free_claimed),
            "updated_at": int(row.updated_at),
        }

    def set_selection(
        self,
        user_id: str,
        commander_id: str,
        *,
        free_claimed: bool = True,
        now: int | None = None,
    ) -> None:
        ts = int(time.time()) if now is None else int(now)
        stmt = sqlite_insert(UserCommanderSelection).values(
            user_id=user_id,
            selected_commander_id=commander_id,
            free_claimed=1 if free_claimed else 0,
            updated_at=ts,
        )
        self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "selected_commander_id": commander_id,
                    "free_claimed": 1 if free_claimed else UserCommanderSelection.free_claimed,
                    "updated_at": ts,
                },
            )
        )
        self.session.flush()

    def claimed_levels(self, user_id: str, commander_id: str | None = None) -> dict[str, set[int]]:
        stmt = select(UserCommanderClaim.commander_id, UserCommanderClaim.level).where(
            UserCommanderClaim.user_id == user_id
        )
        if commander_id:
            stmt = stmt.where(UserCommanderClaim.commander_id == commander_id)
        out: dict[str, set[int]] = {}
        for cid, lvl in self.session.execute(stmt):
            out.setdefault(str(cid), set()).add(int(lvl))
        return out

    def claim_level_once(
        self,
        user_id: str,
        commander_id: str,
        level: int,
        *,
        now: int | None = None,
    ) -> bool:
        ts = int(time.time()) if now is None else int(now)
        stmt = (
            sqlite_insert(UserCommanderClaim)
            .values(
                user_id=user_id,
                commander_id=commander_id,
                level=int(level),
                claimed_at=ts,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "commander_id", "level"])
        )
        result = self.session.execute(stmt)
        self.session.flush()
        return bool(result.rowcount)

    def grant_profile_cosmetic(
        self,
        user_id: str,
        kind: str,
        reward_id: str,
        *,
        source_level: int,
        now: int | None = None,
    ) -> None:
        ts = int(time.time()) if now is None else int(now)
        stmt = (
            sqlite_insert(UserCosmeticReward)
            .values(
                user_id=user_id,
                kind=kind,
                reward_id=reward_id,
                source_season_id=None,
                source_level=int(source_level),
                source_track="commander",
                granted_at=ts,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "kind", "reward_id"])
        )
        self.session.execute(stmt)

    def update_equipped(
        self,
        user_id: str,
        commander_id: str,
        equipped: dict[str, str],
        *,
        now: int | None = None,
    ) -> dict[str, str]:
        ts = int(time.time()) if now is None else int(now)
        row = self.get_owned(user_id, commander_id)
        if row is None:
            raise KeyError("commander not owned")
        current = _decode_equipped(row.equipped_json)
        for key, value in equipped.items():
            if key in current and isinstance(value, str) and value:
                current[key] = value
        row.equipped_json = json.dumps(current, ensure_ascii=False)
        row.updated_at = ts
        self.session.flush()
        return current

    def ai_daily_xp_used(self, user_id: str, day_cst: str) -> int:
        val = self.session.scalar(
            select(func.coalesce(func.sum(CommanderXpEvent.granted_xp), 0)).where(
                CommanderXpEvent.user_id == user_id,
                CommanderXpEvent.day_cst == day_cst,
                CommanderXpEvent.is_ai == 1,
            )
        )
        return int(val or 0)

    def get_xp_event(self, user_id: str, match_id: str) -> dict[str, Any] | None:
        row = self.session.scalar(
            select(CommanderXpEvent).where(
                CommanderXpEvent.user_id == user_id,
                CommanderXpEvent.match_id == str(match_id),
            )
        )
        if row is None:
            return None
        return {
            "commander_id": str(row.commander_id),
            "mode": str(row.mode),
            "is_ai": bool(row.is_ai),
            "day_cst": str(row.day_cst),
            "raw_xp": int(row.raw_xp),
            "granted_xp": int(row.granted_xp),
            "before_xp": int(row.before_xp),
            "after_xp": int(row.after_xp),
            "before_level": int(row.before_level),
            "after_level": int(row.after_level),
            "reason": str(row.reason),
        }

    def record_xp_event_once(
        self,
        *,
        user_id: str,
        match_id: str,
        commander_id: str,
        mode: str,
        is_ai: bool,
        day_cst: str,
        raw_xp: int,
        granted_xp: int,
        before_xp: int,
        after_xp: int,
        before_level: int,
        after_level: int,
        reason: str,
        now: int | None = None,
    ) -> bool:
        ts = int(time.time()) if now is None else int(now)
        stmt = (
            sqlite_insert(CommanderXpEvent)
            .values(
                user_id=user_id,
                match_id=str(match_id),
                commander_id=commander_id,
                mode=mode,
                is_ai=1 if is_ai else 0,
                day_cst=day_cst,
                raw_xp=max(0, int(raw_xp)),
                granted_xp=max(0, int(granted_xp)),
                before_xp=max(0, int(before_xp)),
                after_xp=max(0, int(after_xp)),
                before_level=max(1, int(before_level)),
                after_level=max(1, int(after_level)),
                reason=str(reason or "settled"),
                created_at=ts,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "match_id"])
        )
        res = self.session.execute(stmt)
        if not res.rowcount:
            return False
        if granted_xp > 0:
            row = self.get_owned(user_id, commander_id)
            if row is not None:
                row.xp = after_xp
                row.level = after_level
                row.updated_at = ts
        self.session.flush()
        return True
