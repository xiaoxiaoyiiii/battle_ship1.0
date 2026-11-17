"""雷达和科技侦察共用的空格判定；显形不造成伤害或消耗炮数。"""
from .. import mutations as mutation_rules
from ..room.models import Position, is_ship_alive


def record_reveal_misses(room, caster_id, positions):
    caster = room.players[caster_id]
    opponent = room.players[room.opponent_of(caster_id)]
    affected = []
    for x, y in positions:
        cell = Position(x=x, y=y)
        occupied = any(is_ship_alive(opponent, ship) and cell in (ship.positions or [])
                       for ship in opponent.ships or [])
        if not occupied:
            caster.attacks.append(Position(x=x, y=y, hit=False, ship_sunk=False,
                                           is_splash=True, fog_miss=mutation_rules.active(room, 'E1')))
        affected.append(cell)
    return affected
