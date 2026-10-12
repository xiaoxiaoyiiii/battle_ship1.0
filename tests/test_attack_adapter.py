"""旧运行时对象到 Combat Kernel 的适配测试。"""

from types import SimpleNamespace

from application.attack_service import (
    build_combat_state,
    resolution_to_legacy_payload,
    resolve_legacy_attack,
)


def pos(x, y, **extra):
    return SimpleNamespace(x=x, y=y, **extra)


def test_build_snapshot_does_not_mutate_legacy_objects():
    attacker = SimpleNamespace(
        attacks=[pos(0, 0)],
        remaining_ships=2,
    )
    defender_ship = SimpleNamespace(
        positions=[pos(1, 1), pos(1, 2)],
        hits=[pos(1, 1)],
        invincible=False,
        shield=False,
    )
    defender = SimpleNamespace(ships=[defender_ship], remaining_ships=1)

    state = build_combat_state(
        attacker_id="a",
        defender_id="d",
        attacker=attacker,
        defender=defender,
        attacks_remaining=2,
    )
    result = resolve_legacy_attack(state, attacker_id="a", x=1, y=2)

    assert defender_ship.hits == [pos(1, 1)]
    assert result.ship_sunk is True
    assert resolution_to_legacy_payload(result) == {
        "attacker": "a",
        "x": 1,
        "y": 2,
        "hit": True,
        "ship_sunk": True,
        "remaining_attacks": 1,
        "attacker_remaining_ships": 2,
        "defender_remaining_ships": 0,
        "shield_blocked": False,
    }


def test_adapter_preserves_shield_retry_semantics():
    attacker = SimpleNamespace(attacks=[], remaining_ships=1)
    defender_ship = SimpleNamespace(
        positions=[pos(2, 2)], hits=[], invincible=False, shield=True
    )
    defender = SimpleNamespace(ships=[defender_ship], remaining_ships=1)
    state = build_combat_state(
        attacker_id="a",
        defender_id="d",
        attacker=attacker,
        defender=defender,
        attacks_remaining=2,
    )

    blocked = resolve_legacy_attack(state, attacker_id="a", x=2, y=2)
    retried = resolve_legacy_attack(blocked.state, attacker_id="a", x=2, y=2)

    assert blocked.shield_blocked is True
    assert retried.ship_sunk is True

