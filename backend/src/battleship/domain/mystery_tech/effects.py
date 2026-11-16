"""科技的真实规则；摸牌数量由服务层交给既有共享牌堆执行。"""
import uuid

from .catalog import BY_ID
from .draft import TARGET_SECONDS, state
from ..room.models import BOARD_SIZE, PlayerShip, Position, alive_ships, is_ship_alive

TARGETED = {'emergency_repair', 'battlefield_recall', 'fleet_rebirth', 'sonar_pulse', 'spacetime_fold'}


def has(room, pid, tech_id):
    return room.mystery_tech and tech_id in state(room).get('active', {}).get(pid, [])


def reveal(room, viewer, positions):
    target = room.players[viewer].revealed_positions
    for pos in positions:
        if not any(p.x == pos.x and p.y == pos.y for p in target):
            target.append(Position(pos.x, pos.y))


def protect_new_ship(room, pid, ship):
    if has(room, pid, 'steady_defense'):
        ship.shield = True
    if room.mystery_tech:
        state(room).setdefault('fleet_life', {}).setdefault(pid, {})[id(ship)] = True


def maintain_fleet(room):
    if not room.mystery_tech:
        return
    for pid, player in room.players.items():
        life = state(room).setdefault('fleet_life', {}).setdefault(pid, {})
        for ship in player.ships:
            living = is_ship_alive(player, ship)
            if living and not life.get(id(ship), False):
                protect_new_ship(room, pid, ship)
            life[id(ship)] = living


def absorb_armor(room, owner, ship):
    if not has(room, owner, 'armor_plating'):
        return False
    spent = state(room).setdefault('armor_used', [])
    if id(ship) in spent:
        return False
    spent.append(id(ship))
    if viewer := room.opponent_of(owner):
        reveal(room, viewer, ship.positions)
    return True


def attack_budget(room, pid, base):
    if not room.mystery_tech:
        return base
    amount = base + int(has(room, pid, 'accelerated_loading'))
    if state(room).get('overload_round', {}).get(pid) == room.round:
        amount *= 2
    credit = state(room).get('extra_attacks', {}).get(pid, {})
    from ..room.models import RoomPhase
    active = credit.get('count', 0) if credit.get('round') == room.round and room.current_phase == RoomPhase.BATTLE else 0
    return amount + active + credit.get('pending', 0)


def activate_attack_credits(room, pid):
    """每个新战斗阶段只兑现一次待用攻击，不复用上个阶段已兑现的额度。"""
    if not room.mystery_tech:
        return
    credit = state(room).setdefault('extra_attacks', {}).setdefault(pid, {})
    credit.update(round=room.round, count=credit.get('pending', 0), pending=0)


def prepare_draw_count(room, pid, base):
    if not room.mystery_tech:
        return base
    other = room.opponent_of(pid)
    denied = state(room).get('active', {}).get(other, []).count('exclusion_zone')
    return max(0, base + int(has(room, pid, 'efficient_dispatch')) - denied)


def chain_draw_count(room, pid, layers, participants):
    return max(0, layers - 1) if pid in participants and has(room, pid, 'chain_amplifier') else 0


def magic_blocked(room, pid):
    span = state(room).get('silence', {}).get(pid)
    return bool(room.mystery_tech and span and span[0] <= room.round <= span[1])


def on_sink(room, attacker, defender):
    if attacker == defender or not has(room, attacker, 'overload_reaction'):
        return 0
    from ..battle import grant_extra_attacks
    from ..room.models import RoomPhase
    credit = state(room).setdefault('extra_attacks', {}).setdefault(attacker, {})
    if room.current_phase == RoomPhase.BATTLE and grant_extra_attacks(room, attacker, 1):
        if credit.get('round') != room.round:
            credit.update(round=room.round, count=0)
        credit['count'] = credit.get('count', 0) + 1
    else:
        credit['pending'] = credit.get('pending', 0) + 1
    return 1


def apply(room, pid, tech_id, rng):
    result = {'draw': 0}
    s = state(room)
    technology = BY_ID[tech_id]
    if technology.timing == 'persistent':
        active = s.setdefault('active', {}).setdefault(pid, [])
        if tech_id not in active:
            active.append(tech_id)
        if tech_id == 'steady_defense':
            for ship in alive_ships(room.players[pid]):
                protect_new_ship(room, pid, ship)
    elif tech_id == 'extra_supply':
        result['draw'] = 2
    elif tech_id == 'tidal_rewrite':
        result['discarded'] = list(room.players[pid].magic_hand)
        room.magic_discard.extend(result['discarded'])
        room.players[pid].magic_hand = []
        result['draw'] = 4
    elif tech_id == 'firepower_overload':
        s.setdefault('overload_round', {})[pid] = room.round
    elif tech_id == 'silent_domain':
        s.setdefault('silence', {})[room.opponent_of(pid)] = [room.round + 1, room.round + 2]
    elif tech_id == 'global_scan':
        viewer = room.players[pid]
        choices = [ship for ship in alive_ships(room.players[room.opponent_of(pid)])
                   if not all(pos in viewer.revealed_positions for pos in ship.positions)]
        if choices:
            reveal(room, pid, rng.choice(choices).positions)
    return result


