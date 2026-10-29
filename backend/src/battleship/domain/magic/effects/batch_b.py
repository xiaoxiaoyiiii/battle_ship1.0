"""Batch B: interactive normal cards, field cards and judgement cards (#11).

Ported from the legacy apply_magic_effect branches. Every branch is registered
in battleship.domain.magic.registry; the service owns wire frames and any state
that needs a human choice is represented in room fields (never magic_temp_data
alone, because it is overwritten as a whole).
"""

from __future__ import annotations

from typing import Any

from ... import effects
from ... import replay as replay_rules
from ...room import PlayerShip, alive_ships, card_payload
from ..cards import MagicCard
from .. import precheck, temps
from ..interaction import (
    cell_xy,
    clear_ship_picks,
    find_ship_at,
    pick_cell_from_target,
    placement_blocked_cells,
)
from ..lifecycle import clear_multiturn_effects
from ..registry import register
from ..rules import lanyu_requirement_reason
from .base import EffectContext, EffectResult

DICE_EFFECT_TEXT = {
    1: "复活对方的一艘战舰",
    2: "对方抽一张牌",
    3: "双方各弃一张手牌",
    4: "自己抽两张牌",
    5: "复活自己的至多两艘战舰",
    6: "对手牺牲两艘战舰",
}


@register("桃园结义")
async def taoyuan(ctx: EffectContext) -> EffectResult:
    if ctx.caster.effect_flags.no_draw or ctx.opponent.effect_flags.no_draw:
        return EffectResult(False, "无中生有生效期间，双方无法获得魔法卡")
    count = int(ctx.caster.remaining_ships or 0)
    drawn: list[MagicCard] = []
    for _ in range(min(count, len(ctx.room.magic_deck))):
        drawn.append(ctx.room.magic_deck.pop(0))
    if not drawn:
        return EffectResult(False, "无法抽取卡牌")
    temps.store(ctx.room, {
        "type": "taoyuan_choice",
        "caster": ctx.caster_id,
        "opponent": ctx.opponent_id,
        "cards": drawn,
        "player_deck_backup": [],
    })
    await ctx.emit(
        "taoyuan_waiting",
        {"message": "对方正在结算桃园结义效果 请等待"},
        to=ctx.opponent.socket_id,
    )
    result = EffectResult(
        True, f"抽了{len(drawn)}张牌，请选择", temp_data_id="taoyuan_choice"
    )
    result.extra["cards"] = [card_payload(card) for card in drawn]
    return result


@register("亡羊补牢")
async def wangyang(ctx: EffectContext) -> EffectResult:
    if ctx.caster.effect_flags.no_draw:
        return EffectResult(False, "无中生有生效期间，无法获得魔法卡")
    own_card = ctx.room.magic_discard.pop() if ctx.room.magic_discard else None
    count = max(int(ctx.caster.remaining_ships or 0), int(ctx.opponent.remaining_ships or 0))
    if not ctx.room.magic_discard or count <= 0:
        if own_card is not None:
            # 放回刚才为看一眼而取出的那张：这是回滚（弃牌区内容没变），不是
            # 一次新弃牌，所以不发 CARD_DISCARDED —— 否则同一张牌会被数两次。
            ctx.room.magic_discard.append(own_card)
        return EffectResult(False, "弃牌区没有可挑选的卡牌")
    take = min(count, len(ctx.room.magic_discard))
    candidates = ctx.room.magic_discard[-take:]
    del ctx.room.magic_discard[-take:]
    temps.store(ctx.room, {
        "type": "wangyang_choice",
        "caster": ctx.caster_id,
        "cards": candidates,
        "own_card": own_card,
    })
    result = EffectResult(
        True,
        f"请从弃牌区最新{len(candidates)}张牌中选1张加入手牌",
        temp_data_id="wangyang_choice",
    )
    result.extra["cards"] = [card_payload(card) for card in candidates]
    return result


