"""签到日与当月称号只在这里写 SQL。累计天数由日记录推出。"""
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from .models import DailyCheckin, UserCosmeticReward


class CheckinRepository:
    def __init__(self, session) -> None:
        self.session = session

    def insert_once(self, user_id: str, day: str, now: int) -> bool:
        result = self.session.execute(insert(DailyCheckin).values(
            user_id=user_id, day=day, created_at=int(now),
        ).on_conflict_do_nothing(index_elements=["user_id", "day"]))
        return bool(result.rowcount)

    def month_days(self, user_id: str, year: int, month: int) -> list[int]:
        start = f"{int(year):04d}-{int(month):02d}-01"
        if month == 12:
            end = f"{int(year) + 1:04d}-01-01"
        else:
            end = f"{int(year):04d}-{int(month) + 1:02d}-01"
        rows = self.session.scalars(select(DailyCheckin.day).where(
            DailyCheckin.user_id == user_id,
            DailyCheckin.day >= start,
            DailyCheckin.day < end,
        ).order_by(DailyCheckin.day))
        return [int(day[8:10]) for day in rows]

    def grant_title(self, user_id: str, title_id: str, now: int) -> None:
        self.session.execute(insert(UserCosmeticReward).values(
            user_id=user_id, kind="title", reward_id=title_id,
            source_track="checkin", granted_at=int(now),
        ).on_conflict_do_nothing(index_elements=["user_id", "kind", "reward_id"]))

    def owns_title(self, user_id: str, title_id: str) -> bool:
        return self.session.get(UserCosmeticReward, (user_id, "title", title_id)) is not None

    def issued_title_ids(self) -> list[str]:
        rows = self.session.scalars(select(UserCosmeticReward.reward_id).where(
            UserCosmeticReward.kind == "title",
            UserCosmeticReward.reward_id.like("checkin_%"),
        ).distinct())
        return [str(item) for item in rows]
