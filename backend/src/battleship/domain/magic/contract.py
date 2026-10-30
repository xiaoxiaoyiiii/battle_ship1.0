"""恶魔契约的「船数增减绑定」：一个入口，两个方向，绝不递归。

卡面（`magic_card.json`）：「只要这张卡在场，双方船数的增减就绑定在一起；每次攻击
生效后只结算一次」。用户定稿补齐了另一半：**增加也要绑定**——一方实际多出 N 艘，
另一方同样获得 N 艘部署；一方实际少掉 N 艘，另一方同样完成 N 艘献祭（最多用光活舰）。

三条硬约束写在代码里：

1. **一次原始变化只结算一次**：镜像动作本身也是船数变化，必须在 `mirroring()` 里执行，
   `enabled()` 在镜像期间返回 False，所以镜像不会再触发镜像。
2. **失败 / 无效化 / 零变化不触发**：调用点只在确实增减了一艘之后才请求镜像。
3. **不观察魔法中间态**：整盘替换不把清空再摆回当成击杀；神威除外与返还、
   临时船补充与收回按实际变化联动。绝处逢生等到唯一战舰落地后再结算净减少。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

#: 整盘替换的清空中间态不产生契约义务。
NO_MIRROR_CARDS = frozenset({
    "灵气复苏",
    "败者食尘",
    "回光返照",
})

#: 契约新增的摆船义务：这类船落地时不再反向触发契约。
MIRRORED_PLACEMENT = "mirrored"


def in_play(room: Any) -> bool:
    effects = getattr(room, "game_effects", None) or {}
    if getattr(getattr(room, "state", None), "value", None) == "game_over":
        return False
    return bool(effects.get("demon_contract"))


def enabled(room: Any) -> bool:
    """此刻是否应该镜像：契约在场、且不是镜像自身/整盘重布引发的。"""

    effects = getattr(room, "game_effects", None) or {}
    if not in_play(room):
        return False
    return not effects.get("contract_mirroring") and not effects.get("contract_suppress")


@contextmanager
def mirroring(room: Any) -> Iterator[None]:
    """镜像动作的作用域：期间 `enabled()` 为 False，镜像不会自我触发。"""

    effects = room.game_effects
    previous = effects.get("contract_mirroring")
    effects["contract_mirroring"] = True
    try:
        yield
    finally:
        if previous is None:
            effects.pop("contract_mirroring", None)
        else:
            effects["contract_mirroring"] = previous


@contextmanager
def suppressed(room: Any) -> Iterator[None]:
    """屏蔽效果执行中间态，由调用方按最终净变化统一镜像。"""

    effects = room.game_effects
    previous = effects.get("contract_suppress")
    effects["contract_suppress"] = True
    try:
        yield
    finally:
        if previous is None:
            effects.pop("contract_suppress", None)
        else:
            effects["contract_suppress"] = previous


__all__ = [
    "MIRRORED_PLACEMENT",
    "NO_MIRROR_CARDS",
    "enabled",
    "in_play",
    "mirroring",
    "suppressed",
]
