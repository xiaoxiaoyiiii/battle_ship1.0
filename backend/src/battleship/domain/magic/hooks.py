"""魔法卡 hook 事件目录与发送入口（ticket #36 首版）。

事件名是 domain 内部常量，不是 Socket.IO 协议：发射它们不会产生任何出站帧，
也不进回放/观战日志。所有业务发射点都走 :func:`emit`（目录校验），低层测试
可以直接用 `effects.emit`：

- `hooks.emit`：先校验事件名在 `HOOK_EVENTS` 里，拼错当场 ValueError；
- `effects.emit`：总线原语，只认字符串，不做目录校验。

v1 派发语义（与 `domain/effects._dispatch` 一致，别照别处的"拦截器"想象）：

- **filter 先于 notify**，可以原地改写本次载荷；返回值不被读取，**没有否决权**；
- **notify 拿到的是浅拷贝**，改它影响不到真实载荷与后续 notify；
- `ATTACK_HIT` 是**结算之后**的观察点（伤害、击沉、护盾都已落地），
  filter 此时改不了伤害/击沉，也拦不住已经发生的攻击。

命名沿用现有领域词汇：出牌 / 连锁 / 回合 / 阶段 / 攻击 / 伤害 / 击沉 / 摸牌 /
场地 / 终局。
"""

from __future__ import annotations

from typing import Any, Final

from .. import effects as effect_bus

#: 出牌宣告通过全部闸门、扣牌入连锁之前；filter 可原地改载荷（不能否决）。
CAST_BEFORE: Final[str] = "cast_before"
#: 支付完成：牌已离开手牌并进入连锁；此后失败只能按连锁规则退牌。
CAST_PAID: Final[str] = "cast_paid"
#: 连锁上一张牌结算完成（无效化与早退都已落定）。
CHAIN_RESOLVED: Final[str] = "chain_resolved"
#: 小回合开始；换人分支里 turn 租约已先由 on_turn_switch 过期（本事件在其后）。
TURN_START: Final[str] = "turn_start"
#: 小回合结束、行动者换人之前；turn 租约不在此时过期（见 on_turn_switch）。
TURN_END: Final[str] = "turn_end"
#: 大回合开始：ROUND_END 与 round_end_hook 之后、重新猜拳的 game_state 之前。
ROUND_START: Final[str] = "round_start"
#: 大回合结束；round 租约随后在 on_new_big_round 里过期（本事件之后）。
ROUND_END: Final[str] = "round_end"
#: 进入新阶段（准备 / 战斗 / 结束）；phase 与攻击次数都已改写。
PHASE_ENTER: Final[str] = "phase_enter"
#: 一次攻击结算之后的观察点：命中、伤害、护盾、击沉都已落地。
ATTACK_HIT: Final[str] = "attack_hit"
#: 伤害真正落到棋盘之后（护盾/免疫已经处理完）。
DAMAGE_APPLIED: Final[str] = "damage_applied"
#: 一艘船被击沉（炮击与效果共用的唯一漏斗：MagicService.on_ship_sunk）。
SHIP_SUNK: Final[str] = "ship_sunk"
#: 一艘船被效果直接摧毁（MagicService.on_ship_destroyed）。
SHIP_DESTROYED: Final[str] = "ship_destroyed"
#: 摸牌入手（尚未公开给对手）。
CARD_DRAWN: Final[str] = "card_drawn"
#: 一张牌进入弃牌堆（同一个服务方法里每次弃牌只发一次）。
CARD_DISCARDED: Final[str] = "card_discarded"
#: 场地魔法上场（顶替旧场地之后）。
FIELD_ENTERED: Final[str] = "field_entered"
#: 场地魔法离场（拆除或被顶替之前）。
FIELD_LEFT: Final[str] = "field_left"
#: 终局判定完成、winner 已写入，且结算之前。
GAME_OVER: Final[str] = "game_over"

#: 目录的权威清单；顺序即文档顺序，不含语义。
HOOK_EVENTS: Final[tuple[str, ...]] = (
    CAST_BEFORE,
    CAST_PAID,
    CHAIN_RESOLVED,
    TURN_START,
    TURN_END,
    ROUND_START,
    ROUND_END,
    PHASE_ENTER,
    ATTACK_HIT,
    DAMAGE_APPLIED,
    SHIP_SUNK,
    SHIP_DESTROYED,
    CARD_DRAWN,
    CARD_DISCARDED,
    FIELD_ENTERED,
    FIELD_LEFT,
    GAME_OVER,
)


async def emit(
    room: Any, event: str, payload: dict[str, Any] | None = None
) -> None:
    """发一个目录内事件；未登记的事件名直接 ValueError（拼错不许静默）。"""

    if event not in HOOK_EVENTS:
        raise ValueError(f"未登记的 hook 事件: {event!r}")
    await effect_bus.emit(room, event, payload)


__all__ = [
    "CAST_BEFORE",
    "CAST_PAID",
    "CHAIN_RESOLVED",
    "TURN_START",
    "TURN_END",
    "ROUND_START",
    "ROUND_END",
    "PHASE_ENTER",
    "ATTACK_HIT",
    "DAMAGE_APPLIED",
    "SHIP_SUNK",
    "SHIP_DESTROYED",
    "CARD_DRAWN",
    "CARD_DISCARDED",
    "FIELD_ENTERED",
    "FIELD_LEFT",
    "GAME_OVER",
    "HOOK_EVENTS",
    "emit",
]
