"""client_logins / client_promo_days：客户端登录标记与弹窗每日去重。"""

from sqlalchemy.dialects.sqlite import insert

from .models import ClientLogin, ClientPromoDay
from .unit_of_work import Session


class ClientPromoRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record_client_login(self, user_id: str, platform: str, *,
                            now: int) -> bool:
        """首次客户端登录返回 True（调用方据此投递奖励邮件），重复登录幂等。"""
        statement = insert(ClientLogin).values(
            user_id=user_id, platform=platform, logged_at=now,
        ).on_conflict_do_nothing(index_elements=["user_id"])
        return bool(self.session.execute(statement).rowcount)

    def claim_promo_day(self, user_id: str, day_key: str) -> bool:
        """账号维度每日去重：当日未弹过则占住名额并返回 True。"""
        statement = insert(ClientPromoDay).values(user_id=user_id, day_key=day_key)
        statement = statement.on_conflict_do_update(
            index_elements=["user_id"], set_={"day_key": day_key},
            where=ClientPromoDay.day_key != day_key)
        return bool(self.session.execute(statement).rowcount)
