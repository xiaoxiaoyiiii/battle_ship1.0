"""每日残局的私有引擎快照、日期与热更目录；绝不用于玩家/观众投影。"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .magic.cards import MagicCard, CARD_BY_NAME
from .room.models import Room, Player, PlayerShip, Position, EffectFlags, RoomState, RoomPhase
from .tasks import periods
from .effects import Lease, create_lease, flag_lease_key, project_effect_flags

SNAPSHOT_VERSION = 1
REWARD_TIDE = 30
REWARD_XP = 40
TYPES = {t.__name__: t for t in (Player, PlayerShip, Position, EffectFlags, MagicCard)}
# 连接、日志、计时器、录制器和数据库结算身份由新房间建立，不能带到挑战房。
ROOM_RUNTIME = frozenset('id created_at players name public ranked matchmade is_ai_room ai_difficulty ai_difficulty_by_player match_started_at turn_started_at turn_timer_attacker replay _viewing_recording _viewing_public_frame _viewing_commit_hook viewing_sequence game_logs disconnected disconnect_seq reconnect_tokens match_id task_card_uses settled settlement_result quick_chat_recent quick_chat_last chat_seq chat_history chat_delivered chat_recent chat_last spectators spectate_chat_recent spectate_chat_last effects chain_animation_clients chain_animation_id chain_animation_players chain_animation_deadline chain_display_token chain_display_deadline dice_animation_deadline daily_challenge daily_candidate_snapshots'.split())
PLAYER_RUNTIME = frozenset(('name', 'user_id', 'socket_id', 'registered'))


def daily_window(now: float | None = None) -> dict:
    return periods(now)['daily']


def _encode(value: Any, seats: dict[str, str]) -> Any:
    if isinstance(value, Enum):
        return {'enum': type(value).__name__, 'value': value.value}
    if is_dataclass(value):
        if type(value).__name__ not in TYPES:
            raise ValueError('快照含未支持的引擎对象')
        return {'type': type(value).__name__, 'fields': {
            f.name: _encode(getattr(value, f.name), seats) for f in fields(value)
            if not (isinstance(value, Player) and f.name in PLAYER_RUNTIME)}}
    if isinstance(value, dict):
        return {'map': [[_encode(k, seats), _encode(v, seats)] for k, v in value.items()]}
    if isinstance(value, (list, tuple, set)):
        return {type(value).__name__: [_encode(v, seats) for v in value]}
    if isinstance(value, str):
        return seats.get(value, value)
    if value is None or type(value) in (bool, int, float):
        return value
    raise ValueError('快照含不可序列化的运行态')


def _decode(value: Any, seats: dict[str, str]) -> Any:
    if isinstance(value, str):
        return seats.get(value, value)
    if not isinstance(value, dict):
        return value
    if 'enum' in value:
        return {'RoomState': RoomState, 'RoomPhase': RoomPhase}[value['enum']](value['value'])
    if 'type' in value:
        cls = TYPES[value['type']]
        attrs = {k: _decode(v, seats) for k, v in value['fields'].items()}
        if cls is MagicCard:
            card = CARD_BY_NAME.get(attrs.get('name'))
            if card is None or attrs != card.to_payload():
                raise ValueError('快照卡表已过期')
            return card
        return cls(**attrs)
    if 'map' in value:
        return {_decode(k, seats): _decode(v, seats) for k, v in value['map']}
    for name, constructor in (('list', list), ('tuple', tuple), ('set', set)):
        if name in value:
            return constructor(_decode(v, seats) for v in value[name])
    raise ValueError('快照编码无效')


def snapshot_rejection(room: Room, human: str) -> str | None:
    from .magic.interaction import pending_action_reason
    if not room.is_ai_room or room.ai_difficulty != 'master' or room.daily_challenge:
        return '非普通大师AI局'
    if room.mutation_ids or room.ban_enabled or room.banned_names:
        return '含突变或Ban'
    if room.state != RoomState.ATTACKING or room.current_attacker != human or len(room.players) != 2:
        return '非玩家行动点'
    if any(p.remaining_ships < 1 or p.needs_reset for p in room.players.values()):
        return '零舰或重摆中间态'
    if pending_action_reason(room, human):
        return '魔法选择尚未完成'
    if abs(room.players[human].remaining_ships - next(p.remaining_ships for k, p in room.players.items() if k != human)) > 2:
        return '船差过大'
    if (room.chain or room.chain_resolving or room.chain_waiting or room.priority_pending
            or room.priority_continue or room.magic_temps or room.pending_ship_picks
            or room.pending_dice_discard or room.pending_wuyou_dreams
            or room.effects.subscriptions or room.effects.queue or room.effects.draining):
        return '交互或效果总线尚未稳定'
    if any(not lease.key.startswith('flag:') for lease in room.effects.leases.values()):
        return '未支持的效果租约'
    if room.chain_animation_deadline > time.time() or room.dice_animation_deadline > time.time():
        return '演出进行中'
    return None


def capture_snapshot(room: Room, human: str) -> dict | None:
    if snapshot_rejection(room, human):
        return None
    other = next(pid for pid in room.players if pid != human)
    seats = {human: '@human', other: '@ai'}
    state = {f.name: getattr(room, f.name) for f in fields(Room) if f.name not in ROOM_RUNTIME}
    try:
        leases = [{f.name: getattr(lease, f.name) for f in fields(Lease) if f.name != 'key'}
                  for lease in room.effects.leases.values()]
        return {'version': SNAPSHOT_VERSION, 'room': _encode(state, seats), 'leases': _encode(leases, seats),
                'players': [_encode(room.players[pid], seats) for pid in (human, other)]}
    except ValueError:
        return None


def snapshot_hash(snapshot: dict) -> str:
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def restore_snapshot(snapshot: dict, *, room_id: str, user_id: str, name: str, sid: str) -> Room:
    """只接收运营私有文件，调用者不能从网络传入快照或牌堆。"""
    try:
        if snapshot['version'] != SNAPSHOT_VERSION:
            raise ValueError('快照版本不支持')
        seats = {'@human': user_id, '@ai': f'ai-{room_id}'}
        values = _decode(snapshot['room'], seats)
        required = {f.name for f in fields(Room)} - ROOM_RUNTIME
        if set(values) != required:
            raise ValueError('快照引擎字段不完整或已过期')
        players = [_decode(p, seats) for p in snapshot['players']]
        if len(players) != 2 or any(not isinstance(p, Player) for p in players):
            raise ValueError('快照座位不完整')
        room = Room(room_id, **values)
        players[0].name, players[0].user_id, players[0].socket_id = name, user_id, sid
        players[0].registered = True
        players[1].name, players[1].socket_id = '大师 AI', seats['@ai']
        room.players = dict(zip((user_id, seats['@ai']), players))
        for lease in _decode(snapshot['leases'], seats):
            flags = lease['flags']
            if len(flags) != 1:
                raise ValueError('标记租约无效')
            key = flag_lease_key(next(iter(flags)), lease['owner'])
            lease['uses'] = lease.pop('uses_left')
            create_lease(room, key, **lease)
        if room.effects.leases:
            project_effect_flags(room)
        room.is_ai_room, room.ai_difficulty, room.public = True, 'master', False
        if snapshot_rejection(room, user_id):
            raise ValueError('快照不是无突变无Ban的稳定残局')
        if not room.magic_deck_initialized:
            raise ValueError('快照未固定牌堆')
        room.match_started_at = room.turn_started_at = time.time()
        room.turn_timer_attacker = user_id
        return room
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError('快照不完整') from error


def record_action_point(room: Room) -> None:
    """保留最后5个可还原的真人行动点，独立于公开回放且有界。"""
    human = room.current_attacker
    player = room.players.get(human)
    if not player or not player.registered:
        return
    snapshot = capture_snapshot(room, human)
    if snapshot is None:
        return
    digest = snapshot_hash(snapshot)
    if not room.daily_candidate_snapshots or room.daily_candidate_snapshots[-1]['sha256'] != digest:
        room.daily_candidate_snapshots.append({'snapshot': snapshot, 'sha256': digest})
        room.daily_candidate_snapshots[:] = room.daily_candidate_snapshots[-5:]


class PuzzleCatalog:
    """每次读取完整清单，运营以原子替换文件热更；缺天不补造。"""
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def today(self, day: str) -> dict | None:
        try:
            return self._today(day)
        except (KeyError, TypeError, AttributeError, ZeroDivisionError) as error:
            raise ValueError('关卡目录字段不完整或格式无效') from error

    def _today(self, day: str) -> dict | None:
        if not self.path.exists():
            return None
        manifest = json.loads(self.path.read_text(encoding='utf-8'))
        entries = manifest['daily_puzzles']
        if not isinstance(entries, list) or len(entries) > 7:
            raise ValueError('每周目录最多7关')
        dates = [item['date'] for item in entries]
        if len(dates) != len(set(dates)):
            raise ValueError('目录生效日重复')
        chosen = next((item for item in entries if item['date'] == day), None)
        if chosen is None:
            return None
        path = (self.path.parent / chosen['snapshot']).resolve()
        if not path.is_relative_to(self.path.parent.resolve()):
            raise ValueError('快照路径越界')
        snapshot = json.loads(path.read_text(encoding='utf-8'))
        if snapshot_hash(snapshot) != chosen['sha256']:
            raise ValueError('快照摘要不匹配')
        # 启动前就验证，配置错误不消耗玩家次数。
        restore_snapshot(snapshot, room_id='check', user_id='check-user', name='校验', sid='check')
        quality = chosen['quality']
        if not quality.get('solved') or quality['random_trials'] < 50 or quality['random_wins'] / quality['random_trials'] > .1:
            raise ValueError('关卡未通过自动质量门槛')
        return {**chosen, 'state': snapshot}
