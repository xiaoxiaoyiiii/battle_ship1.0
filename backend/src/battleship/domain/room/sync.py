"""Assembly of the `room_sync` reconnect snapshot.

The authoritative shape is the legacy `_build_room_sync` (server.py:10498-10639),
frozen at **45 top-level keys** (DECISIONS D9). Field names and default semantics
must stay identical; `RoomSync` in `contracts.events_out` validates the result so
a missing/extra key fails loudly instead of silently changing the wire shape.

Ticket #7 owns the keys that describe the room skeleton, seats, board attacks and
reconnect bookkeeping. Keys that belong to later tickets (chain sanitisation,
placement panel, ship-pick queue, effect badges with card text) are produced from
the room state that already exists, with the same empty/default shapes the old
server sends when those subsystems are idle.
"""

from __future__ import annotations

from typing import Any

from ...contracts.identity import RoomKind
from ..magic import interaction as interaction_rules
from .models import (
    PUBLIC_EFFECT_FLAGS,
    Player,
    Room,
    RoomState,
    alive_ships,
    field_magic_name,
    is_ship_alive,
    opponent_of,
    opponent_seat_state,
    room_match_mode,
    seat_label,
    turn_timing,
)

#: Legacy `_EFFECT_BADGES`: (effect_flags field, card name, expiry text, suffix).
EFFECT_BADGES: tuple[tuple[str, str, str, str], ...] = (
    ("subsidy", "百亿补贴", "本回合结束时失效", ""),
    ("wuxian", "五险一金", "本回合攻击次数第一次归零时触发一次，触发后失效", ""),
    ("vampire", "饮血", "本回合结束时失效", ""),
    ("treasure_hunter", "八方来财", "本回合结束时失效", ""),
    ("prediction", "神机妙算", "本大回合结束（重新猜拳）时失效", ""),
    ("double_attacks", "火力全开", "本回合结束时失效", ""),
    ("battle_spirit", "越战越勇", "本回合结束时失效", ""),
    ("last_stand", "绝处逢生", "本回合结束时失效", "锁卡"),
    ("last_stand_win", "绝处逢生", "本局一直有效", "击杀即胜"),
    ("no_draw", "无中生有", "本大回合结束（重新猜拳）时失效", ""),
)

PRIORITY_ACTION_TEXT = {
    "enter_battle": "进入战斗阶段",
    "enter_end": "进入结束阶段",
}

def _my_magic_temp(room: Room, player_id: str) -> dict[str, Any] | None:
    """自己的待选魔法项（对手与观战永远拿不到）。"""

    temp = room.magic_temp_data if isinstance(room.magic_temp_data, dict) else {}
    if not temp:
        return None
    caster = temp.get("caster")
    if caster is None and isinstance(temp.get("pending_placement"), dict):
        caster = temp["pending_placement"].get("caster")
    if caster is None and isinstance(temp.get("pending_shenji"), dict):
        caster = temp["pending_shenji"].get("caster")
    if caster != player_id:
        return None
    return dict(temp)


def room_kind(room: Room) -> RoomKind:
    if room.is_ai_room:
        return RoomKind.AI
    if room.matchmade:
        return RoomKind.MATCHMAKING
    return RoomKind.CUSTOM


def _value(value: Any) -> Any:
    """Accept both the RoomState/RoomPhase enum and a legacy plain string."""

    return getattr(value, "value", value)


def card_payload(card: Any) -> dict[str, Any]:
    """Serialize a card exactly like the legacy `__dict__` dump did."""

    if isinstance(card, dict):
        return {
            "name": card.get("name"),
            "speed": card.get("speed"),
            "type": card.get("type"),
            "description": card.get("description"),
        }
    return {
        "name": getattr(card, "name", None),
        "speed": getattr(card, "speed", None),
        "type": getattr(card, "type", None),
        "description": getattr(card, "description", None),
    }


def _effect_badges(player: Player | None) -> list[dict[str, Any]]:
    if player is None:
        return []
    from ..magic.cards import CARD_BY_NAME

    flags = player.effect_flags
    badges: list[dict[str, Any]] = []
    for attr, label, expiry, suffix in EFFECT_BADGES:
        if not getattr(flags, attr, None):
            continue
        badges.append(
            {
                "name": label,
                "key": attr,
                "label": f"{label}·{suffix}" if suffix else label,
                # Card text comes from the single card table, never a second copy.
                "description": CARD_BY_NAME.get(label).description
                if label in CARD_BY_NAME
                else "",
                "expires": expiry,
            }
        )
    return badges


