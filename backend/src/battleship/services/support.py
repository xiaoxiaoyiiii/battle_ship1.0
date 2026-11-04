"""推广提醒不参与对局结算或经济奖励。"""
import time
from datetime import datetime, timedelta, timezone


class SupportService:
    def __init__(self, database):
        self.database = database

    def claim(self, user_id: str, *, now: float | None = None) -> bool:
        if not user_id:
            return False
        day_key = datetime.fromtimestamp(
            time.time() if now is None else now, timezone(timedelta(hours=8))).date().isoformat()
        with self.database.unit_of_work() as uow:
            if uow.users.get(user_id) is None:
                return False
            return uow.support.claim(user_id, day_key)
