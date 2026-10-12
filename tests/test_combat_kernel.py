"""Phase 1：Combat Kernel 的纯规则测试。"""

import ast
from pathlib import Path

import pytest

from domain.combat import (
    AttackCommand,
    Cell,
    CombatRuleError,
    CombatState,
    ShipState,
    resolve_attack,
)


def ship(*cells: tuple[int, int], hits=(), **flags) -> ShipState:
    return ShipState(
        positions=frozenset(Cell(x, y) for x, y in cells),
        hits=frozenset(Cell(x, y) for x, y in hits),
        **flags,
    )


def state(*ships, attacks=2, attacked=(), defender_remaining=None):
    return CombatState(
        attacker_id="a",
        defender_id="d",
        defender_ships=tuple(ships),
        attacked_cells=frozenset(Cell(x, y) for x, y in attacked),
        attacks_remaining=attacks,
        attacker_remaining_ships=2,
        defender_remaining_ships=(len(ships) if defender_remaining is None else defender_remaining),
    )


def test_miss_consumes_attack_and_records_cell():
    result = resolve_attack(state(ship((5, 5))), AttackCommand("a", 0, 0))

    assert result.hit is False
    assert result.ship_sunk is False
    assert result.remaining_attacks == 1
    assert Cell(0, 0) in result.state.attacked_cells
    assert result.state.defender_remaining_ships == 1


def test_hit_updates_ship_without_sinking():
    result = resolve_attack(state(ship((1, 1), (1, 2))), AttackCommand("a", 1, 1))

    assert result.hit is True
    assert result.ship_sunk is False
    assert result.state.defender_ships[0].hits == frozenset({Cell(1, 1)})
    assert result.state.defender_remaining_ships == 1


def test_last_hit_sinks_ship_and_decrements_remaining_count():
    result = resolve_attack(
        state(ship((1, 1), (1, 2), hits=((1, 1),))),
        AttackCommand("a", 1, 2),
    )

    assert result.ship_sunk is True
    assert result.state.defender_ships[0].sunk is True
    assert result.state.defender_remaining_ships == 0
    assert [event.kind for event in result.events] == ["attack_resolved", "ship_sunk"]


def test_invincible_ship_is_visible_but_not_damaged():
    result = resolve_attack(state(ship((1, 1), invincible=True)), AttackCommand("a", 1, 1))

    assert result.hit is True
    assert result.ship_sunk is False
    assert result.state.defender_ships[0].hits == frozenset()


def test_shield_blocks_damage_and_allows_retry_of_same_cell():
    first = resolve_attack(state(ship((1, 1), shield=True)), AttackCommand("a", 1, 1))

    assert first.shield_blocked is True
    assert first.state.defender_ships[0].shield is False
    assert Cell(1, 1) not in first.state.attacked_cells
    assert first.remaining_attacks == 1

    second = resolve_attack(first.state, AttackCommand("a", 1, 1))
    assert second.hit is True
    assert second.shield_blocked is False
    assert second.state.defender_ships[0].hits == frozenset({Cell(1, 1)})


def test_forced_kill_ignores_invincibility_and_shield():
    result = resolve_attack(
        state(ship((1, 1), (1, 2), invincible=True, shield=True)),
        AttackCommand("a", 1, 1, forced_kill=True),
    )

    assert result.ship_sunk is True
    assert result.shield_blocked is False
    assert result.state.defender_ships[0].sunk is True
    assert result.state.defender_remaining_ships == 0


@pytest.mark.parametrize(
    "command",
    [AttackCommand("a", -1, 0), AttackCommand("a", 6, 0), AttackCommand("a", 1, 1)],
)
def test_invalid_or_duplicate_attack_is_rejected(command):
    base = state(ship((5, 5)), attacked=((1, 1),))
    with pytest.raises(CombatRuleError):
        resolve_attack(base, command)


def test_wrong_attacker_and_empty_turn_are_rejected():
    with pytest.raises(CombatRuleError, match="攻击回合"):
        resolve_attack(state(ship((0, 0))), AttackCommand("other", 1, 1))
    with pytest.raises(CombatRuleError, match="攻击次数"):
        resolve_attack(state(ship((0, 0)), attacks=0), AttackCommand("a", 1, 1))


def test_domain_kernel_has_no_runtime_framework_imports():
    source = Path(__file__).parents[1] / "domain" / "combat.py"
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