def _spectate_chain_payload(room: Room) -> dict[str, Any]:
    """Public chain shape shared by the live stream and the reconnect snapshot.

    Delegates to :func:`battleship.domain.spectate.public_chain` so the sanitising
    (raw `targets` -> public preview, `player_id` -> `p1`/`p2`) has exactly one
    implementation for the live feed, the reconnect snapshot and the spectator
    snapshot. Imported lazily: `spectate` imports `room.models`, and this module
    is imported by the `room` package initialiser.
    """

    from ..spectate import public_chain

    return public_chain(room)


def _priority_pending_for(room: Room, player_id: str) -> dict[str, Any] | None:
    pending = room.priority_pending
    if pending and pending.get("actor") == player_id:
        return pending
    return None


def _shenji_wait_reason(room: Room, player_id: str) -> str | None:
    pending = (room.magic_temp_data or {}).get("pending_shenji") or {}
    caster = pending.get("caster")
    if not caster or caster == player_id:
        return None
    return "对方正在宣言神机妙算，请等待宣言完成"


def _top_ship_pick(room: Room, player_id: str) -> dict[str, Any] | None:
    mine = [
        pick
        for pick in room.pending_ship_picks
        if isinstance(pick, dict) and pick.get("player") == player_id
    ]
    from ..magic.interaction import ship_pick_priority

    mine.sort(
        key=lambda pick: (
            -ship_pick_priority(pick.get("reason")),
            int(pick.get("seq") or 0),
        )
    )
    return mine[0] if mine else None


def _my_pending_sacrifice_payload(room: Room, player_id: str) -> dict[str, Any] | None:
    top = _top_ship_pick(room, player_id)
    if top is None or top.get("silent"):
        return None
    return {key: top.get(key) for key in ("reason", "message", "priority")}


def _my_pending_sacrifice_ships(room: Room, player_id: str) -> list[dict[str, Any]]:
    top = _top_ship_pick(room, player_id)
    if top is None or top.get("silent"):
        return []
    player = room.players[player_id]
    return [
        {"positions": [{"x": pos.x, "y": pos.y} for pos in ship.positions]}
        for ship in alive_ships(player)
    ]


def _placement_blocked_cells(room: Room, player_id: str) -> list[dict[str, int]]:
    # One implementation only: the interaction module owns placement legality.
    from ..magic.interaction import placement_blocked_cells

    return placement_blocked_cells(room, player_id)


def _magic_temp_data(room: Room) -> dict[str, Any]:
    return room.magic_temp_data if isinstance(room.magic_temp_data, dict) else {}


