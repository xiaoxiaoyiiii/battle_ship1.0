"""Batch A: non-interactive normal cards (ticket #10).

Every function here is registered in battleship.domain.magic.registry.
"Non-interactive" means the card needs no ship pick, placement or extra choice
from the caster; area/line target cards are included because their target is
already part of use_magic_card (the target-selection protocol is ticket #10).
Field cards, judgement cards and cards that wait for a player to click a ship
belong to #11; the chain-only cards belong to #12.

Behaviour is ported from the legacy apply_magic_effect branches, including the
messages the player sees.
"""

from __future__ import annotations

from typing import Any, Iterable

from ... import effects
from ...battle import (
    SPLASH_NEEDS_HIT,
    line_cells,
    resolve_area_strike,
    resolve_splash,
    splash_error,
)
from ...room import BOARD_SIZE, PlayerShip, Position, alive_ships, is_ship_alive
from ..cards import MagicCard
from ..deck import revive_sunken_ships
from ..hooks import SHIP_DESTROYED, SHIP_SUNK
from ..registry import register
from .base import EffectContext, EffectResult


# --------------------------------------------------------------------- helpers


def _attack_payload(ctx: EffectContext, x: int, y: int, hit: bool,
                    sunk: bool) -> dict[str, Any]:
    return {
        "attacker": ctx.caster_id,
        "x": x,
        "y": y,
        "hit": hit,
        "ship_sunk": sunk,
        "shield_blocked": False,
        "remaining_attacks": ctx.room.attacks_remaining,
        "attacker_remaining_ships": ctx.caster.remaining_ships,
        "defender_remaining_ships": ctx.opponent.remaining_ships,
    }


async def _emit_area_cells(ctx: EffectContext, cells: Iterable[Any]) -> list[Position]:
    affected: list[Position] = []
    for cell in cells:
        await ctx.emit(
            "attack_result",
            _attack_payload(ctx, cell.x, cell.y, cell.hit, cell.ship_sunk),
            room=ctx.room.id,
        )
        affected.append(Position(x=cell.x, y=cell.y, hit=cell.hit, ship_sunk=cell.ship_sunk))
    return affected


def _unique_sunk(cells: Iterable[Any]) -> list[PlayerShip]:
    seen: set[int] = set()
    result: list[PlayerShip] = []
    for cell in cells:
        ship = getattr(cell, "sunk_ship", None)
        if ship is not None and id(ship) not in seen:
            seen.add(id(ship))
            result.append(ship)
    return result


async def _finish_if_wiped(ctx: EffectContext) -> bool:
    opponent = ctx.opponent
    if opponent.remaining_ships <= 0 and len(opponent.ships or []) > 0:
        await ctx.finish(ctx.caster_id, ctx.opponent_id, "魔法卡清空对方棋盘")
        return True
    return False


def _in_area(area: dict[str, int], position: Position) -> bool:
    return (
        area["x1"] <= position.x <= area["x2"]
        and area["y1"] <= position.y <= area["y2"]
    )


def _record_reveal_misses(
    ctx: EffectContext, positions: Iterable[tuple[int, int]]
) -> list[Position]:
    """Record misses exactly like the legacy scan cards: hits are not recorded."""

    affected: list[Position] = []
    for x, y in positions:
        cell = Position(x=x, y=y)
        hit = any(
            is_ship_alive(ctx.opponent, ship) and cell in (ship.positions or [])
            for ship in ctx.opponent.ships or []
        )
        if not hit:
            ctx.caster.attacks.append(
                Position(x=x, y=y, hit=False, ship_sunk=False, is_splash=True)
            )
        affected.append(cell)
    return affected


# ------------------------------------------------------------------ speed 1


@register("余音绕梁")
async def echoing_beam(ctx: EffectContext) -> EffectResult:
    if ctx.phase != "preparation" or ctx.room.current_attacker != ctx.caster_id:
        return EffectResult(False, "只能在自己的准备阶段使用")
    # #38：余音绕梁 = round 边界、2 层的租约，每个结束阶段消耗 1 层。
    effects.grant_flag(
        ctx.room, ctx.caster_id, "forced_kill",
        boundary=effects.BOUNDARY_ROUND, value=2,
    )
    return EffectResult(True, "接下来两个攻击阶段（本回合与下一回合）将造成强制击杀")


