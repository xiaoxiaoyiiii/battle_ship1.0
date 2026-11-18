"""指挥官技能局内纯规则：适用模式、发动检查、延迟锁定可见性脱敏、赤潮/铁锚状态判定。"""

from __future__ import annotations

from typing import Any

from ..room.models import (
    Player,
    PlayerShip,
    Room,
    RoomPhase,
    RoomState,
    alive_ships,
    opponent_of,
)
from .catalog import DEFAULT_COMMANDER_ID, get_commander

FIREPOWER_CONTROL_TOTAL = 6
QINGTONG_COOLDOWN_ROUNDS = 4  # 不计发动当回合，再完整经过 4 个大回合 => used_round + 5


def _state_val(room: Room) -> str:
    return str(getattr(room.state, "value", room.state) or "")


def _phase_val(room: Room) -> str:
    return str(getattr(room.current_phase, "value", room.current_phase) or "")


def is_commander_skill_enabled(room: Room | None) -> bool:
    """每日挑战关闭指挥官技能；休闲/排位/神秘科技大乱斗/人机/自定义房默认开启且无开关。"""
    if room is None:
        return False
    return not bool(getattr(room, "daily_challenge", None))


def firepower_control_active(room: Room | None, player_id: str | None) -> bool:
    if room is None or not player_id or not is_commander_skill_enabled(room):
        return False
    return (getattr(room, "firepower_control_round", None) or {}).get(player_id) == room.round


def firepower_control_remaining(room: Room, player_id: str) -> int:
    player = room.players.get(player_id)
    used = int(getattr(player, "commander_shots_used_this_round", 0) or 0) if player else 0
    return max(0, FIREPOWER_CONTROL_TOTAL - max(0, used))


def dauntless_active(room: Room | None, player_id: str | None) -> bool:
    if room is None or not player_id or not is_commander_skill_enabled(room):
        return False
    return (getattr(room, "dauntless_round", None) or {}).get(player_id) == room.round


def ship_id_key(ship: PlayerShip | None) -> str:
    """稳定识别房内某一艘舰船实例（只用于服务端内部标记跟踪，不依赖外泄下标）。"""
    return str(id(ship)) if ship is not None else ""


def clear_delayed_locks_for_ship(room: Room, player_id: str, ship: PlayerShip | None) -> None:
    """舰船沉没、牺牲或重部署离开棋盘后，立刻清理所有未揭晓的延迟锁定标记（复活不恢复）。"""
    if room is None or ship is None:
        return
    key = ship_id_key(ship)
    locks = getattr(room, "delayed_locks", None)
    if not locks:
        return
    room.delayed_locks = [
        entry
        for entry in locks
        if not (
            entry.get("target_player_id") == player_id
            and (entry.get("ship_obj") is ship or entry.get("ship_id") == key)
        )
    ]


def clear_delayed_locks_for_player(room: Room, player_id: str) -> None:
    """整盘清空或重摆棋盘时立即清掉针对该玩家的所有未揭晓延迟锁定标记。"""
    locks = getattr(room, "delayed_locks", None)
    if not locks:
        return
    room.delayed_locks = [
        entry for entry in locks if entry.get("target_player_id") != player_id
    ]


def can_use_commander_skill_in_chain(room: Room, player_id: str | None) -> bool:
    """铁锚与归航在连锁响应或阶段优先权窗口是否仍可发动速阶三技能。"""
    return commander_skill_error(room, player_id, in_chain_window=True) is None


