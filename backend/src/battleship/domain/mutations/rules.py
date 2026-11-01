"""房间突变的纯规则；支付、网络与流程推进由服务层编排。"""
from __future__ import annotations

from typing import Any
import uuid

from .catalog import entries_for, roll_mutations, validate_selection, weekly_pack


def active(room, key: str) -> bool:
    return not room.ranked and key in room.mutation_ids


def storm_active(room) -> bool:
    if not active(room, "D2"):
        return False
    if room.round >= 5:
        room.mutation_storm_active = True
    return room.mutation_storm_active


def prepare_draw_count(room, *, first: bool, include_supply: bool = True) -> int:
    count = (0 if first else 1) if active(room, "C2") else (1 if first else 2)
    if include_supply and active(room, "C1"):
        count += 1
    return count * (2 if storm_active(room) else 1)


def prepare_supply_count(room) -> int:
    return (1 if active(room, "C1") else 0) * (2 if storm_active(room) else 1)


def battle_bonus(room) -> int:
    return (2 if active(room, "A3") else 0) + (2 if storm_active(room) else 0)


def preparation_key(room) -> str:
    return f"{room.round}:{room.current_attacker}:{room.mutation_preparation_seq}"


def begin_preparation(room) -> None:
    room.mutation_preparation_seq += 1
    storm_active(room)


def preparation_cast(room, player_id: str) -> bool:
    return room.mutation_preparation_casts.get(player_id) == preparation_key(room)


def round_casts(room, player_id: str) -> int:
    record = room.mutation_casts.get(player_id, {})
    return int(record.get("count", 0)) if record.get("round") == room.round else 0


def extra_discard_required(room, player_id: str) -> bool:
    return (active(room, "C3") and getattr(room.current_phase, "value", room.current_phase) == "preparation"
            and not preparation_cast(room, player_id))


def cast_error(room, player_id: str, card) -> str | None:
    if active(room, "B1") and int(card.speed) == 3:
        return "静默海域：不能发动速阶3魔法"
    if active(room, "B2") and int(card.speed) != 3 and card.type != "场地":
        return "闪电窗口：只能发动速阶3或场地魔法"
    if active(room, "B3") and round_casts(room, player_id) >= 1:
        return "单一律：本大回合已经发动过一张魔法"
    if extra_discard_required(room, player_id) and len(room.players[player_id].magic_hand) < 2:
        return "弃潮祭：首次发动须另弃一张手牌，至少需要两张手牌"
    return None


def discard_cost_error(room, player_id: str, card, targets: dict) -> str | None:
    if not extra_discard_required(room, player_id):
        return None
    hand = room.players[player_id].magic_hand
    declared = next((index for index, candidate in enumerate(hand)
                     if candidate.name == card.name and candidate.speed == card.speed), -1)
    index = targets.get("mutation_discard_index")
    if type(index) is not int or not 0 <= index < len(hand) or index == declared:
        return "弃潮祭：请选择发动牌以外的一张手牌额外弃置"
    return None


def pay_discard_cost(room, player_id: str, targets: dict):
    if extra_discard_required(room, player_id):
        card = room.players[player_id].magic_hand.pop(targets["mutation_discard_index"])
        room.magic_discard.append(card)
        return card
    return None


def note_cast(room, player_id: str) -> None:
    room.mutation_casts[player_id] = {"round": room.round, "count": round_casts(room, player_id) + 1}
    if getattr(room.current_phase, "value", room.current_phase) == "preparation":
        room.mutation_preparation_casts[player_id] = preparation_key(room)


def enter_battle_error(room, player_id: str) -> str | None:
    if active(room, "A4") and not preparation_cast(room, player_id):
        from ..magic.rules import evaluate_cast
        if any(evaluate_cast(room, player_id, card) is None for card in room.players[player_id].magic_hand):
            return "禁炮法令：本准备阶段至少发动一张合法魔法后才能进入战斗"
    return None


def configure_room(room, mode: str, *, ids: list[str] | None = None, rng, now=None) -> None:
    week = weekly_pack(now)
    if mode == "ranked" or room.ranked:
        selected = []
    elif mode in {"casual", "ai"}:
        selected = roll_mutations([entry["id"] for entry in week["entries"]], rng)
    else:
        error = validate_selection([] if ids is None else ids)
        if error:
            raise ValueError(error)
        selected = list(ids or [])
    room.mutation_ids = selected
    room.mutation_week_id = week["week_id"]
    room.mutation_entries = entries_for(selected)


def prepare_start(room, rng) -> None:
    if room.mutation_token or len(room.players) != 2:
        return
    if active(room, "D1"):
        room.mutation_dice_rolls = {pid: rng.randint(1, 6) for pid in room.players}
        room.starting_ship_cap = min(room.mutation_dice_rolls.values())
    for player in room.players.values():
        player.max_ships = room.starting_ship_cap
    if room.mutation_ids and not room.ranked:
        room.mutation_token = uuid.uuid4().hex
        room.mutation_confirmed.update(pid for pid in room.players if room.is_ai_room and pid.startswith("ai-"))


def confirmation_pending(room) -> bool:
    return bool(room.mutation_token and any(pid not in room.mutation_confirmed for pid in room.players))


def confirm(room, player_id: str, token: Any) -> str | None:
    if player_id not in room.players or not room.mutation_token or token != room.mutation_token:
        return "本局突变确认已失效，请重新读取本局完整文案"
    room.mutation_confirmed.add(player_id)
    return None


def payload(room, player_id: str) -> dict | None:
    if room.ranked or not room.mutation_ids:
        return None
    return {
        "ids": list(room.mutation_ids), "entries": [dict(entry) for entry in room.mutation_entries],
        "week_id": room.mutation_week_id, "confirmation_required": bool(room.mutation_token),
        "confirmed": player_id in room.mutation_confirmed,
        "waiting_for": sum(pid not in room.mutation_confirmed for pid in room.players),
        "ack_token": room.mutation_token, "starting_ship_cap": room.starting_ship_cap,
        "dice_rolls": dict(room.mutation_dice_rolls), "storm_active": storm_active(room),
        "preparation_cast": preparation_cast(room, player_id), "round_casts": round_casts(room, player_id),
        "extra_discard_required": extra_discard_required(room, player_id),
    }


def visible_reveals(room, player_id: str) -> list[dict]:
    points = {(pos.x, pos.y) for pos in room.players[player_id].revealed_positions}
    points.update(tuple(point) for point in room.mutation_revealed.get(player_id, []))
    return [{"x": x, "y": y} for x, y in sorted(points)]


def visible_attacks(attacks) -> list:
    return [attack for attack in (attacks or []) if not getattr(attack, "fog_miss", False)]


def reveal_ship(room, player_id: str, ship) -> None:
    viewer = room.opponent_of(player_id)
    if viewer:
        known = room.mutation_revealed.setdefault(viewer, [])
        for position in ship.positions:
            cell = (position.x, position.y)
            if cell not in known:
                known.append(cell)