@register("无中生有")
async def out_of_nothing(ctx: EffectContext) -> EffectResult:
    drawn = 0
    for _ in range(2):
        if await ctx.draw(ctx.caster_id) is not None:
            drawn += 1
    # 无中生有：双方都在本大回合内无法获得魔法卡（turn 边界不清）。
    effects.grant_flag(ctx.room, ctx.caster_id, "no_draw", boundary=effects.BOUNDARY_ROUND)
    effects.grant_flag(ctx.room, ctx.opponent_id, "no_draw", boundary=effects.BOUNDARY_ROUND)
    if drawn == 2:
        message = "抽了2张牌，本回合双方无法获得魔法卡"
    elif drawn == 1:
        message = "只抽到1张牌（牌堆不足），本回合双方无法获得魔法卡"
    else:
        message = "牌堆已空，没有抽到牌；本回合双方仍然无法获得魔法卡"
    return EffectResult(True, message)


@register("极限增援")
async def reinforcement(ctx: EffectContext) -> EffectResult:
    total_turns = 2
    ctx.room.game_effects["reinforcement_check"] = {
        "turn": ctx.room.round + total_turns,
        "caster": ctx.caster_id,
        "remaining_turns": total_turns,
        "activated_round": ctx.room.round,
    }
    await ctx.emit(
        "reinforcement_activated", {"remaining_turns": total_turns}, room=ctx.room.id
    )
    await ctx.sync_active_effects()
    return EffectResult(True, "极限增援已激活，剩余2回合后结算")


@register("无暇圣心")
async def holy_heart(ctx: EffectContext) -> EffectResult:
    total_turns = 2
    ctx.room.game_effects["holy_heart"] = {
        "turn": ctx.room.round + total_turns,
        "caster": ctx.caster_id,
        "remaining_turns": total_turns,
        "no_damage": True,
    }
    await ctx.emit(
        "holy_heart_activated", {"remaining_turns": total_turns}, room=ctx.room.id
    )
    await ctx.sync_active_effects()
    return EffectResult(True, "无暇圣心已激活，剩余2回合后结算")


@register("火力全开")
async def full_power(ctx: EffectContext) -> EffectResult:
    flags = ctx.caster.effect_flags
    in_battle = (
        getattr(ctx.room.state, "value", ctx.room.state) == "attacking"
        and ctx.phase == "battle"
        and ctx.room.current_attacker == ctx.caster_id
    )
    if in_battle and not flags.double_attacks:
        ctx.room.attacks_remaining = max(0, ctx.room.attacks_remaining) * 2
        effects.consume_flag(ctx.room, ctx.caster_id, "double_attacks")
        await ctx.emit(
            "attacks_updated",
            {
                "current_attacker": ctx.room.current_attacker,
                "attacks_remaining": ctx.room.attacks_remaining,
            },
            room=ctx.room.id,
        )
        return EffectResult(True, f"本回合攻击次数翻倍，当前攻击次数为{ctx.room.attacks_remaining}")
    effects.grant_flag(
        ctx.room, ctx.caster_id, "double_attacks", boundary=effects.BOUNDARY_TURN
    )
    return EffectResult(True, "本回合攻击次数翻倍")


# ------------------------------------------------------------------ speed 2


@register("溅射")
async def splash(ctx: EffectContext) -> EffectResult:
    reason = splash_error(ctx.room, ctx.caster_id)
    if reason:
        return EffectResult(False, reason)
    result = resolve_splash(ctx.room, ctx.caster_id)
    affected = await _emit_area_cells(ctx, result.cells)
    for ship in _unique_sunk(result.cells):
        await ctx.on_ship_sunk(ctx.opponent_id, ship)
    if result.ships_sunk:
        await ctx.sync_ships()
    if result.last_chance:
        await ctx.finish(ctx.caster_id, ctx.opponent_id, "回光返照失败")
        return EffectResult(True, "溅射命中回光返照目标，直接获胜", game_over=True,
                            affected_positions=affected)
    if await _finish_if_wiped(ctx):
        return EffectResult(True, f"溅射攻击命中{result.hit_count}个目标，对方战舰全灭",
                            game_over=True, affected_positions=affected)
    return EffectResult(True, f"溅射攻击命中{result.hit_count}个目标",
                        affected_positions=affected)


