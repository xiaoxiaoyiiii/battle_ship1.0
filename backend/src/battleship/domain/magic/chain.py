"""Chain stack shapes and rules (ticket #12).

The stack is LIFO: the last card pushed resolves first. This module owns the
pure parts only -- who may respond, what a negation card targets, and whether
「平等条约」 may negate a given stack item. Wire frames, timers and effect
execution live in :mod:`battleship.services.magic`; card behaviour lives in
`battleship.domain.magic.effects`.

Legacy reference: server.py:9189-9422 (negation target + treaty table),
9425-9446 (response gate), 9642-9765 (resolution order). DECISIONS D2: a
negated item is skipped outright (field cards only go to the discard pile), not
"placed then torn down" as CLAUDE.md used to describe.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..ai.difficulty import difficulty_of
from ..room import Room, RoomState, alive_ships, opponent_of
from .cards import MagicCard
from .rules import blocked_cells, evaluate_cast, lanyu_requirement_reason

#: The response window every responder gets (legacy CHAIN_RESPONSE_SECONDS).
CHAIN_RESPONSE_SECONDS = 10


@dataclass
class ChainItem:
    player_id: str
    card: MagicCard
    targets: Any = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    negated: bool = False
    negated_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "card": self.card.to_payload(),
            "targets": self.targets,
            "timestamp": self.timestamp,
            "negated": self.negated,
            "negated_by": self.negated_by,
        }


@dataclass
class ChainResult:
    card: MagicCard
    caster: str
    success: bool = True
    message: str = ""
    negate_target: bool = False
    negated_skip: bool = False
    negated_by: str | None = None
    affected_positions: list[Any] = field(default_factory=list)
    game_over: bool = False
    #: Card-specific payload keys (cards / max_ships / ...) frozen from the
    #: legacy ChainResult.__dict__ dump.
    extra: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "card": self.card.to_payload(),
            "caster": self.caster,
            "success": self.success,
            "message": self.message,
        }
        if self.negate_target:
            payload["negate_target"] = True
        if self.negated_skip:
            payload["negated_skip"] = True
            payload["negated_by"] = self.negated_by
        if self.affected_positions:
            payload["affected_positions"] = [
                _position_payload(pos) for pos in self.affected_positions
            ]
        if self.game_over:
            payload["game_over"] = True
        for key, value in (self.extra or {}).items():
            payload.setdefault(key, value)
        return payload


def _position_payload(position: Any) -> Any:
    if isinstance(position, dict):
        return position
    if all(hasattr(position, key) for key in ("x", "y")):
        return {
            "x": int(position.x),
            "y": int(position.y),
            "hit": bool(getattr(position, "hit", False)),
            "ship_sunk": bool(getattr(position, "ship_sunk", False)),
        }
    return position


# --------------------------------------------------------------------- window


def speed3_cards(player: Any) -> list[MagicCard]:
    """The responder's own speed-3 cards (legacy `_speed3_cards`)."""

    if player is None:
        return []
    return [card for card in player.magic_hand if int(card.speed) == 3]


def usable_speed3_cards(room: Room, player_id: str | None) -> list[MagicCard]:
    """Speed-3 cards this player could actually chain **right now**.

    手牌里有速阶3 不等于能出：`can_play_magic_card` 对速阶3 恒为 True，卡片专属
    条件（亡羊补牢没弃牌、卧薪尝胆船数不够、滥竽充数船已满、效果未接入…）只在
    `evaluate_cast` 里拦。窗口按「有没有一张能出」开：否则玩家看到的是一个没有
    任何可点选项的 10 秒窗口，双方都只能等超时才结算（实测 AI 出牌 → 人类连锁 →
    AI 无合法响应 pass → 人类只剩不可用速阶3，结算被拖到 10.02s）。
    """

    if not player_id:
        return []
    player = room.players.get(player_id)
    if player is None:
        return []
    return [
        card
        for card in player.magic_hand
        if int(card.speed) == 3 and evaluate_cast(room, str(player_id), card) is None
    ]


def ai_can_negate_chain_top(room: Room, ai_id: str) -> bool:
    """失灵与平等条约只反制对手的非免疫栈顶，避免自我无效化。"""

    if not room.chain:
        return False
    top = room.chain[-1]
    if getattr(top, "player_id", None) == ai_id:
        return False
    return getattr(getattr(top, "card", None), "name", None) not in (
        "看破！",
        "加百列之光",
    )


