"""Magic-card playability and pre-deduction guards (ticket #10).

This module is the **only** server-side implementation of
`can_play_magic_card` and of the "previous shot" / ship-count requirements.
The front end may mirror it for greying-out cards, but the server decision is
authoritative.

`field_magic_name` (`domain/room/models.py`) and `action_wait_reason`
(`domain/battle.py`) are re-exported here for the ticket-era import paths; this
module does not implement them (CLAUDE #1: one implementation per rule).

`evaluate_cast` is the **one** pre-cast gate both activation paths
(`services.magic.use_magic_card` and `services.magic.chain_response`) call
(spec #35 §7), so the order and the wording of every refusal live here only.

速阶一按统一口径只允许在自己的准备阶段发动；卡面另有时点限制时先校验卡面。
"""

from __future__ import annotations

from typing import Any

from ..battle import action_wait_reason
from ..room import Room, RoomPhase
from ..room.models import field_magic_name
from .cards import MagicCard
from .interaction import ship_pick_blocked_reason

END_PHASE_PLAYABLE: tuple[str, ...] = ("Freezing！",)

# 滥竽充数补至标准六舰，不能把本次重摆要求的船数当作补船上限。
LANYU_TARGET_SHIPS = 6

#: 兵粮寸断: one roll, <3 fails, >=3 grants two skipped draw phases.
BINGLIANG_FAIL_BELOW = 3
BINGLIANG_SKIP_PHASES = 2
_FIELD_NAME = "禁忌果实"
_FIELD_NEGATION_CARDS = frozenset({"失灵！"})

#: Refusal text for a card whose effect is not registered yet. One wording for
#: both activation paths and for the settlement refund path (services/magic.py).
UNIMPLEMENTED = "【{name}】效果尚未接入（后续批次），本张卡未消耗"


def value(value: Any) -> Any:
    return getattr(value, "value", value)


def freezing_block_reason(room: Room, player_id: str, card: MagicCard) -> str | None:
    """Freezing！ needs first player + end phase + no enemy ship lost this turn."""

    if room.current_attacker != player_id:
        return "Freezing！只能在自己的结束阶段发动"
    if room.attack_order and room.attack_order[0] != player_id:
        return "Freezing！只能在自己先手的回合发动"
    if value(room.current_phase) != RoomPhase.END.value:
        return "Freezing！只能在结束阶段发动"
    if room.players[player_id].ship_reductions_this_turn > 0:
        return "本回合已使对方船数减少，无法发动 Freezing！"
    return None


def last_attack_requirement_reason(room: Room, player_id: str, card: MagicCard) -> str | None:
    """Cards whose face says "after your previous shot" (饮血/越战越勇/溅射/雷达子弹)."""

    if card.name not in ("饮血", "越战越勇", "溅射", "雷达子弹"):
        return None
    last = getattr(room, "last_attack", None)
    if not isinstance(last, dict) or last.get("attacker") != player_id:
        return f"{card.name}需要在自己攻击过之后才能使用"
    if card.name in ("饮血", "越战越勇"):
        if not last.get("ship_sunk"):
            return f"{card.name}需要在击沉对方一艘战舰后立即使用"
    elif not last.get("hit"):
        return f"{card.name}需要在自己上一发攻击命中对方后才能使用"
    return None


def wangyang_requirement_reason(room: Room, player_id: str, card: MagicCard) -> str | None:
    if card.name != "亡羊补牢":
        return None
    if not room.magic_discard:
        return "弃牌区没有卡牌，亡羊补牢无法发动"
    return None


def woxin_requirement_reason(room: Room, player_id: str, card: MagicCard) -> str | None:
    if card.name != "卧薪尝胆":
        return None
    opponent_id = room.opponent_of(player_id)
    if not opponent_id or opponent_id not in room.players:
        return None
    mine = room.players[player_id].remaining_ships
    theirs = room.players[opponent_id].remaining_ships
    if mine >= theirs:
        return f"自己的船数({mine})不小于对方({theirs})，卧薪尝胆无法发动"
    return None


def lanyu_requirement_reason(room: Room, player_id: str, card: MagicCard) -> str | None:
    if card.name != "滥竽充数":
        return None
    player = room.players[player_id]
    if player.remaining_ships >= LANYU_TARGET_SHIPS:
        return f"自己的船数已满({player.remaining_ships}/{LANYU_TARGET_SHIPS})，滥竽充数无法发动"
    if len(blocked_cells(room, player_id)) >= 36:
        return "棋盘已无可放置的格子，滥竽充数无法发动"
    return None


def blocked_cells(room: Room, player_id: str) -> set[tuple[int, int]]:
    blocked: set[tuple[int, int]] = set()
    opponent_id = room.opponent_of(player_id)
    if opponent_id:
        blocked |= {(a.x, a.y) for a in (room.players[opponent_id].attacks or [])}
    player = room.players[player_id]
    for ship in list(player.ships or []) + list(player.sunken_ships or []):
        blocked |= {(p.x, p.y) for p in (ship.positions or [])}
    for hole in room.game_effects.get("shenwei_holes") or []:
        if hole.get("player") == player_id:
            for x in range(hole["x1"], hole["x2"] + 1):
                for y in range(hole["y1"], hole["y2"] + 1):
                    blocked.add((x, y))
    return blocked