@register("雷达子弹")
async def radar_bullet(ctx: EffectContext) -> EffectResult:
    last = ctx.room.last_attack or {}
    if last.get("attacker") != ctx.caster_id or not last.get("hit"):
        return EffectResult(False, "必须在击中对方战舰后使用")
    x, y = int(last["x"]), int(last["y"])
    positions = [
        (x + dx, y + dy)
        for dy in (-1, 0, 1)
        for dx in (-1, 0, 1)
        if not (dx == 0 and dy == 0)
        and 0 <= x + dx < BOARD_SIZE and 0 <= y + dy < BOARD_SIZE
    ]
    for px, py in positions:
        ctx.caster.revealed_positions.append(Position(x=px, y=py))
    affected = _record_reveal_misses(ctx, positions)
    for position in affected:
        await ctx.emit(
            "attack_result",
            _attack_payload(ctx, position.x, position.y, False, False),
            room=ctx.room.id,
        )
    await ctx.emit(
        "revealed_positions",
        {"positions": [{"x": px, "y": py} for px, py in positions]},
        to=ctx.caster.socket_id,
    )
    return EffectResult(True, "已扫描周围八格战舰位置", affected_positions=affected)


@register("越战越勇")
async def battle_spirit(ctx: EffectContext) -> EffectResult:
    last = ctx.room.last_attack or {}
    if last.get("attacker") != ctx.caster_id or not last.get("ship_sunk"):
        return EffectResult(False, "必须在击沉对方战舰后立即使用")
    effects.grant_flag(
        ctx.room, ctx.caster_id, "battle_spirit", boundary=effects.BOUNDARY_TURN
    )
    gained = await ctx.grant_attacks(1)
    if gained:
        return EffectResult(
            True,
            f"越战越勇生效：攻击次数 +{gained}（当前 {ctx.room.attacks_remaining} 次），"
            "本大回合再击沉战舰还会 +1",
        )
    return EffectResult(True, "越战越勇生效，本回合击沉战舰时攻击次数净增加1")


@register("神威！")
async def shenwei(ctx: EffectContext) -> EffectResult:
    area = ctx.area()
    if area is None:
        return EffectResult(False, "需要选择目标区域")
    board = ctx.board_side() or "opponent"
    target_id = ctx.caster_id if board == "self" else ctx.opponent_id
    target = ctx.room.players[target_id]

    excluded: list[PlayerShip] = []
    for index in range(len(target.ships) - 1, -1, -1):
        ship = target.ships[index]
        if any(_in_area(area, pos) for pos in ship.positions):
            excluded.append(ship)
            del target.ships[index]
            target.remaining_ships -= 1

    return_turn = ctx.room.round + 1
    ctx.room.game_effects.setdefault("shenwei_holes", []).append({
        "player": target_id, "x1": area["x1"], "y1": area["y1"],
        "x2": area["x2"], "y2": area["y2"], "return_turn": return_turn,
    })
    await ctx.emit(
        "shenwei_hole",
        {"player": target_id, "area": area, "return_turn": return_turn},
        room=ctx.room.id,
    )

    if board != "self" and len(excluded) == 1:
        ship = excluded[0]
        if ship not in target.sunken_ships:
            target.sunken_ships.append(ship)
        await ctx.on_ship_sunk(ctx.opponent_id, ship)
        message = "目标区域内1艘战舰被击沉"
    else:
        ctx.room.game_effects.setdefault("excluded_ships", []).append({
            "ships": excluded, "player": target_id, "return_turn": return_turn,
        })
        if excluded:
            await ctx.notify_treasure(len(excluded), None)
        message = f"目标区域内{len(excluded)}艘战舰被暂时除外"

    await ctx.sync_ships()
    if ctx.opponent.remaining_ships <= 0 and len(ctx.opponent.ships or []) > 0:
        await ctx.finish(ctx.caster_id, ctx.opponent_id, "神威！清空对方棋盘")
        return EffectResult(True, message + "，对方战舰全灭，直接获胜", game_over=True)
    if ctx.caster.remaining_ships <= 0 and board == "self":
        await ctx.finish(ctx.opponent_id, ctx.caster_id, "神威！清空己方棋盘")
        return EffectResult(True, message + "，己方战舰全灭，判负", game_over=True)
    return EffectResult(True, message)


