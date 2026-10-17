"""Phase 3：回合与阶段状态机测试。"""

import ast
from pathlib import Path

import pytest

from domain.turns import (
    TurnRuleError,
    TurnState,
    end_turn,
    enter_battle,
    enter_end,
)


def state(**overrides):
    values = {
        "attack_order": ("a", "b"),
        "current_attacker": "a",
        "current_phase": "preparation",
        "attacks_remaining": 0,
        "round": 1,
    }
    values.update(overrides)
    return TurnState(**values)


def test_preparation_to_battle_preserves_caller_computed_attacks():
    result = enter_battle(state(), attacks_remaining=4)
    assert result.current_phase == "battle"
    assert result.attacks_remaining == 4


def test_battle_to_end_requires_no_attackable_work():
    with pytest.raises(TurnRuleError):
        enter_end(state(current_phase="battle", attacks_remaining=1), has_attackable_cells=True)
    result = enter_end(state(current_phase="battle", attacks_remaining=1), has_attackable_cells=False)
    assert result.current_phase == "end"


def test_end_turn_changes_player_and_resets_phase_and_attacks():
    result = end_turn(state(current_phase="end", attacks_remaining=2))
    assert result.kind == "turn_change"
    assert result.state.current_attacker == "b"
    assert result.state.current_phase == "preparation"
    assert result.state.attacks_remaining == 0
    assert result.state.round == 1


def test_last_player_end_starts_new_round():
    result = end_turn(state(current_attacker="b", current_phase="end"))
    assert result.kind == "new_round"
    assert result.state.current_attacker == "a"
    assert result.state.round == 2


def test_skip_opponent_turn_moves_to_new_round_without_stopping_on_skipped_player():
    result = end_turn(
        state(current_phase="end", skip_opponent_turn="b")
    )
    assert result.kind == "new_round"
    assert result.skipped_player == "b"
    assert result.state.current_attacker == "a"
    assert result.state.skip_opponent_turn is None


def test_skip_next_turn_advances_to_next_available_player():
    result = end_turn(state(current_phase="end", skip_next_turn="b"))
    assert result.kind == "new_round"
    assert result.skipped_player == "b"
    assert result.state.current_attacker == "a"


def test_skip_opponent_stages_does_not_increment_round():
    result = end_turn(state(current_phase="end", skip_opponent_stages="b"))
    assert result.kind == "stage_skipped"
    assert result.skipped_player == "b"
    assert result.state.current_attacker == "a"
    assert result.state.round == 1
    assert result.state.attacks_remaining == 0


@pytest.mark.parametrize(
    "bad", [
        {"attack_order": ("a",), "current_attacker": "a"},
        {"attack_order": ("a", "a"), "current_attacker": "a"},
        {"attack_order": ("a", "b"), "current_attacker": "x"},
    ]
)
def test_invalid_turn_state_is_rejected(bad):
    with pytest.raises(TurnRuleError):
        state(**bad)


def test_illegal_phase_transitions_are_rejected():
    with pytest.raises(TurnRuleError):
        enter_battle(state(current_phase="battle"), attacks_remaining=1)
    with pytest.raises(TurnRuleError):
        enter_end(state(), has_attackable_cells=False)
    with pytest.raises(TurnRuleError):
        end_turn(state())


def test_domain_turns_has_no_runtime_framework_imports():
    source = Path(__file__).parents[1] / "domain" / "turns.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = {
        node.names[0].name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import) and node.names
    }
    imported.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert imported.isdisjoint({"flask", "flask_socketio", "sqlite3", "server"})