@register("灵气复苏")
async def lingqi(ctx: EffectContext) -> EffectResult:
    max_ships = max(1, int(ctx.caster.remaining_ships or 0), int(ctx.opponent.remaining_ships or 0))
    temps.store(ctx.room, {
        "type": "lingqi_choice",
        "caster": ctx.caster_id,
        "opponent": ctx.opponent_id,
        "max_ships": max_ships,
    })
    await ctx.emit(
        "lingqi_waiting",
        {"message": "对方正在结算灵气复苏效果 请等待"},
        to=ctx.opponent.socket_id,
    )
    result = EffectResult(True, "请选择灵气复苏的船数", temp_data_id="lingqi_choice")
    result.extra["max_ships"] = max_ships
    return result


@register("明智埋葬")
async def bury(ctx: EffectContext) -> EffectResult:
    deck = ctx.room.magic_deck or []
    hand = ctx.opponent.magic_hand or []
    if not deck and not hand:
        return EffectResult(False, "牌堆与对方手牌均为空，无法发动")
    candidates: list[dict[str, Any]] = []
    for source, pile in (("deck", deck), ("opponent_hand", hand)):
        for index, card in enumerate(pile):
            candidates.append({
                "source": source,
                "index": index,
                "name": card.name,
                "speed": card.speed,
                "type": card.type,
                "description": card.description,
            })
    temps.store(ctx.room, {
        "type": "bury_choice",
        "caster": ctx.caster_id,
        "candidates": candidates,
    })
    result = EffectResult(True, "请选择要埋葬的卡牌（牌堆或对方手牌）", temp_data_id="bury_choice")
    result.extra["cards"] = [dict(entry) for entry in candidates]
    return result


@register("仁王之盾")
async def renwang(ctx: EffectContext) -> EffectResult:
    if int(ctx.caster.remaining_ships or 0) == 0:
        return EffectResult(False, "没有战舰可保护")
    choice = {
        "type": "shield_choice",
        "caster": ctx.caster_id,
        "ships": [
            {"positions": [{"x": p.x, "y": p.y} for p in ship.positions]}
            for ship in ctx.caster.ships
        ],
    }
    temps.store(ctx.room, choice)
    picked = await ctx.request_ship_pick(
        ctx.caster_id,
        "shield_choice",
        "仁王之盾：请选择要保护的战舰（至多 3 艘）",
        False,
        True,
    )
    if picked is not None:
        # AI 座位同步给出答案：就地加盾并结束这一项，否则 temp 会一直挂着。
        already_shielded = picked.shield
        picked.shield = True
        temps.finish_id(ctx.room, str(choice["id"]))
        await ctx.sync_player_ships(ctx.caster_id)
        return EffectResult(True, "已为 1 艘战舰添加护盾", extra={"audio_silent": already_shielded})
    return EffectResult(True, "请选择要保护的战舰", temp_data_id="shield_choice")


@register("神之宣告")
async def divine_decree(ctx: EffectContext) -> EffectResult:
    if int(ctx.caster.remaining_ships or 0) <= 2:
        return EffectResult(False, "您的船数不足，无法使用神之宣告")

    # 连锁里可能已经把目标船弄死了：动手之前再查一次，整体失败而不是部分献祭。
    stale = precheck.resolution_error(
        ctx.room, ctx.caster_id, "神之宣告", ctx.targets
    )
    if stale:
        return EffectResult(False, stale)

    chosen: list[PlayerShip] = []
    raw = ctx.targets.get("selected_cells") if isinstance(ctx.targets, dict) else None
    if isinstance(raw, list):
        for cell in raw:
            xy = cell_xy(cell)
            if xy is None:
                continue
            ship = find_ship_at(ctx.caster, xy, alive_only=True)
            if ship is not None and ship not in chosen:
                chosen.append(ship)
    if len(chosen) < 2:
        # 卡面要求「选自己两艘船死亡」：没选够就拒绝并退牌，不能替玩家随机献祭。
        return EffectResult(False, "请先选中自己两艘要牺牲的战舰")

    for ship in chosen[:2]:
        await ctx.sacrifice_ship(ctx.caster_id, ship, "divine_decree")

    try:
        effect_choice = int(
            (ctx.targets or {}).get("effect_choice")
            if (ctx.targets or {}).get("effect_choice") is not None
            else (ctx.room.magic_temp_data or {}).get("effect_choice", 1)
        )
    except (TypeError, ValueError):
        effect_choice = 1

    if effect_choice == 1:
        picked = await ctx.request_ship_pick(
            ctx.opponent_id,
            "divine_decree",
            "神之宣告生效：请点选一艘自己的战舰，使其阵亡",
            False,
            False,
        )
        if picked is not None:
            await ctx.sacrifice_ship(ctx.opponent_id, picked, "divine_decree")
            return EffectResult(True, "牺牲两艘战舰，对方一艘战舰被摧毁")
        return EffectResult(True, "牺牲两艘战舰，等待对方选择阵亡的战舰")

    ctx.room.skip_opponent_stages = ctx.opponent_id
    return EffectResult(True, "牺牲两艘战舰，跳过对方本回合所有阶段")