@register("冻结")
async def freeze(ctx: EffectContext) -> EffectResult:
    area = ctx.area()
    if area is None:
        return EffectResult(False, "需要选择目标区域")
    frozen_count = 0
    for ship in ctx.opponent.ships:
        if not is_ship_alive(ctx.opponent, ship):
            continue
        if any(_in_area(area, pos) for pos in ship.positions) and not ship.frozen:
            ship.frozen = ctx.room.round + 1
            frozen_count += 1
    if frozen_count:
        await ctx.sync_player_ships(ctx.opponent_id)
    ctx.room.game_effects["frozen_area"] = {
        "x1": int(area["x1"]), "y1": int(area["y1"]),
        "x2": int(area["x2"]), "y2": int(area["y2"]),
        "owner": ctx.opponent_id,
        "caster": ctx.caster_id,
        "frozen": frozen_count,
        "until_round": ctx.room.round + 1,
    }
    await ctx.emit("frozen_area", dict(ctx.room.game_effects["frozen_area"]), room=ctx.room.id)
    return EffectResult(True, f"冻结了{frozen_count}艘战舰")


@register("轰炸")
async def bomb(ctx: EffectContext) -> EffectResult:
    line = ctx.line()
    if line is None:
        return EffectResult(False, "需要选择目标行或列")
    cells = line_cells(line["type"], int(line["index"]))
    result = resolve_area_strike(ctx.room, ctx.caster_id, cells, kind="bomb")
    affected = await _emit_area_cells(ctx, result.cells)
    for ship in _unique_sunk(result.cells):
        await ctx.notify_treasure(1, None)
        await ctx.on_ship_sunk(ctx.opponent_id, ship)
    if result.ships_sunk:
        await ctx.sync_ships()
    message = f"轰炸成功击沉{result.ships_sunk}艘战舰"
    if await _finish_if_wiped(ctx):
        return EffectResult(True, message + "，对方战舰全灭", game_over=True,
                            affected_positions=affected)
    return EffectResult(True, message, affected_positions=affected)


@register("硫磺火焰")
async def sulfur(ctx: EffectContext) -> EffectResult:
    cells = ctx.cells("target_cells")
    if not isinstance(cells, list) or len(cells) != 6:
        return EffectResult(False, "需要选择恰好6个连续的格子")
    result = resolve_area_strike(ctx.room, ctx.caster_id, cells, kind="sulfur")
    affected = await _emit_area_cells(ctx, result.cells)
    for ship in _unique_sunk(result.cells):
        await ctx.notify_treasure(1, None)
        await ctx.on_ship_sunk(ctx.opponent_id, ship)
    if result.ships_sunk:
        await ctx.sync_ships()
    message = f"硫磺火焰成功击杀{result.ships_sunk}艘战舰"
    if await _finish_if_wiped(ctx):
        return EffectResult(True, message + "，对方战舰全灭", game_over=True,
                            affected_positions=affected)
    return EffectResult(True, message, affected_positions=affected)


@register("探测雷达")
async def detection_radar(ctx: EffectContext) -> EffectResult:
    area = ctx.area()
    if area is None:
        return EffectResult(False, "需要选择目标区域")
    positions = [
        (x, y)
        for y in range(area["y1"], area["y2"] + 1)
        for x in range(area["x1"], area["x2"] + 1)
    ]
    for px, py in positions:
        ctx.caster.revealed_positions.append(Position(x=px, y=py))
    affected = _record_reveal_misses(ctx, positions)
    for position in affected:
        await ctx.emit(
            "attack_result",
            _attack_payload(ctx, position.x, position.y, False, False),
            room=ctx.room.id,
        )
    await ctx.emit(
        "revealed_positions",
        {"positions": [{"x": px, "y": py} for px, py in positions]},
        to=ctx.caster.socket_id,
    )
    return EffectResult(True, "已探测目标区域战舰位置", affected_positions=affected)


@register("饮血")
async def vampire(ctx: EffectContext) -> EffectResult:
    last = ctx.room.last_attack or {}
    if last.get("attacker") != ctx.caster_id or not last.get("ship_sunk"):
        return EffectResult(False, "需要在击沉对方一艘战舰后才能使用")
    effects.grant_flag(ctx.room, ctx.caster_id, "vampire", boundary=effects.BOUNDARY_ROUND)
    await ctx.draw(ctx.caster_id)
    await ctx.emit("message", {"text": "饮血发动，立即抽一张卡"}, to=ctx.caster.socket_id)
    return EffectResult(True, "饮血生效：已为刚才击沉的战舰抽一张牌，接下来每击杀一艘船再抽一张。")


