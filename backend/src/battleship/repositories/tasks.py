"""任务计数的持久化接口，复用对局结算事务。"""
from sqlalchemy import select, func
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session
from .models import UserTaskCounter

class TaskRepository:
    def __init__(self, session: Session):
        self.session = session

    def increment(self, user_id: str, day: str, metric: str, amount: int = 1) -> None:
        if amount <= 0:
            return
        statement = insert(UserTaskCounter).values(user_id=user_id, day=day, metric=metric, value=amount)
        self.session.execute(statement.on_conflict_do_update(
            index_elements=['user_id', 'day', 'metric'],
            set_={'value': UserTaskCounter.value + statement.excluded.value}))

    def totals(self, user_id: str, start: str, end: str) -> dict[str, int]:
        rows = self.session.execute(select(UserTaskCounter.metric, func.sum(UserTaskCounter.value)).where(
            UserTaskCounter.user_id == user_id, UserTaskCounter.day >= start,
            UserTaskCounter.day < end).group_by(UserTaskCounter.metric))
        return {metric: int(value) for metric, value in rows}
