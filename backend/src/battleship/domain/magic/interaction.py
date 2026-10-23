"""Player-interaction state for card effects (ticket #11).

Everything that waits for a human choice lives here as pure room mutation:
the per-player ship-pick priority queue, the discard-one-card obligation and
the mid-game placement rules. Services own the wire frames.

One table per concern; no second copy is allowed to drift from these.
"""

from __future__ import annotations

from typing import Any

from ..room import BOARD_SIZE, Player, PlayerShip, Position, Room, alive_ships

#: Card effects that wait for "click one of your own ships", by priority.
SHIP_PICK_PRIORITY: dict[str, int] = {
    "demon_contract": 100,
    "divine_decree": 80,
    "trap_setup": 75,
    "dice_sacrifice": 70,
    "kraken_eye": 60,
    "trap_sacrifice": 65,
    "shield_choice": 40,
}

SHIP_PICK_LABELS: dict[str, str] = {
    "demon_contract": "恶魔契约",
    "divine_decree": "神之宣告",
    "kraken_eye": "克苏鲁之眼",
    "shield_choice": "仁王之盾",
    "trap_setup": "守株待兔",
    "trap_sacrifice": "守株待兔",
    "dice_sacrifice": "命运骰子",
}

#: Only these reasons may actually sacrifice the clicked ship.
SACRIFICE_REASONS = frozenset({
    "demon_contract",
    "divine_decree",
    "dice_sacrifice",
    "trap_sacrifice",
})

SHIP_PICK_CARDS: dict[str, str] = {
    "克苏鲁之眼": "kraken_eye",
    "神之宣告": "divine_decree",
    "仁王之盾": "shield_choice",
    "命运骰子": "dice_sacrifice",
    "守株待兔": "trap_setup",
}


def ship_pick_priority(reason: Any) -> int:
    try:
        return int(SHIP_PICK_PRIORITY.get(str(reason), 0))
    except (TypeError, ValueError):
        return 0


def my_ship_picks(room: Room, player_id: str | None) -> list[dict[str, Any]]:
    picks = getattr(room, "pending_ship_picks", None)
    if not isinstance(picks, list) or not player_id:
        return []
    mine = [p for p in picks if isinstance(p, dict) and p.get("player") == player_id]
    mine.sort(key=lambda p: (-ship_pick_priority(p.get("reason")), int(p.get("seq") or 0)))
    return mine


def top_ship_pick(room: Room, player_id: str | None) -> dict[str, Any] | None:
    mine = my_ship_picks(room, player_id)
    return mine[0] if mine else None


def register_ship_pick(
    room: Room,
    player_id: str,
    reason: str,
    message: str,
    *,
    allow_duplicate: bool = False,
    silent: bool = False,
) -> dict[str, Any] | None:
    """Queue one pick; returns the existing entry when de-duplicated."""

    picks = getattr(room, "pending_ship_picks", None)
    if not isinstance(picks, list):
        room.pending_ship_picks = picks = []
    if not allow_duplicate:
        for pick in picks:
            if (
                isinstance(pick, dict)
                and pick.get("player") == player_id
                and pick.get("reason") == reason
            ):
                return pick
    room.ship_pick_seq = int(getattr(room, "ship_pick_seq", 0) or 0) + 1
    entry = {
        "player": player_id,
        "reason": reason,
        "message": message,
        "priority": ship_pick_priority(reason),
        "seq": room.ship_pick_seq,
    }
    if silent:
        entry["silent"] = True
    picks.append(entry)
    return None


def consume_ship_pick(room: Room, player_id: str, reason: str | None = None) -> bool:
    picks = getattr(room, "pending_ship_picks", None)
    if not isinstance(picks, list):
        return False
    top = top_ship_pick(room, player_id)
    if top is None:
        return False
    if reason is not None and top.get("reason") != reason:
        return False
    try:
        picks.remove(top)
    except ValueError:
        return False
    return True


def clear_ship_picks(room: Room, player_id: str | None = None) -> None:
    picks = getattr(room, "pending_ship_picks", None)
    if not isinstance(picks, list):
        return
    if player_id is None:
        room.pending_ship_picks = []
    else:
        room.pending_ship_picks = [
            p for p in picks
            if not (isinstance(p, dict) and p.get("player") == player_id)
        ]


def clear_ship_picks_by_reason(room: Room, reason: str) -> list[dict[str, Any]]:
    if not reason:
        return []
    picks = getattr(room, "pending_ship_picks", None)
    if not isinstance(picks, list):
        return []
    removed = [p for p in picks if isinstance(p, dict) and p.get("reason") == reason]
    if not removed:
        return []
    room.pending_ship_picks = [
        p for p in picks if not (isinstance(p, dict) and p.get("reason") == reason)
    ]
    return removed


def ship_pick_blocked_reason(room: Room, player_id: str, card_name: str) -> str:
    wanted = SHIP_PICK_CARDS.get(str(card_name or ""))
    if not wanted:
        return ""
    top = top_ship_pick(room, player_id)
    if top is None:
        return ""
    if ship_pick_priority(top.get("reason")) <= ship_pick_priority(wanted):
        return ""
    label = SHIP_PICK_LABELS.get(str(top.get("reason")), "一个待处理的选船效果")
    return f"请先完成「{label}」的选船，再使用这张卡"


def find_ship_at(player: Player, cell: tuple[int, int], *, alive_only: bool = True) -> PlayerShip | None:
    for ship in player.ships or []:
        if alive_only and not _alive(player, ship):
            continue
        if any(pos.x == cell[0] and pos.y == cell[1] for pos in ship.positions or []):
            return ship
    return None


def _alive(player: Player, ship: PlayerShip) -> bool:
    from ..room import is_ship_alive

    return is_ship_alive(player, ship)


