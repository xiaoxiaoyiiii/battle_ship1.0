"""外观商店：已有解锁判据、扣款、流水及权益同事务完成。"""
import time
from typing import Any

from ..domain.shop import SHOP_BY_ID, owned_cosmetics, storage_kind
from ..domain.tide_ash import CURRENCY
from ..repositories import Database
from .progression import ProgressionService


class ShopService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def view(self, user_id: str) -> dict[str, Any]:
        with self.database.unit_of_work() as uow:
            if not user_id or not uow.users.get(user_id):
                return {"ok": False, "reason": "unauthorized", "currency": CURRENCY,
                        "balance": 0, "items": []}
            owned = owned_cosmetics(ProgressionService(self.database).unlock_stats(uow, user_id))
            return {
                "ok": True, "currency": CURRENCY, "balance": uow.tide_ash.balance(user_id),
                "items": [{"id": item.id, "kind": item.kind, "name": item.name,
                           "price": item.price,
                           "owned": (storage_kind(item.kind), item.id) in owned,
                           "purchasable": (storage_kind(item.kind), item.id) not in owned}
                          for item in uow.shop.items()],
            }

    def purchase(self, user_id: str, item_id: str, *, now: int | None = None) -> dict[str, Any]:
        now = int(time.time()) if now is None else int(now)
        with self.database.unit_of_work() as uow:
            if not user_id or not uow.users.get(user_id):
                return {"ok": False, "reason": "unauthorized"}
            item = SHOP_BY_ID.get(item_id)
            if item is None:
                return {"ok": False, "reason": "item_unavailable"}
            uow.tide_ash.lock(user_id, now=now)
            owned = owned_cosmetics(ProgressionService(self.database).unlock_stats(uow, user_id))
            balance = uow.tide_ash.balance(user_id)
            if (storage_kind(item.kind), item.id) in owned:
                return {"ok": False, "reason": "already_owned", "balance": balance}
            if balance < item.price:
                return {"ok": False, "reason": "insufficient_funds", "balance": balance}
            if not uow.tide_ash.apply_once(user_id, "shop_purchase", item.id, -item.price, now=now):
                raise RuntimeError("商店扣款来源与外观权益不一致")
            if not uow.shop.grant_once(user_id, item, now=now):
                raise RuntimeError("商店外观授予冲突，扣款已回滚")
            return {"ok": True, "reason": "purchased", "balance": uow.tide_ash.balance(user_id),
                    "item": {"id": item.id, "kind": item.kind, "owned": True}}
