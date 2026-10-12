"""准备、战斗、结束和回合交接的纯状态机。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal


TurnPhase = Literal["preparation", "battle", "end"]
TransitionKind = Literal["turn_change", "new_round", "stage_skipped"]


class TurnRuleError(ValueError):
    """阶段或回合转换不合法。"""


@dataclass(frozen=True)
class TurnState:
    attack_order: tuple[str, ...]
    current_attacker: str
    current_phase: TurnPhase = "preparation"
    attacks_remaining: int = 0
    round: int = 1
    skip_opponent_turn: str | None = None
    skip_next_turn: str | None = None
    skip_opponent_stages: str | None = None

    def __post_init__(self) -> None:
        if len(self.attack_order) < 2:
            raise TurnRuleError("回合顺序至少需要两名玩家")
        if len(set(self.attack_order)) != len(self.attack_order):
            raise TurnRuleError("回合顺序不能包含重复玩家")
        if self.current_attacker not in self.attack_order:
            raise TurnRuleError("当前攻击者不在回合顺序中")
        if self.current_phase not in ("preparation", "battle", "end"):
            raise TurnRuleError("未知的回合阶段")
        if self.attacks_remaining < 0:
            raise TurnRuleError("攻击次数不能为负数")
        if self.round < 1:
            raise TurnRuleError("大回合编号必须为正数")


@dataclass(frozen=True)
class TurnTransition:
    state: TurnState
    kind: TransitionKind
    skipped_player: str | None = None


def enter_battle(state: TurnState, attacks_remaining: int) -> TurnState:
    """从准备阶段进入战斗阶段。

    攻击次数由应用层按当前场地、船数和卡牌效果计算后传入；状态机只负责
    校验阶段并保存结果，避免复制攻击次数规则。
    """

    if state.current_phase != "preparation":
        raise TurnRuleError("只能从准备阶段进入战斗阶段")
    if attacks_remaining < 0:
        raise TurnRuleError("攻击次数不能为负数")
    return replace(state, current_phase="battle", attacks_remaining=attacks_remaining)


def enter_end(state: TurnState, *, has_attackable_cells: bool) -> TurnState:
    """从战斗阶段进入结束阶段。

    没有攻击次数，或棋盘已没有可攻击格时允许结束；否则拒绝交阶段。
    """

    if state.current_phase != "battle":
        raise TurnRuleError("只能从战斗阶段进入结束阶段")
    if state.attacks_remaining > 0 and has_attackable_cells:
        raise TurnRuleError("还有剩余攻击次数且存在可攻击格")
    return replace(state, current_phase="end")


def end_turn(state: TurnState) -> TurnTransition:
    """结束当前玩家回合，计算下一阶段和下一位玩家。"""

    if state.current_phase != "end":
        raise TurnRuleError("只能从结束阶段交接回合")

    current_index = state.attack_order.index(state.current_attacker)
    next_index = (current_index + 1) % len(state.attack_order)
    next_attacker = state.attack_order[next_index]
    skipped_player = None
    next_state = state

    # Freezing！：跳过对方本回合，直接进入新大回合。
    if next_state.skip_opponent_turn == next_attacker:
        skipped_player = next_attacker
        next_state = replace(next_state, skip_opponent_turn=None)
        next_index = (next_index + 1) % len(state.attack_order)
        next_attacker = state.attack_order[next_index]

    # 一般性的下一回合跳过。
    if next_state.skip_next_turn == next_attacker:
        skipped_player = next_attacker
        next_state = replace(next_state, skip_next_turn=None)
        next_index = (next_index + 1) % len(state.attack_order)
        next_attacker = state.attack_order[next_index]

    # 神之宣告：只跳过本大回合内对方阶段，不翻页。
    if next_state.skip_opponent_stages == next_attacker:
        skipped_player = next_attacker
        next_state = replace(next_state, skip_opponent_stages=None)
        next_index = (next_index + 1) % len(state.attack_order)
        next_attacker = state.attack_order[next_index]
        return TurnTransition(
            state=replace(
                next_state,
                current_attacker=next_attacker,
                current_phase="preparation",
                attacks_remaining=0,
            ),
            kind="stage_skipped",
            skipped_player=skipped_player,
        )

    if next_index == 0:
        return TurnTransition(
            state=replace(
                next_state,
                current_attacker=next_attacker,
                current_phase="preparation",
                attacks_remaining=0,
                round=state.round + 1,
            ),
            kind="new_round",
            skipped_player=skipped_player,
        )

    return TurnTransition(
        state=replace(
            next_state,
            current_attacker=next_attacker,
            current_phase="preparation",
            attacks_remaining=0,
        ),
        kind="turn_change",
        skipped_player=skipped_player,
    )