def pick_cell_from_target(target_data: Any) -> tuple[int, int] | None:
    if not isinstance(target_data, dict):
        return None
    area = target_data.get("target_area")
    if isinstance(area, dict):
        try:
            return int(area["x1"]), int(area["y1"])
        except (KeyError, TypeError, ValueError):
            return None
    if "x" in target_data and "y" in target_data:
        try:
            return int(target_data["x"]), int(target_data["y"])
        except (TypeError, ValueError):
            return None
    return None


# ------------------------------------------------------------------ placement


def own_occupied_cells(player: Player, *, ignore_sunken: bool = False) -> set[tuple[int, int]]:
    cells: set[tuple[int, int]] = set()
    for ship in player.ships or []:
        if ignore_sunken and not _alive(player, ship):
            continue
        for pos in ship.positions or []:
            cells.add((pos.x, pos.y))
    if not ignore_sunken:
        for ship in player.sunken_ships or []:
            for pos in ship.positions or []:
                cells.add((pos.x, pos.y))
    return cells


def _shenwei_blocked(room: Room, player_id: str) -> set[tuple[int, int]]:
    blocked: set[tuple[int, int]] = set()
    for hole in room.game_effects.get("shenwei_holes") or []:
        if not isinstance(hole, dict) or hole.get("player") != player_id:
            continue
        for x in range(int(hole["x1"]), int(hole["x2"]) + 1):
            for y in range(int(hole["y1"]), int(hole["y2"]) + 1):
                blocked.add((x, y))
    return blocked


def placement_blocked_cells(
    room: Room, player_id: str, *, ignore_sunken: bool = False
) -> list[dict[str, int]]:
    blocked: set[tuple[int, int]] = set()
    opponent_id = room.opponent_of(player_id)
    if opponent_id:
        for attack in room.players[opponent_id].attacks or []:
            blocked.add((attack.x, attack.y))
    blocked |= own_occupied_cells(room.players[player_id], ignore_sunken=ignore_sunken)
    blocked |= _shenwei_blocked(room, player_id)
    return [{"x": x, "y": y} for (x, y) in sorted(blocked)]


def placement_blocked_for(
    room: Room, player_id: str, pending: dict[str, Any] | None
) -> list[dict[str, int]]:
    """同一份禁止格：实时 `placement_request` 与重连快照都用它。

    `last_stand` 只允许原本有船的格子、`shenji_redeploy` 允许沉船格与自己未被打过的
    格；两条规则**只能有一处实现**，否则刷新前后看到的合法格会不一样。
    """

    kind = (pending or {}).get("kind")
    if kind == "shenji_redeploy":
        allowed = {
            xy
            for xy in (
                cell_xy(a)
                for a in (room.game_effects.get("shenji_redeploy_cells") or [])
            )
            if xy
        }
        return [
            cell
            for cell in placement_blocked_cells(room, player_id, ignore_sunken=True)
            if (cell["x"], cell["y"]) not in allowed
        ]
    blocked = placement_blocked_cells(room, player_id)
    if kind == "last_stand":
        allowed = {
            xy
            for xy in (
                cell_xy(a)
                for a in (room.game_effects.get("last_stand_cells") or [])
            )
            if xy
        }
        return [cell for cell in blocked if (cell["x"], cell["y"]) not in allowed]
    return blocked


def placement_allowed_for(
    room: Room, pending: dict[str, Any] | None
) -> list[Any]:
    """与 `placement_blocked_for` 配套的「必须落在这些格」清单。"""

    kind = (pending or {}).get("kind")
    if kind == "last_stand":
        return list(room.game_effects.get("last_stand_cells") or [])
    if kind == "shenji_redeploy":
        return list(room.game_effects.get("shenji_redeploy_cells") or [])
    return []


def placement_error(
    room: Room,
    player_id: str,
    x: int,
    y: int,
    *,
    allow_cells: set[tuple[int, int]] | None = None,
    ignore_sunken: bool = False,
) -> str | None:
    if not (0 <= x < BOARD_SIZE and 0 <= y < BOARD_SIZE):
        return "坐标超出棋盘范围"
    allow = allow_cells or set()
    opponent_id = room.opponent_of(player_id)
    if opponent_id:
        if (x, y) in {(a.x, a.y) for a in room.players[opponent_id].attacks or []} and (
            x, y
        ) not in allow:
            return "该位置已被对方攻击过，不能放置"
    if (x, y) in _shenwei_blocked(room, player_id):
        return "该区域已被神威！扣掉，不能放置"
    if (x, y) in own_occupied_cells(room.players[player_id], ignore_sunken=ignore_sunken):
        return "该位置已被己方战舰占用"
    return None


def cell_xy(cell: Any) -> tuple[int, int] | None:
    if isinstance(cell, dict):
        x, y = cell.get("x"), cell.get("y")
    elif isinstance(cell, (list, tuple)) and len(cell) >= 2:
        x, y = cell[0], cell[1]
    else:
        return None
    try:
        return int(x), int(y)
    except (TypeError, ValueError):
        return None


__all__ = [
    "SACRIFICE_REASONS",
    "SHIP_PICK_CARDS",
    "SHIP_PICK_LABELS",
    "SHIP_PICK_PRIORITY",
    "cell_xy",
    "clear_ship_picks",
    "clear_ship_picks_by_reason",
    "consume_ship_pick",
    "find_ship_at",
    "my_ship_picks",
    "own_occupied_cells",
    "pick_cell_from_target",
    "placement_allowed_for",
    "placement_blocked_cells",
    "placement_blocked_for",
    "placement_error",
    "register_ship_pick",
    "ship_pick_blocked_reason",
    "ship_pick_priority",
    "top_ship_pick",
]
