"""账号推广提醒的每日原子占位。"""
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from .models import UserSupportPrompt


class SupportRepository:
    def __init__(self, session: Session):
        self.session = session

    def claim(self, user_id: str, day_key: str) -> bool:
        statement = insert(UserSupportPrompt).values(user_id=user_id, day_key=day_key)
        statement = statement.on_conflict_do_update(
            index_elements=['user_id'], set_={'day_key': day_key},
            where=UserSupportPrompt.day_key != day_key)
        return bool(self.session.execute(statement).rowcount)
