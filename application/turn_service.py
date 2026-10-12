"""旧 GameRoom 与回合状态机之间的只读适配。"""

from __future__ import annotations

from typing import Any

from domain.turns import TurnState, TurnTransition, end_turn, enter_battle, enter_end


def build_turn_state(room: Any) -> TurnState:
    """读取旧房间的回合字段，不修改房间。"""

    return TurnState(
        attack_order=tuple(room.attack_order),
        current_attacker=room.current_attacker,
        current_phase=room.current_phase,
        attacks_remaining=room.attacks_remaining,
        round=room.round,
        skip_opponent_turn=getattr(room, "skip_opponent_turn", None),
        skip_next_turn=getattr(room, "skip_next_turn", None),
        skip_opponent_stages=getattr(room, "skip_opponent_stages", None),
    )


def predict_enter_battle(room: Any, attacks_remaining: int) -> TurnState:
    return enter_battle(build_turn_state(room), attacks_remaining)


def predict_enter_end(room: Any, *, has_attackable_cells: bool) -> TurnState:
    return enter_end(build_turn_state(room), has_attackable_cells=has_attackable_cells)


def predict_end_turn(room: Any) -> TurnTransition:
    return end_turn(build_turn_state(room))