@register("Freezing！")
async def freezing(ctx: EffectContext) -> EffectResult:
    if ctx.room.attack_order and ctx.room.attack_order[0] != ctx.caster_id:
        return EffectResult(False, "Freezing！只能在自己先手的回合发动")
    if ctx.phase != "end":
        return EffectResult(False, "Freezing！只能在结束阶段发动")
    if ctx.caster.damage_dealt_this_turn > 0:
        return EffectResult(False, "本回合已使对方船数减少，无法发动 Freezing！")
    ctx.room.skip_opponent_turn = ctx.opponent_id
    return EffectResult(True, "Freezing！生效，跳过对方本回合的所有阶段")


@register("五险一金")
async def five_insurances(ctx: EffectContext) -> EffectResult:
    from ..rules import field_magic_name

    if field_magic_name(ctx.room) == "教皇旨意":
        return EffectResult(False, "教皇旨意生效中，本回合攻击次数为0，五险一金无法发动")
    if ctx.caster.damage_dealt_this_turn > 0:
        return EffectResult(False, "本回合已造成伤害，无法发动")
    effects.grant_flag(ctx.room, ctx.caster_id, "wuxian", boundary=effects.BOUNDARY_TURN)
    if await ctx.maybe_wuxian():
        return EffectResult(True, "攻击次数已用尽且未造成伤害，攻击次数 +3")
    return EffectResult(True, "五险一金已生效：用完本回合所有攻击次数且未造成伤害时，攻击次数 +3")


@register("卧薪尝胆")
async def bitter_training(ctx: EffectContext) -> EffectResult:
    if ctx.caster.remaining_ships >= ctx.opponent.remaining_ships:
        return EffectResult(False, "自己的船数不小于对方，卧薪尝胆无法发动")
    alive = alive_ships(ctx.caster)
    if not alive:
        return EffectResult(False, "没有战舰可添加护盾")
    for ship in alive:
        ship.shield = True
    await ctx.sync_player_ships(ctx.caster_id)
    await ctx.emit(
        "shields_added", {"player": ctx.caster_id, "count": len(alive)}, room=ctx.room.id
    )
    await ctx.log(
        f"第{ctx.room.round}回合 · {ctx.name(ctx.caster_id)} 的【卧薪尝胆】"
        f"为{len(alive)}艘战舰添加护盾",
        "magic",
        {"caster": ctx.caster_id, "card": "卧薪尝胆", "count": len(alive)},
    )
    return EffectResult(True, f"已为{len(alive)}艘战舰添加护盾")


# ------------------------------------------------------------------ speed 3


@register("八方来财")
async def treasure_hunter(ctx: EffectContext) -> EffectResult:
    effects.grant_flag(
        ctx.room, ctx.caster_id, "treasure_hunter", boundary=effects.BOUNDARY_ROUND
    )
    return EffectResult(True, "战舰数目变化时抽一张牌")


@register("百亿补贴")
async def subsidy(ctx: EffectContext) -> EffectResult:
    """自己的船被击沉/摧毁时攻击次数 +3。

    炮击（BattleService.sink_hooks）与效果摧毁（ctx.on_ship_destroyed）最后都
    落在 MagicService 的同一个 SHIP_SUNK / SHIP_DESTROYED 漏斗上，所以这里只要
    订阅两个事件、把 +3 写进租约投影即可；订阅随 subsidy 租约在大回合边界消失。
    """

    owner = ctx.caster_id
    key = effects.flag_lease_key("subsidy", owner)
    fresh = effects.get_lease(ctx.room, key) is None
    lease = effects.grant_flag(
        ctx.room, owner, "subsidy", boundary=effects.BOUNDARY_ROUND
    )
    if not fresh:
        # 重复施放只刷新同一条租约；再订阅一次会让一次击沉 +6。
        return EffectResult(True, "船被击败时攻击次数加3")

    async def on_owner_ship_lost(payload: dict[str, Any]) -> None:
        if payload.get("owner_id") != owner:
            return
        effects.adjust_flag(
            ctx.room, owner, "subsidy_bonus", 3, boundary=effects.BOUNDARY_ROUND
        )
        player = ctx.room.players.get(owner)
        if player is not None and player.socket_id:
            await ctx.emit(
                "message",
                {"text": "百亿补贴生效，你的攻击次数 +3"},
                to=player.socket_id,
            )

    for event in (SHIP_SUNK, SHIP_DESTROYED):
        effects.subscribe(
            ctx.room,
            event,
            on_owner_ship_lost,
            kind=effects.KIND_NOTIFY,
            lease_key=lease.key,
        )
    return EffectResult(True, "船被击败时攻击次数加3")