@register("绝处逢生")
async def last_stand(ctx: EffectContext) -> EffectResult:
    if int(ctx.caster.remaining_ships or 0) < 3:
        return EffectResult(False, "需要至少3艘战舰才能发动")

    sacrificed = alive_ships(ctx.caster)
    original_cells = [[p.x, p.y] for ship in sacrificed for p in ship.positions]
    for ship in sacrificed:
        ship.hits = list(ship.positions)
        if ship in ctx.caster.ships:
            ctx.caster.ships.remove(ship)
        if ship not in ctx.caster.sunken_ships:
            ctx.caster.sunken_ships.append(ship)
        replay_rules.note_ship_lost(
            ctx.room, ctx.caster_id, [{"x": p.x, "y": p.y} for p in ship.positions]
        )
    ctx.caster.remaining_ships = 0

    await ctx.clear_board_effects([ctx.caster_id], "绝处逢生")
    if sacrificed:
        await ctx.on_ship_destroyed(ctx.caster_id, sacrificed[-1])
        for ship in sacrificed:
            await ctx.emit(
                "ship_sacrificed",
                {
                    "player": ctx.caster_id,
                    "positions": [{"x": p.x, "y": p.y} for p in ship.positions],
                    "reason": "last_stand",
                },
                room=ctx.room.id,
            )
        await ctx.sync_ships()
        await ctx.sync_player_ships(ctx.caster_id)
    await ctx.clear_multiturn_effects("绝处逢生")

    snapshot = ctx.room.game_effects.get(f"prediction_initial_{ctx.caster_id}")
    if isinstance(snapshot, dict):
        snapshot["sunken"] = len(ctx.caster.sunken_ships)

    ctx.room.game_effects["last_stand_cells"] = original_cells
    ctx.room.game_effects["last_stand_owner"] = ctx.caster_id
    cells = [{"x": x, "y": y} for x, y in original_cells]
    await ctx.emit("last_stand_cells", {"cells": cells, "owner": ctx.caster_id}, room=ctx.room.id)

    # #38：锁卡是 turn 边界，「击杀即胜」要活到终局（match 边界）。
    effects.grant_flag(ctx.room, ctx.caster_id, "last_stand", boundary=effects.BOUNDARY_TURN)
    effects.grant_flag(
        ctx.room, ctx.caster_id, "last_stand_win", boundary=effects.BOUNDARY_MATCH
    )
    await ctx.sync_active_effects()
    await ctx.start_placement(ctx.caster_id, "last_stand", 1)
    await ctx.refresh_replay_ships()
    return EffectResult(
        True,
        "已牺牲全部战舰，请在所有原本有战舰的格子上选择一格放置唯一一艘战舰",
        temp_data_id="last_stand_choice",
    )


@register("死者苏生")
async def revive_one(ctx: EffectContext) -> EffectResult:
    if not ctx.caster.sunken_ships:
        return EffectResult(False, "没有可复活的战舰")
    await ctx.start_placement(ctx.caster_id, "revive", 1)
    return EffectResult(
        True,
        "请选择复活战舰的部署位置（未被攻击过的空格）",
        temp_data_id="revive_choice",
    )