def can_play_magic_card(room: Room, player_id: str, card: MagicCard) -> bool:
    """统一发动时点与场地封锁，卡面限制优先于通用速阶。"""

    player = room.players.get(player_id)
    if player is None:
        return False
    if getattr(player.effect_flags, "last_stand", False):
        return False
    if field_magic_name(room) == _FIELD_NAME:
        if card.name not in _FIELD_NEGATION_CARDS and card.type != "场地":
            return False
    if card.name in END_PHASE_PLAYABLE:
        return freezing_block_reason(room, player_id, card) is None
    if card.name == "八方来财":
        return value(room.current_phase) == RoomPhase.PREPARATION.value
    if card.name == "神机妙算":
        own_turn = room.current_attacker == player_id
        return own_turn or value(room.current_phase) == RoomPhase.PREPARATION.value
    if card.name == "五险一金" and field_magic_name(room) == "教皇旨意":
        return False
    speed = int(card.speed)
    if speed == 3:
        return True
    if room.current_attacker != player_id:
        return False
    phase = value(room.current_phase)
    if phase == RoomPhase.PREPARATION.value:
        return speed in (1, 2)
    if phase == RoomPhase.BATTLE.value:
        return speed == 2
    if phase == RoomPhase.END.value:
        return card.name in END_PHASE_PLAYABLE
    return False


def playability_reason(room: Room, player_id: str, card: MagicCard) -> str:
    """Readable rejection text, in the same priority order as the legacy handler."""

    player = room.players[player_id]
    if getattr(player.effect_flags, "last_stand", False):
        return "绝处逢生生效中，本回合你的其余魔法卡全部无效"
    if field_magic_name(room) == _FIELD_NAME and not (
        card.name in _FIELD_NEGATION_CARDS or card.type == "场地"
    ):
        return "场地魔法“禁忌果实”生效中，只能使用失灵！与场地魔法卡"
    if card.name in END_PHASE_PLAYABLE:
        return freezing_block_reason(room, player_id, card) or ""
    if card.name == "八方来财":
        return "八方来财只能在双方的准备阶段使用"
    if card.name == "神机妙算":
        return "神机妙算只能在对方准备阶段，或自己的全部阶段使用"
    if card.name == "五险一金" and field_magic_name(room) == "教皇旨意":
        return "教皇旨意生效中，本回合攻击次数为0，五险一金无法发动"
    if int(card.speed) != 3 and room.current_attacker != player_id:
        return f"速阶{card.speed}的魔法卡只能在自己的回合使用（现在不是你的回合）"
    if int(card.speed) == 1:
        return "速阶1的魔法卡只能在自己的准备阶段使用"
    return f"当前阶段{value(room.current_phase)}无法使用速阶{card.speed}的魔法卡"


def evaluate_cast(room: Room, player_id: str, card: MagicCard) -> str | None:
    """The single pre-cast gate both activation paths share (spec #35 §7).

    Returns None when the cast may proceed, otherwise the exact wire wording
    of the refusal. The order is fixed: playability -> per-card requirements ->
    ship-pick obligation -> registry. Neither service may re-list these checks.
    """

    if not can_play_magic_card(room, player_id, card):
        return playability_reason(room, player_id, card)
    if card.name in ("盗亦有道", "亡羊补牢") and room.players[player_id].effect_flags.no_draw:
        return "无中生有效果生效中，本回合无法获得魔法卡"
    for reason in (
        last_attack_requirement_reason(room, player_id, card),
        wangyang_requirement_reason(room, player_id, card),
        woxin_requirement_reason(room, player_id, card),
        lanyu_requirement_reason(room, player_id, card),
    ):
        if reason:
            return reason
    blocked = ship_pick_blocked_reason(room, player_id, card.name)
    if blocked:
        return blocked
    # registry imports the effect batches, which import this module: resolve it
    # lazily so the gate module stays *below* the dispatch table.
    from .registry import is_implemented

    if not is_implemented(card):
        return UNIMPLEMENTED.format(name=card.name)
    return None


__all__ = [
    "BINGLIANG_FAIL_BELOW",
    "BINGLIANG_SKIP_PHASES",
    "END_PHASE_PLAYABLE",
    "LANYU_TARGET_SHIPS",
    "UNIMPLEMENTED",
    "action_wait_reason",
    "blocked_cells",
    "can_play_magic_card",
    "evaluate_cast",
    "field_magic_name",
    "freezing_block_reason",
    "lanyu_requirement_reason",
    "last_attack_requirement_reason",
    "playability_reason",
    "value",
    "wangyang_requirement_reason",
    "woxin_requirement_reason",
]