@register("看破！")
async def see_through(ctx: EffectContext) -> EffectResult:
    ctx.opponent.magic_blocked = True
    ctx.opponent.magic_blocked_round = ctx.room.round
    return EffectResult(True, "本回合对方魔法卡被无效化")


@register("疗愈")
async def heal(ctx: EffectContext) -> EffectResult:
    if not ctx.caster.sunken_ships:
        return EffectResult(False, "没有可复活的战舰")
    sunken_before = list(ctx.caster.sunken_ships)
    revived = revive_sunken_ships(ctx.room, ctx.caster_id, 2, reveal_to=ctx.opponent_id)
    if revived == 0:
        return EffectResult(False, "没有可复活的战舰")
    revived_ids = {id(ship) for ship in ctx.caster.ships if id(ship) in {id(item) for item in sunken_before}}
    revived_positions = [
        {"x": position.x, "y": position.y}
        for ship in ctx.caster.ships
        if id(ship) in revived_ids
        for position in ship.positions
    ]
    await ctx.emit(
        "revived_positions",
        {"player": ctx.caster_id, "positions": revived_positions, "card": "疗愈"},
        room=ctx.room.id,
    )
    await ctx.notify_treasure(revived, None)
    await ctx.sync_ships()
    await ctx.sync_player_ships(ctx.caster_id)
    return EffectResult(True, f"疗愈生效，{revived} 艘战舰在原地复活")


@register("盗亦有道")
async def steal(ctx: EffectContext) -> EffectResult:
    stolen_card = None
    stolen_entry = None
    for entry in reversed(ctx.room.magic_history):
        if entry.get("caster") != ctx.caster_id and not entry.get("stolen"):
            stolen_entry = entry
            stolen_card = entry.get("card")
            break
    if stolen_card is None:
        return EffectResult(False, "对方没有使用过魔法卡")
    # Remove the physical copy from the discard pile so this is a transfer.
    for index, candidate in enumerate(ctx.room.magic_discard):
        if candidate is stolen_card or (
            candidate.name == stolen_card.name and candidate.speed == stolen_card.speed
        ):
            ctx.room.magic_discard.pop(index)
            break
    if stolen_entry is not None:
        stolen_entry["stolen"] = True
    ctx.caster.magic_hand.append(stolen_card)
    await ctx.sync_hand(ctx.caster_id)
    return EffectResult(True, f"成功盗取对方的{stolen_card.name}")


@register("钢筋铁骨")
async def iron_bones(ctx: EffectContext) -> EffectResult:
    alive = alive_ships(ctx.caster)
    if ctx.caster.remaining_ships < 2 or len(alive) < 2:
        return EffectResult(False, "需要至少2艘战舰才能发动")
    sacrificed = alive[-1]
    ctx.caster.ships.remove(sacrificed)
    if sacrificed not in ctx.caster.sunken_ships:
        ctx.caster.sunken_ships.append(sacrificed)
    ctx.caster.remaining_ships -= 1
    for ship in ctx.caster.ships:
        if is_ship_alive(ctx.caster, ship):
            ship.invincible = True
    return EffectResult(True, "牺牲一艘战舰，其他战舰进入无敌状态")


BATCH_A_CARDS: tuple[str, ...] = (
    "余音绕梁",
    "无中生有",
    "极限增援",
    "无暇圣心",
    "火力全开",
    "溅射",
    "雷达子弹",
    "越战越勇",
    "神威！",
    "冻结",
    "轰炸",
    "硫磺火焰",
    "探测雷达",
    "饮血",
    "Freezing！",
    "五险一金",
    "卧薪尝胆",
    "八方来财",
    "百亿补贴",
    "看破！",
    "疗愈",
    "盗亦有道",
    "钢筋铁骨",
)


__all__ = ["BATCH_A_CARDS"]