@register("回光返照")
async def last_chance(ctx: EffectContext) -> EffectResult:
    if ctx.room.attack_order and ctx.room.attack_order[0] != ctx.caster_id:
        return EffectResult(False, "只能在自己先手时发动")

    await ctx.clear_board_effects([ctx.caster_id], "回光返照")
    await ctx.clear_multiturn_effects("回光返照")
    ctx.caster.ships = []
    ctx.caster.sunken_ships = []
    ctx.caster.remaining_ships = 0
    ctx.caster.needs_reset = True
    ctx.opponent.attacks = []
    ctx.opponent.revealed_positions = []
    await ctx.emit_board_attacks()
    replay_rules.note_board_reset(ctx.room, ctx.caster_id)
    replay_rules.note_board_replaced(ctx.room, ctx.caster_id)

    ctx.room.current_phase = ctx.room.current_phase.__class__.END
    ctx.room.state = ctx.room.state.__class__.PLACING_SHIPS
    ctx.room.attacks_remaining = 0
    ctx.caster.max_ships = 6
    ctx.room.huiguang_awaiting_placement = True
    ctx.room.game_effects["reset_audio"] = {"caster": ctx.caster_id, "card": "回光返照"}
    await ctx.emit(
        "reset_gameboard",
        {
            "new_max_ships": ctx.caster.max_ships,
            "message": "回光返照生效，请重新摆放战舰",
        },
        to=ctx.caster.socket_id,
    )
    await ctx.ai_place_board(ctx.caster_id)

    ctx.room.game_effects["last_chance"] = {
        "caster": ctx.caster_id,
        "active": True,
        "round": ctx.room.round,
    }
    return EffectResult(
        True,
        "已清空棋盘，请重新摆放战舰，本回合战斗阶段跳过。"
        "若对方在本大回合内对您的船造成伤害，您将直接判负",
    )


@register("败者食尘")
async def polar_reversal(ctx: EffectContext) -> EffectResult:
    await ctx.clear_board_effects(list(ctx.room.players), "败者食尘")
    await ctx.clear_multiturn_effects("败者食尘")
    for player in ctx.room.players.values():
        player.ships = []
        player.attacks = []
        player.remaining_ships = 0
        player.needs_reset = True
        player.revealed_positions = []
        player.max_ships = 6
        player.sunken_ships = []
        if hasattr(player, "opponent_attacks"):
            player.opponent_attacks = []
        player.magic_blocked = False
        player.magic_blocked_round = None
        player.damage_dealt_this_turn = 0
        player.ship_reductions_this_turn = 0
    # #38：整对象重置统一走 reset_all（match 边界清租约 + 投影）。
    effects.reset_all(ctx.room)

    ctx.room.field_magic = None
    ctx.room.field_magic_owner = None
    ctx.room.game_effects = {}
    # 不要在这里清连锁与弃牌堆：本效果可能正是连锁里的一张，清掉会让下层
    # 待结算的卡既不被结算也不退牌（吞卡）；chain 由 _resolve_chain 收尾。
    temps.clear(ctx.room)
    clear_ship_picks(ctx.room)
    ctx.room.pending_wuyou_dreams = {}
    ctx.room.pending_bingliang = {}
    ctx.room.bingliang_skip_draw = {}
    ctx.room.pending_dice_discard = {}
    ctx.room.pending_dice_discard_label = {}
    discard_queue = getattr(ctx.room, "dice_discard_queue", None)
    if discard_queue is not None:
        discard_queue.clear()
    ctx.room.last_attack = None
    ctx.room.skip_opponent_turn = None
    ctx.room.skip_next_turn = None
    ctx.room.skip_opponent_stages = None
    ctx.room.huiguang_awaiting_placement = False
    replay_rules.note_board_reset(ctx.room)
    replay_rules.note_board_replaced(ctx.room)

    ctx.room.lingqi_saved_state = {
        "attack_order": list(ctx.room.attack_order),
        "current_attacker": ctx.room.current_attacker,
        "current_phase": getattr(ctx.room.current_phase, "value", ctx.room.current_phase),
        "round": ctx.room.round,
        "attacks_remaining": ctx.room.attacks_remaining,
    }
    ctx.room.lingqi_resurgence_applied = True
    ctx.room.state = ctx.room.state.__class__.PLACING_SHIPS
    ctx.room.attacks_remaining = 0
    ctx.room.polar_reversal_applied = True
    ctx.room.game_effects["zero_attacks_round"] = ctx.room.round
    ctx.room.game_effects["reset_audio"] = {"caster": ctx.caster_id, "card": "败者食尘"}

    for player in ctx.room.players.values():
        await ctx.emit(
            "reset_gameboard",
            {
                "new_max_ships": player.max_ships,
                "message": "败者食尘生效，双方棋盘已重置为6艘，请重新摆放（手牌保留）",
            },
            to=player.socket_id,
        )
    await ctx.ai_place_board(ctx.caster_id)
    for other_id in list(ctx.room.players):
        if other_id != ctx.caster_id:
            await ctx.ai_place_board(other_id)
    return EffectResult(
        True,
        "败者食尘生效：双方棋盘重置为6艘并重新摆放，手牌保留；本大回合双方攻击次数为0",
    )


