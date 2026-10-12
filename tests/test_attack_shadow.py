"""Phase 2：新旧攻击核心结果的对照工具测试。"""

from application.attack_shadow import compare_core_result
from domain.combat import AttackCommand, Cell, CombatState, ShipState, resolve_attack


def test_compare_core_result_is_empty_when_legacy_matches():
    state = CombatState(
        attacker_id="a",
        defender_id="d",
        defender_ships=(ShipState(frozenset({Cell(1, 1)})),),
        attacks_remaining=2,
        attacker_remaining_ships=1,
        defender_remaining_ships=1,
    )
    expected = resolve_attack(state, AttackCommand("a", 1, 1))

    assert compare_core_result(
        expected,
        hit=True,
        ship_sunk=True,
        shield_blocked=False,
        remaining_attacks=1,
        defender_remaining_ships=0,
    ) == {}


def test_compare_core_result_reports_only_differences():
    state = CombatState(
        attacker_id="a",
        defender_id="d",
        defender_ships=(ShipState(frozenset({Cell(1, 1)})),),
        attacks_remaining=2,
        attacker_remaining_ships=1,
        defender_remaining_ships=1,
    )
    expected = resolve_attack(state, AttackCommand("a", 0, 0))

    assert compare_core_result(
        expected,
        hit=True,
        ship_sunk=False,
        shield_blocked=False,
        remaining_attacks=1,
        defender_remaining_ships=1,
    ) == {"hit": (False, True)}