def _wrecks(player):
    seen = set()
    wrecks = []
    permanent = {id(ship) for ship in player.permanently_destroyed_ships}
    for ship in player.sunken_ships:
        if id(ship) not in seen | permanent and ship.positions:
            seen.add(id(ship))
            wrecks.append(ship)
    return wrecks


def legal_cells(room, owner):
    player = room.players[owner]
    occupied = {(pos.x, pos.y) for ship in alive_ships(player) for pos in ship.positions}
    shot = {(pos.x, pos.y) for pos in room.players[room.opponent_of(owner)].attacks}
    return [{'x': x, 'y': y} for x in range(BOARD_SIZE) for y in range(BOARD_SIZE)
            if (x, y) not in occupied | shot]


def target_request(room, pid, tech_id, *, now, remaining=None, request_id=None):
    player = room.players[pid]
    other = room.opponent_of(pid)
    kind = 'revive' if tech_id in ('emergency_repair', 'battlefield_recall') else tech_id
    wrecks = _wrecks(player) if kind == 'revive' else []
    indices = list(range(len(wrecks)))
    cells = legal_cells(room, pid) if kind in ('revive', 'fleet_rebirth') else []
    if tech_id == 'spacetime_fold':
        target = room.players[other]
        indices = [i for i, ship in enumerate(target.ships) if is_ship_alive(target, ship)]
    if tech_id == 'sonar_pulse':
        cells = [{'x': x, 'y': y} for x in range(5) for y in range(5)]
    count = min(len(indices), 1 if tech_id == 'emergency_repair' else 2) if kind == 'revive' else 1
    if tech_id == 'fleet_rebirth':
        count = min(max(0, 6 - player.remaining_ships), len(cells))
    return {'request_id': request_id or uuid.uuid4().hex, 'player_id': pid, 'tech_id': tech_id,
            'kind': kind, 'deadline': int((now + TARGET_SECONDS) * 1000),
            'remaining': count if remaining is None else remaining,
            'legal_cells': cells, 'ship_indices': indices,
            # 时空折叠的可选活舰为该科技的授权瞄准信息，只给施放者。
            'ships': [{'ship_index': i, 'positions': [{'x': pos.x, 'y': pos.y} for pos in room.players[other].ships[i].positions]}
                      for i in indices] if tech_id == 'spacetime_fold' else [
                          {'ship_index': i, 'positions': [{'x': pos.x, 'y': pos.y} for pos in ship.positions]}
                          for i, ship in enumerate(wrecks)]}


def actionable(request):
    if request['remaining'] <= 0:
        return False
    if request['kind'] in ('revive', 'spacetime_fold') and not request['ship_indices']:
        return False
    if request['kind'] != 'spacetime_fold' and not request['legal_cells']:
        return False
    return True


def answer(room, request, data):
    pid = request['player_id']; kind = request['kind']
    player = room.players[pid]
    other = room.opponent_of(pid)
    if kind in ('revive', 'spacetime_fold'):
        index = data.get('ship_index')
        if type(index) is not int or index not in request['ship_indices']:
            return '请选择合法的战舰'
    if kind == 'spacetime_fold':
        from ..battle import apply_ship_sunk
        target = room.players[other]
        ship = target.ships[index]
        if not is_ship_alive(target, ship):
            return '目标战舰已不存活'
        ship.hits = list(ship.positions)
        apply_ship_sunk(room, other, ship)
        request['sunk_ship'] = ship
        return None
    x, y = data.get('x'), data.get('y')
    if type(x) is not int or type(y) is not int:
        return '请选择合法的格子'
    if kind == 'sonar_pulse':
        if not (0 <= x < 5 and 0 <= y < 5):
            return '请选择棋盘内的2×2区域左上角'
        reveal(room, pid, [Position(x+dx, y+dy) for dx in range(2) for dy in range(2)])
        return None
    allowed = {(p['x'], p['y']) for p in legal_cells(room, pid)}
    if (x, y) not in allowed:
        return '必须放在对方没打过且没有活舰的格子'
    wrecks = _wrecks(player)
    if kind == 'revive' and not 0 <= index < len(wrecks):
        return '请选择仍可复活的沉船'
    ship = wrecks[index] if kind == 'revive' else PlayerShip(positions=[Position(x,y)])
    if kind == 'revive':
        origin = ship.positions[0]
        positions = [Position(x+pos.x-origin.x, y+pos.y-origin.y) for pos in ship.positions]
        if not {(p.x,p.y) for p in positions} <= allowed:
            return '整艘战舰必须放在合法格子'
        ship.positions = positions
        player.sunken_ships = [dead for dead in player.sunken_ships if dead is not ship]
        if not any(existing is ship for existing in player.ships):
            player.ships.append(ship)
    else:
        if player.remaining_ships >= 6:
            return '舰队已补到6艘'
        player.ships.append(ship)
    ship.hits = []; ship.frozen = None; ship.invincible = False; ship.shield = False
    player.remaining_ships += 1
    protect_new_ship(room,pid,ship)
    return None
