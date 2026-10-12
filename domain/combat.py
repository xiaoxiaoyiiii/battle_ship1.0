"""纯攻击规则内核。

这里不处理房间查找、身份鉴权、Socket 广播、回放、统计或卡牌副作用。
这些职责留在应用层和兼容适配层，便于逐步替换旧的 ``server.handle_attack``。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal


BOARD_SIZE = 6


class CombatRuleError(ValueError):
    """攻击命令违反领域规则。"""


@dataclass(frozen=True, order=True)
class Cell:
    """棋盘上的一个合法坐标。"""

    x: int
    y: int

    def __post_init__(self) -> None:
        if isinstance(self.x, bool) or isinstance(self.y, bool):
            raise CombatRuleError("坐标必须是整数")
        if not isinstance(self.x, int) or not isinstance(self.y, int):
            raise CombatRuleError("坐标必须是整数")
        if not (0 <= self.x < BOARD_SIZE and 0 <= self.y < BOARD_SIZE):
            raise CombatRuleError("攻击坐标超出棋盘范围")


@dataclass(frozen=True)
class ShipState:
    """攻击规则需要看到的船状态。

    ``hits`` 只保存已经命中的船格。船沉没后仍保留在列表中，
    这与旧运行时的 ``Player.ships`` 语义一致。
    """

    positions: frozenset[Cell]
    hits: frozenset[Cell] = frozenset()
    invincible: bool = False
    shield: bool = False

    def __post_init__(self) -> None:
        if not self.positions:
            raise CombatRuleError("战舰必须至少占用一个格子")
        if not self.hits.issubset(self.positions):
            raise CombatRuleError("命中格必须属于战舰")

    @property
    def sunk(self) -> bool:
        return self.hits == self.positions


@dataclass(frozen=True)
class CombatState:
    """一次攻击所需的最小状态快照。"""

    attacker_id: str
    defender_id: str
    defender_ships: tuple[ShipState, ...]
    attacked_cells: frozenset[Cell] = frozenset()
    attacks_remaining: int = 0
    attacker_remaining_ships: int = 0
    defender_remaining_ships: int = 0

    def __post_init__(self) -> None:
        if self.attacks_remaining < 0:
            raise CombatRuleError("攻击次数不能为负数")
        if self.attacker_remaining_ships < 0 or self.defender_remaining_ships < 0:
            raise CombatRuleError("剩余战舰数不能为负数")


@dataclass(frozen=True)
class AttackCommand:
    attacker_id: str
    x: int
    y: int
    forced_kill: bool = False

    @property
    def cell(self) -> Cell:
        return Cell(self.x, self.y)


CombatEventKind = Literal["attack_resolved", "shield_absorbed", "ship_sunk"]


@dataclass(frozen=True)
class CombatEvent:
    kind: CombatEventKind
    attacker_id: str
    defender_id: str
    cell: Cell
    ship_index: int | None = None


@dataclass(frozen=True)
class CombatResolution:
    """领域层攻击结果和下一状态。"""

    state: CombatState
    attacker_id: str
    defender_id: str
    cell: Cell
    hit: bool
    ship_sunk: bool
    shield_blocked: bool
    remaining_attacks: int
    attacker_remaining_ships: int
    defender_remaining_ships: int
    events: tuple[CombatEvent, ...] = field(default_factory=tuple)


def resolve_attack(state: CombatState, command: AttackCommand) -> CombatResolution:
    """在快照上结算一发攻击，并返回不可变的下一状态。

    该函数只实现攻击规则，不触发任何外部副作用。调用方负责把事件映射成
    旧版广播、回放、统计和卡牌效果。
    """

    if command.attacker_id != state.attacker_id:
        raise CombatRuleError("还没到你的攻击回合")
    if state.attacks_remaining <= 0:
        raise CombatRuleError("本回合攻击次数已用尽")

    cell = command.cell
    if cell in state.attacked_cells:
        raise CombatRuleError("你已经攻击过这个位置了")

    ships = list(state.defender_ships)
    ship_index = next(
        (index for index, ship in enumerate(ships) if cell in ship.positions),
        None,
    )
    hit = ship_index is not None
    ship_sunk = False
    shield_blocked = False
    events: list[CombatEvent] = []

    if ship_index is not None:
        ship = ships[ship_index]
        if command.forced_kill:
            next_hits = frozenset(ship.positions)
            ship_sunk = not ship.sunk
            ships[ship_index] = replace(ship, hits=next_hits, shield=False)
        elif ship.invincible:
            # 无敌只显形，不造成伤害。
            pass
        elif ship.shield:
            shield_blocked = True
            ships[ship_index] = replace(ship, shield=False)
            events.append(
                CombatEvent(
                    kind="shield_absorbed",
                    attacker_id=state.attacker_id,
                    defender_id=state.defender_id,
                    cell=cell,
                    ship_index=ship_index,
                )
            )
        else:
            next_hits = ship.hits | {cell}
            ship_sunk = next_hits == ship.positions and not ship.sunk
            ships[ship_index] = replace(ship, hits=frozenset(next_hits))

    defender_remaining_ships = state.defender_remaining_ships
    if ship_sunk:
        defender_remaining_ships = max(0, defender_remaining_ships - 1)
        events.append(
            CombatEvent(
                kind="ship_sunk",
                attacker_id=state.attacker_id,
                defender_id=state.defender_id,
                cell=cell,
                ship_index=ship_index,
            )
        )

    # 护盾挡下的炮弹不计入已攻击格，但仍消耗一次攻击次数。
    attacked_cells = state.attacked_cells if shield_blocked else state.attacked_cells | {cell}
    next_state = replace(
        state,
        defender_ships=tuple(ships),
        attacked_cells=frozenset(attacked_cells),
        attacks_remaining=max(0, state.attacks_remaining - 1),
        defender_remaining_ships=defender_remaining_ships,
    )
    events.insert(
        0,
        CombatEvent(
            kind="attack_resolved",
            attacker_id=state.attacker_id,
            defender_id=state.defender_id,
            cell=cell,
            ship_index=ship_index,
        ),
    )
    return CombatResolution(
        state=next_state,
        attacker_id=state.attacker_id,
        defender_id=state.defender_id,
        cell=cell,
        hit=hit,
        ship_sunk=ship_sunk,
        shield_blocked=shield_blocked,
        remaining_attacks=next_state.attacks_remaining,
        attacker_remaining_ships=state.attacker_remaining_ships,
        defender_remaining_ships=defender_remaining_ships,
        events=tuple(events),
    )

