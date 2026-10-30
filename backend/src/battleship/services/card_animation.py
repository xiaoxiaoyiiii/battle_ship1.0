"""只描述可见演出范围；卡牌规则与真实状态提交仍由魔法服务负责。"""
from __future__ import annotations

from typing import Any

from ..domain.battle import splash_cells
from ..domain.magic.chain import ChainItem
from ..domain.magic.precheck import healing_ships
from ..domain.room import Room
from ..domain.spectate.rules import preview_node

KINDS = {
    "轰炸": "bomb", "神威！": "vortex", "冻结": "ice", "硫磺火焰": "fire",
    "溅射": "splash", "看破！": "seal", "无暇圣心": "sanctuary", "疗愈": "heal",
}


def effect_description(card: str, kind: str, caster: str, target: str,
                       cells: list[dict] | None = None) -> dict[str, Any]:
    return {"card": card, "kind": kind, "caster": caster, "target": target,
            "cells": cells or [], "duration_ms": 1350 if kind in ("ice", "fire", "vortex") else 1250,
            "impact": .43 if kind in ("ice", "fire") else .45}


def chain_card_effect(room: Room, item: ChainItem) -> dict[str, Any] | None:
    """公开选区走既有白名单，恢复坐标先保留为内部字段，逐座位私发。"""
    if item.negated:
        return None
    name, caster = item.card.name, item.player_id
    other = room.opponent_of(caster)
    kind = KINDS.get(name)
    if not kind or not other:
        # 反制链项由真正被标无效的下一张卡面承接特效；拆场地则作用于场地区。
        if name in ("失灵！", "加百列之光") and not room.chain and room.field_magic:
            return effect_description(name, "negate" if name == "失灵！" else "gabriel", caster, "field")
        return None
    target = caster if kind == "heal" else "both" if kind == "sanctuary" else other
    result = effect_description(name, kind, caster, target)
    if kind in ("bomb", "vortex", "ice", "fire"):
        targets = item.targets if isinstance(item.targets, dict) else {}
        preview = preview_node(targets, name, room, board=targets.get("board"))
        if not preview:
            return None
        result["target"] = caster if preview["board"] == "self" else other
        result["cells"] = preview["cells"]
    elif kind == "splash":
        last = room.last_attack or {}
        if last.get("attacker") != caster or not last.get("hit"):
            return None
        result["cells"] = [{"x": x, "y": y} for x, y in splash_cells(room)]
        result["origin"] = {"x": last["x"], "y": last["y"]}
    elif kind == "heal":
        positions = [{"x": p.x, "y": p.y} for ship in healing_ships(room, caster, item.targets or {}) for p in ship.positions]
        if not positions:
            return None
        result["_private_cells"] = positions
    return result


def effect_for_viewer(description: dict, viewer: str) -> dict:
    """新部署与护盾落点只给施法者，对手始终只有不定位的整盘反馈。"""
    result = {key: value for key, value in description.items() if not key.startswith("_")}
    private = description.get("_private_cells")
    if private and viewer == description.get("caster"):
        result["private_targets"] = True
        result["private_cells"] = private
    return result
