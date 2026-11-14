"""皮肤拥有、碎片账本、选用与抽卡幂等，均在调用方 UoW 内提交。"""
from __future__ import annotations

import time

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from .models import (
    CardSkinOwned,
    CardSkinSelection,
    CardSkinShardLedger,
    CardSkinShardWallet,
    GachaRequest,
)


class SkinRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def lock_shards(self, user_id: str, *, now: int | None = None) -> None:
        now = int(time.time()) if now is None else int(now)
        statement = insert(CardSkinShardWallet).values(user_id=user_id, balance=0, updated_at=now)
        self.session.execute(statement.on_conflict_do_update(
            index_elements=["user_id"], set_={"balance": CardSkinShardWallet.balance},
        ))

    def shard_balance(self, user_id: str) -> int:
        return int(self.session.scalar(select(CardSkinShardWallet.balance).where(
            CardSkinShardWallet.user_id == user_id,
        )) or 0)

    def apply_shards_once(self, user_id: str, source_kind: str, source_id: str, delta: int,
                          *, now: int | None = None) -> bool:
        now = int(time.time()) if now is None else int(now)
        delta = int(delta)
        if delta == 0:
            return True
        self.lock_shards(user_id, now=now)
        if self.shard_balance(user_id) + delta < 0:
            return False
        result = self.session.execute(insert(CardSkinShardLedger).values(
            user_id=user_id, source_kind=source_kind, source_id=str(source_id),
            delta=delta, created_at=now,
        ).on_conflict_do_nothing(index_elements=["user_id", "source_kind", "source_id"]))
        if not result.rowcount:
            return False
        self.session.execute(update(CardSkinShardWallet).where(
            CardSkinShardWallet.user_id == user_id,
        ).values(balance=CardSkinShardWallet.balance + delta, updated_at=now))
        return True

    def owned_ids(self, user_id: str) -> set[str]:
        rows = self.session.scalars(select(CardSkinOwned.skin_id).where(CardSkinOwned.user_id == user_id))
        return {str(item) for item in rows}

    def grant_once(self, user_id: str, skin_id: str, source: str, source_id: str, *, now: int) -> bool:
        result = self.session.execute(insert(CardSkinOwned).values(
            user_id=user_id, skin_id=skin_id, source=source, source_id=str(source_id),
            granted_at=int(now),
        ).on_conflict_do_nothing(index_elements=["user_id", "skin_id"]))
        return bool(result.rowcount)

    def selections(self, user_id: str) -> dict[str, str]:
        rows = self.session.scalars(select(CardSkinSelection).where(CardSkinSelection.user_id == user_id))
        return {row.card_name: row.skin_id for row in rows}

    def selected_skin(self, user_id: str, card_name: str) -> str | None:
        row = self.session.get(CardSkinSelection, (user_id, card_name))
        return None if row is None else str(row.skin_id)

    def set_selection(self, user_id: str, card_name: str, skin_id: str, *, now: int) -> None:
        self.session.execute(insert(CardSkinSelection).values(
            user_id=user_id, card_name=card_name, skin_id=skin_id, updated_at=int(now),
        ).on_conflict_do_update(
            index_elements=["user_id", "card_name"],
            set_={"skin_id": skin_id, "updated_at": int(now)},
        ))

    def clear_selection(self, user_id: str, card_name: str) -> None:
        row = self.session.get(CardSkinSelection, (user_id, card_name))
        if row is not None:
            self.session.delete(row)

    def gacha_request(self, user_id: str, request_id: str) -> GachaRequest | None:
        return self.session.get(GachaRequest, (user_id, request_id))

    def save_gacha_request(self, user_id: str, request_id: str, *, pool_id: str, count: int,
                           cost: int, response: str, now: int) -> None:
        self.session.execute(insert(GachaRequest).values(
            user_id=user_id, request_id=request_id, pool_id=pool_id, count=int(count),
            cost=int(cost), response=response, created_at=int(now),
        ).on_conflict_do_nothing(index_elements=["user_id", "request_id"]))
