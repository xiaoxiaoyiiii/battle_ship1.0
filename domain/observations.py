"""供旁路能力读取的不可变事实，不携带运行时房间引用。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class AttackObservation:
    present: bool
    attacked: frozenset[tuple[int, int]]
    revealed: frozenset[tuple[int, int]]


@dataclass(frozen=True)
class CardObservation:
    present: bool
    hand_names: tuple[str | None, ...]
    own_ships: int
    opponent_ships: int
    last_hit: bool
    last_sunk: bool
    own_known_count: int
    opponent_known_count: int
    own_attacked_count: int


@dataclass(frozen=True)
class PlacementObservation:
    opponent_attacked: frozenset[tuple[int, int]]
    candidates: tuple[tuple[int, int] | None, ...]


@dataclass(frozen=True)
class ShipPickObservation:
    opponent_attacked: frozenset[tuple[int, int]]
    candidate_cells: tuple[frozenset[tuple[int, int]], ...]


@dataclass(frozen=True)
class TargetObservation:
    present: bool
    attacked: frozenset[tuple[int, int]]
    revealed: frozenset[tuple[int, int]]
    own_ship_cells: frozenset[tuple[int, int]]


@dataclass(frozen=True)
class ChoiceObservation:
    own_ships: int
    opponent_ships: int
    attacks_remaining: int


@dataclass(frozen=True)
class SeatSnapshot:
    player_ids: tuple[str, ...]


@dataclass(frozen=True)
class SettlementSnapshot:
    rounds: int
    winner_hits: int
    loser_hits: int
    winner_ships: int
    loser_ships: int
    duration_sec: float
    ended_by: str

    def facts(self) -> dict:
        """保留现有规则的字段语义，包括历史命名。"""
        wh, lh = self.winner_hits, self.loser_hits
        return {
            'rounds': self.rounds, 'attacker_total_hits': wh,
            'defender_total_hits': lh, 'loser_total_hits': lh,
            'attackers': ['a'] * (int(wh > 0) + int(lh > 0)),
            'max_hits': max(wh, lh), 'foe_ships': self.loser_ships,
            'total_ships': self.winner_ships + self.loser_ships,
            'duration_sec': self.duration_sec, 'ended_by': self.ended_by,
        }