@register("守株待兔")
async def trap(ctx: EffectContext) -> EffectResult:
    if int(ctx.caster.remaining_ships or 0) == 0:
        return EffectResult(False, "没有战舰可设置陷阱")
    picked = await ctx.request_ship_pick(
        ctx.caster_id, "trap_setup", "守株待兔：请点选一艘自己的战舰设置陷阱", False, False
    )
    if picked is None:
        return EffectResult(True, "请选择要设置陷阱的战舰")
    already_trapped = picked.trap
    picked.trap = True
    await ctx.log(
        f"第{ctx.room.round}回合 · {ctx.name(ctx.caster_id)} 的【守株待兔】为一艘战舰设置陷阱",
        "magic",
        {"caster": ctx.caster_id, "card": "守株待兔"},
    )
    await ctx.emit(
        "trap_set",
        {
            "player": ctx.caster_id,
        },
        room=ctx.room.id,
    )
    return EffectResult(True, "已为一艘战舰设置陷阱（本回合该船被击沉时对方需牺牲两艘）", extra={"audio_silent": already_trapped})


@register("神机妙算")
async def shenji(ctx: EffectContext) -> EffectResult:
    if "prediction" not in (ctx.room.magic_temp_data or {}):
        await ctx.open_shenji(ctx.caster_id)
        return EffectResult(True, "请宣言预测减少的船数（0-6）", temp_data_id="shenji_declare")
    try:
        value = max(0, min(6, int(ctx.room.magic_temp_data.get("prediction", 0))))
    except (TypeError, ValueError):
        value = 0
    await ctx.apply_shenji(ctx.caster_id, value)
    return EffectResult(True, f"宣言船数减少{value}，若预测成功则不会减少")


@register("增援")
async def reinforce(ctx: EffectContext) -> EffectResult:
    await ctx.start_placement(ctx.caster_id, "reinforce", 1)
    return EffectResult(
        True, "请选择增援战舰的部署位置（未被攻击过的空格）",
        temp_data_id="reinforcement_choice",
    )


@register("滥竽充数")
async def lanyu(ctx: EffectContext) -> EffectResult:
    reason = lanyu_requirement_reason(ctx.room, ctx.caster_id, ctx.card)
    if reason:
        return EffectResult(False, reason)
    max_ships = int(getattr(ctx.caster, "max_ships", 6) or 6)
    needed = max_ships - int(ctx.caster.remaining_ships or 0)
    available = 36 - len(placement_blocked_cells(ctx.room, ctx.caster_id))
    count = min(needed, available)
    if count <= 0:
        return EffectResult(False, "没有可放置的格子，滥竽充数无法生效")
    ctx.room.game_effects.setdefault("lanyu_temp_ships", {}).setdefault(ctx.caster_id, [])
    await ctx.start_placement(ctx.caster_id, "lanyu", count)
    await ctx.log(
        f"第{ctx.room.round}回合 · {ctx.name(ctx.caster_id)} 的【滥竽充数】"
        f"补充{count}艘战舰（大回合结束时收回）",
        "magic",
        {"caster": ctx.caster_id, "card": "滥竽充数", "count": count},
    )
    return EffectResult(
        True,
        f"请选择{count}艘补充战舰的部署位置（大回合结束时强制收回）",
        temp_data_id="lanyu_placement",
    )


