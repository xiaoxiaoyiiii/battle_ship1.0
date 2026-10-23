"""魔法卡「待选择项」的唯一存放点：一张激活、其余排队。

为什么需要它：老实现把待处理选择塞进 `room.magic_temp_data` 这一个槽里，
第二张互动牌（如灵气复苏）会直接覆盖第一张（仁王之盾）——前一个选择被静默
丢弃、`pending_ship_picks` 还留着没人能确认。这里用一个 §键 → 选择项§ 的
字典加一个「激活槽」`magic_temp_data`：

* `store(room, temp)` 先入字典；激活槽空着就顺手激活，否则排队等前一个确认；
* `finish(room, key)` 只清掉自己那项，然后把最早排队的提上来（返回被提升的项，
  调用方负责把它写进响应，让客户端知道下一个该确认什么）；
* `clear(room)` 用于整盘重置类效果（败者食尘、回城重置、AI 自行处理）。

`magic_temp_data` 保留原语义（当前激活项），因此既有读取方（同步快照、AI、
阶段门禁）不用改；它们只应看到玩家此刻真正要处理的那一项。
"""

from __future__ import annotations

from typing import Any

from ..room.models import Room

#: 选择项的键：普通项用 `type`，摆船用 `pending_placement`，神机妙算用
#: `pending_shenji`——这三类在老代码里就不是同一个形状，键必须能区分它们。
_KEY_FIELDS = ("type", "pending_placement", "pending_shenji")


def key_of(temp: dict[str, Any]) -> str | None:
    for field in _KEY_FIELDS:
        value = temp.get(field)
        if field == "type" and isinstance(value, str) and value:
            return value
        if field != "type" and isinstance(value, dict):
            return field
    return None


def store(room: Room, temp: dict[str, Any]) -> dict[str, Any] | None:
    """把待选择项放进队列；返回被**激活**的那项（不是激活项时返回 None）。"""

    key = key_of(temp)
    if key is None:
        return None
    room.magic_temps[key] = temp
    active = room.magic_temp_data if isinstance(room.magic_temp_data, dict) else {}
    if not active or key_of(active) is None:
        room.magic_temp_data = temp
        return temp
    return None


def active(room: Room) -> dict[str, Any]:
    return room.magic_temp_data if isinstance(room.magic_temp_data, dict) else {}


def queued(room: Room) -> list[str]:
    current = key_of(active(room))
    return [key for key in room.magic_temps if key != current]


def finish(room: Room, key: str | None = None) -> dict[str, Any] | None:
    """清掉 `key`（默认当前激活项），提升下一项；返回被提升的项。"""

    current = active(room)
    target = key or key_of(current)
    if target:
        room.magic_temps.pop(target, None)
    if key_of(current) == target or not current:
        room.magic_temp_data = {}
        for pending_key in list(room.magic_temps):
            promoted = room.magic_temps.pop(pending_key)
            room.magic_temp_data = promoted
            # 让调用方（确认入口）知道现在轮到哪一项，客户端据此换面板。
            room.magic_promoted = promoted
            return promoted
    return None


def clear(room: Room) -> None:
    room.magic_temps.clear()
    room.magic_temp_data = {}
    room.magic_promoted = None


__all__ = ["active", "clear", "finish", "key_of", "queued", "store"]
