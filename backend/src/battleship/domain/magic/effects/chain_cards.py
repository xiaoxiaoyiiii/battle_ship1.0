"""Chain negation cards: 失灵！ / 平等条约 / 加百列之光 (ticket #12).

These three are registered here, not in batch A, because their behaviour is the
chain engine's other half: they mark the item directly below them on the stack
as negated, and they may also tear down an already-placed field card when the
stack is empty. The target/immunity rule `negation_target` is shared with the
resolution engine (one implementation, DECISIONS #1).

Legacy reference: server.py:13318-13341 (`_tear_down_field_magic`),
14431-14467 (平等条约), 14846-14882 (加百列之光), 15036-15081 (失灵！).
"""

from __future__ import annotations

from typing import Any

from ...battle import recalc_attacker_attacks
from ..cards import MagicCard
from ..chain import equal_treaty_verdict, negation_target
from ..field import tear_down_field_magic as field_tear_down
from ..registry import register
from .base import EffectContext, EffectResult


# --------------------------------------------------------------- field magic


def _tear_down_field_magic(room: Any, caster_id: str | None = None) -> tuple[MagicCard | None, bool]:
    """Remove the active field card through the one field implementation."""

    if not room.field_magic:
        return None, False
    before = int(room.attacks_remaining or 0)
    in_battle = getattr(room.current_phase, 'value', room.current_phase) == 'battle'
    previous_base = recalc_attacker_attacks(room) if in_battle else 0
    room.attacks_remaining = before
    torn = field_tear_down(
        room, caster_id or room.current_attacker or ""
    )
    current_base = recalc_attacker_attacks(room)
    if in_battle:
        from ...battle import attacks_forced_zero
        room.attacks_remaining = 0 if attacks_forced_zero(room) else max(0, before + current_base - previous_base)
    return torn, int(room.attacks_remaining or 0) != before


async def _emit_field_teardown(ctx: EffectContext, torn: MagicCard,
                               attacks_changed: bool) -> None:
    await ctx.emit(
        "field_magic_updated",
        {"player_id": ctx.caster_id, "card": None},
        room=ctx.room.id,
    )
    if attacks_changed:
        await ctx.emit(
            "attacks_updated",
            {
                "current_attacker": ctx.room.current_attacker,
                "attacks_remaining": ctx.room.attacks_remaining,
            },
            room=ctx.room.id,
        )


# --------------------------------------------------------------- the cards


@register("失灵！")
async def shiling(ctx: EffectContext) -> EffectResult:
    # In a chain: negate the item directly below (self-negation included).
    if ctx.room.chain:
        target, why = negation_target(ctx.room, "失灵！")
        if target is None:
            return EffectResult(False, why or "没有可无效化的魔法卡")
        return EffectResult(True, f"将无效化{target.card.name}", negate_target=True)

    # No chain: tear down an already-placed field card (either owner's).
    if ctx.room.field_magic:
        torn, attacks_changed = _tear_down_field_magic(ctx.room, ctx.caster_id)
        await _emit_field_teardown(ctx, torn, attacks_changed)
        return EffectResult(True, f"成功无效化场地魔法「{getattr(torn, 'name', '')}」")

    # Otherwise fall back to the last card the opponent played this round.
    history = ctx.room.magic_history
    if history and history[-1].get("caster") != ctx.caster_id:
        last = history[-1]
        last_card = last.get("card")
        last_name = getattr(last_card, "name", None)
        if last_name in ("看破！", "加百列之光"):
            return EffectResult(False, "该魔法免疫失灵！")
        if last.get("round", ctx.room.round) != ctx.room.round:
            return EffectResult(False, "对方上一张魔法卡不是本回合使用的，失灵！无法无效化")
        history.pop()
        return EffectResult(True, f"无效化了{last_name}（若其效果已结算则不会回滚）")
    return EffectResult(False, "没有可无效化的魔法卡")


@register("加百列之光")
async def gabriel(ctx: EffectContext) -> EffectResult:
    """无效上一张连锁牌，并同时拆除当前场地。"""

    negated_count = 0
    chain_negated = False
    if ctx.room.chain:
        negated_count += 1
        chain_negated = True

    if not chain_negated and ctx.room.magic_history:
        last = ctx.room.magic_history[-1]
        if last.get("caster") != ctx.caster_id:
            ctx.room.magic_history.pop()
            negated_count += 1
            chain_negated = True

    torn = None
    attacks_changed = False
    if ctx.room.field_magic:
        torn, attacks_changed = _tear_down_field_magic(ctx.room, ctx.caster_id)
        negated_count += 1

    if negated_count == 0:
        return EffectResult(False, "没有可无效化的魔法卡或场地魔法")
    if torn is not None:
        await _emit_field_teardown(ctx, torn, attacks_changed)
        message = f"成功无效化场地魔法「{getattr(torn, 'name', '')}」"
        if chain_negated:
            message += "，并无效化上一张魔法卡"
        return EffectResult(True, message, negate_target=chain_negated)
    return EffectResult(True, "成功无效化连锁中的魔法卡", negate_target=chain_negated)


@register("平等条约")
async def equal_treaty(ctx: EffectContext) -> EffectResult:
    target, why = negation_target(ctx.room, "平等条约")
    if target is None:
        return EffectResult(False, why or "没有可无效化的魔法卡")
    # 看破！ can suppress this card inside the same chain, after it was played.
    if getattr(ctx.caster, "magic_blocked", False):
        return EffectResult(
            False, "你已被看破！压制，本回合魔法卡无效，平等条约无法发动"
        )
    would_change, reason = equal_treaty_verdict(ctx.room, target)
    if not would_change:
        return EffectResult(False, f"没有可无效化的船数改变效果（{reason}）")
    return EffectResult(True, f"将无效化{target.card.name}", negate_target=True)


__all__ = ["gabriel", "shiling", "equal_treaty"]