@register("克苏鲁之眼")
async def kraken_eye(ctx: EffectContext) -> EffectResult:
    if not ctx.caster.ships or not ctx.opponent.ships:
        return EffectResult(False, "双方都必须有战舰才能使用")
    cell = pick_cell_from_target(ctx.targets)
    if cell is None:
        return EffectResult(False, "请选择一艘自己的战舰")
    caster_ship = find_ship_at(ctx.caster, cell, alive_only=True)
    if caster_ship is None:
        return EffectResult(False, "必须选择自己【还活着】的战舰所在的格子（已沉没的船不能选）")

    revealed_new = any(p not in ctx.opponent.revealed_positions for p in caster_ship.positions)
    ctx.opponent.revealed_positions.extend(caster_ship.positions)
    if ctx.opponent.socket_id:
        await ctx.emit(
            "revealed_positions",
            {"positions": [{"x": p.x, "y": p.y} for p in caster_ship.positions]},
            to=ctx.opponent.socket_id,
        )
    picked = await ctx.request_ship_pick(
        ctx.opponent_id,
        "kraken_eye",
        "克苏鲁之眼生效：请点选一艘自己的战舰暴露位置",
        False,
        False,
    )
    if picked is not None:
        revealed_new |= any(p not in ctx.caster.revealed_positions for p in picked.positions)
        ctx.caster.revealed_positions.extend(picked.positions)
        if ctx.caster.socket_id:
            await ctx.emit(
                "revealed_positions",
                {"positions": [{"x": p.x, "y": p.y} for p in picked.positions]},
                to=ctx.caster.socket_id,
            )
        return EffectResult(True, "双方各暴露一艘战舰位置", extra={"audio_silent": not revealed_new})
    for pick in ctx.room.pending_ship_picks:
        if pick.get("reason") == "kraken_eye" and pick.get("source_caster") == ctx.caster_id:
            pick["audio_revealed_new"] = revealed_new
    return EffectResult(True, "已暴露自己一艘战舰的位置，等待对方选择要暴露的战舰")


# --------------------------------------------------------------------- fields


@register("恶魔契约")
async def demon_contract(ctx: EffectContext) -> EffectResult:
    await ctx.place_field(ctx.card)
    ctx.room.game_effects["demon_contract"] = True
    return EffectResult(True, "恶魔契约生效，双方船数增减绑定")


@register("禁忌果实")
async def forbidden_fruit(ctx: EffectContext) -> EffectResult:
    await ctx.place_field(ctx.card)
    return EffectResult(True, "禁忌果实生效，双方只能使用失灵！和场地魔法")


@register("伊甸园")
async def eden(ctx: EffectContext) -> EffectResult:
    await ctx.place_field(ctx.card)
    if (
        getattr(ctx.room.state, "value", ctx.room.state) == "attacking"
        and ctx.phase == "preparation"
        and ctx.room.current_attacker in ctx.room.players
    ):
        await ctx.recalc_attacks()
        await ctx.emit(
            "attacks_updated",
            {
                "current_attacker": ctx.room.current_attacker,
                "attacks_remaining": ctx.room.attacks_remaining,
            },
            room=ctx.room.id,
        )
    return EffectResult(True, "伊甸园生效，攻击次数变为6-n")


@register("教皇旨意")
async def papal_edict(ctx: EffectContext) -> EffectResult:
    await ctx.place_field(ctx.card)
    ctx.room.game_effects["papal_edict"] = True
    ctx.room.attacks_remaining = 0
    await ctx.emit(
        "attacks_updated",
        {
            "current_attacker": ctx.room.current_attacker,
            "attacks_remaining": 0,
        },
        room=ctx.room.id,
    )
    return EffectResult(True, "教皇旨意已生效，双方攻击次数变为0，通过弃置魔法卡攻击对方两次")


# ----------------------------------------------------------------- judgement