def build_room_sync(
    room: Room, player_id: str, *, turn_timeout_seconds: int = 0
) -> dict[str, Any]:
    """Build the reconnect snapshot for one seated player (ticket #43 plus `opponent_registered`).

    `turn_timeout_seconds` is the configured watchdog timeout; the room snapshot
    does not own a second copy, it asks the same service that performs the
    fallback action (see `RoomService.turn_timeout_seconds`).
    """

    from ...contracts.events_out import RoomSync

    player = room.players[player_id]
    opponent_id = opponent_of(room, player_id)
    opponent = room.players.get(opponent_id) if opponent_id else None
    pending_placement = _magic_temp_data(room).get("pending_placement") or {}
    placing_for_me = pending_placement.get("caster") == player_id
    last_stand_cells = [
        {"x": x, "y": y} for (x, y) in (room.game_effects.get("last_stand_cells") or [])
    ]

    payload = {
        "room_id": room.id,
        "state": _value(room.state),
        "current_phase": _value(room.current_phase),
        "current_attacker": room.current_attacker,
        "attacks_remaining": room.attacks_remaining,
        "round": room.round,
        "attack_order": list(room.attack_order),
        "player_id": player_id,
        "player_seat": seat_label(room, player_id),
        "player_name": player.name,
        "opponent_name": opponent.name if opponent else None,
        "is_ai_room": bool(room.is_ai_room),
        "ranked": bool(room.ranked),
        "mode": room_match_mode(room),
        "winner": room.winner,
        "game_over_reason": room.game_over_reason,
        "field_magic": field_magic_name(room),
        "remaining_ships": player.remaining_ships,
        "ships": [
            {
                "positions": [{"x": pos.x, "y": pos.y} for pos in ship.positions],
                "frozen": bool(getattr(ship, "frozen", None)),
                "shield": bool(getattr(ship, "shield", False)),
                "alive": is_ship_alive(player, ship),
            }
            for ship in player.ships
        ],
        "opponent_shielded_ships": [
            [{"x": pos.x, "y": pos.y} for pos in ship.positions]
            for ship in (opponent.ships if opponent else [])
            if bool(getattr(ship, "shield", False)) and is_ship_alive(opponent, ship)
        ],
        "hand": [card_payload(card) for card in player.magic_hand],
        "attacks": [
            {"x": attack.x, "y": attack.y, "hit": attack.hit}
            for attack in (player.attacks or [])
        ],
        "opponent_attacks": [
            {"x": attack.x, "y": attack.y, "hit": attack.hit}
            for attack in ((opponent.attacks if opponent else []) or [])
        ],
        "opponent_remaining_ships": opponent.remaining_ships if opponent else 0,
        "shenwei_holes": list(room.game_effects.get("shenwei_holes") or []),
        "chain": _spectate_chain_payload(room),
        "chain_waiting": bool(room.chain_waiting),
        "chain_window": room.chain_window,
        "priority_waiting": (
            {
                "action": room.priority_pending.get("action"),
                "action_text": PRIORITY_ACTION_TEXT.get(
                    room.priority_pending.get("action"), "阶段转换"
                ),
            }
            if _priority_pending_for(room, player_id)
            else None
        ),
        "shenji_waiting": (
            {"text": "等待对方神机妙算宣言中"}
            if _shenji_wait_reason(room, player_id)
            else None
        ),
        "active_effects": sorted(
            name
            for name, value in vars(player.effect_flags).items()
            if value and name in PUBLIC_EFFECT_FLAGS
        ),
        "last_stand_lock": bool(getattr(player.effect_flags, "last_stand", False)),
        "last_stand_win": bool(getattr(player.effect_flags, "last_stand_win", False)),
        "effect_badges": {
            "self": _effect_badges(player),
            "opponent": _effect_badges(opponent) if opponent else [],
        },
        "pending_placement": dict(pending_placement) if placing_for_me else None,
        "pending_placement_blocked": (
            interaction_rules.placement_blocked_for(
                room, player_id, pending_placement
            )
            if placing_for_me
            else []
        ),
        "pending_placement_allowed": (
            interaction_rules.placement_allowed_for(room, pending_placement)
            if placing_for_me
            else []
        ),
        "last_stand_cells": last_stand_cells,
        "last_stand_owner": room.game_effects.get("last_stand_owner"),
        "frozen_area": dict(room.game_effects.get("frozen_area") or {}) or None,
        "magic_blocked": bool(getattr(player, "magic_blocked", False)),
        "effect_flags": {name: value for name, value in vars(player.effect_flags).items() if value},
        "pending_sacrifice": _my_pending_sacrifice_payload(room, player_id),
        "pending_sacrifice_ships": _my_pending_sacrifice_ships(room, player_id),
        "rps_choices": (
            dict(room.rps_choices) if room.state == RoomState.ROCK_PAPER_SCISSORS else {}
        ),
        # Ticket #43 additive tail: the countdown truth and the waiting-seat
        # visibility, both derived from state the snapshot already reads.
        **turn_timing(room, turn_timeout_seconds),
        **opponent_seat_state(room, player_id),
        # 重连要能整盘重布（灵气复苏/败者食尘把船数改了）与恢复自己的待选项。
        # 待选项**只回给发起者**：对手与观战拿到的是 None / False，看不到别人的选择。
        "max_ships": int(getattr(player, "max_ships", 0) or 0),
        "needs_reset": bool(getattr(player, "needs_reset", False)),
        "magic_temp": _my_magic_temp(room, player_id),
        "dice_discard_pending": bool(
            (room.pending_dice_discard or {}).get(player_id) is False
        ),
    }
    # Validation is the freeze: adding/removing a key without updating the
    # contract model fails here instead of silently drifting the wire shape.
    return RoomSync.model_validate(payload).model_dump()


def debug_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


__all__ = [
    "build_room_sync",
    "card_payload",
    "room_kind",
    "DEFAULT_MAX_SHIPS",
]
