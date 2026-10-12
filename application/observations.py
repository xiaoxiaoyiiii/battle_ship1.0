"""在兼容边界提取最少信息；消费者不持有 GameRoom。"""
from domain.observations import (
    AttackObservation, CardObservation, ChoiceObservation, PlacementObservation, SeatSnapshot,
    SettlementSnapshot, ShipPickObservation, TargetObservation,
)


def _cells(values):
    cells = set()
    for value in values or ():
        x = value.get('x') if isinstance(value, dict) else getattr(value, 'x', None)
        y = value.get('y') if isinstance(value, dict) else getattr(value, 'y', None)
        if isinstance(x, int) and isinstance(y, int):
            cells.add((x, y))
    return frozenset(cells)


def attack_observation(room, player_id):
    player = (getattr(room, 'players', None) or {}).get(player_id)
    return AttackObservation(
        player is not None, _cells(getattr(player, 'attacks', None)),
        _cells(getattr(player, 'revealed_positions', None)),
    )


def _opponent(room, player_id):
    for pid, player in (getattr(room, 'players', None) or {}).items():
        if pid != player_id:
            return player
    return None


def _cell(value):
    x = value.get('x') if isinstance(value, dict) else getattr(value, 'x', None)
    y = value.get('y') if isinstance(value, dict) else getattr(value, 'y', None)
    return (x, y) if isinstance(x, int) and isinstance(y, int) else None


def card_observation(room, player_id):
    player = (getattr(room, 'players', None) or {}).get(player_id)
    if player is None:
        return CardObservation(False, (), 0, 0, False, False, 0, 0, 0)
    opponent = _opponent(room, player_id)
    own_attacked = _cells(getattr(player, 'attacks', None))
    last = getattr(room, 'last_attack', None)
    last = last if isinstance(last, dict) else {}
    return CardObservation(
        True,
        tuple(getattr(card, 'name', None) for card in (getattr(player, 'magic_hand', None) or ())),
        int(getattr(player, 'remaining_ships', 0) or 0),
        int(getattr(opponent, 'remaining_ships', 0) or 0) if opponent is not None else 0,
        bool(last.get('hit')), bool(last.get('ship_sunk')),
        len(_cells(getattr(player, 'revealed_positions', None))),
        len(_cells(getattr(opponent, 'revealed_positions', None))) if opponent is not None else 0,
        len(own_attacked),
    )


def placement_observation(room, player_id, candidates):
    opponent = _opponent(room, player_id)
    return PlacementObservation(
        _cells(getattr(opponent, 'attacks', None)),
        tuple(_cell(candidate) if not isinstance(candidate, tuple) else candidate
              for candidate in candidates),
    )


def ship_pick_observation(room, player_id, candidates):
    opponent = _opponent(room, player_id)
    return ShipPickObservation(
        _cells(getattr(opponent, 'attacks', None)),
        tuple(_cells(getattr(ship, 'positions', None)) for ship in candidates),
    )


def target_observation(room, player_id):
    player = (getattr(room, 'players', None) or {}).get(player_id)
    if player is None:
        return TargetObservation(False, frozenset(), frozenset(), frozenset())
    own_cells = frozenset().union(*(
        _cells(getattr(ship, 'positions', None))
        for ship in (getattr(player, 'ships', None) or ())
    ))
    return TargetObservation(
        True, _cells(getattr(player, 'attacks', None)),
        _cells(getattr(player, 'revealed_positions', None)), own_cells,
    )


def choice_observation(room, player_id):
    player = (getattr(room, 'players', None) or {}).get(player_id)
    opponent = _opponent(room, player_id)
    return ChoiceObservation(
        int(getattr(player, 'remaining_ships', 0) or 0),
        int(getattr(opponent, 'remaining_ships', 0) or 0),
        int(getattr(room, 'attacks_remaining', 0) or 0),
    )


def seat_snapshot(room):
    players = getattr(room, 'players', None)
    return SeatSnapshot(tuple(str(pid) for pid in players) if isinstance(players, dict) else ())


def settlement_snapshot(room, winner_id, loser_id, duration_sec):
    winner, loser = room.players.get(winner_id), room.players.get(loser_id)
    def ships(player):
        return getattr(player, 'ships', None) or ()
    def hits(player):
        return sum(len(getattr(ship, 'hits', None) or ()) for ship in ships(player))
    return SettlementSnapshot(
        max(0, int(getattr(room, 'round', 0) or 0)), hits(winner), hits(loser),
        len(ships(winner)), len(ships(loser)), duration_sec,
        getattr(room, 'end_reason', None) or 'attacks',
    )
