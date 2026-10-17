"""旧运行时对象与 Combat Kernel 之间的兼容适配。

该模块不导入 ``server``，因此可以在领域测试和后续 shadow 对照测试中独立使用。
真正的房间写回、Socket 广播和结算仍由旧 handler 负责，接管时机留给后续阶段。
"""

from __future__ import annotations

from typing import Any, Iterable

from domain.combat import (
    AttackCommand,
    Cell,
    CombatResolution,
    CombatState,
    ShipState,
    resolve_attack,
)


def _cell(value: Any) -> Cell:
    if isinstance(value, dict):
        return Cell(value["x"], value["y"])
    return Cell(value.x, value.y)


def _cells(values: Iterable[Any]) -> frozenset[Cell]:
    return frozenset(_cell(value) for value in values)


def build_combat_state(
    *,
    attacker_id: str,
    defender_id: str,
    attacker: Any,
    defender: Any,
    attacks_remaining: int,
) -> CombatState:
    """从旧 ``Player`` 形状构造领域快照。

    只读取旧对象，不修改它。`attacker.attacks` 是本回合已经攻击过的格子，
    `defender.ships` 是仍保留沉船记录的完整船列表。
    """

    ships = tuple(
        ShipState(
            positions=_cells(ship.positions),
            hits=_cells(ship.hits),
            invincible=bool(getattr(ship, "invincible", False)),
            shield=bool(getattr(ship, "shield", False)),
        )
        for ship in getattr(defender, "ships", ())
    )
    return CombatState(
        attacker_id=attacker_id,
        defender_id=defender_id,
        defender_ships=ships,
        attacked_cells=_cells(getattr(attacker, "attacks", ())),
        attacks_remaining=int(attacks_remaining),
        attacker_remaining_ships=int(getattr(attacker, "remaining_ships", 0)),
        defender_remaining_ships=int(getattr(defender, "remaining_ships", 0)),
    )


def resolve_legacy_attack(
    state: CombatState,
    *,
    attacker_id: str,
    x: int,
    y: int,
    forced_kill: bool = False,
) -> CombatResolution:
    """为旧 handler 提供明确的命令入口。"""

    return resolve_attack(
        state,
        AttackCommand(
            attacker_id=attacker_id,
            x=x,
            y=y,
            forced_kill=forced_kill,
        ),
    )


def resolution_to_legacy_payload(result: CombatResolution) -> dict[str, Any]:
    """转换成现有 ``AttackResult.to_dict`` 使用的字段形状。"""

    return {
        "attacker": result.attacker_id,
        "x": result.cell.x,
        "y": result.cell.y,
        "hit": result.hit,
        "ship_sunk": result.ship_sunk,
        "remaining_attacks": result.remaining_attacks,
        "attacker_remaining_ships": result.attacker_remaining_ships,
        "defender_remaining_ships": result.defender_remaining_ships,
        "shield_blocked": result.shield_blocked,
    }

