"""客户端（桌面/移动壳）登录标记、下载提示去重与客户端专属奖励邮件。

约定（2026-11-05 与用户裁定）：
* 壳与 APK 的浏览器标识追加 ``BattleshipClient/``（platform 后缀），
  服务端在登录成功时读到该标记即记录“该账号客户端登录过”；
* 客户端登录时尝试投递奖励邮件（500 潮汐徽记 + 专属头像框「远航之环」），
  每账号仅一次：邮件 source_key 防重复，投递失败可在下次登录时补投；
* 下载提示弹窗：游客按浏览器本地去重（前端），登录账号按账号每日一次
  （本模块 claim_promo_day），北京时间按天；
* 永久常驻活动，无截止日期。
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from ..infra.logging import get_logger
from ..repositories import Database
from .mailbox import MailboxService

logger = get_logger("client_promo")

#: 壳端浏览器标识（lib.rs / Android WebView 追加的后缀）。
CLIENT_UA_MARKER = "BattleshipClient/"

REWARD_TIDE = 500
REWARD_SOURCE_KEY = "client-voyage-v1"
MAIL_TITLE = "客户端专属奖励：远航之环"
MAIL_BODY = (
    "你在战舰棋客户端登录过了，这份航海者的心意请收下：\n"
    "500 潮汐徽记，以及专属头像框「远航之环」。\n"
    "那些勇敢的舰长，总是会不断向更远的航线进发。"
)

_DAY = timezone(timedelta(hours=8))


def day_key(now: float | None = None) -> str:
    return datetime.fromtimestamp(
        time.time() if now is None else now, _DAY).date().isoformat()


def platform_from_ua(ua: str | None) -> str | None:
    """从浏览器标识识别客户端壳；非客户端返回 None。"""
    if not ua or CLIENT_UA_MARKER not in ua:
        return None
    return "android" if "Android" in ua else "desktop"


class ClientPromoService:
    def __init__(self, database: Database):
        self.database = database

    def record_client_login(self, user_id: str, ua: str | None, *,
                            now: int | None = None) -> bool:
        """登录成功后标记客户端登录，幂等投递奖励，失败后下次登录补投。

        返回是否为首次记录（仅供日志/测试，重复调用幂等安全）。
        """
        platform = platform_from_ua(ua)
        if not platform or not user_id:
            return False
        now = int(time.time()) if now is None else int(now)
        with self.database.unit_of_work() as uow:
            if uow.users.get(user_id) is None:
                return False
            first = uow.client_promo.record_client_login(user_id, platform, now=now)
        # 登录记录不代表邮件已成功投递；沿用邮件幂等编号安全补投。
        self._deliver_reward_mail(user_id)
        logger.info("客户端登录记录", extra={"user_id": user_id,
                                          "platform": platform, "first": first})
        return first

    def _deliver_reward_mail(self, user_id: str) -> None:
        mailbox = MailboxService(self.database)
        try:
            result = mailbox.send(
                actor="system",
                title=MAIL_TITLE,
                body=MAIL_BODY,
                attachments=[
                    {"kind": "tide_ash", "amount": REWARD_TIDE},
                    {"kind": "frame", "reward_id": "client_voyage"},
                ],
                audience={"kind": "single", "user_id": user_id},
                source_key=f"{REWARD_SOURCE_KEY}:{user_id}",
            )
        except Exception:  # noqa: BLE001 - 邮件失败不阻断登录，仅记录待排查
            logger.exception("客户端奖励邮件投递失败", extra={"user_id": user_id})
            return
        logger.info("客户端奖励邮件投递", extra={"user_id": user_id,
                                               "result": result})

    def claim_promo_day(self, user_id: str, *,
                        now: float | None = None) -> bool:
        """下载提示弹窗的账号维度每日去重；True 表示当日可弹。"""
        if not user_id:
            return False
        with self.database.unit_of_work() as uow:
            if uow.users.get(user_id) is None:
                return False
            return uow.client_promo.claim_promo_day(user_id, day_key(now))
