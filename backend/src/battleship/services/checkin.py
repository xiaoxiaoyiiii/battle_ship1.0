"""每日签到：日记录、徽记流水和满勤称号在同一个事务里提交。"""
from __future__ import annotations

import time
from typing import Any

from ..domain.checkin import (
    DAILY_TIDE, SOURCE_KIND, build_state, civil_date, daily_source_id,
    milestone_source_id, milestones_for, now_seconds, pending_milestones,
    title_identity,
)
from ..domain.progression import profile_spec
from ..repositories import Database


def sync_checkin_catalog(uow, now: float) -> None:
    """图鉴保留当月，以及已经发出去的历史月。"""
    today = civil_date(now)
    profile_spec.ensure_checkin_month(today.year, today.month)
    for reward_id in uow.checkins.issued_title_ids():
        profile_spec.ensure_checkin_reward(reward_id)


def _claimed_days(uow, user_id: str, year: int, month: int) -> set[int]:
    mapping = {
        item["days"]: milestone_source_id(year, month, item["days"])
        for item in milestones_for(year, month)
    }
    present = uow.tide_ash.source_ids_present(user_id, SOURCE_KIND, list(mapping.values()))
    return {days for days, source_id in mapping.items() if source_id in present}


class CheckinService:
    def __init__(self, database: Database, *, clock=None) -> None:
        self.database = database
        self.clock = clock or time.time

    def view(self, user_id: str) -> dict[str, Any] | None:
        now = now_seconds(self.clock())
        with self.database.unit_of_work() as uow:
            if uow.users.get(user_id) is None:
                return None
            sync_checkin_catalog(uow, now)
            return self._state(uow, user_id, now)

    def claim(self, user_id: str) -> dict[str, Any] | None:
        now = now_seconds(self.clock())
        today = civil_date(now)
        with self.database.unit_of_work() as uow:
            if uow.users.get(user_id) is None:
                return None
            sync_checkin_catalog(uow, now)
            inserted = uow.checkins.insert_once(user_id, today.isoformat(), now)
            granted = {
                "daily_tide": 0,
                "milestone_tide": 0,
                "milestones_triggered": [],
                "title": None,
            }
            if inserted:
                if not uow.tide_ash.apply_once(
                    user_id, SOURCE_KIND, daily_source_id(today.isoformat()), DAILY_TIDE, now=now,
                ):
                    raise RuntimeError("签到每日入账失败")
                granted["daily_tide"] = DAILY_TIDE
                claimed = _claimed_days(uow, user_id, today.year, today.month)
                count = len(uow.checkins.month_days(user_id, today.year, today.month))
                full_days = milestones_for(today.year, today.month)[-1]["days"]
                for item in pending_milestones(today.year, today.month, count, claimed):
                    source_id = milestone_source_id(today.year, today.month, item["days"])
                    if not uow.tide_ash.apply_once(
                        user_id, SOURCE_KIND, source_id, item["tide"], now=now,
                    ):
                        raise RuntimeError("签到里程碑入账失败")
                    granted["milestones_triggered"].append(item["days"])
                    granted["milestone_tide"] += item["tide"]
                    if item["days"] == full_days:
                        identity = title_identity(today.year, today.month)
                        uow.checkins.grant_title(user_id, identity["id"], now)
                        profile_spec.ensure_checkin_month(today.year, today.month)
                        granted["title"] = {"id": identity["id"], "name": identity["name"]}
            state = self._state(uow, user_id, now)
        return {"already_checked": not inserted, "granted": granted, **state}

    @staticmethod
    def _state(uow, user_id: str, now: int) -> dict[str, Any]:
        today = civil_date(now)
        title = title_identity(today.year, today.month)
        return build_state(
            now=now,
            checked_days=uow.checkins.month_days(user_id, today.year, today.month),
            claimed=_claimed_days(uow, user_id, today.year, today.month),
            balance=uow.tide_ash.balance(user_id),
            owned=uow.checkins.owns_title(user_id, title["id"]),
        )
