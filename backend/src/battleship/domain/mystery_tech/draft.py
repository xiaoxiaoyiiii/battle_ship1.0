"""三选一与身份投影；所有时间为同一权威绝对期限，不因刷新延长。"""
from copy import deepcopy
import time

from .catalog import BY_ID, TECHNOLOGIES
from ..room.models import RoomState, seat_label

SELECTION_SECONDS = 20
TARGET_SECONDS = 15


def enforce_mode(room):
    if not room.mystery_tech:
        return
    room.ranked = False
    room.ban_enabled = False
    room.ban_phase = 'off'
    room.banned_names.clear()
    room.ban_selections.clear()
    room.ban_confirmed.clear()
    room.mutation_ids = []
    room.mutation_entries = []
    room.mutation_confirmed.clear()
    room.mutation_token = ''


def probabilities(round_no):
    index = 1 + max(0, int(round_no) // 5)
    mythic = min(100, 2 + 3 * (index - 1))
    legendary = min(100 - mythic, 18 + 6 * (index - 1))
    return {'quality': max(0, 100 - legendary - mythic), 'legendary': legendary, 'mythic': mythic}


def pick(round_no, excluded, rng, *, tier=None):
    available = [t for t in TECHNOLOGIES if t.id not in excluded]
    if not available:
        return None
    same = [t for t in available if t.tier == tier]
    if same:
        return rng.choice(same).id
    rates = probabilities(round_no)
    # 先按原概率抽分档；抽光的档按剩余分档的概率重归一。
    tiers = [key for key in rates if any(t.tier == key for t in available)]
    weights = [rates[key] for key in tiers]
    chosen = rng.choices(tiers, weights=weights if sum(weights) else None, k=1)[0]
    return rng.choice([t for t in available if t.tier == chosen]).id


def state(room):
    return room.mystery_tech_state


def used(room):
    s = state(room)
    return {entry['tech_id'] for entry in s.get('history', [])} | {
        key for key in s.get('locked', {}).values() if key}


def due(room):
    return room.mystery_tech and (room.round == 1 or room.round % 5 == 0) and state(room).get('selection_round') != room.round


def begin(room, rng, *, now=None):
    if not due(room):
        return False
    enforce_mode(room)
    now = time.time() if now is None else now
    s = state(room)
    s.update(stage='selecting', selection_round=room.round, deadline=int((now + SELECTION_SECONDS) * 1000),
             offers={}, locked={}, target=None, queue=[], cursor=0)
    for pid in room.players:
        slots = []
        for _ in range(3):
            tech_id = pick(room.round, used(room) | {slot['tech_id'] for slot in slots}, rng)
            if tech_id:
                slots.append({'tech_id': tech_id, 'refresh_used': False})
        s['offers'][pid] = slots
    room.state = RoomState.MYSTERY_TECH_SELECTION
    if not room.match_started_at and all(player.ships for player in room.players.values()):
        room.match_started_at = now
    room.rps_choices = {}
    room.rps_processed = False
    for pid, slots in s['offers'].items():
        if not slots:
            s['locked'][pid] = None
    _publish_if_ready(room)
    return True


def _selection_error(room, pid, now):
    s = state(room)
    if not room.mystery_tech or s.get('stage') != 'selecting' or pid not in s.get('offers', {}):
        return '当前不在科技选择阶段'
    if pid in s['locked']:
        return '已锁定科技'
    if int(now * 1000) >= s['deadline']:
        return '科技选择已超时'
    return None


def refresh(room, pid, index, rng, *, now=None):
    now = time.time() if now is None else now
    if error := _selection_error(room, pid, now):
        return error
    slots = state(room)['offers'][pid]
    if type(index) is not int or not 0 <= index < len(slots):
        return '无效的科技槽位'
    slot = slots[index]
    if slot['refresh_used']:
        return '这张科技已经刷新过'
    replacement = pick(room.round, used(room) | {x['tech_id'] for x in slots}, rng)
    if replacement is None:
        return '科技池已抽光，无法刷新'
    slots[index] = {'tech_id': replacement, 'refresh_used': True}
    return None


def _repair_options(room, pid, rng):
    slots = state(room)['offers'][pid]
    forbidden = used(room)
    for slot in list(slots):
        if slot['tech_id'] not in forbidden:
            continue
        replacement = pick(room.round, forbidden | {x['tech_id'] for x in slots}, rng,
                           tier=BY_ID[slot['tech_id']].tier)
        if replacement:
            slot['tech_id'] = replacement
        else:
            slots.remove(slot)


def _publish_if_ready(room):
    s = state(room)
    if len(s['locked']) != len(room.players):
        return
    history = s.setdefault('history', [])
    for pid in room.players:
        if tech_id := s['locked'][pid]:
            history.append({'player_id': pid, 'tech_id': tech_id, 'round': room.round})
    s['stage'] = 'locked'
    room.state = RoomState.ROCK_PAPER_SCISSORS


def lock(room, pid, tech_id, rng, *, now=None):
    now = time.time() if now is None else now
    if error := _selection_error(room, pid, now):
        return error
    s = state(room)
    if not isinstance(tech_id, str) or tech_id not in {slot['tech_id'] for slot in s['offers'][pid]}:
        return '请选择当前出示的科技'
    if tech_id in used(room):
        _repair_options(room, pid, rng)
        return '该科技已被选走，已补换可选科技'
    s['locked'][pid] = tech_id
    _publish_if_ready(room)
    return None


def expire(room, rng, *, now=None):
    now = time.time() if now is None else now
    s = state(room)
    if s.get('stage') != 'selecting' or now * 1000 < s['deadline']:
        return False
    for pid in room.players:
        if pid in s['locked']:
            continue
        _repair_options(room, pid, rng)
        slots = s['offers'][pid]
        s['locked'][pid] = rng.choice(slots)['tech_id'] if slots else None
    _publish_if_ready(room)
    return True


def snapshot(room, viewer=None, *, now=None):
    if not room.mystery_tech:
        return None
    now = time.time() if now is None else now
    s = state(room)
    selected = [{**entry, 'seat': seat_label(room, entry['player_id']),
                 'technology': BY_ID[entry['tech_id']].payload()}
                for entry in s.get('history', [])]
    out = {'enabled': True, 'stage': s.get('stage', 'idle'), 'selection_round': s.get('selection_round'),
           'deadline': s.get('deadline') if s.get('stage') == 'selecting' else None,
           'remaining_ms': max(0, s.get('deadline', 0) - int(now * 1000)) if s.get('stage') == 'selecting' else 0,
           'selected': selected, 'resolving_player': (s.get('target') or {}).get('player_id') or s.get('waiting_player'),
           'pending_extra_attacks': {seat_label(room, pid): credit.get('pending', 0)
                                     for pid, credit in s.get('extra_attacks', {}).items() if credit.get('pending', 0)},
           'locked_players': [seat_label(room, pid) for pid in s.get('locked', {})]}
    if viewer in room.players:
        out['options'] = [{**deepcopy(slot), 'technology': BY_ID[slot['tech_id']].payload()}
                          for slot in s.get('offers', {}).get(viewer, [])] if s.get('stage') == 'selecting' else []
        out['locked_tech_id'] = s.get('locked', {}).get(viewer)
        target = s.get('target')
        from .effects import TARGETED
        out['target'] = deepcopy(target) if target and target['player_id'] == viewer and target.get('tech_id') in TARGETED else None
    return out
