"""观看端的权威状态投影；只描述结果，不执行规则，不接触网络或数据库。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from . import mutations
from .room import Room, card_payload, is_ship_alive, seat_order
from .room.sync import _effect_badges
from .magic.rules import field_magic_name

VIEW_VERSION = 2
RULES_VERSION = 'weekly-mutation-v3'


def labels(room: Room) -> dict[str, str]:
    return {pid: f'p{i + 1}' for i, pid in enumerate(seat_order(room)[:2])}


def side_of(room: Room, identifier: Any) -> str | None:
    if identifier is None or identifier == '':
        return None
    for pid, side in labels(room).items():
        player = room.players[pid]
        if identifier in (pid, player.socket_id, player.user_id):
            return side
    return None


def point(value: Any) -> dict[str, int] | None:
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        x, y = value[:2]
    elif isinstance(value, dict):
        x, y = value.get('x'), value.get('y')
    else:
        x, y = getattr(value, 'x', None), getattr(value, 'y', None)
    if type(x) is int and type(y) is int and 0 <= x < 6 and 0 <= y < 6:
        return {'x': x, 'y': y}
    return None


def _points(values: Any) -> list[dict[str, int]]:
    return [p for value in (values or []) if (p := point(value)) is not None]


def _area(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    keys = ('x1', 'y1', 'x2', 'y2')
    if not all(type(value.get(key)) is int for key in keys):
        return None
    return {key: value[key] for key in keys}


def freeze_rules(room: Room) -> dict[str, Any]:
    ranked = bool(room.ranked)
    ids = [] if ranked else list(room.mutation_ids)
    return deepcopy({
        'version': RULES_VERSION,
        'mode': 'ranked' if ranked else 'ai' if room.is_ai_room else 'casual' if room.matchmade else 'custom',
        'ids': ids, 'entries': [] if ranked else room.mutation_entries,
        'week_id': room.mutation_week_id, 'starting_ship_cap': room.starting_ship_cap,
        'dice_rolls': {labels(room)[pid]: n for pid, n in room.mutation_dice_rolls.items() if pid in labels(room)},
        'banned_names': sorted(room.banned_names),
    })


def _shot(attack: Any, *, fact: bool = False) -> dict | None:
    p = point(attack)
    if p is None:
        return None
    p.update(hit=bool(attack.hit), sunk=bool(attack.ship_sunk),
             area=bool(attack.is_bomb or attack.is_sulfur or attack.is_splash))
    if fact:
        p['fog_miss'] = bool(attack.fog_miss)
    return p


def _board(room: Room, pid: str, *, full: bool) -> dict[str, Any]:
    player = room.players[pid]
    other_id = room.opponent_of(pid)
    other = room.players.get(other_id)
    incoming = other.attacks if other else []
    fleet = []
    if full:
        for ship in player.ships:
            hit_keys = {(hit.x, hit.y) for hit in ship.hits}
            for p in _points(ship.positions):
                fleet.append({**p, 'hit': (p['x'], p['y']) in hit_keys,
                              'sunk': not is_ship_alive(player, ship),
                              'shielded': bool(ship.shield), 'frozen': bool(ship.frozen),
                              'invincible': bool(ship.invincible), 'trap': bool(ship.trap)})
    # mutation_revealed 按观察者存对方位置；公开亮舰只取这一份，不混入私有侦察。
    reveals = _points(room.mutation_revealed.get(other_id, [])) if mutations.active(room, 'E3') else []
    if full and other:
        reveals = _points(mutations.visible_reveals(room, other_id))
    effects = room.game_effects or {}
    frozen = effects.get('frozen_area')
    holes = [_area(h) for h in (effects.get('shenwei_holes') or []) if side_of(room, h.get('player')) == labels(room)[pid]]
    return {
        'fleet': fleet,
        'marks': [row for a in mutations.visible_attacks(incoming) if (row := _shot(a)) is not None],
        'shots': [row for a in incoming if (row := _shot(a, fact=True)) is not None] if full else [],
        'reveals': reveals,
        'holes': [h for h in holes if h is not None],
        'frozen_area': _area(frozen) if isinstance(frozen, dict) and side_of(room, frozen.get('owner')) == labels(room)[pid] else None,
        'last_stand': _points(effects.get('last_stand_cells')) if side_of(room, effects.get('last_stand_owner')) == labels(room)[pid] else [],
    }


def build_view_frame(room: Room, *, audience: Literal['replay', 'spectator']) -> dict[str, Any]:
    if audience not in ('replay', 'spectator'):
        raise ValueError('未知观看范围')
    full = audience == 'replay'
    seats = labels(room)
    from .spectate.rules import public_chain
    return deepcopy({
        'version': VIEW_VERSION, 'audience': audience,
        'context': {
            'state': getattr(room.state, 'value', room.state),
            'phase': getattr(room.current_phase, 'value', room.current_phase),
            'round': room.round, 'current_side': side_of(room, room.current_attacker),
            'attacks_remaining': room.attacks_remaining, 'field_magic': field_magic_name(room),
            'winner': side_of(room, room.winner), 'reason': getattr(room, 'game_over_reason', None),
            'needs_reset': [side for pid, side in seats.items() if room.players[pid].needs_reset],
            'storm_active': bool(room.mutation_storm_active),
            'cast_counts': {side: mutations.round_casts(room, pid) for pid, side in seats.items()},
            'preparation_cast': {side: mutations.preparation_cast(room, pid) for pid, side in seats.items()},
            'extra_discard_required': {side: mutations.extra_discard_required(room, pid) for pid, side in seats.items()},
        },
        'rules': freeze_rules(room),
        'players': {side: {
            'name': player.name or side, 'remaining_ships': player.remaining_ships,
            'hand_count': len(player.magic_hand),
            'cards': [card_payload(card) for card in player.magic_hand] if full or mutations.active(room, 'E2') else None,
            'effects': _effect_badges(room, pid, player),
        } for pid, side in seats.items() for player in [room.players[pid]]},
        'boards': {side: _board(room, pid, full=full) for pid, side in seats.items()},
        'chain': public_chain(room),
    })


def public_cue(cue: dict[str, Any], room: Room) -> dict[str, Any] | None:
    """演出单独构造公开字段；私有落点和玩家 ACK 令牌不复制。"""
    if not isinstance(cue, dict):
        return None
    out = {key: deepcopy(cue[key]) for key in ('stage', 'order', 'first', 'negated_skip', 'negated_by', 'success', 'duration_ms') if key in cue}
    chain = cue.get('chain')
    if isinstance(chain, list):
        out['chain'] = [{'card': row.get('card'), 'seat': row.get('seat') if row.get('seat') in ('p1', 'p2') else side_of(room, row.get('player_id')), 'negated': bool(row.get('negated')),
                         **({'mastery_tier':row['mastery_tier']} if type(row.get('mastery_tier')) is int and 1<=row['mastery_tier']<=4 else {})} for row in chain if isinstance(row, dict)]
    effect = cue.get('effect')
    if isinstance(effect, dict):
        visible = {key: deepcopy(effect[key]) for key in ('effect_id', 'kind', 'card', 'duration_ms', 'impact') if key in effect}
        visible['caster'] = side_of(room, effect.get('caster'))
        target = effect.get('target')
        visible['target'] = target if target in ('field', 'both') else side_of(room, target)
        visible['cells'] = _points(effect.get('cells'))
        if point(effect.get('origin')) is not None:
            visible['origin'] = point(effect['origin'])
        out['effect'] = visible
    if cue.get('stage') in ('attack_windup', 'attack_tail') and point(cue.get('cell')) is not None:
        out['attacker'] = side_of(room, cue.get('attacker'))
        out['target'] = side_of(room, cue.get('target'))
        out['cell'] = point(cue['cell'])
        result = cue.get('result') or {}
        out['result'] = {key: bool(result.get(key)) for key in ('hit', 'sunk', 'shield_blocked', 'invincible')}
    return out or None


def replay_cue(cue: dict[str, Any], room: Room) -> dict[str, Any] | None:
    """赛后演出也统一座位方向；授权落点只进入完整录像。"""
    out = public_cue(cue, room)
    if out and isinstance(cue.get('effect'), dict) and 'effect' in out:
        private = cue['effect'].get('_private_cells') or cue['effect'].get('private_cells')
        if private:
            out['effect']['_private_cells'] = _points(private)
    return out
