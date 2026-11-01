"""商店授予外观；购买来源与扣款幂等由徽记流水记录。"""
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from ..domain.shop import SHOP_ITEMS, ShopItem, storage_kind
from .models import UserCosmeticReward


class ShopRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def items(self) -> tuple[ShopItem, ...]:
        return SHOP_ITEMS

    def grant_once(self, user_id: str, item: ShopItem, *, now: int) -> bool:
        result = self.session.execute(insert(UserCosmeticReward).values(
            user_id=user_id, kind=storage_kind(item.kind), reward_id=item.id,
            source_season_id=None, source_level=None, source_track="shop", granted_at=int(now),
        ).on_conflict_do_nothing(index_elements=["user_id", "kind", "reward_id"]))
        return bool(result.rowcount)
