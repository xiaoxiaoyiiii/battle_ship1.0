"""Combat Kernel 与旧攻击结果的可选对照工具。"""

from __future__ import annotations

from typing import Any

from domain.combat import CombatResolution


def compare_core_result(
    expected: CombatResolution,
    *,
    hit: bool,
    ship_sunk: bool,
    shield_blocked: bool,
    remaining_attacks: int,
    defender_remaining_ships: int,
) -> dict[str, tuple[Any, Any]]:
    """返回新旧核心结果的差异，不抛异常、不改变对局状态。"""

    actual = {
        "hit": hit,
        "ship_sunk": ship_sunk,
        "shield_blocked": shield_blocked,
        "remaining_attacks": remaining_attacks,
        "defender_remaining_ships": defender_remaining_ships,
    }
    predicted = {
        "hit": expected.hit,
        "ship_sunk": expected.ship_sunk,
        "shield_blocked": expected.shield_blocked,
        "remaining_attacks": expected.remaining_attacks,
        "defender_remaining_ships": expected.defender_remaining_ships,
    }
    return {
        name: (predicted[name], actual[name])
        for name in predicted
        if predicted[name] != actual[name]
    }

