"""v2 只记录实际状态替换与演出；同一步允许多个顺序事件。"""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from .viewing import build_view_frame

CHECKPOINT_INTERVAL = 32
MAX_STEPS = 2000
MAX_BYTES = 512 * 1024


def _state(room):
    state = getattr(room, '_viewing_recording', None)
    if state is None:
        frame = build_view_frame(room, audience='replay')
        state = {'initial_state': frame, 'last': frame, 'events': [], 'checkpoints': [],
                 'seq': 0, 'state_count': 0, 'truncated': ''}
        room._viewing_recording = state
    return state


def record_state(room, *, step: int, cause: str) -> int:
    if getattr(room, 'settled', False):
        return (getattr(room, '_viewing_recording', None) or {}).get('seq', 0)
    state = _state(room)
    if step >= MAX_STEPS or len(state['events']) >= MAX_STEPS * 8:
        state['truncated'] = '此回放被截断（超过记录上限）'
        return state['seq']
    current = build_view_frame(room, audience='replay')
    # 规则文案在本局第一次捕获后冻结；动态额度等已放在 context。
    current['rules'] = state['initial_state']['rules']
    patch = {key: value for key, value in current.items() if value != state['last'].get(key)}
    if not patch:
        return state['seq']
    state['seq'] += 1
    state['events'].append({'seq': state['seq'], 'step': max(0, step), 'type': 'state',
                            'cause': cause, 'patch': patch})
    state['last'] = current
    state['state_count'] += 1
    if state['state_count'] % CHECKPOINT_INTERVAL == 0:
        state['checkpoints'].append({'seq': state['seq'], 'step': max(0, step), 'frame': deepcopy(current)})
    return state['seq']


def record_presentation(room, cue: dict[str, Any], *, step: int) -> int:
    if getattr(room, 'settled', False):
        return (getattr(room, '_viewing_recording', None) or {}).get('seq', 0)
    state = _state(room)
    if state['truncated'] or getattr(room, 'settled', False):
        return state['seq']
    if step >= MAX_STEPS or len(state['events']) >= MAX_STEPS * 8:
        state['truncated'] = '此回放被截断（超过记录上限）'
        return state['seq']
    state['seq'] += 1
    state['events'].append({'seq': state['seq'], 'step': max(0, step), 'type': 'presentation', 'cue': deepcopy(cue)})
    return state['seq']


def _size(payload):
    return len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def finalize_v2(room, *, metadata: dict | None = None, max_bytes: int = MAX_BYTES) -> dict | None:
    state = getattr(room, '_viewing_recording', None)
    if state is None:
        return None
    meta = metadata or {}
    payload = deepcopy({
        **{key: meta[key] for key in ('p1_name', 'p2_name', 'seats', 'started_at', 'steps', 'nodes') if key in meta},
        'version': 2, 'initial_state': state['initial_state'], 'events': state['events'],
        'checkpoints': state['checkpoints'], 'truncated': state['truncated'] or meta.get('truncated') or '',
    })
    while _size(payload) > max_bytes and payload['events']:
        payload['truncated'] = '此回放被截断（超过大小上限）'
        events = payload['events']
        cut_step = events[len(events) // 2]['step']
        kept = [event for event in events if event['step'] < cut_step]
        payload['events'] = kept
        last_seq = kept[-1]['seq'] if kept else 0
        last_step = kept[-1]['step'] if kept else 0
        payload['checkpoints'] = [c for c in payload['checkpoints'] if c['seq'] <= last_seq]
        payload['steps'] = [s for s in payload.get('steps', []) if s['i'] <= last_step]
        payload['nodes'] = [n for n in payload.get('nodes', []) if n['step'] <= last_step]
    # 初始局面本身超限时不保存损坏或空壳录像。
    return payload if _size(payload) <= max_bytes else None