def commander_skill_error(
    room: Room | None,
    player_id: str | None,
    *,
    in_chain_window: bool = False,
) -> str | None:
    """统一发动前置检查；返回 None 表示当前可点选发动。"""
    if room is None or not player_id or player_id not in room.players:
        return "无效的房间或玩家"
    if not is_commander_skill_enabled(room):
        return "每日挑战模式不开放指挥官技能"
    if _state_val(room) != RoomState.ATTACKING.value:
        return "当前阶段无法发动指挥官技能"

    player = room.players[player_id]
    cmd = get_commander(getattr(player, "commander_id", None) or DEFAULT_COMMANDER_ID)
    if cmd is None:
        return "未知的指挥官角色"
    skill = cmd.skill
    opponent_id = opponent_of(room, player_id)
    if not opponent_id or opponent_id not in room.players:
        return "对手尚未就位"

    # 待处理交互闸门（含未完成重摆、待弃牌、待宣言等；阶段转换询问期间响应方可在优先级窗口用速阶三技能）
    if room.mystery_tech and _state_val(room) != RoomState.ATTACKING.value:
        return "请先完成神秘科技选择与结算"

    from ..magic.interaction import pending_action_reason
    pending = pending_action_reason(room, player_id)
    if pending:
        return pending

    if (room.pending_dice_discard or {}).get(player_id) is False:
        return "请先完成命运骰子弃牌"

    # 不入链主动技能：赤潮「火力统制」、青瞳「延迟锁定」
    if not skill.enters_chain:
        if room.chain or room.chain_waiting or room.chain_resolving:
            return f"「{skill.name}」为非入链技能，不能在连锁中发动"
        if room.priority_pending or room.priority_continue:
            return "阶段转换询问中，无法发动非入链技能"
        if room.current_attacker != player_id or _phase_val(room) not in (
            RoomPhase.PREPARATION.value,
            RoomPhase.BATTLE.value,
        ):
            return f"「{skill.name}」只能在己方准备或战斗阶段发动"
    else:
        # 入链技能（速阶三）：任意合法出牌及连锁响应窗口可用
        if room.chain_resolving:
            return "连锁结算中，无法发动技能"
        if room.chain_waiting:
            if room.chain_window != player_id:
                return "当前不是你的连锁响应窗口"
        elif room.priority_pending:
            if room.priority_pending.get("responder") != player_id:
                return "正在等待对方响应阶段转换"
        elif not in_chain_window:
            # 普通合法出牌窗口：当前攻方在准备/战斗阶段，或在连锁响应窗口内
            if room.current_attacker != player_id or _phase_val(room) not in (
                RoomPhase.PREPARATION.value,
                RoomPhase.BATTLE.value,
            ):
                return f"当前不是你的合法出牌或连锁响应窗口，无法发动「{skill.name}」"

    if skill.kind == "limited":
        if int(getattr(player, "commander_skill_used_count", 0) or 0) >= int(skill.max_uses or 1):
            return f"「{skill.name}」为整局限定技，本局已使用过"
    elif skill.kind == "cooldown":
        next_round = int(getattr(player, "commander_next_available_round", 1) or 1)
        if room.round < next_round:
            remain = next_round - room.round
            return f"「{skill.name}」冷却中，还需等待 {remain} 个大回合（第 {next_round} 回合可用）"
    elif skill.kind == "per_chain":
        used_in_chain = (getattr(room, "commander_chain_uses", None) or {}).get(player_id, set())
        if skill.id in used_in_chain:
            return f"「{skill.name}」在同一条连锁内至多发动 1 次"

    if skill.id == "delayed_lock":
        if not alive_ships(room.players[opponent_id]):
            return "对方当前没有存活舰船，无法发动延迟锁定"
    elif skill.id == "sacrifice_gambit":
        if int(player.remaining_ships or 0) <= 1 or len(alive_ships(player)) <= 1:
            return "「弃舰筹谋」需要己方存活舰船数量大于 1"

    return None


def _seat_public_commander(
    room: Room,
    seat_id: str,
    player: Player,
) -> dict[str, Any]:
    cmd = get_commander(getattr(player, "commander_id", None) or DEFAULT_COMMANDER_ID)
    skill = cmd.skill if cmd else None
    next_round = int(getattr(player, "commander_next_available_round", 1) or 1)
    used_count = int(getattr(player, "commander_skill_used_count", 0) or 0)
    cooldown_left = max(0, next_round - int(room.round or 1))
    return {
        "player_id": seat_id,
        "commander_id": cmd.id if cmd else DEFAULT_COMMANDER_ID,
        "commander_name": cmd.name if cmd else "赤潮",
        "commander_level": max(1, int(getattr(player, "commander_level", 1) or 1)),
        "cosmetics": dict(getattr(player, "commander_cosmetics", None) or {}),
        "skill": skill.to_dict() if skill else None,
        "skill_used_count": used_count,
        "last_used_round": getattr(player, "commander_last_used_round", None),
        "next_available_round": next_round,
        "cooldown_remaining": cooldown_left,
        "firepower_control_active": firepower_control_active(room, seat_id),
        "dauntless_active": dauntless_active(room, seat_id),
        "shots_used_this_round": int(getattr(player, "commander_shots_used_this_round", 0) or 0),
    }