def choose_ai_response_card(room: Room, player_id: str) -> MagicCard | None:
    """困难和大师的反制选择，开窗与实际响应共用此入口。"""

    player = room.players.get(player_id)
    if (difficulty_of(room, player_id) not in ("hard", "master")
            or player is None or not room.chain
            or room.chain[-1].player_id == player_id):
        return None
    if (player.magic_blocked
            and getattr(player, "magic_blocked_round", room.round) == room.round
            or getattr(player.effect_flags, "last_stand", False)):
        return None
    usable = usable_speed3_cards(room, player_id)
    # 能用失灵时保留加百列；平等条约额外遵守真实船数变化判据。
    for name in ("失灵！", "平等条约", "加百列之光"):
        card = next((card for card in usable if card.name == name), None)
        if card is None:
            continue
        if name != "加百列之光" and not ai_can_negate_chain_top(room, player_id):
            continue
        if name == "平等条约" and not equal_treaty_verdict(room, room.chain[-1])[0]:
            continue
        return card
    return None


def can_respond(room: Room, player_id: str | None) -> bool:
    """Whether this player may respond with a speed-3 card right now."""

    if not player_id:
        return False
    player = room.players.get(player_id)
    if player is None or (
        player.magic_blocked
        and getattr(player, "magic_blocked_round", room.round) == room.round
    ):
        return False
    # 绝处逢生 locks every other magic card for the turn, chained responses included.
    if getattr(player.effect_flags, "last_stand", False):
        return False
    if player_id.startswith("ai-"):
        return choose_ai_response_card(room, player_id) is not None
    return bool(usable_speed3_cards(room, player_id))


def clear_display(room: Room) -> None:
    room.chain_display_token = None
    room.chain_display_deadline = None


def display_still_current(room: Room, token: int) -> bool:
    """The display-delay task may resolve only once, and only while current."""

    if not room.chain:
        return False
    if room.chain_timer != token:
        return False
    if getattr(room.state, "value", room.state) == RoomState.GAME_OVER.value:
        return False
    return not room.chain_waiting


# ------------------------------------------------------------- negation rules


def negation_target(room: Room, self_name: str) -> tuple[ChainItem | None, str | None]:
    """「无效化正下方那一项」的目标解析 + 免疫关系 (single implementation).

    Contract: the current item has already been popped, so `room.chain[-1]` is
    the item directly below it (the next one to resolve). 失灵！ and 平等条约
    share this function so a future immunity rule cannot apply to only one.
    """

    if not room.chain:
        return None, f"{self_name}只能在连锁中发动：现在没有可无效化的「正下方那一项」"
    target = room.chain[-1]
    name = getattr(getattr(target, "card", None), "name", None)
    if name == "看破！":
        return None, f"看破！优先于{self_name}，无法无效化"
    if name == "加百列之光":
        return None, f"加百列之光免疫{self_name}"
    return target, None


#: target item -> does this card really change a player's ship count?
TreatyPredicate = Callable[[Room, ChainItem], bool]


def _treaty_kill_hits_alive_ship(room: Room, target_item: ChainItem,
                                 cells: Any) -> bool:
    """At least one *living* ship sits on these cells (bomb / sulfur shared)."""

    victim_id = opponent_of(room, target_item.player_id)
    victim = room.players.get(victim_id) if victim_id else None
    if victim is None:
        return False
    wanted = {
        (int(cell["x"]), int(cell["y"]))
        for cell in cells
        if isinstance(cell, dict) and "x" in cell and "y" in cell
    }
    if not wanted:
        return False
    return any(
        (position.x, position.y) in wanted
        for ship in alive_ships(victim)
        for position in ship.positions
    )


def _treaty_bomb_line_kills(room: Room, target_item: ChainItem) -> bool:
    targets = target_item.targets if isinstance(target_item.targets, dict) else {}
    line = targets.get("target_line")
    if not isinstance(line, dict):
        return False
    try:
        index = int(line.get("index"))
    except (TypeError, ValueError):
        return False
    if not 0 <= index < 6:
        return False
    if line.get("type") == "row":
        cells = [{"x": x, "y": index} for x in range(6)]
    elif line.get("type") == "col":
        cells = [{"x": index, "y": y} for y in range(6)]
    else:
        return False
    return _treaty_kill_hits_alive_ship(room, target_item, cells)


def _treaty_sulfur_kills(room: Room, target_item: ChainItem) -> bool:
    targets = target_item.targets if isinstance(target_item.targets, dict) else {}
    cells = targets.get("target_cells")
    if not isinstance(cells, list) or len(cells) != 6:
        return False
    return _treaty_kill_hits_alive_ship(room, target_item, cells)


