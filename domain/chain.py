"""卡牌连锁栈与响应窗口的纯状态机。"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


class ChainRuleError(ValueError):
    """连锁命令不满足当前状态。"""


@dataclass(frozen=True)
class ChainItemState:
    item_id: str
    caster_id: str
    card_name: str
    targets: Any
    timestamp: float
    negated: bool = False
    negated_by: str | None = None


@dataclass(frozen=True)
class ChainState:
    items: tuple[ChainItemState, ...] = ()
    waiting_for: str | None = None
    passes: int = 0
    window_open: bool = False

    def push(self, item: ChainItemState, first_responder: str | None = None) -> "ChainState":
        if self.window_open:
            raise ChainRuleError("响应窗口开启时不能直接压入连锁")
        return replace(self, items=self.items + (item,), waiting_for=first_responder,
                       passes=0, window_open=first_responder is not None)

    def open_window(self, player_id: str) -> "ChainState":
        if not self.items:
            raise ChainRuleError("空连锁不能开启响应窗口")
        return replace(self, waiting_for=player_id, passes=0, window_open=True)

    def respond(self, player_id: str, opponent_id: str) -> "ChainState":
        if not self.window_open or self.waiting_for != player_id:
            raise ChainRuleError("当前玩家不能响应")
        return replace(self, waiting_for=opponent_id, passes=0)

    def pass_response(self, player_id: str, opponent_id: str) -> tuple["ChainState", bool]:
        if not self.window_open or self.waiting_for != player_id:
            raise ChainRuleError("当前玩家不能放弃响应")
        passes = self.passes + 1
        if passes >= 2:
            return replace(self, waiting_for=None, passes=passes, window_open=False), True
        return replace(self, waiting_for=opponent_id, passes=passes), False

    def negate_top(self, by_card: str) -> "ChainState":
        if not self.items:
            raise ChainRuleError("空连锁没有可无效化的牌")
        return replace(self, items=self.items[:-1] + (replace(self.items[-1], negated=True,
                                                               negated_by=by_card),))

    def pop_next(self) -> tuple["ChainState", ChainItemState | None]:
        if self.window_open:
            raise ChainRuleError("响应窗口尚未关闭")
        if not self.items:
            return self, None
        return replace(self, items=self.items[:-1]), self.items[-1]
