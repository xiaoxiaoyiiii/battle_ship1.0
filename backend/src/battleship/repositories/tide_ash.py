"""徽记余额与来源流水，在调用方 UoW 内一起提交。"""
import time

from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from .models import TideAshLedger, TideAshWallet


class TideAshRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def lock(self, user_id: str, *, now: int | None = None) -> None:
        """先取得 SQLite 写锁，再读帽额或余额，避免并发读旧余额后超发。"""
        now = int(time.time()) if now is None else int(now)
        statement = insert(TideAshWallet).values(user_id=user_id, balance=0, updated_at=now)
        self.session.execute(statement.on_conflict_do_update(
            index_elements=["user_id"], set_={"balance": TideAshWallet.balance},
        ))

    def balance(self, user_id: str) -> int:
        return int(self.session.scalar(select(TideAshWallet.balance).where(
            TideAshWallet.user_id == user_id,
        )) or 0)

    def granted_between(self, user_id: str, source_kind: str, start: int, end: int) -> int:
        return int(self.session.scalar(select(func.coalesce(func.sum(TideAshLedger.delta), 0)).where(
            TideAshLedger.user_id == user_id, TideAshLedger.source_kind == source_kind,
            TideAshLedger.created_at >= int(start), TideAshLedger.created_at < int(end),
        )) or 0)

    def apply_once(self, user_id: str, source_kind: str, source_id: str, delta: int,
                   *, now: int | None = None) -> bool:
        now = int(time.time()) if now is None else int(now)
        delta = int(delta)
        self.lock(user_id, now=now)
        if self.balance(user_id) + delta < 0:
            return False
        result = self.session.execute(insert(TideAshLedger).values(
            user_id=user_id, source_kind=source_kind, source_id=str(source_id),
            delta=delta, created_at=now,
        ).on_conflict_do_nothing(index_elements=["user_id", "source_kind", "source_id"]))
        if not result.rowcount:
            return False
        self.session.execute(update(TideAshWallet).where(TideAshWallet.user_id == user_id).values(
            balance=TideAshWallet.balance + delta, updated_at=now,
        ))
        return True