def _treaty_splash_kills(room: Room, target_item: ChainItem) -> bool:
    """Splash reads `room.last_attack` (it has no targets of its own)."""

    last = room.last_attack or {}
    if last.get("attacker") != target_item.player_id or not last.get("hit"):
        return False
    try:
        x, y = int(last["x"]), int(last["y"])
    except (KeyError, TypeError, ValueError):
        return False
    neighbors = {(x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)}
    neighbors = {(a, b) for (a, b) in neighbors if 0 <= a < 6 and 0 <= b < 6}
    victim_id = opponent_of(room, target_item.player_id)
    victim = room.players.get(victim_id) if victim_id else None
    if victim is None:
        return False
    for ship in alive_ships(victim):
        hits = {(hit.x, hit.y) for hit in (ship.hits or [])}
        if any(
            (position.x, position.y) in neighbors
            and (position.x, position.y) not in hits
            for position in ship.positions
        ):
            return True
    return False


def _treaty_revive_has_wreck(room: Room, target_item: ChainItem) -> bool:
    player = room.players.get(target_item.player_id)
    return bool(player is not None and getattr(player, "sunken_ships", None))


def _treaty_reinforce_has_cell(room: Room, target_item: ChainItem) -> bool:
    if target_item.player_id not in room.players:
        return False
    return len(blocked_cells(room, target_item.player_id)) < 36


def _treaty_lanyu_refills(room: Room, target_item: ChainItem) -> bool:
    if target_item.player_id not in room.players:
        return False
    return lanyu_requirement_reason(room, target_item.player_id, target_item.card) is None


def _treaty_shenji_can_restore(room: Room, target_item: ChainItem) -> bool:
    player = room.players.get(target_item.player_id)
    return bool(player is not None and alive_ships(player))


def _treaty_last_stand_self_sacrifice(room: Room, target_item: ChainItem) -> bool:
    player = room.players.get(target_item.player_id)
    return bool(player is not None and alive_ships(player))


#: The single "can 平等条约 negate this" table (author's 2026-09-24 ruling).
EQUAL_TREATY_SHIP_CHANGE_RULES: dict[str, tuple[TreatyPredicate, str]] = {
    "轰炸": (_treaty_bomb_line_kills, "目标行/列里必须有还活着的船；打在空行/空列上不沉船"),
    "硫磺火焰": (_treaty_sulfur_kills, "选定的 6 个格子里必须有还活着的船"),
    "溅射": (_treaty_splash_kills, "上一发命中格的上下左右四格里必须有仍可被溅射击沉的战舰（护盾无效）"),
    "疗愈": (_treaty_revive_has_wreck, "场上没有可复活的沉船时不会复活"),
    "死者苏生": (_treaty_revive_has_wreck, "同上（与疗愈共用同一个判据函数）"),
    "增援": (_treaty_reinforce_has_cell, "棋盘上还有可放置的空格才会真的 +1"),
    "滥竽充数": (_treaty_lanyu_refills, "与它自己的出牌闸门同一份判据（船数未满 + 有空格）"),
    "神机妙算": (_treaty_shenji_can_restore, "★ 只判到必要条件（还有活船可沉）：改船数与否要等它自己结算后才宣言 x"),
    "绝处逢生": (_treaty_last_stand_self_sacrifice, "牺牲自己全部战舰 ⇒ 只要有活船就真的会改船数"),
}

#: Cards explicitly ruled *not* negatable by 平等条约, with the reason.
EQUAL_TREATY_NOT_NEGOTIABLE: dict[str, str] = {
    "恶魔契约": "作者已裁：它造成的「牺牲」不算可被无效化的船数变化",
    "神之宣告": "同上（牺牲两艘自己的船，再让对方牺牲一艘）",
    "命运骰子": "同上（摇到 6 点让对方牺牲）",
    "守株待兔": "同上（陷阱触发后让对方牺牲）",
}


def equal_treaty_verdict(room: Room, target_item: ChainItem) -> tuple[bool, str]:
    """The only consumer of the treaty table: (would change, readable reason)."""

    name = getattr(getattr(target_item, "card", None), "name", None)
    row = EQUAL_TREATY_SHIP_CHANGE_RULES.get(name)
    if row is None:
        return False, f"{name}不会造成可被无效化的船数变化"
    predicate, why = row
    try:
        return bool(predicate(room, target_item)), why
    except Exception as error:  # noqa: BLE001 - unknown must fail closed, not silently
        return False, f"{name}的船数变化判据无法判定（{error!r}）"


__all__ = [
    "CHAIN_RESPONSE_SECONDS",
    "ChainItem",
    "ChainResult",
    "EQUAL_TREATY_NOT_NEGOTIABLE",
    "EQUAL_TREATY_SHIP_CHANGE_RULES",
    "ai_can_negate_chain_top",
    "can_respond",
    "choose_ai_response_card",
    "clear_display",
    "display_still_current",
    "equal_treaty_verdict",
    "negation_target",
    "speed3_cards",
]
