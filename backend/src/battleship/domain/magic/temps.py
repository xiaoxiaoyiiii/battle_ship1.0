"""魔法卡「待选择项」的唯一存放点：一张激活、其余排队。

为什么需要它：老实现把待处理选择塞进 `room.magic_temp_data` 这一个槽里，第二张互动
牌（如灵气复苏）会直接覆盖第一张（仁王之盾）——前一个选择被静默丢弃、
`pending_ship_picks` 还留着没人能确认。

键为什么不是「卡牌类型」：两个玩家同时放仁王之盾时 type 都是 `shield_choice`，
按 type 存储会让第二个人覆盖第一个人，先确认的人 `finish` 还会把对方的项删掉。
所以存储键是**每次请求唯一的身份**：`<归属者>#<类型>#<序号>`；`type` 只用于协议
（前端认识的 `temp_data_id`）。消费时必须按「归属者 + 类型」匹配当前激活项，
别人的同类项一律不动。
"""

from __future__ import annotations

from typing import Any

from ..room.models import Room

#: 选择项的协议类型：普通项用 `type`，摆船用 `pending_placement`，神机妙算用
#: `pending_shenji`——这三类在老代码里就不是同一个形状。
_KEY_FIELDS = ("type", "pending_placement", "pending_shenji")


def key_of(temp: dict[str, Any]) -> str | None:
    """协议类型（`shield_choice` / `pending_placement` …），不是存储键。"""

    for field in _KEY_FIELDS:
        value = temp.get(field)
        if field == "type" and isinstance(value, str) and value:
            return value
        if field != "type" and isinstance(value, dict):
            return field
    return None


def owner_of(temp: dict[str, Any]) -> str | None:
    """谁的待选择项：普通项用 `caster`，摆船/神机在子字典里。"""

    caster = temp.get("caster")
    if isinstance(caster, str) and caster:
        return caster
    for field in ("pending_placement", "pending_shenji"):
        nested = temp.get(field)
        if isinstance(nested, dict):
            nested_caster = nested.get("caster") or nested.get("owner")
            if isinstance(nested_caster, str) and nested_caster:
                return nested_caster
    return None


def store(room: Room, temp: dict[str, Any]) -> dict[str, Any] | None:
    """把待选择项放进队列；返回被**激活**的那项（排队时返回 None）。"""

    kind = key_of(temp)
    if kind is None:
        return None
    owner = owner_of(temp) or "?"
    room.magic_temp_seq = int(getattr(room, "magic_temp_seq", 0) or 0) + 1
    identity = f"{owner}#{kind}#{room.magic_temp_seq}"
    temp["id"] = identity
    room.magic_temps[identity] = temp
    active = room.magic_temp_data if isinstance(room.magic_temp_data, dict) else {}
    if not active or key_of(active) is None:
        room.magic_temp_data = temp
        return temp
    return None


def active(room: Room) -> dict[str, Any]:
    return room.magic_temp_data if isinstance(room.magic_temp_data, dict) else {}


def queued(room: Room) -> list[str]:
    """排队中的项（不含当前激活），按入队顺序。"""

    current = str(active(room).get("id") or "")
    return [key for key in room.magic_temps if key != current]


def queued_kinds(room: Room) -> list[str]:
    """排队项的协议类型列表（探针/日志用；身份仍以 `queued` 的 id 为准）。"""

    return [key_of(item) or key for key, item in room.magic_temps.items() if key in queued(room)]


def _promote_next(room: Room) -> dict[str, Any] | None:
    room.magic_temp_data = {}
    for pending_key in list(room.magic_temps):
        promoted = room.magic_temps.pop(pending_key)
        room.magic_temp_data = promoted
        room.magic_promoted = promoted
        return promoted
    return None


def finish(room: Room, kind: str | None = None, *, owner: str | None = None) -> dict[str, Any] | None:
    """消费当前激活项并提升下一项；返回被提升的项。

    `kind`/`owner` 都给了就只有「确实是这个人的这一类」才会被消费——别人的同类
    选择项、以及已经换人的激活项都不会被误清。
    """

    current = active(room)
    if not current:
        return None
    if kind is not None and key_of(current) != kind:
        return None
    if owner is not None and owner_of(current) != owner:
        return None
    room.magic_temps.pop(str(current.get("id") or ""), None)
    room.magic_temp_data = {}
    room.magic_promoted = None
    return _promote_next(room)


def finish_id(room: Room, identity: str) -> dict[str, Any] | None:
    """按存储键消费（AI 同步完成的项用它，绝不按类型猜）。"""

    temp = room.magic_temps.pop(identity, None)
    if temp is None:
        return None
    current = active(room)
    if str(current.get("id") or "") == identity:
        room.magic_temp_data = {}
        room.magic_promoted = None
        return _promote_next(room)
    return None


def clear(room: Room) -> None:
    room.magic_temps.clear()
    room.magic_temp_data = {}
    room.magic_promoted = None


__all__ = [
    "active",
    "clear",
    "finish",
    "finish_id",
    "key_of",
    "owner_of",
    "queued",
    "queued_kinds",
    "store",
]