@register("命运骰子")
async def dice_of_fate(ctx: EffectContext) -> EffectResult:
    roll = int(ctx.rng.randint(1, 6))
    effect_text = DICE_EFFECT_TEXT[roll]
    await ctx.emit(
        "dice_rolled",
        {
            "roll": roll,
            "caster": ctx.caster_id,
            "effect_text": effect_text,
            "card": "命运骰子",
            "duration_ms": 3200,
        },
        room=ctx.room.id,
    )
    await ctx.log(
        f"第{ctx.room.round}回合 · {ctx.name(ctx.caster_id)} 使用【命运骰子】"
        f"摇出 {roll} 点：{effect_text}",
        "magic",
        {"caster": ctx.caster_id, "roll": roll, "card": "命运骰子"},
    )
    if roll == 1:
        from ..deck import revive_sunken_ships

        revived = (
            revive_sunken_ships(ctx.room, ctx.opponent_id, 1, reveal_to=ctx.caster_id)
            if ctx.opponent.sunken_ships
            else 0
        )
        message = "摇出1点：" + effect_text + (
            "，对方一艘战舰复活" if revived else "，对方没有可原地复活的沉船"
        )
    elif roll == 2:
        drawn = await ctx.draw(ctx.opponent_id)
        message = "摇出2点：" + effect_text + (
            "，对方抽了一张牌" if drawn else "，但对方未能抽牌（牌堆空或被禁止抽卡）"
        )
    elif roll == 3:
        await ctx.start_dice_discard(ctx.caster_id, ctx.opponent_id, None, "命运骰子")
        message = "摇出3点：" + effect_text + "，等待双方选择弃牌"
    elif roll == 4:
        drawn = 0
        for _ in range(2):
            if await ctx.draw(ctx.caster_id) is not None:
                drawn += 1
        message = f"摇出4点：{effect_text}（实际抽到{drawn}张）"
    elif roll == 5:
        from ..deck import revive_sunken_ships

        count = min(2, len(ctx.caster.sunken_ships))
        revived = (
            revive_sunken_ships(ctx.room, ctx.caster_id, count, reveal_to=ctx.opponent_id)
            if count
            else 0
        )
        message = "摇出5点：" + effect_text + (
            f"，自己复活了{revived}艘战舰" if revived else "，自己没有可原地复活的沉船"
        )
    else:
        alive = alive_ships(ctx.opponent)
        need = min(2, len(alive))
        sacrificed = 0
        for _ in range(need):
            picked = await ctx.request_ship_pick(
                ctx.opponent_id, "dice_sacrifice", "命运骰子：请点选一艘战舰牺牲", True, False
            )
            if picked is not None:
                await ctx.sacrifice_ship(ctx.opponent_id, picked, "dice_sacrifice")
                sacrificed += 1
        if need == 0:
            message = "摇出6点：" + effect_text + "，但对方没有可牺牲的战舰"
        elif sacrificed == need:
            message = f"摇出6点：{effect_text}（对方已牺牲{sacrificed}艘）"
        else:
            message = "摇出6点：" + effect_text + "，等待对方点选牺牲的战舰"
    return EffectResult(True, message)


@register("无忧梦呓")
async def wuyou(ctx: EffectContext) -> EffectResult:
    pending = ctx.room.pending_wuyou_dreams
    if not isinstance(pending, dict):
        pending = {}
        ctx.room.pending_wuyou_dreams = pending
    pending[ctx.caster_id] = int(pending.get(ctx.caster_id) or 0) + 1
    return EffectResult(
        True,
        f"无忧梦呓生效，{ctx.name(ctx.opponent_id)} 的下一个回合开始时拼点判定",
    )


@register("兵粮寸断")
async def bingliang(ctx: EffectContext) -> EffectResult:
    pending = ctx.room.pending_bingliang
    if not isinstance(pending, dict):
        pending = {}
        ctx.room.pending_bingliang = pending
    pending[ctx.caster_id] = int(pending.get(ctx.caster_id) or 0) + 1
    return EffectResult(
        True,
        f"兵粮寸断生效，{ctx.name(ctx.opponent_id)} 的准备阶段开始时判定",
    )


BATCH_B_CARDS: tuple[str, ...] = (
    "桃园结义", "亡羊补牢", "灵气复苏", "明智埋葬", "仁王之盾", "神之宣告",
    "绝处逢生", "死者苏生", "回光返照", "败者食尘", "守株待兔", "神机妙算",
    "增援", "滥竽充数", "克苏鲁之眼",
    "恶魔契约", "禁忌果实", "伊甸园", "教皇旨意",
    "命运骰子", "无忧梦呓", "兵粮寸断",
)

__all__ = ["BATCH_B_CARDS", "DICE_EFFECT_TEXT"]
