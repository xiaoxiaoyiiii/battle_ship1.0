"""出牌前的目标预检：能在扣牌之前判断的，绝不拖到结算。

为什么单独一层：`sanitize_targets` 只看坐标与形状，不碰棋盘状态；但像「神之宣告」
这种要求「恰好两艘自己的活舰」的卡，等到结算再发现目标失效就已经入连锁、进了弃牌
堆，只能靠退款补救。把这类检查放到**扣牌之前**，无效目标就完全没有副作用。
"""

from __future__ import annotations

from typing import Any

from ..room.models import Player, PlayerShip, Room, alive_ships, is_ship_alive
from .interaction import cell_xy, find_ship_at
from .cards import MagicCard

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


def healing_candidates(player: Player) -> list[PlayerShip]:
    """原位置没有活舰占用的沉船，去掉重复记录。"""
    occupied = {(p.x, p.y) for ship in alive_ships(player) for p in ship.positions}
    candidates: list[PlayerShip] = []
    for ship in player.sunken_ships:
        if not ship.positions or any((p.x, p.y) in occupied for p in ship.positions):
            continue
        if not any(ship is other for other in candidates):
            candidates.append(ship)
    return candidates


def healing_ships(room: Room, player_id: str, targets: dict[str, Any]) -> list[PlayerShip]:
    """只返回明确选定的沉船，不替玩家补选其它目标。"""
    player = room.players.get(player_id)
    raw = targets.get('selected_cells')
    if player is None or not isinstance(raw, list):
        return []
    candidates = healing_candidates(player)
    picked: list[PlayerShip] = []
    for cell in raw:
        xy = cell_xy(cell)
        ship = next((s for s in candidates if any((p.x, p.y) == xy for p in s.positions)), None)
        if ship is not None and not any(ship is other for other in picked):
            picked.append(ship)
    return picked


def healing_error(room: Room, player_id: str, targets: dict[str, Any]) -> str | None:
    raw = targets.get('selected_cells')
    if targets.get('board', 'self') != 'self':
        return '疗愈只能选择自己的沉船'
    if not isinstance(raw, list) or not 1 <= len(raw) <= 2:
        return '请选择一艘或两艘要原地复活的沉船'
    if len(healing_ships(room, player_id, targets)) != len(raw):
        return '请选择不同的己方沉船，且原位置不能被活舰占用'
    return None


def steal_candidate(room: Room, player_id: str) -> tuple[MagicCard, Any] | None:
    """按宣告先后取对手最近的未盗卡，已结算记录与当前连锁共用规则。"""

    candidates: list[tuple[float, int, MagicCard, Any]] = []
    for index, entry in enumerate(getattr(room, "magic_history", []) or []):
        if entry.get("caster") == player_id or entry.get("stolen"):
            continue
        card = entry.get("card")
        if card is not None:
            declared_at = float(entry.get("declared_at", entry.get("timestamp", 0)) or 0)
            candidates.append((declared_at, index, card, entry))
    offset = len(room.magic_history)
    for index, item in enumerate(room.chain):
        if item.player_id == player_id or getattr(item, "stolen", False):
            continue
        candidates.append((float(item.timestamp), offset + index, item.card, item))
    if not candidates:
        return None
    _timestamp, _index, card, source = max(candidates, key=lambda value: value[:2])
    return card, source


def steal_error(room: Room, player_id: str) -> str | None:
    """没有可盗卡时在扣牌前拒绝，当前连锁中的卡也属于已打出的卡。"""

    return None if steal_candidate(room, player_id) else "对方还没有使用过魔法卡，盗亦有道无法发动"


def precheck(room: Room, player_id: str, card_name: str, targets: dict[str, Any]) -> str | None:
    """扣牌前的状态级校验入口；None 表示放行。"""

    if card_name == '钢筋铁骨':
        if len(alive_ships(room.players[player_id])) < 2:
            return '需要至少两艘活舰才能发动钢筋铁骨'
        raw = targets.get('selected_cells')
        if targets.get('board', 'self') != 'self' or not isinstance(raw, list) or len(raw) != 1 or len(_selected_ships(room, player_id, targets)) != 1:
            return '请选择一艘自己的存活战舰作为钢筋铁骨的牺牲目标'
        return None
    if card_name == "神之宣告":
        return divine_decree_error(room, player_id, targets)
    if card_name == STEAL_CARD:
        return steal_error(room, player_id)
    if card_name == '疗愈':
        return healing_error(room, player_id, targets)
    return None


def resolution_error(
    room: Room, player_id: str, card_name: str, targets: dict[str, Any]
) -> str | None:
    """入链之后、真正动手之前再查一次：目标在连锁响应里被弄死就整体失败。"""

    if card_name == '钢筋铁骨':
        return precheck(room, player_id, card_name, targets)
    if card_name == '疗愈':
        return healing_error(room, player_id, targets)
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
    "healing_candidates",
    "healing_ships",
    "healing_error",
    "divine_decree_error",
    "precheck",
    "resolution_error",
]