def _delayed_locks_for_viewer(room: Room, viewer_id: str | None) -> list[dict[str, Any]]:
    """信息裁剪关键函数：
    - 仅当 viewer_id == target_player_id（被标记船的船主）时，返回具体 ship_id 和格子坐标；
    - 青瞳施放方、观战方与匿名视角绝不获得 ship_id 与 coordinates。
    """
    out: list[dict[str, Any]] = []
    for entry in getattr(room, "delayed_locks", None) or []:
        target_pid = entry.get("target_player_id")
        target_player = room.players.get(target_pid)
        ship_obj = entry.get("ship_obj")
        if target_player is None or ship_obj is None or ship_obj not in target_player.ships:
            continue
        item: dict[str, Any] = {
            "id": entry.get("id"),
            "caster_id": entry.get("caster_id"),
            "target_player_id": target_pid,
            "used_round": entry.get("used_round"),
            "reveal_after_round": entry.get("reveal_after_round"),
            "cells": [],
        }
        if viewer_id is not None and viewer_id == target_pid:
            item["ship_id"] = entry.get("ship_id")
            item["cells"] = [
                {"x": int(p.x), "y": int(p.y)}
                for p in (getattr(ship_obj, "positions", None) or [])
            ]
        out.append(item)
    return out


def commander_room_state(room: Room, viewer_id: str | None) -> dict[str, Any]:
    """生成给指定视角（玩家本人或观战者）的指挥官当局状态投影。"""
    opponent_id = opponent_of(room, viewer_id) if viewer_id else None
    self_player = room.players.get(viewer_id) if viewer_id else None
    opp_player = room.players.get(opponent_id) if opponent_id else None

    enabled = is_commander_skill_enabled(room)
    can_use = False
    reason: str | None = "每日挑战模式不开放指挥官技能" if not enabled else None
    if enabled and viewer_id and self_player is not None:
        reason = commander_skill_error(room, viewer_id)
        can_use = reason is None

    return {
        "enabled": enabled,
        "self": _seat_public_commander(room, viewer_id, self_player) if self_player and viewer_id else None,
        "opponent": _seat_public_commander(room, opponent_id, opp_player) if opp_player and opponent_id else None,
        "can_use_skill": can_use,
        "unavailable_reason": reason,
        "delayed_locks": _delayed_locks_for_viewer(room, viewer_id),
        "revealed_locks": list((getattr(room, "game_effects", None) or {}).get("delayed_lock_revealed") or []),
    }


def commander_spectate_state(room: Room) -> dict[str, Any]:
    """观战端 / 回放公开视角（只按 p1/p2 标签导出，绝不泄漏任何延迟锁定目标坐标）。"""
    order = [str(pid) for pid in room.players]
    seat_map = {pid: f"p{index + 1}" for index, pid in enumerate(order[:2])}
    sides: dict[str, Any] = {}
    for index, pid in enumerate(order[:2]):
        label = f"p{index + 1}"
        sides[label] = _seat_public_commander(room, pid, room.players[pid])
    revealed = [
        {
            "id": row.get("id"),
            "caster_side": seat_map.get(str(row.get("caster_id")), "unknown"),
            "target_side": seat_map.get(str(row.get("target_player_id")), "unknown"),
            "revealed_round": row.get("revealed_round"),
            "cells": list(row.get("cells") or []),
        }
        for row in ((getattr(room, "game_effects", None) or {}).get("delayed_lock_revealed") or [])
    ]
    return {
        "enabled": is_commander_skill_enabled(room),
        "sides": sides,
        "delayed_locks": _delayed_locks_for_viewer(room, None),
        "revealed_locks": revealed,
    }


__all__ = [
    "FIREPOWER_CONTROL_TOTAL",
    "QINGTONG_COOLDOWN_ROUNDS",
    "can_use_commander_skill_in_chain",
    "clear_delayed_locks_for_player",
    "clear_delayed_locks_for_ship",
    "commander_room_state",
    "commander_skill_error",
    "commander_spectate_state",
    "dauntless_active",
    "firepower_control_active",
    "firepower_control_remaining",
    "is_commander_skill_enabled",
    "ship_id_key",
]
