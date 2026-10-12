"""在兼容边界提取最少信息；消费者不持有 GameRoom。"""
from domain.observations import AttackObservation, SeatSnapshot, SettlementSnapshot


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
