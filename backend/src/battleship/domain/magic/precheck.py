"""出牌前的目标预检：能在扣牌之前判断的，绝不拖到结算。

为什么单独一层：`sanitize_targets` 只看坐标与形状，不碰棋盘状态；但像「神之宣告」
这种要求「恰好两艘自己的活舰」的卡，等到结算再发现目标失效就已经入连锁、进了弃牌
堆，只能靠退款补救。把这类检查放到**扣牌之前**，无效目标就完全没有副作用。
"""

from __future__ import annotations

from typing import Any

from ..room.models import Room, alive_ships, is_ship_alive
from .interaction import cell_xy, find_ship_at

#: 结算阶段重新校验用：目标船必须仍然活着且互不相同。
DIVINE_DECREE_SHIPS = 2


def _selected_ships(room: Room, player_id: str, targets: dict[str, Any]) -> list[Any]:
    """按 `selected_cells` 取自己的活舰（保序、去重）。"""

    player = room.players.get(player_id)
    if player is None:
        return []
    raw = targets.get("selected_cells") if isinstance(targets, dict) else None
    if not isinstance(raw, list):
        return []
    picked: list[Any] = []
    for cell in raw:
        xy = cell_xy(cell)
        if xy is None:
            continue
        ship = find_ship_at(player, xy, alive_only=True)
        if ship is not None and ship not in picked:
            picked.append(ship)
    return picked


def divine_decree_error(room: Room, player_id: str, targets: dict[str, Any]) -> str | None:
    """神之宣告：必须显式选中恰好两艘不同的己方活舰，并给出合法分支。"""

    player = room.players.get(player_id)
    if player is None:
        return "房间人数不足"
    if int(player.remaining_ships or 0) <= 2:
        return "您的船数不足，无法使用神之宣告"
    picked = _selected_ships(room, player_id, targets)
    if len(picked) != DIVINE_DECREE_SHIPS:
        return "请先选中自己两艘要牺牲的战舰"
    raw = targets.get("selected_cells") or []
    if len(raw) < DIVINE_DECREE_SHIPS:
        return "请先选中自己两艘要牺牲的战舰"
    choice = targets.get("effect_choice")
    if choice is None:
        return "请选择神之宣告的后续效果"
    try:
        choice_value = int(choice)
    except (TypeError, ValueError):
        return "神之宣告的效果选择非法"
    if choice_value not in (1, 2):
        return "神之宣告的效果选择非法"
    return None


STEAL_CARD = "盗亦有道"


def steal_error(room: Room, player_id: str) -> str | None:
    """盗亦有道：对手还没有「可被偷」的结算记录时就别入链。

    旧行为是把卡打出去、扣牌、入连锁，结算时才发现无牌可偷，再靠退款把卡塞回手里；
    玩家看到的是「打出成功但卡还在」外加一次空连锁，很容易以为要再打一次才生效。
    """

    for entry in reversed(getattr(room, "magic_history", []) or []):
        if entry.get("caster") == player_id:
            continue
        if entry.get("stolen"):
            continue
        return None
    return "对方还没有使用过魔法卡，盗亦有道无法发动"


def precheck(room: Room, player_id: str, card_name: str, targets: dict[str, Any]) -> str | None:
    """扣牌前的状态级校验入口；None 表示放行。"""

    if card_name == "神之宣告":
        return divine_decree_error(room, player_id, targets)
    if card_name == STEAL_CARD:
        return steal_error(room, player_id)
    return None


def resolution_error(
    room: Room, player_id: str, card_name: str, targets: dict[str, Any]
) -> str | None:
    """入链之后、真正动手之前再查一次：目标在连锁响应里被弄死就整体失败。"""

    if card_name != "神之宣告":
        return None
    player = room.players.get(player_id)
    if player is None:
        return "房间人数不足"
    picked = _selected_ships(room, player_id, targets)
    if len(picked) != DIVINE_DECREE_SHIPS:
        return "目标战舰已失效，神之宣告未能生效"
    if not all(is_ship_alive(player, ship) for ship in picked):
        return "目标战舰已失效，神之宣告未能生效"
    _ = alive_ships(player)
    return None


__all__ = [
    "DIVINE_DECREE_SHIPS",
    "STEAL_CARD",
    "steal_error",
    "divine_decree_error",
    "precheck",
    "resolution_error",
]
