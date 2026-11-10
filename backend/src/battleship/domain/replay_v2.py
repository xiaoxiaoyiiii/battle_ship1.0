"""v2 只记录实际状态替换与演出；同一步允许多个顺序事件。"""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from .replay import MAX_REPLAY_BYTES
from .viewing import build_view_frame

CHECKPOINT_INTERVAL = 32
MAX_STEPS = 2000
MAX_BYTES = MAX_REPLAY_BYTES
# 初始状态只有一帧，不应因为放宽整局容量而接受异常巨大的起始局面。
MAX_INITIAL_BYTES = 512 * 1024


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
    if _size(payload['initial_state']) > min(max_bytes, MAX_INITIAL_BYTES):
        return None
    if _size(payload) <= max_bytes:
        return payload

    def prefix(last_step: int) -> dict:
        kept = [event for event in payload['events'] if event['step'] <= last_step]
        last_seq = kept[-1]['seq'] if kept else 0
        return {
            **payload, 'truncated': '此回放被截断（超过大小上限）', 'events': kept,
            'checkpoints': [c for c in payload['checkpoints'] if c['seq'] <= last_seq],
            'steps': [s for s in payload.get('steps', []) if s['i'] <= last_step],
            'nodes': [n for n in payload.get('nodes', []) if n['step'] <= last_step],
        }

    # 按完整步骤二分寻找最长前缀，同一步的状态与演出不能拆开。
    # 无状态变化的日志步同样参与容量计算，不因最后一个事件较早而丢失。
    boundaries = sorted({e['step'] for e in payload['events']}
                        | {s['i'] for s in payload.get('steps', [])})
    best = prefix(-1)
    if _size(best) > max_bytes:
        return None
    lo, hi = 0, len(boundaries) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = prefix(boundaries[mid])
        if _size(candidate) <= max_bytes:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    return best
