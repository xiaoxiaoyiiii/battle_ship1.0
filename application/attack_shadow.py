"""Combat Kernel 与旧攻击结果的可选对照工具。"""

from __future__ import annotations

from typing import Any, Callable

from domain.combat import CombatResolution


class AttackShadow:
    """可选的旧攻击路径对照器。

    影子路径只读取当前房间状态并返回预测结果，异常也只能记录日志，不能
    影响正式攻击流程。将这段诊断逻辑集中在这里，避免 ``server.py`` 混入
    兼容性代码，同时保留注入点供测试替换旧内核。
    """

    def __init__(
        self,
        *,
        build_state: Callable[..., Any],
        resolve_legacy: Callable[..., CombatResolution],
        log_exception: Callable[[str], None],
    ) -> None:
        self._build_state = build_state
        self._resolve_legacy = resolve_legacy
        self._log_exception = log_exception

    def resolve(
        self,
        room: Any,
        attacker_id: str,
        defender_id: str,
        x: int,
        y: int,
        *,
        enabled: bool,
    ) -> CombatResolution | None:
        if not enabled:
            return None
        try:
            state = self._build_state(
                attacker_id=attacker_id,
                defender_id=defender_id,
                attacker=room.players[attacker_id],
                defender=room.players[defender_id],
                attacks_remaining=room.attacks_remaining,
            )
            return self._resolve_legacy(
                state,
                attacker_id=attacker_id,
                x=x,
                y=y,
                forced_kill=room.players[attacker_id].effect_flags.forced_kill > 0,
            )
        except Exception:
            self._log_exception('combat shadow 预期计算失败')
            return None


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

