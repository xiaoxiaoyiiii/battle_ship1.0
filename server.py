# eventlet 下必须先 monkey_patch，且必须早于任何可能使用 socket/ssl/threading
# 的标准库导入：否则后台任务里的 time.sleep 会阻塞整个单线程 hub
# （掉线宽限 30s / 连锁超时 10s 都会让服务器假死）。
try:
    import eventlet
    eventlet.monkey_patch()
except ImportError:
    pass

import functools
import json
import os
import random
import threading
import time
import uuid
import secrets
from typing import Any
import logging
from flask import render_template, request, session, jsonify
from flask_socketio import SocketIO, join_room, emit as semit

import db  # local database helpers for users and matches
from api import app
from file import read_json

# 调试事件开关：仅在显式设置环境变量 ENABLE_TEST_EVENTS=1 时启用。
# 默认关闭，避免公网玩家通过 test_* 事件作弊（直接判胜、白嫖卡牌、读取对方船位等）。
ENABLE_TEST_EVENTS = os.environ.get('ENABLE_TEST_EVENTS') == '1'


def _test_event(fn):
    """包装调试事件：未启用时静默拒绝，防止公网滥用。"""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not ENABLE_TEST_EVENTS:
            return {'status': 'error', 'message': '调试事件未启用'}
        return fn(*args, **kwargs)
    return wrapper


def _require_live_room(fn):
    """写操作门禁：对局已结束（state == 'game_over'）后一律拒绝。

    此前这些 handler 只校验「房间/玩家/身份」与阶段，不看 state，导致终局后：
    重新布船会把 game_over 倒回 rock_paper_scissors（对局复活，且该房间再也
    不会被 reaper 回收）；胜者还能继续投降，把已经记过账的胜负翻转。
    与 @_test_event 一样必须写在 @socketio.on(...) 的内侧。
    """
    @functools.wraps(fn)
    def wrapper(data=None, *args, **kwargs):
        room = None
        try:
            if isinstance(data, dict) and data.get('room_id'):
                room = room_manager.get_room(data['room_id'])
        except Exception:
            room = None
        if room is not None and getattr(room, 'state', None) == 'game_over':
            return {'status': 'error', 'message': '对局已结束'}
        result = fn(data, *args, **kwargs)
        # 成功做出一次操作的玩家 → 重置思考计时。
        # 超时兜底只针对「卡住完全不动」的人，不该惩罚在慢慢想、一直在操作的人。
        try:
            if (room is not None and isinstance(result, dict)
                    and result.get('status') == 'success'):
                pid = (data or {}).get('player_id')
                if pid and pid in room.players and room.current_attacker == pid:
                    room.turn_started_at = time.time()
        except Exception:
            pass
        return result
    return wrapper


def record_card_use(card, count=1):
    """记一次卡牌使用（卡牌图鉴里「使用次数」的来源）。

    只做统计，任何异常都吞掉：统计不该影响对局。场地魔法同样计数。
    """
    try:
        name = getattr(card, 'name', card)
        if name:
            db.record_card_use(name, count)
    except Exception:
        pass


def emit(event, data, to=None, room: str | None = None):
    json_data = json.dumps(data, default=lambda o: o.__dict__)
    try:
        return semit(event, json.loads(json_data), to=to, room=room)
    except RuntimeError:
        # 无请求上下文（如后台任务/定时器）时直接走 SocketIO 服务端发送
        return socketio.emit(event, json.loads(json_data), to=to, room=room)


class GameLog:
    def __init__(self, text: str, event_type: str = 'info', payload: dict | None = None):
        self.ts = int(time.time())
        self.type = event_type
        self.text = text
        self.detail = payload
    
    def to_dict(self):
        return {
            'ts': self.ts,
            'type': self.type,
            'text': self.text,
            'detail': self.detail
        }


def _log_name(room, player_id):
    """日志里统一用玩家名，取不到则退回 id。"""
    p = room.players.get(player_id)
    return (p.name or player_id) if p else player_id


def add_game_log(room, text: str, event_type: str = 'info', payload: dict | None = None):
    """Append a lightweight battle log entry and push it to clients."""
    if not hasattr(room, 'game_logs'):
        room.game_logs = []
    entry = GameLog(text, event_type, payload)
    room.game_logs.append(entry.to_dict())
    # 实时推送给房间内两个客户端（无 socket 上下文时 emit 内部已兜底）
    try:
        emit('game_log', entry.to_dict(), room=room.id)
    except Exception:
        pass


def log_magic(room, caster_id, card, extra=''):
    """统一记录魔法卡使用（连锁结算的唯一入口调用）。"""
    name = _log_name(room, caster_id)
    tail = f'，{extra}' if extra else ''
    add_game_log(room, f'第{room.round}回合 · {name} 使用了【{card.name}】{tail}',
                 'magic', {'caster': caster_id, 'card': card.name})


# 在线人数统计
online_users = set()
magic_cards: list["MagicCard"]
@app.route('/api/online_count')
def api_online_count():
    """获取当前在线人数"""
    return jsonify({'online_count': len(online_users)})

class Position:
    x: int
    y: int
    hit: bool = False
    ship_sunk: bool = False
    is_sulfur: bool = False
    is_bomb: bool = False
    is_splash: bool = False

    def __init__(self, x: int, y: int, hit=False, ship_sunk=False, is_sulfur=False, is_bomb=False, is_splash=False):
        self.x = x
        self.y = y
        self.ship_sunk = ship_sunk
        self.is_sulfur = is_sulfur
        self.round = None
        self.hit = hit
        self.is_bomb = is_bomb
        self.is_splash = is_splash

    def __eq__(self, other):
        if isinstance(other, dict):
            return self.x == other.get('x') and self.y == other.get('y')
        else:
            return self.x == other.x and self.y == other.y


class PlayerShip:
    invincible: bool
    positions: list[Position]
    hits: list[Position]
    shield: bool = False  # 是否有护盾

    def __init__(self, positions: list[Position], hits: list[Position],**kwargs):
        self.invincible = False
        # 确保positions是Position对象列表
        self.positions = []
        for pos in positions:
            if isinstance(pos, dict):
                self.positions.append(Position(**pos))
            else:
                self.positions.append(pos)
        # 确保hits是Position对象列表
        self.hits = []
        for hit in hits:
            if isinstance(hit, dict):
                self.hits.append(Position(**hit))
            else:
                self.hits.append(hit)


class MagicCard:
    name: str
    speed: int
    type: str
    description: str

    def __init__(self, name: str, speed: int = "", type: str = "", description: str = ""):
        self.name = name
        if speed != "" and type != "" and description != "":
            self.speed = speed
            self.type = type
            self.description = description
            return
        # 客户端可能只传 name；按名查卡。找不到时抛 ValueError（而非 IndexError），
        # 由调用方捕获并返回错误响应，避免恶意/残缺卡牌数据直接让 handler 崩溃。
        card = next((c for c in magic_cards if c.name == name), None)
        if card is None:
            raise ValueError(f"未知的魔法卡: {name!r}")
        self.speed = card.speed
        self.type = card.type
        self.description = card.description


class EffectFlags:
    treasure_hunter: bool = False
    prediction: bool = False
    subsidy: bool = False
    subsidy_bonus: int = 0  # 百亿补贴：自己每沉一艘船累计的额外攻击次数
    no_draw: bool = False
    forced_kill: int = 0  # 强制击杀次数
    vampire: bool = False  # 饮血效果
    last_stand: bool = False  # 绝处逢生效果
    double_attacks: bool = False
    battle_spirit: bool = False
    # 五险一金：出牌时只「挂上保险」，等本回合攻击次数第一次归零、
    # 且那时确实没让对方减船，才真正 +3（见 _maybe_trigger_wuxian_yijin）。
    # 不放进 permanent_flags，所以回合切换会被清掉 —— 没触发就作废，符合卡面「这一回合」。
    wuxian: bool = False


class Player:
    magic_hand: list[MagicCard]
    effect_flags: EffectFlags
    name: str
    ships: list[PlayerShip]
    attacks: list[Position]
    remaining_ships: int
    needs_reset: bool
    revealed_positions: list[Position]
    # 设置新的船数限制
    max_ships: Any
    sunken_ships: Any
    user_id: str
    sid: str  # 添加sid属性来存储socket会话ID

    def __init__(self, name: str, ships: list[PlayerShip], attacks: list[Position], remaining_ships: int, user_id: str = None, sid: str = None):
        self.magic_blocked = None
        self.damage_dealt_this_turn = 0
        self.magic_hand = []
        self.effect_flags = EffectFlags()
        self.name = name
        self.ships = ships
        self.sid = sid  # 初始化sid属性
        self.attacks = attacks
        self.remaining_ships = remaining_ships
        self.needs_reset = False
        self.revealed_positions = []
        self.max_ships = None
        self.user_id = user_id
        self.sunken_ships = []  # 被击沉的船，用于死者苏生/疗愈等效果


class GameRoom:
    id: str
    players: dict[str, Player]
    state: str
    rps_choices: dict[str, str]
    attack_order: list[str]
    current_attacker: str
    attacks_remaining: int
    round: int
    winner: str
    field_magic: str
    magic_history: list[dict[str, Any]]  # 无写入
    game_effects: dict[str, Any]
    current_phase: str
    magic_temp_data: dict[str, Any]
    magic_discard: list[MagicCard]
    magic_deck: list[MagicCard]
    chain: list[dict[str, Any]]
    chain_waiting: bool
    chain_timer: float
    chain_window: str | None
    chain_passes: int
    last_attack: Any
    def __init__(self, room_id):
        self.id = room_id
        self.created_at = time.time()  # 用于回收「建了但一直没人入座」的房间
        self.players = {}
        self.state = 'waiting'  # waiting, placing_ships, rock_paper_scissors, attacking, game_over
        self.rps_choices = {}
        self.attack_order = []
        self.current_attacker = ""
        self.attacks_remaining = 0
        self.round = 1
        self.winner = ""
        # 魔法卡相关状态
        self.field_magic = None  # 场地区域（存卡牌实例，空=None）
        self.magic_history = []  # 魔法卡使用历史
        self.game_effects = {}  # 游戏效果跟踪
        self.current_phase = 'preparation'  # 当前阶段
        self.magic_temp_data = {}  # 魔法卡临时数据
        self.field_magic_owner = None  # 当前场地魔法的施放者（用于归属判断）
        self.magic_discard = []  # 全局弃牌堆（所有玩家使用过的魔法卡）
        self.magic_deck = []  # 全局共享魔法卡堆
        # 连锁相关状态
        self.chain = []  # 连锁栈
        self.chain_waiting = False  # 是否有待响应的连锁窗口
        self.chain_timer = -1  # 连锁回应计时器（代际令牌）
        self.chain_window = None  # 当前响应窗口归属的玩家
        self.chain_passes = 0  # 连续放弃次数（达 2 即结算）
        self.last_attack = None  # 记录最后一次攻击的信息
        self.game_logs: list[dict[str, Any]] = []
        self.rps_processed = False  # 记录猜拳结果是否已经处理过
        self.skip_opponent_turn = None  # 用于 Freezing!/神之宣告跳过对方回合
        self.skip_next_turn = None  # 用于跳过下一个玩家回合
        # 掉线/重连（2026-09-07 新增）
        self.disconnected = {}        # player_id -> {'deadline': float, 'token': int}（宽限期内）
        self.disconnect_seq = 0       # 掉线计时器代际令牌
        self.reconnect_tokens = {}    # player_id -> 一次性重连 token
        self.game_over_reason = None  # None | 'opponent_disconnected'

    def init_player_magic(self, player_id: str, magic_cards):
        """初始化玩家魔法卡相关状态"""
        # 初始化玩家的魔法卡状态
        self.players[player_id].magic_hand = []  # 初始手牌为空

        # 仅在第一次调用时初始化全局共享魔法卡堆
        if not self.magic_deck:
            # 复制并洗牌创建全局共享卡堆
            self.magic_deck = magic_cards.copy()
            random.shuffle(self.magic_deck)

    def draw_card(self, player_id: str):
        """抽卡逻辑，返回抽到的卡牌，使用全局共享卡堆"""
        # 检查是否有禁止抽卡效果
        effect_flags = self.players[player_id].effect_flags
        if effect_flags.no_draw:
            return None

        # 牌堆为空，无法抽卡
        if not self.magic_deck:
            return None

        # 从全局共享牌堆顶部抽一张卡
        card = self.magic_deck.pop(0)

        # 检查手牌中是否已有相同卡牌（除了"失灵！"）
        if card.name != '失灵！' and any(c.name == card.name and c.speed == card.speed for c in
                                        self.players[player_id].magic_hand):
            # 避免重复卡牌，放入弃牌堆
            self.discard_card(player_id, card)
            return None

        # 将卡牌加入手牌
        self.players[player_id].magic_hand.append(card)
        # 通知客户端手牌更新
        player = self.players[player_id]
        emit('hand_updated', {
            'hand': player.magic_hand
        }, room=player.sid)

        return card  # 返回抽到的卡牌

    def discard_card(self, player_id: str, card: MagicCard):
        """将卡牌放入弃牌堆；若它仍在手牌中，一并移出手牌。

        注意：MagicCard 没有 __eq__，原先用 list.index(card) 在"牌堆抽出的同名牌"
        场景下必然抛 ValueError（把整条攻击/魔法结算打断）。这里改为按对象身份匹配，
        找不到就只进弃牌堆，不再抛异常。
        """
        hand = self.players[player_id].magic_hand
        removed = False
        for i, c in enumerate(hand):
            if c is card:
                hand.pop(i)
                removed = True
                break
        self.magic_discard.append(card)
        return removed
    
# 添加魔法卡牌数据定义（与客户端 magic_cards.js 保持一致）
magic_cards = list(map(lambda x: MagicCard(**x), read_json('./static/magic_card.json')))

# CORS：默认只放行本地开发地址；生产用环境变量 CORS_ORIGINS 指定域名（逗号分隔）。
_cors_origins = [
    o.strip()
    for o in os.environ.get(
        'CORS_ORIGINS',
        'http://localhost:5000,http://127.0.0.1:5000',
    ).split(',')
    if o.strip()
]
socketio = SocketIO(app, cors_allowed_origins=_cors_origins)

# 聊天消息最大长度
MAX_CHAT_MSG_LEN = 100

class RoomManager:
    def __init__(self):
        # 游戏房间数据结构
        self.rooms: dict[str, GameRoom] = {}
        # 匹配队列：单结构列表，避免"三列平行数组"在并发下错位。
        # 每项形如 {'sid': str, 'name': str, 'user_id': str | None}
        self.match_queue: list[dict] = []
        # 保护 rooms / match_queue 的读写（eventlet 下 threading 已被 monkey_patch）
        self._lock = threading.RLock()

    # 房间管理方法
    def create_room(self, room_id: str = None) -> str:
        """创建新房间，返回房间ID"""
        if not room_id:
            room_id = str(uuid.uuid4())[:6]
        with self._lock:
            self.rooms[room_id] = GameRoom(room_id)
        return room_id

    def create_ai_room(self, player_id: str, player_name: str, player_user_id=None,
                         difficulty: str = 'normal') -> str:
        """创建人机对战房间：预置AI玩家，真人随后 join_room 走正常双人开局流程"""
        room_id = str(uuid.uuid4())[:6]
        room = GameRoom(room_id)
        room.is_ai_room = True
        room.ai_difficulty = difficulty if difficulty in AI_DIFFICULTIES else 'normal'
        with self._lock:
            self.rooms[room_id] = room
        ai_id = 'ai-' + room_id
        room.players[ai_id] = Player(name='AI', ships=[], attacks=[], remaining_ships=0, user_id=None, sid=ai_id)
        room.init_player_magic(ai_id, magic_cards)
        return room_id

    def join_room(self, room_id: str, player_id: str, player_name: str, sid: str) -> bool:
        """玩家加入房间，返回是否成功"""
        with self._lock:
            if room_id not in self.rooms:
                return False

            room = self.rooms[room_id]
            if len(room.players) >= 2:
                return False

            room.players[player_id] = Player(**{
                'name': player_name,
                'ships': [],
                'attacks': [],
                'remaining_ships': 0,
                'user_id': player_id,
                'sid': sid
            })
        return True

    def get_room(self, room_id: str) -> GameRoom | None:
        """获取房间对象"""
        return self.rooms.get(room_id)

    def delete_room(self, room_id: str) -> bool:
        """删除房间，返回是否成功"""
        with self._lock:
            if room_id in self.rooms:
                del self.rooms[room_id]
                return True
        return False

    def get_all_rooms(self) -> dict[str, GameRoom]:
        """获取所有房间"""
        return self.rooms

    # 匹配功能方法
    def add_to_match_queue(self, player_id: str, player_name: str, user_id: str = None) -> bool:
        """添加玩家到匹配队列，返回是否成功"""
        with self._lock:
            if any(e['sid'] == player_id for e in self.match_queue):
                return False
            self.match_queue.append({'sid': player_id, 'name': player_name, 'user_id': user_id})
        return True

    def remove_from_match_queue(self, player_id: str) -> bool:
        """从匹配队列移除玩家，返回是否成功"""
        with self._lock:
            for i, entry in enumerate(self.match_queue):
                if entry['sid'] == player_id:
                    self.match_queue.pop(i)
                    return True
        return False

    def has_player_in_match_queue(self, player_id: str) -> bool:
        """检查玩家是否在匹配队列中"""
        return any(e['sid'] == player_id for e in self.match_queue)

    def get_match_queue_size(self) -> int:
        """获取匹配队列大小"""
        return len(self.match_queue)


# 创建RoomManager实例
room_manager = RoomManager()


def _identity_check(room, claimed_player_id, server_pid, sid):
    """纯身份校验（无副作用，便于单测）。房间 key 存在两种约定，两种都认：
    - 自定义房/人机房（走 join_room）：key = 登录用户的 session user_id（游客=入座 sid）
    - 匹配房：key = 入匹配队列时的 socket sid（无论是否登录，user_id 只存 Player.user_id）
    因此只要满足任一即可：
    1) 声称的 player_id == 会话 user_id（登录态，且容忍重连后 sid 变化）
    2) 该座位登记的连接 == 当前连接（key=sid 的各流程，以及登录用户同连接场景）"""
    if not room or claimed_player_id not in room.players:
        return False
    if server_pid and claimed_player_id == server_pid:
        return True
    return room.players[claimed_player_id].sid == sid


def _identity_ok(room, claimed_player_id):
    """从当前请求上下文取身份后校验，防止伪造他人 player_id 操作。
    无请求上下文（如单元测试直调 handler）时跳过连接校验，仅保留成员校验。"""
    try:
        server_pid = session.get('user_id')
    except RuntimeError:
        server_pid = None
    try:
        sid = request.sid
    except RuntimeError:
        sid = None
    if server_pid is None and sid is None:
        return room is not None and claimed_player_id in room.players
    return _identity_check(room, claimed_player_id, server_pid, sid)


def field_magic_name(room):
    """返回场地区域上的场地魔法卡名（字符串）；无场地时返回空字符串。"""
    if not room or not room.field_magic:
        return ""
    fm = room.field_magic
    return fm.name if hasattr(fm, 'name') else fm


def _clear_field_magic_effects(room):
    """场地被顶替/拆除时，清理它留下的房间级效果标记。

    否则「加百列之光」拆掉恶魔契约/教皇旨意后，其效果仍永久生效。
    """
    room.game_effects.pop('demon_contract', None)
    room.game_effects.pop('papal_edict', None)


def _place_field_magic(room, caster_id, card):
    """将场地魔法卡实例放入场地区域；若已有不同名的旧卡，将其（实例）移入弃牌堆。
    返回被顶掉的旧卡（可能为 None）。"""
    old = room.field_magic
    room.field_magic = card
    room.field_magic_owner = caster_id
    if old and getattr(old, 'name', None) != card.name:
        room.magic_discard.append(old)
        _clear_field_magic_effects(room)
    emit('field_magic_updated', {'player_id': caster_id, 'card': card}, room=room.id)
    return old




# 测试功能：添加所有魔法卡到手牌
@socketio.on('test_add_all_magic_cards')
@_test_event
def test_add_all_magic_cards(data):
    room_id = data['room_id']
    player_id = data['player_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 将所有魔法卡添加到玩家手牌
    room.players[player_id].magic_hand = magic_cards.copy()

    # 通知客户端手牌更新
    player = room.players[player_id]
    emit('hand_updated', {
        'hand': player.magic_hand
    }, room=player.sid)

    return {'status': 'success', 'message': f'已添加 {len(magic_cards)} 张魔法卡到手牌'}


@socketio.on('test_set_player_ships')
@_test_event
def test_set_player_ships(data):
    room_id = data['room_id']
    player_id = data['player_id']
    ship_count = data['ship_count']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    player = room.players[player_id]
    opponent_id = next(p for p in room.players if p != player_id)
    opponent = room.players[opponent_id]

    # 清除现有船只
    player.ships = []
    player.remaining_ships = 0

    # 添加新船只
    from random import sample
    all_positions = [(x, y) for x in range(6) for y in range(6)]
    used_positions = set()

    for ship_size in [3, 2, 2, 1, 1, 1][:ship_count]:
        # 随机生成船只位置（水平或垂直）
        placed = False
        while not placed:
            direction = sample(['horizontal', 'vertical'], 1)[0]
            if direction == 'horizontal':
                x = sample(range(6 - ship_size + 1), 1)[0]
                y = sample(range(6), 1)[0]
                positions = [(x + i, y) for i in range(ship_size)]
            else:
                x = sample(range(6), 1)[0]
                y = sample(range(6 - ship_size + 1), 1)[0]
                positions = [(x, y + i) for i in range(ship_size)]

            # 检查是否与现有船只重叠
            if not any(pos in used_positions for pos in positions):
                # 创建船只
                ship_positions = [Position(x=x, y=y) for x, y in positions]
                player.ships.append(PlayerShip(positions=ship_positions, hits=[]))
                player.remaining_ships += 1
                
                # 更新已用位置
                used_positions.update(positions)
                placed = True

    # 更新客户端
    _emit_ships_updated(room)

    return {'status': 'success', 'message': f'已设置玩家船只数量为 {ship_count}'}


@socketio.on('test_clear_all_effects')
@_test_event
def test_clear_all_effects(data):
    room_id = data['room_id']

    room = room_manager.get_room(room_id)
    if not room:
        return {'status': 'error', 'message': '无效的房间'}

    # 清除所有游戏效果
    room.game_effects = {}
    room.field_magic = None
    room.polar_reversal_applied = False
    room.last_attack = None
    room.magic_temp_data = {}

    # 清除所有玩家效果
    for player_id in room.players:
        player = room.players[player_id]
        # 重置效果标志
        if hasattr(player, 'effect_flags'):
            player.effect_flags = EffectFlags()
        # 清除船只效果
        for ship in player.ships:
            ship.invincible = False
            ship.shield = False
        # 清空沉船记录
        if hasattr(player, 'sunken_ships'):
            player.sunken_ships = []
        # 清除回合数据
        player.damage_dealt_this_turn = 0

    return {'status': 'success', 'message': '已清除所有魔法效果'}


@socketio.on('test_add_specific_magic_card')
@_test_event
def test_add_specific_magic_card(data):
    room_id = data['room_id']
    player_id = data['player_id']
    card_name = data['card_name']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 查找指定魔法卡
    card = next((c for c in magic_cards if c.name == card_name), None)
    if not card:
        return {'status': 'error', 'message': f'未找到名为 {card_name} 的魔法卡'}

    # 添加到玩家手牌
    room.players[player_id].magic_hand.append(card)

    # 通知客户端手牌更新
    player = room.players[player_id]
    emit('hand_updated', {
        'hand': player.magic_hand
    }, room=player.sid)

    return {'status': 'success', 'message': f'已添加魔法卡 {card_name} 到手牌'}


@socketio.on('test_get_game_state')
@_test_event
def test_get_game_state(data):
    room_id = data['room_id']

    room = room_manager.get_room(room_id)
    if not room:
        return {'status': 'error', 'message': '无效的房间'}

    # 构建游戏状态信息
    game_state = {
        'room_id': room_id,
        'state': room.state,
        'current_attacker': room.current_attacker,
        'attacks_remaining': room.attacks_remaining,
        'field_magic': room.field_magic.name if hasattr(room.field_magic, 'name') else room.field_magic,
        'game_effects': list(room.game_effects.keys()),
        'players': {}
    }

    # 添加玩家信息
    for player_id in room.players:
        player = room.players[player_id]
        game_state['players'][player_id] = {
            'remaining_ships': player.remaining_ships,
            'magic_hand_count': len(player.magic_hand),
            'effect_flags': vars(player.effect_flags) if hasattr(player, 'effect_flags') else {},
            'damage_dealt_this_turn': getattr(player, 'damage_dealt_this_turn', 0),
            'ships': [{
                'positions': [(p.x, p.y) for p in ship.positions],
                'hits': [(p['x'], p['y']) if isinstance(p, dict) else (p.x, p.y) for p in ship.hits],
                'invincible': ship.invincible,
                'shield': ship.shield
            } for ship in player.ships]
        }

    return {'status': 'success', 'game_state': game_state}


@socketio.on('test_reset_game')
@_test_event
def test_reset_game(data):
    room_id = data['room_id']

    room = room_manager.get_room(room_id)
    if not room:
        return {'status': 'error', 'message': '无效的房间'}

    # 重置游戏状态
    room.state = 'placing_ships'
    room.attack_order = []
    room.current_attacker = ""
    room.attacks_remaining = 0
    room.field_magic = None
    room.game_effects = {}
    room.polar_reversal_applied = False
    room.last_attack = None
    room.magic_temp_data = {}
    room.chain = []
    room.chain_waiting = False
    room.chain_window = None
    room.chain_passes = 0

    # 重置玩家状态
    for player_id in room.players:
        player = room.players[player_id]
        player.ships = []
        player.remaining_ships = 0
        player.attacks = []
        player.magic_hand = []
        player.damage_dealt_this_turn = 0
        
        if hasattr(player, 'effect_flags'):
            player.effect_flags = EffectFlags()
        
        if hasattr(player, 'opponent_attacks'):
            player.opponent_attacks = []
        
        player.revealed_positions = []
        player.needs_reset = True

    return {'status': 'success', 'message': '游戏状态已重置'}


@socketio.on('create_ai_room')
def handle_create_ai_room(data):
    """处理创建人机对战房间的请求"""
    player_id = request.sid
    player_name = data.get('player_name', '玩家')
    player_user_id = data.get('user_id', None)
    difficulty = data.get('difficulty') or 'normal'

    # 创建人机对战房间
    room_id = room_manager.create_ai_room(player_id, player_name, player_user_id, difficulty)
    
    # 让玩家加入房间
    join_room(room_id)
    
    # 返回房间信息
    return {
        'status': 'success',
        'room_id': room_id,
        'message': '人机对战房间创建成功'
    }


@socketio.on('test_set_opponent_ships')
@_test_event
def test_set_opponent_ships(data):
    room_id = data['room_id']
    player_id = data['player_id']
    ship_count = data['ship_count']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    opponent_id = next(p for p in room.players if p != player_id)
    opponent = room.players[opponent_id]
    player = room.players[player_id]

    # 清除现有船只
    opponent.ships = []
    opponent.remaining_ships = 0

    # 添加新船只
    from random import sample
    all_positions = [(x, y) for x in range(6) for y in range(6)]
    used_positions = set()

    for ship_size in [3, 2, 2, 1, 1, 1][:ship_count]:
        # 随机生成船只位置（水平或垂直）
        placed = False
        while not placed:
            direction = sample(['horizontal', 'vertical'], 1)[0]
            if direction == 'horizontal':
                x = sample(range(6 - ship_size + 1), 1)[0]
                y = sample(range(6), 1)[0]
                positions = [(x + i, y) for i in range(ship_size)]
            else:
                x = sample(range(6), 1)[0]
                y = sample(range(6 - ship_size + 1), 1)[0]
                positions = [(x, y + i) for i in range(ship_size)]

            # 检查是否与现有船只重叠
            if not any(pos in used_positions for pos in positions):
                # 创建船只
                ship_positions = [Position(x=x, y=y) for x, y in positions]
                opponent.ships.append(PlayerShip(positions=ship_positions, hits=[]))
                opponent.remaining_ships += 1
                
                # 更新已用位置
                used_positions.update(positions)
                placed = True

    # 更新客户端
    _emit_ships_updated(room)

    return {'status': 'success', 'message': f'已设置对方船只数量为 {ship_count}'}


@socketio.on('test_end_turn')
@_test_event
def test_end_turn(data):
    room_id = data['room_id']

    room = room_manager.get_room(room_id)
    if not room:
        return {'status': 'error', 'message': '无效的房间'}

    # 结束当前回合
    if room.current_phase == 'battle':
        # 进入结束阶段
        room.current_phase = 'end'
    elif room.current_phase == 'end':
        # 切换到下一回合
        current_index = room.attack_order.index(room.current_attacker)
        next_index = (current_index + 1) % len(room.attack_order)
        room.current_attacker = room.attack_order[next_index]
        room.current_phase = 'preparation'
        room.attacks_remaining = room.players[room.current_attacker].remaining_ships

    return {'status': 'success', 'message': '回合已结束'}


@socketio.on('test_win_game')
@_test_event
def test_win_game(data):
    room_id = data['room_id']
    player_id = data['player_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 直接设置玩家为胜利
    room.state = 'game_over'
    room.winner = player_id
    
    emit('game_over', {'winner': player_id}, room=room_id)
    return {'status': 'success', 'message': '游戏胜利已设置'}


@socketio.on('test_lose_game')
@_test_event
def test_lose_game(data):
    room_id = data['room_id']
    player_id = data['player_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 直接设置玩家为失败
    opponent_id = next(p for p in room.players if p != player_id)
    room.state = 'game_over'
    room.winner = opponent_id
    
    emit('game_over', {'winner': opponent_id}, room=room_id)
    return {'status': 'success', 'message': '游戏失败已设置'}


@socketio.on('test_get_magic_cards_list')
@_test_event
def test_get_magic_cards_list(data):
    # 返回所有可用的魔法卡列表
    cards_list = []
    for card in magic_cards:
        cards_list.append({
            'name': card.name,
            'speed': card.speed,
            'type': card.type,
            'description': card.description
        })
    
    return {'status': 'success', 'magic_cards': cards_list}


@socketio.on('test_auto_attack')
@_test_event
def test_auto_attack(data):
    room_id = data['room_id']
    player_id = data['player_id']
    attack_count = data.get('count', 1)

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    opponent_id = next(p for p in room.players if p != player_id)
    opponent = room.players[opponent_id]

    # 记录攻击结果
    attack_results = []

    for _ in range(attack_count):
        if room.attacks_remaining <= 0:
            break

        # 选择一个未攻击过的随机位置        
        all_positions = [(x, y) for x in range(6) for y in range(6)]
        attacked_positions = [(a.x, a.y) for a in room.players[player_id].attacks]
        available_positions = [pos for pos in all_positions if pos not in attacked_positions]

        if not available_positions:
            break

        target_x, target_y = random.choice(available_positions)

        # 执行攻击
        hit = False
        ship_sunk = False
        
        for i, ship in enumerate(opponent.ships):
            if Position(x=target_x, y=target_y) in ship.positions:
                hit = True
                
                if ship.shield:
                    ship.shield = False
                elif not ship.invincible:
                    ship.hits.append(Position(x=target_x, y=target_y))
                    
                    if len(ship.hits) == len(ship.positions):
                        ship_sunk = True
                        opponent.remaining_ships -= 1
                
                break

        # 记录攻击
        attack = type('Attack', (), {})
        attack.x = target_x
        attack.y = target_y
        attack.hit = hit
        attack.ship_sunk = ship_sunk
        
        room.players[player_id].attacks.append(attack)
        room.attacks_remaining -= 1

        # 收集攻击结果
        attack_results.append({
            'x': target_x,
            'y': target_y,
            'hit': hit,
            'ship_sunk': ship_sunk
        })

        # 检查游戏是否结束
        if opponent.remaining_ships <= 0:
            room.state = 'game_over'
            room.winner = player_id
            emit('game_over', {'winner': player_id}, room=room_id)
            break

    return {'status': 'success', 'message': f'已执行 {len(attack_results)} 次自动攻击', 'attack_results': attack_results}



@app.route('/lobby')
def lobby():
    # SPA entry point for lobby view
    return render_template('index.html', username=session.get('username'))

@socketio.on('create_room')
def handle_create_room(data):
    room_id = room_manager.create_room()
    # 优先使用登录后的 user_id，否则使用 sid（游客模式）
    player_id = session.get('user_id', request.sid)
    player_name = session.get('username', data.get('player_name', '匿名玩家'))
    # 明确指定socket_id加入Socket.IO房间
    join_room(room_id, request.sid)
    room = room_manager.get_room(room_id)
    if room:
        room.players[player_id] = Player(**{
            'name': player_name,
            'ships': [],
            'attacks': [],
            'remaining_ships': 0,  # 初始化剩余战舰数量
            'user_id': player_id,
            'sid': request.sid  # 传递sid给Player构造函数
        })
    return {'status': 'success', 'room_id': room_id}

@socketio.on('join_room')
def handle_join_room(data):
    room_id = data['room_id']
    # 优先使用登录后的 user_id，否则使用 sid（游客模式）
    player_id = session.get('user_id', request.sid)
    player_name = session.get('username', data.get('player_name', '匿名玩家'))

    room = room_manager.get_room(room_id)
    if not room:
        emit('error', {'message': '房间不存在'}, room=request.sid)
        return {'status': 'error', 'message': '房间不存在'}

    if len(room.players) >= 2:
        emit('error', {'message': '房间已满'}, room=request.sid)
        return {'status': 'error', 'message': '房间已满'}

    # 添加玩家到房间（key 为 user_id 或 sid）
    room.players[player_id] = Player(**{
        'name': player_name,
        'ships': [],
        'attacks': [],
        'remaining_ships': 0,  # 初始化剩余战舰数量
        'user_id': player_id,
        'sid': request.sid  # 传递sid给Player构造函数
    })

    # 添加玩家到Socket.IO房间
    join_room(room_id, request.sid)
    # 检查是否所有玩家都已加入
    if len(room.players) == 2:
        # 所有玩家都已加入，开始游戏
        room.state = 'placing_ships'

        # 初始化魔法卡牌系统
        room.init_player_magic(list(room.players.keys())[0], magic_cards)
        room.init_player_magic(list(room.players.keys())[1], magic_cards)

        # 为每个玩家添加对方的名字
        # 准备发送给两个玩家的游戏状态
        game_state_data = {
            'state': 'placing_ships',
            'room_id': room_id
        }

        # 为每个玩家添加对方的名字
        for player_id in room.players:
            opponent_id = next(p for p in room.players if p != player_id)
            player = room.players[player_id]
            emit('game_state', {
                **game_state_data,
                'player_id': player_id,
                'player_name': player.name,
                'opponent_name': room.players[opponent_id].name
            }, to=player.sid)

    # 返回响应给客户端，包含player_id
    return {'status': 'success', 'player_id': player_id}


# 局内聊天事件
@socketio.on('connect')
def handle_connect():
    """处理客户端连接事件"""
    sid = request.sid
    online_users.add(sid)
    print(f"Client connected: {sid}, online users: {len(online_users)}")

    # 启动已结束房间的后台回收任务与回合计时看门狗（均幂等）
    try:
        _ensure_reaper()
    except Exception:
        pass
    try:
        _ensure_turn_timer()
    except Exception:
        pass

    # 掉线重连兜底：若该登录用户仍在一局未结束的对局中（且已不在宽限外），
    # 主动推送 resume_game，让客户端自动重连恢复（覆盖关标签页/浏览器后重开场景）。
    try:
        server_pid = session.get('user_id')
    except Exception:
        server_pid = None
    if server_pid:
        candidates = []
        for room_id, room in room_manager.get_all_rooms().items():
            if room.state == 'game_over':
                continue
            for pid, p in room.players.items():
                # 座位属于该登录用户（自定义/人机房 key=user_id，匹配房 key=sid 但 user_id 一致），
                # 且该座位登记的连接不是当前新连接（即刚掉线/换连接重开）
                if p.user_id == server_pid and p.sid != sid:
                    candidates.append((room_id, pid))
        if len(candidates) == 1:
            room_id, pid = candidates[0]
            emit('resume_game', {
                'room_id': room_id,
                'player_id': pid,
                'message': '检测到未结束的对局，正在恢复…',
            }, to=sid)
            # 预发放重连 token
            room = room_manager.get_room(room_id)
            if room:
                tok = secrets.token_hex(16)
                room.reconnect_tokens[pid] = tok
                emit('reconnect_token', {'token': tok}, to=sid)


@socketio.on('disconnect')
def handle_disconnect():
    """处理客户端断开连接事件"""
    sid = request.sid
    if sid in online_users:
        online_users.remove(sid)
    print(f"Client disconnected: {sid}, online users: {len(online_users)}")
    
    # 清理相关数据：从匹配队列移除该连接
    if room_manager.has_player_in_match_queue(sid):
        room_manager.remove_from_match_queue(sid)

    # 掉线宽限：若该连接正坐在某未结束房间的座位上，启动 30s 重连窗口。
    # 注意：不能在 disconnect 处理器内同步 emit（eventlet 下会卡住 hub），
    # 因此把通知+计时整体放入后台任务（先让 disconnect 收尾完成）。
    for room_id, room in room_manager.get_all_rooms().items():
        for pid, p in list(room.players.items()):
            if p.sid == sid:
                socketio.start_background_task(_start_disconnect_grace, room_id, player_id=pid)
                return


@socketio.on('chat_message')
def handle_chat_message(data):
    player_id = session.get('user_id', request.sid)
    username = session.get('username', f'玩家{str(player_id)[:6]}')
    msg = (data.get('message') or '').strip()
    if not msg:
        return
    msg = msg[:MAX_CHAT_MSG_LEN]
    # 查找玩家所在房间
    room_id = data.get('room_id')
    # 仅房间内广播
    room = room_manager.get_room(room_id)
    # 安全：必须确实坐在这个房间里，否则任意连接都能向别人的房间发言
    if room and not any(p.sid == request.sid for p in room.players.values()):
        return
    if room:
        for pid in room.players:
            is_me = (room.players[pid].name == username)
            emit('chat_message', {
                'username': username,
                'message': msg,
                'isMe': is_me
            }, to=room.players[pid].sid)
        # 标记自己和对手
    else:
        # fallback: 仅回发给自己
        emit('chat_message', {'username': username, 'message': msg, 'isMe': True}, room=request.sid)


@socketio.on('find_match')
def handle_find_match(data):
    """处理玩家匹配请求"""
    socket_sid = request.sid
    db_user_id = session.get('user_id', socket_sid)
    player_name = data.get('player_name', '匿名玩家')
    user_id = session.get('user_id')

    # 检查玩家是否已经在匹配队列中
    if room_manager.has_player_in_match_queue(socket_sid):
        return {'status': 'error', 'message': '你已经在匹配队列中'}

    # 将玩家加入队列
    room_manager.add_to_match_queue(socket_sid, player_name, user_id)
    emit('match_queued', {'status': 'success', 'message': '已加入匹配队列'})

    # 尝试匹配：队列操作全程持锁，事件在锁外发送，避免并发下队列错位。
    # 配对规则：跳过与队首同一登录账号的记录（同一账号多标签页），直到找到
    # 可配对的对手；找不到时把队首放回并等待新玩家，绝不能回队后重试（会死循环）。
    matched = []
    with room_manager._lock:
        while len(room_manager.match_queue) >= 2:
            p1 = room_manager.match_queue.pop(0)
            partner_idx = None
            for i, p in enumerate(room_manager.match_queue):
                if p1['user_id'] is None or p['user_id'] is None or p1['user_id'] != p['user_id']:
                    partner_idx = i
                    break
            if partner_idx is None:
                # 队列里全是同一账号的重复记录：放回队首，等待新玩家入队
                room_manager.match_queue.insert(0, p1)
                break
            p2 = room_manager.match_queue.pop(partner_idx)

            room_id = room_manager.create_room()
            room = room_manager.get_room(room_id)
            room.players[p1['sid']] = Player(**{
                'name': p1['name'],
                'ships': [],
                'attacks': [],
                'remaining_ships': 0,
                'user_id': p1['user_id'],
                'sid': p1['sid']
            })
            room.players[p2['sid']] = Player(**{
                'name': p2['name'],
                'ships': [],
                'attacks': [],
                'remaining_ships': 0,
                'user_id': p2['user_id'],
                'sid': p2['sid']
            })
            room.init_player_magic(p1['sid'], magic_cards)
            room.init_player_magic(p2['sid'], magic_cards)
            room.state = 'placing_ships'
            matched.append((room_id, p1, p2))

    for room_id, p1, p2 in matched:
        join_room(room_id, p1['sid'])
        join_room(room_id, p2['sid'])
        for me, opp in ((p1, p2), (p2, p1)):
            emit('game_state', {
                'state': 'placing_ships',
                'room_id': room_id,
                'player_id': me['sid'],
                'player_name': me['name'],
                'opponent_name': opp['name']
            }, to=me['sid'])

    return {'status': 'success', 'message': '开始寻找匹配'}


@socketio.on('cancel_match')
def handle_cancel_match(data):
    """处理玩家取消匹配请求：队列以 socket sid 为 key，按当前连接出队。"""
    sid = request.sid
    room_manager.remove_from_match_queue(sid)
    emit('match_canceled', {'status': 'success', 'message': '已取消匹配'}, to=sid)
    return {'status': 'success', 'message': '已取消匹配'}



@socketio.on('place_ships')
@_require_live_room
def handle_place_ships(data):
    room_id = data['room_id']
    player_id = data['player_id']
    ships = data['ships']
    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 服务端校验布船：数量匹配上限、坐标合法且不重叠，防止越界/重叠/刷船。
    if not isinstance(ships, list) or not ships:
        return {'status': 'error', 'message': '布船数据无效'}
    expected = int(getattr(room.players[player_id], 'max_ships', None) or 6)
    if len(ships) != expected:
        return {'status': 'error', 'message': f'需要放置 {expected} 艘战舰'}
    occupied = set()
    for s in ships:
        if not isinstance(s, dict):
            return {'status': 'error', 'message': '战舰数据格式错误'}
        positions = s.get('positions') or []
        if not isinstance(positions, list) or not positions:
            return {'status': 'error', 'message': '战舰缺少位置信息'}
        for pos in positions:
            if not isinstance(pos, dict):
                return {'status': 'error', 'message': '战舰坐标格式错误'}
            try:
                px, py = int(pos['x']), int(pos['y'])
            except (KeyError, TypeError, ValueError):
                return {'status': 'error', 'message': '战舰坐标非法'}
            if not (0 <= px <= 5 and 0 <= py <= 5):
                return {'status': 'error', 'message': '战舰坐标超出棋盘范围'}
            if (px, py) in occupied:
                return {'status': 'error', 'message': '战舰不能重叠'}
            occupied.add((px, py))

    room.players[player_id].ships = list(map(lambda x: PlayerShip(**x), ships))

    # AI房间：人类摆完后为AI自动摆船
    if getattr(room, 'is_ai_room', False):
        ai_id = _ai_player_id(room)
        if ai_id and player_id != ai_id and not room.players[ai_id].ships:
            _ai_place_ships(room, ai_id)

    # 新增：计算并设置剩余战舰数量（攻击次数）
    room.players[player_id].remaining_ships = len(ships)

    # 检查是否所有玩家都已放置战舰
    all_placed = all(len(p.ships) > 0 for p in room.players.values())
    if all_placed:
        # 灵气复苏：这是中途重新摆放，不重新猜拳。
        # 恢复到施法前的先后手与阶段，只把棋盘换成新船数。
        if getattr(room, 'lingqi_resurgence_applied', False):
            room.lingqi_resurgence_applied = False
            saved = getattr(room, 'lingqi_saved_state', None) or {}
            room.lingqi_saved_state = None

            room.attack_order = saved.get('attack_order') or list(room.players.keys())
            room.current_attacker = saved.get('current_attacker') or room.attack_order[0]
            room.round = saved.get('round', room.round)
            room.current_phase = saved.get('current_phase', 'preparation')
            room.state = 'attacking'

            # 攻击次数随船数变化：准备阶段还没开打，按新船数重算；
            # 战斗/结束阶段保留原本剩余次数，避免凭空多出攻击。
            if room.current_phase == 'preparation':
                _recalc_attacker_attacks(room)
            else:
                room.attacks_remaining = saved.get('attacks_remaining', room.attacks_remaining)

            emit('game_message', {
                'message': '双方已重新摆放战舰，继续当前回合',
                'type': 'info'
            }, room=room_id)
            emit('game_state', {
                'state': 'attacking',
                'current_attacker': room.current_attacker,
                'current_phase': room.current_phase,
                'attacks_remaining': room.attacks_remaining,
                'round': room.round,
            }, room=room_id)
            # 若当前攻击者是 AI，继续驱动其回合
            _maybe_run_ai_turn(room)
            return {'status': 'success'}

        room.state = 'rock_paper_scissors'
        # 重置猜拳选择和处理标记，确保新的猜拳阶段从空开始
        room.rps_choices = {}
        room.rps_processed = False

        emit('game_state', {'state': 'rock_paper_scissors'}, room=room_id)

    return {'status': 'success'}


@socketio.on('rps_choice')
@_require_live_room
def handle_rps_choice(data):
    room_id = data['room_id']
    player_id = data['player_id']
    choice = data['choice']  # 'rock', 'paper', 'scissors'

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 出拳值必须合法：此前任意字符串都会被写进 rps_choices，
    # determine_rps_winner 里 win_conditions[c1] 会直接 KeyError（结算方 handler
    # 抛异常、猜拳卡死、双方都拿不到 rps_result）；若非法值恰好属于 players[1]，
    # 又会走进 else 分支让「出非法拳的一方」直接获胜。
    if choice not in ('rock', 'paper', 'scissors'):
        return {'status': 'error', 'message': '无效的出拳'}

    # AI房间：AI自动出拳
    if getattr(room, 'is_ai_room', False):
        ai_id = _ai_player_id(room)
        if ai_id and ai_id not in room.rps_choices:
            room.rps_choices[ai_id] = random.choice(['rock', 'paper', 'scissors'])

    room.rps_choices[player_id] = choice
    
    # 检查是否所有玩家都已做出选择
    if len(room.rps_choices) == len(room.players) and not room.rps_processed:
        # 标记为已处理，防止重复执行
        room.rps_processed = True
        
        # 决定猜拳结果
        result = determine_rps_winner(room)
        emit('rps_result', result, room=room_id)

        # 平局：order 为空，不进攻击阶段，等双方重新出拳
        # （determine_rps_winner 已清空 rps_choices 并复位 rps_processed）
        if result.status == 'tie' or len(result.order) < 2:
            return {'status': 'success', 'message': '平局，重新猜拳'}

        # 设置攻击顺序
        room.attack_order = result.order
        winner = room.attack_order[0]  # 先手
        loser = room.attack_order[1]  # 后手
        room.current_attacker = winner

        # 初始化攻击次数 - 如果是败者食尘生效的回合，攻击次数为0
        if hasattr(room, 'polar_reversal_applied') and room.polar_reversal_applied:
            room.attacks_remaining = 0
            # 清除败者食尘标记
            room.polar_reversal_applied = False
        else:
            room.attacks_remaining = max(0, room.players[winner].remaining_ships - frozen_ship_count(room.players[winner]))
            _recalc_attacker_attacks(room)

        # 猜拳后抽卡逻辑：先手1张，后手2张
        # 先手抽1张
        winner_card = room.draw_card(winner)
        # 后手抽2张
        loser_card1 = room.draw_card(loser)
        loser_card2 = room.draw_card(loser)

        room.state = 'attacking'
        # 设置当前阶段为准备阶段
        room.current_phase = 'preparation'
        # AI先手时自动驱动其回合
        _maybe_run_ai_turn(room)
        emit('game_state', {
            'state': 'attacking',
            'current_attacker': winner,
            'current_phase': 'preparation',
            'attacks_remaining': room.attacks_remaining,
            'winner_card': winner_card,
            'loser_cards': [loser_card1, loser_card2],
            'round': room.round,
            # 攻击顺序：[先手, 后手]。前端需要它来判断「自己是否先手」
            # （Freezing！ 这类卡只在先手方可用）
            'attack_order': list(room.attack_order),
        }, room=room_id)

    return {'status': 'success'}


class RPSResult:
    def __init__(self, status: str, message: str, winner: str = None, loser: str = None, choices: dict = None, order: list = None):
        self.status = status
        self.message = message
        self.winner = winner
        self.loser = loser
        self.choices = choices or {}
        self.order = order or []
    
    def to_dict(self):
        return {
            'status': self.status,
            'message': self.message,
            'winner': self.winner,
            'loser': self.loser,
            'choices': self.choices,
            'order': self.order
        }


class ChainItem:
    def __init__(self, player_id: str, card: MagicCard, targets: list, timestamp: float):
        self.player_id = player_id
        self.card = card
        self.targets = targets
        self.timestamp = timestamp
        self.negated = False  # 被连锁中更上方的卡牌无效化

    def to_dict(self):
        return {
            'player_id': self.player_id,
            'card': self.card,
            'targets': self.targets,
            'timestamp': self.timestamp,
            'negated': self.negated
        }


class AttackResult:
    def __init__(self, attacker: str, x: int, y: int, hit: bool, ship_sunk: bool, remaining_attacks: int, attacker_remaining_ships: int, defender_remaining_ships: int):
        self.attacker = attacker
        self.x = x
        self.y = y
        self.hit = hit
        self.ship_sunk = ship_sunk
        self.remaining_attacks = remaining_attacks
        self.attacker_remaining_ships = attacker_remaining_ships
        self.defender_remaining_ships = defender_remaining_ships
    
    def to_dict(self):
        return {
            'attacker': self.attacker,
            'x': self.x,
            'y': self.y,
            'hit': self.hit,
            'ship_sunk': self.ship_sunk,
            'remaining_attacks': self.remaining_attacks,
            'attacker_remaining_ships': self.attacker_remaining_ships,
            'defender_remaining_ships': self.defender_remaining_ships
        }


class ChainResult:
    def __init__(self, card: MagicCard, caster: str, success: bool = True, message: str = ''):
        self.card = card
        self.caster = caster
        self.success = success
        self.message = message
    
    def __getitem__(self, key):
        return getattr(self, key)
    
    def __setitem__(self, key, value):
        setattr(self, key, value)
    
    def to_dict(self):
        return {
            'card': self.card,
            'caster': self.caster,
            'success': self.success,
            'message': self.message
        }


def determine_rps_winner(room: GameRoom):
    players = list(room.players.keys())
    p1, p2 = players[0], players[1]
    c1, c2 = room.rps_choices[p1], room.rps_choices[p2]

    # 处理平局情况
    if c1 == c2:
        room.rps_choices = {}
        room.rps_processed = False  # 重置处理标记，确保可以重新处理
        return RPSResult('tie', '平局，重新猜拳')

    # 兜底：非法出拳值不得让结算抛 KeyError（handler 已做枚举校验，
    # 但这里是纯函数，任何调用路径都不该因为脏数据炸掉整局）
    if c1 not in ('rock', 'paper', 'scissors') or c2 not in ('rock', 'paper', 'scissors'):
        room.rps_choices = {}
        room.rps_processed = False
        return RPSResult('tie', '出拳无效，重新猜拳')

    # 判断胜负
    win_conditions = {
        'rock': 'scissors',
        'paper': 'rock',
        'scissors': 'paper'
    }

    # 正确逻辑：判断c1是否克制c2
    if win_conditions[c1] == c2:
        winner, loser = p1, p2
    else:
        winner, loser = p2, p1

    return RPSResult(
        status='win',
        message=f'{winner} 获胜',
        winner=winner,
        loser=loser,
        choices={p1: c1, p2: c2},
        order=[winner, loser]  # 攻击顺序
    )


# ============ 明智埋葬：选择解析与结算（两条链路共用同一份实现） ============
def _bury_choice_target(room, target_data):
    """把客户端提交的选择解析成 (source, index, 期望卡名)；失败返回 (None, 错误信息)。

    候选卡由 apply_magic_effect 按「牌堆在前、对方手牌在后」的扁平顺序下发：
    - card_index 是候选总表里的扁平下标（前端 cards.forEach 的 index）；
    - source_index 是该卡在自己来源列表（牌堆 / 对方手牌）内的下标。
    两者都要能落到同一张牌上：优先用 source_index 精确定位，否则用扁平下标
    到候选表里换取真实的 (source, index)；没有候选表（旧数据/测试直调）时，
    card_index 就按来源列表内的下标理解。
    """
    source = target_data.get('source')
    if source is None:
        source = 'deck'
    if source not in ('deck', 'opponent_hand'):
        return None, '无效的选择'

    def _as_index(value):
        # 注意 bool 是 int 的子类，True/False 不能当下标用
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

    candidates = (room.magic_temp_data or {}).get('candidates') or []

    def _candidate_name(idx):
        for c in candidates:
            if c.get('source') == source and c.get('index') == idx:
                return c.get('name')
        return None

    expected = None
    index = _as_index(target_data.get('source_index'))
    if index is None:
        flat = _as_index(target_data.get('card_index'))
        if flat is not None and flat < len(candidates):
            candidate = candidates[flat]
            # 扁平下标只有与来源一致时才采用，否则退回「来源列表内下标」的约定
            if candidate.get('source') == source:
                index = _as_index(candidate.get('index'))
                expected = candidate.get('name')
        if index is None:
            index = flat
    else:
        expected = _candidate_name(index)

    if index is None:
        return None, '无效的选择'
    return (source, index, expected), None


def _apply_bury_choice(room, player_id, target_data):
    """结算明智埋葬：把选中的牌（牌堆或对方手牌）放进弃牌堆，施法者再摸一张。

    ⚠️ 必须从原位置真移除。只 append 到弃牌堆的话，同一张牌会同时留在
    牌堆/对方手牌里，对方还能再用一次（复制卡）。
    """
    resolved, err = _bury_choice_target(room, target_data)
    if resolved is None:
        return {'status': 'error', 'message': err}
    source, index, expected = resolved

    opponent = None
    if source == 'deck':
        pile = room.magic_deck if isinstance(room.magic_deck, list) else []
    else:
        opponent_id = _opponent_of(room, player_id)
        opponent = room.players.get(opponent_id) if opponent_id else None
        if opponent is None:
            return {'status': 'error', 'message': '无效的选择'}
        pile = opponent.magic_hand

    if not (0 <= index < len(pile)):
        return {'status': 'error', 'message': '无效的选择'}

    if expected and pile[index].name != expected:
        # 候选下发后位置可能被同一连锁里的其它卡改动（抽取/洗牌）：
        # 按下标埋会埋错牌，改按卡名找回原来那张。
        moved = next((i for i, c in enumerate(pile) if c.name == expected), None)
        if moved is None:
            return {'status': 'error', 'message': '选中的卡牌已不在原处'}
        index = moved

    buried = pile.pop(index)
    room.magic_discard.append(buried)

    # 无论有没有摸到牌，这次选择都已经用完：先清空待选择状态，避免重复结算
    room.magic_temp_data = {}

    # draw_card 内部会 emit hand_updated（摸到重名卡时那张会自动进弃牌堆）。
    # 先记下摸牌前的牌堆张数：摸牌后牌堆可能正好空掉，
    # 用它才能区分「本来就没牌可摸」和「摸到重名牌被丢弃」。
    deck_size_before = len(room.magic_deck) if isinstance(room.magic_deck, list) else 0
    drawn = room.draw_card(player_id)
    if opponent is not None:
        # 对方手牌少了一张，需要单独同步（draw_card 只通知施法者自己）
        emit('hand_updated', {'hand': opponent.magic_hand}, to=opponent.sid)

    # 摸牌可能被规则挡下（牌堆空 / 无中生有封锁 / 摸到重名牌自动进弃牌堆）。
    # 这些情况原先都是静默的，玩家只会看到「没有摸到牌」而不知为何 —— 如实说明。
    if drawn is not None:
        detail = f'埋葬了「{buried.name}」，并摸到了「{drawn.name}」'
    elif room.players[player_id].effect_flags.no_draw:
        detail = f'埋葬了「{buried.name}」，但「无中生有」生效中，本大回合无法摸牌'
    elif deck_size_before == 0:
        detail = f'埋葬了「{buried.name}」，但牌堆已空，没能摸到牌'
    else:
        detail = f'埋葬了「{buried.name}」，摸到的牌与手牌重复，已直接进弃牌堆'

    add_game_log(room, f'第{room.round}回合 · {_log_name(room, player_id)} 的【明智埋葬】{detail}',
                 'magic', {'caster': player_id, 'card': '明智埋葬', 'buried': buried.name})
    return {'status': 'success', 'message': detail}


# select_magic_target 允许客户端提交的字段白名单（其余一律丢弃）
_SELECTION_TARGET_KEYS = {
    'caster_choice', 'opponent_choice', 'card_index', 'ship_indices',
    'effect_choice', 'prediction', 'index', 'target_area', 'target_line',
    'source', 'source_index',
}


# 添加新的Socket事件处理
@socketio.on('select_magic_target')
@_require_live_room
def handle_magic_target(data):
    room_id = data['room_id']
    player_id = data['player_id']
    target_data = data['target_data']
    temp_data_id = data['temp_data_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 存储临时目标数据（仅接受"选择类"字段）
    # 安全：此前直接合并客户端任意 JSON，可注入 pending_placement 等
    # 服务端状态，从而无限增援战舰。这里白名单过滤，禁止覆盖服务端键。
    if not isinstance(target_data, dict):
        return {'status': 'error', 'message': '目标数据格式错误'}
    safe_target_data = {k: v for k, v in target_data.items()
                        if k in _SELECTION_TARGET_KEYS}
    room.magic_temp_data = {**room.magic_temp_data, **safe_target_data}

    # 需要选择的操作：全部委托给 confirm_magic_target（前端唯一在用的入口）。
    # 此前这里是第二套独立实现，与在用的那份语义已经漂移：桃园结义剩余牌
    # 进「弃牌堆」（在用版是放回牌堆）、不采用对方自选的 opponent_choice、
    # 也不广播 hand_updated / taoyuan_complete。两份实现并存 = 修一处漏一处。
    if temp_data_id in ('taoyuan_choice', 'bury_choice', 'shield_choice'):
        return confirm_magic_target({
            'room_id': room_id,
            'player_id': player_id,
            'temp_data_id': temp_data_id,
            'target_data': safe_target_data,
        })

    # 未知 temp_data_id：保持历史行为（只存不结算）
    return {'status': 'success'}


# 修改攻击处理函数，添加魔法效果检查
def frozen_ship_count(player) -> int:
    """统计处于冻结状态的战舰数（冻结的船不提供攻击次数）。"""
    return sum(1 for s in player.ships if getattr(s, 'frozen', None))


def _grant_subsidy_bonus(room, holder_id: str) -> bool:
    """百亿补贴：持卡者的船被击败时，给【持卡者自己】累计 +3 次攻击。

    卡面：「接下来如果自己的船被对方击败了，自己的攻击次数每有一艘船死亡就加3」。
    原实现直接加在 room.attacks_remaining（属于当前攻击者 = 对手），
    等于把奖励送给了对手，且下回合重算后持卡者永远拿不到。
    """
    player = room.players.get(holder_id)
    if not player or not player.effect_flags.subsidy:
        return False
    flags = player.effect_flags
    flags.subsidy_bonus = int(getattr(flags, 'subsidy_bonus', 0) or 0) + 3
    emit('message', {'text': '百亿补贴生效，你的攻击次数 +3'}, to=player.sid)
    return True


def _count_stats_for(room) -> bool:
    """人机对局是否计入战绩。

    打电脑必胜，若算进 users.wins / 连胜，排行榜（按 wins DESC 排序）与个人战绩
    都会被刷成假数据（线上账号 z1w6qn 的「3 胜 0 负 3 连胜」全部来自人机）。
    人机对局仍写入 matches 表以便回看历史，只是不参与统计。
    """
    return not getattr(room, 'is_ai_room', False)


def _check_last_chance(room, attacker_id: str, defender_id: str) -> bool:
    """回光返照：对使用者的船造成伤害则其直接判负。返回是否触发。"""
    eff = room.game_effects.get('last_chance')
    if eff and eff.get('caster') == defender_id and eff.get('round', room.round) == room.round:
        room.state = 'game_over'
        room.winner = attacker_id
        add_game_log(room, f"第{room.round}回合 · {_log_name(room, defender_id)} 触发回光返照失败并判负", 'result', {
            'winner': attacker_id,
            'loser': defender_id
        })
        # 记录战绩（若为已登录用户）
        try:
            winner_user_id = room.players[attacker_id].user_id
            loser_user_id = room.players[defender_id].user_id
            if winner_user_id or loser_user_id:
                db.record_match(winner_user_id or attacker_id, loser_user_id or defender_id,
                                getattr(room, 'game_logs', None), count_stats=_count_stats_for(room))
        except Exception:
            pass
        emit('game_over', {'winner': attacker_id}, room=room.id)
        return True
    return False


def _on_ship_destroyed(room, owner_id: str, ship, hits_added=None, source='magic'):
    """一艘船被摧毁后的通用副作用（普通攻击与区域魔法共用同一份实现）。

    普通攻击路径原先在 _apply_ship_sunk_effects 里内联；溅射 / 轰炸 / 硫磺火焰
    各自又写了一份，且都漏掉了两件事：

      ① 平等条约快照（game_effects['last_ship_change']）—— 这些卡造成的船数
         变化因此**无法被平等条约无效化**（卡面允许无效化"船数改变效果"）；
      ② 无暇圣心**中断** —— 它们只把 no_damage 置 False，效果本身既没被中断
         也没有广播，等于"有船沉了但无暇圣心还在"。

    source 记录这艘船是「怎么死的」，平等条约据此判断能不能无效化：
      - 'attack' 普通炮击 / 教皇旨意弃卡攻击
      - 'magic'  魔法卡造成的击沉（溅射 / 轰炸 / 硫磺火焰）
    卡面只允许无效化【魔法卡】造成的船数改变，攻击造成的不在此列。
    """
    owner = room.players[owner_id]
    room.game_effects['last_ship_change'] = {
        'round': room.round,  # 卡面"立即发动"：只允许无效化本大回合的船数改变
        'player': owner_id,
        'count': 1,
        'ship': ship,  # 保存 ship 引用，供平等条约完全回滚
        'hits_added': list(hits_added or []),
        'source': source,
    }

    # 百亿补贴: 自己的船被击败时，自己的攻击次数 +3
    if _grant_subsidy_bonus(room, owner_id):
        if room.game_effects.get('last_ship_change', {}).get('player') == owner_id:
            room.game_effects['last_ship_change']['subsidy_granted'] = True

    # 无暇圣心：只要有战舰被击沉就中断
    if 'holy_heart' in room.game_effects:
        del room.game_effects['holy_heart']
        emit('holy_heart_interrupted', {
            'reason': '有战舰被击沉，无暇圣心效果中断'
        }, room=room.id)


def _apply_ship_sunk_effects(room, room_id, attacker_id, defender_id, ship, target_x, target_y):
    """击沉一艘战舰后的共同副作用（handle_attack / _do_attack 共用）。

    包含：船数扣减、沉船记录、平等条约快照、百亿补贴、恶魔契约、
    八方来财、无暇圣心中断。
    """
    defender = room.players[defender_id]
    defender.remaining_ships -= 1
    defender.sunken_ships.append(ship)

    # 平等条约快照 + 百亿补贴 + 无暇圣心中断（与区域魔法共用）
    # source='attack'：炮击造成的船数减少，平等条约无效化不了（卡面只针对魔法卡）
    _on_ship_destroyed(room, defender_id, ship, [Position(x=target_x, y=target_y)],
                       source='attack')

    # 恶魔契约: 绑定船数增减 - 任意一方船被击杀，另一方也要牺牲一艘
    # 牺牲由该方玩家自己在棋盘上点选（AI 自动），不再随机。
    if room.game_effects.get('demon_contract'):
        _request_demon_contract_sacrifice(room, defender_id)

    # 八方来财: 战舰数目变化时抽一张牌
    if defender.effect_flags.treasure_hunter:
        room.draw_card(defender_id)
        emit('message', {'text': '八方来财生效，摸一张牌'}, to=defender.sid)

    # 检查无暇圣心效果：如果有战舰被击沉，中断效果
    if 'holy_heart' in room.game_effects:
        del room.game_effects['holy_heart']
        emit('holy_heart_interrupted', {
            'reason': '有战舰被击沉，无暇圣心效果中断'
        }, room=room_id)


def _apply_attacker_damage_buffs(room, room_id, attacker_id):
    """攻击造成伤害后攻击方触发的效果：饮血、越战越勇、伤害统计。"""
    attacker = room.players[attacker_id]
    if attacker.effect_flags.vampire:
        room.draw_card(attacker_id)
        emit('message', {'text': '饮血效果发动，抽一张卡'}, to=attacker.sid)
    if attacker.effect_flags.battle_spirit:
        room.attacks_remaining += 1
        emit('message', {'text': '越战越勇效果发动，攻击次数净增加1'}, room=room_id)
    attacker.damage_dealt_this_turn += 1


def _finish_game_win(room, room_id, winner_id, loser_id, log_message=None):
    """对局结束：置状态、记日志、记录战绩并广播 game_over。"""
    if room.state == 'game_over':
        # 幂等：对局已结束时不重复记账/广播（防止刷战绩）
        return
    room.state = 'game_over'
    room.winner = winner_id
    add_game_log(room, log_message or f"第{room.round}回合 · {_log_name(room, winner_id)} 获胜，游戏结束",
                 'result', {'winner': winner_id, 'loser': loser_id})
    try:
        winner_user_id = room.players[winner_id].user_id
        loser_user_id = room.players[loser_id].user_id
        # 只有当至少有一个是已登录用户时才记录
        if winner_user_id or loser_user_id:
            db.record_match(winner_user_id or winner_id, loser_user_id or loser_id,
                            getattr(room, 'game_logs', None), count_stats=_count_stats_for(room))
    except Exception:
        pass
    emit('game_over', {'winner': winner_id}, room=room_id)


@socketio.on('attack')
@_require_live_room
def handle_attack(data):
    room_id = data['room_id']
    attacker_id = data['player_id']
    target_x = data['x']
    target_y = data['y']

    room = room_manager.get_room(room_id)
    if not room or attacker_id not in room.players or not _identity_ok(room, attacker_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    if room.state == 'game_over':
        return {'status': 'error', 'message': '对局已结束'}
    frz = _frozen_reason(room, attacker_id)
    if frz:
        return {'status': 'error', 'message': frz}

    # 输入校验：坐标必须是 0-5 的【整数】，避免越界/非法类型被记为一次攻击；
    # 也拒绝 1.9 这类小数（原先 int() 会静默截断成 1，打到别的格子）
    try:
        fx, fy = float(target_x), float(target_y)
    except (TypeError, ValueError):
        return {'status': 'error', 'message': '非法的攻击坐标'}
    if not (fx.is_integer() and fy.is_integer()):
        return {'status': 'error', 'message': '非法的攻击坐标'}
    target_x, target_y = int(fx), int(fy)
    if not (0 <= target_x <= 5 and 0 <= target_y <= 5):
        return {'status': 'error', 'message': '攻击坐标超出棋盘范围'}

    # 检查是否是当前攻击者
    if attacker_id != room.current_attacker:
        return {'status': 'error', 'message': '还没到你的攻击回合'}

    # 新增：检查当前是否为战斗阶段
    if room.current_phase != 'battle':
        return {'status': 'error', 'message': '当前不是战斗阶段'}

    # 连锁窗口开着时不能继续攻击：卡牌效果要到 resolve_chain 才真正执行，
    # 此时放行会让「先结算的攻击」与「后结算的卡」互相盖掉（end_turn 早已用
    # 同一条件拦截，攻击却漏了 —— 同一状态两种口径）。
    if room.chain or room.chain_waiting:
        return {'status': 'error', 'message': '连锁结算中，请等待响应窗口结束后再攻击'}

    # 次数校验：此前缺失，改客户端（或前端连点绕过 DOM 判断）即可无限攻击
    if room.attacks_remaining <= 0:
        return {'status': 'error', 'message': '本回合攻击次数已用尽'}

    # 检查是否已经攻击过这个位置
    if any(a.x == target_x and a.y == target_y for a in room.players[attacker_id].attacks):
        return {'status': 'error', 'message': '你已经攻击过这个位置了'}

    # 找到对手
    defender_id = next(p for p in room.players if p != attacker_id)
    defender_ships = room.players[defender_id].ships

    # 神威！：被扣掉的区域不可攻击
    if _cell_in_shenwei_hole(room, defender_id, target_x, target_y):
        return {'status': 'error', 'message': '该区域已被神威！扣掉，无法攻击'}

    # 检查是否击中（统一路径：强制击杀与普通攻击共用一套结算）
    hit = False
    ship_sunk = False
    for i, ship in enumerate(defender_ships):
        if {'x': target_x, 'y': target_y} not in ship.positions:
            continue
        hit = True

        # 更新无暇圣心效果：如果有伤害，标记no_damage为False（无敌状态不算造成伤害）
        if 'holy_heart' in room.game_effects and not ship.invincible:
            room.game_effects['holy_heart']['no_damage'] = False

        # 检查攻击者是否有强制击杀效果
        has_forced_kill = room.players[attacker_id].effect_flags.forced_kill > 0

        if has_forced_kill:
            # 强制击杀效果：忽略无敌和盾牌状态，记录击中位置并直接击沉
            defender_ships[i].hits = defender_ships[i].hits + [Position(x=target_x, y=target_y)]
            ship_sunk = True
            _apply_ship_sunk_effects(room, room_id, attacker_id, defender_id,
                                     defender_ships[i], target_x, target_y)
        elif ship.invincible:
            # 无敌状态，只显形不造成伤害
            ship_sunk = False
        elif ship.shield:
            # 盾牌状态，抵挡一次伤害
            ship_sunk = False
            ship.shield = False
        else:
            # 记录击中位置
            defender_ships[i].hits = defender_ships[i].hits + [Position(x=target_x, y=target_y)]
            # 检查船是否被击沉
            if len(defender_ships[i].hits) == len(defender_ships[i].positions):
                ship_sunk = True
                _apply_ship_sunk_effects(room, room_id, attacker_id, defender_id,
                                         defender_ships[i], target_x, target_y)
            else:
                ship_sunk = False

        # 造成伤害（含强制击杀）时才触发攻击方增益与胜负检查
        if has_forced_kill or (not ship.invincible and not ship.shield):
            # 检查回光返照效果：造成伤害即判负
            if _check_last_chance(room, attacker_id, defender_id):
                return {'status': 'success', 'game_over': True}

            # 发送战舰数更新事件
            _emit_ships_updated(room)

            # 饮血 / 越战越勇 / 伤害统计
            _apply_attacker_damage_buffs(room, room_id, attacker_id)

            # 检查绝处逢生效果：直接获胜
            if room.players[attacker_id].effect_flags.last_stand:
                _finish_game_win(room, room_id, attacker_id, defender_id,
                                 f"第{room.round}回合 · {_log_name(room, attacker_id)} 触发绝处逢生并获胜")
                return {'status': 'success', 'game_over': True}

            # 注意：强制击杀按【攻击阶段】计数，不按击杀次数消耗，
            # 改为在进入结束阶段时消耗（见 handle_enter_end_phase）。
        break


    # 记录最后一次攻击（用于溅射等效果）
    room.last_attack = {
        'attacker': attacker_id,
        'x': target_x,
        'y': target_y,
        'hit': hit,
        'ship_sunk': ship_sunk,
        'round': room.round
    }

    # 减少攻击次数
    room.attacks_remaining -= 1
    # 确保攻击次数不会为负数
    room.attacks_remaining = max(0, room.attacks_remaining)

    # 记录本次攻击到attacks列表（修复重复攻击校验与AI追踪失效）
    room.players[attacker_id].attacks.append(Position(**{
        'x': target_x,
        'y': target_y,
        'hit': hit,
        'ship_sunk': ship_sunk
    }))

    # 准备攻击结果
    attack_result = AttackResult(
        attacker=attacker_id,
        x=target_x,
        y=target_y,
        hit=hit,
        ship_sunk=ship_sunk,
        remaining_attacks=room.attacks_remaining,
        attacker_remaining_ships=room.players[attacker_id].remaining_ships,
        defender_remaining_ships=room.players[defender_id].remaining_ships
    )

    add_game_log(room, f"第{room.round}回合 · {_log_name(room, attacker_id)} 攻击 ({target_x},{target_y}) — {'命中' if hit else '未命中'}{'，击沉战舰' if ship_sunk else ''}",
                 'attack', {
                     'attacker': attacker_id,
                     'target': {'x': target_x, 'y': target_y},
                     'hit': hit,
                     'ship_sunk': ship_sunk
                 })

    emit('attack_result', attack_result, room=room_id)

    # 检查游戏是否结束（统一用 <= 0 判据，兼容效果的非常规扣减）；
    # 对手"根本没船"（未布船 / 放置流程中途）不算被消灭，避免空棋盘被一击判胜
    if (room.players[defender_id].remaining_ships <= 0
            and len(room.players[defender_id].ships) > 0):
        _finish_game_win(room, room_id, attacker_id, defender_id)
        return {'status': 'success', 'game_over': True}

    # 攻击次数为0时，不自动切换攻击者，让玩家手动进入结束阶段
    # 玩家需要点击"进入结束阶段"按钮来结束当前回合
    if room.attacks_remaining == 0:
        # 五险一金：本回合攻击次数第一次归零 —— 若此刻确实没让对方减船，则 +3
        # （触发后攻击次数不再是 0，下面的广播会把最新次数带给前端）
        _maybe_trigger_wuxian_yijin(room, attacker_id)

    if room.attacks_remaining == 0:
        # 只发送攻击次数更新，不切换攻击者
        emit('attacks_updated', {
            'current_attacker': room.current_attacker,
            'attacks_remaining': room.attacks_remaining
        }, room=room_id)

    return {'status': 'success'}


@socketio.on('enter_battle_phase')
@_require_live_room
def enter_battle_phase(data):
    room_id = data['room_id']
    player_id = data['player_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    frz = _frozen_reason(room, player_id)
    if frz:
        return {'status': 'error', 'message': frz}

    # 检查是否是当前攻击者的准备阶段
    if room.current_attacker == player_id and room.current_phase == 'preparation':
        # 切换到战斗阶段
        room.current_phase = 'battle'
        if field_magic_name(room) == "伊甸园":
            room.attacks_remaining = 6 - room.players[player_id].remaining_ships

        # 检查是否有攻击次数翻倍效果
        if room.players[player_id].effect_flags.double_attacks:
            # 翻倍当前攻击次数：冻结船不提供攻击次数，且保留百亿补贴累计加成
            base_attacks = max(
                0, room.players[player_id].remaining_ships - frozen_ship_count(room.players[player_id]))
            room.attacks_remaining = (base_attacks * 2
                                      + int(getattr(room.players[player_id].effect_flags,
                                                    'subsidy_bonus', 0) or 0))
            # 广播攻击次数更新
            emit('attacks_updated', {
                'current_attacker': room.current_attacker,
                'attacks_remaining': room.attacks_remaining
            }, room=room_id)
            # 移除翻倍效果，因为它只持续一个大回合
            room.players[player_id].effect_flags.double_attacks = False
        if field_magic_name(room) == "教皇旨意":
            room.attacks_remaining = 0

        # 五险一金：进战斗阶段时攻击次数就可能是 0（教皇旨意直接把次数压成 0），
        # 这也算「本回合第一次归零」，要给它触发机会。
        if room.attacks_remaining <= 0:
            _maybe_trigger_wuxian_yijin(room, player_id)

        # 广播阶段更新
        emit('phase_updated', {
            'current_phase': room.current_phase,
            'current_attacker': room.current_attacker
        }, room=room_id)
        return {'status': 'success'}

    return {'status': 'error', 'message': '无法进入战斗阶段'}


# 添加结束战斗阶段，进入结束阶段
@socketio.on('enter_end_phase')
@_require_live_room
def handle_enter_end_phase(data):
    room_id = data['room_id']
    player_id = data['player_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 检查是否是当前攻击者的战斗阶段
    if room.current_attacker == player_id and room.current_phase == 'battle':
        # 检查是否还有剩余攻击次数
        if room.attacks_remaining > 0:
            return {'status': 'error', 'message': '你还有剩余攻击次数，无法进入结束阶段'}
        
        # 进入结束阶段
        room.current_phase = 'end'

        # 余音绕梁按攻击阶段计数：本回合的攻击阶段结束即消耗一次
        flags = room.players[player_id].effect_flags
        if getattr(flags, 'forced_kill', 0) > 0:
            flags.forced_kill -= 1
            if flags.forced_kill <= 0:
                del flags.forced_kill

        # 清除越战越勇效果
        room.players[player_id].effect_flags.battle_spirit=False
        
        emit('phase_updated', {
            'current_phase': room.current_phase,
            'current_attacker': room.current_attacker
        }, room=room_id)

        return {'status': 'success', 'message': '已进入结束阶段'}

    # 兜底：不满足条件时必须回一个 dict。
    # 返回 None 会让前端 ack 回调拿到 undefined，读 response.status 直接抛
    # TypeError，把真正的错误提示整个吞掉（控制台里只剩一行莫名其妙的报错）。
    return {'status': 'error', 'message': '当前不是你的战斗阶段'}


def switch_turn_after_end_phase(room, opponent_id):
    # 模拟结束阶段处理时间
    time.sleep(2)

    # 切换到对方回合
    room.current_attacker = opponent_id
    room.attacks_remaining = max(0, room.players[opponent_id].remaining_ships - frozen_ship_count(room.players[opponent_id]))  # 存活战舰数减去冻结数
    _recalc_attacker_attacks(room)
    room.current_phase = 'preparation'
    
    # 重置本回合伤害统计
    room.players[opponent_id].damage_dealt_this_turn = 0

    # 广播回合变化 - 移除了回合切换时的额外抽卡
    emit('turn_change', {
        'current_attacker': opponent_id,
        'attacks_remaining': room.attacks_remaining,
        'phase': 'preparation'
    }, room=room.id)
    # 轮到AI时自动驱动其回合
    _maybe_run_ai_turn(room)


# 添加结束结束阶段，切换到对方准备阶段
@socketio.on('end_turn')
@_require_live_room
def end_turn(data):
    room_id = data['room_id']
    player_id = data['player_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    frz = _frozen_reason(room, player_id)
    if frz:
        return {'status': 'error', 'message': frz}

    # 连锁未结算时禁止结束回合。
    # 卡牌效果在 resolve_chain 里才真正执行，若此时放行换人，
    # 效果会落在「下一个人已经是当前攻击者」之后 —— Freezing！ 这种
    # 「跳过对方回合」的效果就这么凭空丢了（还不会被任何人察觉）。
    if room.chain or room.chain_waiting:
        return {'status': 'error', 'message': '连锁结算中，请等待响应窗口结束后再结束回合'}

    # 检查是否是当前攻击者的结束阶段
    if room.current_attacker == player_id and room.current_phase == 'end':
        current_index = room.attack_order.index(room.current_attacker)
        next_index = (current_index + 1) % len(room.attack_order)

        # 如果是最后一个玩家结束回合，开始新的大回合
        if next_index == 0:
            # 进入新回合，重置状态
            room.round += 1

            # 看破！：新大回合开始重置双方的魔法封锁
            for p_id in room.players:
                room.players[p_id].magic_blocked = None

            # 神威！：除外的战舰到期回归原位，并恢复被扣掉的区域
            _restore_due_shenwei(room, room.round)

            # 解冻到期的战舰（冻结跨本大回合+下一大回合，第三大回合开始时解除）
            for p_id in room.players:
                thawed = False
                for s in room.players[p_id].ships:
                    if getattr(s, 'frozen', None) and s.frozen < room.round:
                        del s.frozen
                        thawed = True
                if thawed:
                    # 解冻同样要让玩家看到（否则棋盘上一直挂着雪花）
                    _emit_player_ships(room, p_id)

            # 回光返照只持续自己发动的那一个大回合
            room.game_effects.pop('last_chance', None)

            # 新大回合：双方本回合伤害统计归零
            # （此前唯一重置点在死代码 switch_turn_after_end_phase 内，
            #  导致 damage_dealt_this_turn 只增不减，五险一金/Freezing! 失效）
            for p_id in room.players:
                room.players[p_id].damage_dealt_this_turn = 0

            # 更新并检查极限增援效果
            if 'reinforcement_check' in room.game_effects:
                check = room.game_effects['reinforcement_check']
                # 卡面：不算生效的那个大回合，所以进入下一个大回合时先不递减
                # （room.round 此处已 +1；activated_round 那个大回合不计入）
                if room.round > int(check.get('activated_round', room.round - 1)) + 1:
                    check['remaining_turns'] -= 1
                remaining_turns = check['remaining_turns']

                # 通知客户端剩余回合更新
                emit('reinforcement_turn_updated', {
                    'remaining_turns': remaining_turns
                }, room=room_id)

                # 当剩余回合归0时，执行极限增援结算
                if remaining_turns <= 0:
                    # 执行极限增援效果：船数少的一方获胜
                    player1_id = list(room.players.keys())[0]
                    player2_id = list(room.players.keys())[1]
                    player1_ships = room.players[player1_id].remaining_ships
                    player2_ships = room.players[player2_id].remaining_ships

                    if player1_ships < player2_ships:
                        winner = player1_id
                    elif player2_ships < player1_ships:
                        winner = player2_id
                    else:
                        # 船数相同，随机选择获胜者或继续游戏
                        # 按照需求，当倒计回合归0时直接判定，所以即使船数相同也要选择
                        winner = random.choice([player1_id, player2_id])

                    # 统一收尾：记日志 + 记战绩 + 广播 game_over
                    # （原先这条终局路径只置状态不写战绩）
                    loser = player2_id if winner == player1_id else player1_id
                    _finish_game_win(room, room_id, winner, loser,
                                     f"第{room.round}回合 · 极限增援生效，船数少的一方获胜")

                    # 广播游戏结束
                    emit('game_state', {
                        'state': 'game_over',
                        'winner': winner,
                        'reason': '极限增援生效，船数少的一方等到了增援并获胜了！'
                    }, room=room_id)
                    return {'status': 'success', 'game_over': True, 'winner': winner}

                # 更新game_effects中的剩余回合
                room.game_effects['reinforcement_check'] = check

            # 更新并检查无暇圣心效果
            if 'holy_heart' in room.game_effects:
                check = room.game_effects['holy_heart']
                # 只有当双方都未造成伤害时才更新
                if check['no_damage']:
                    # 更新剩余回合计数
                    check['remaining_turns'] -= 1
                    remaining_turns = check['remaining_turns']

                    # 通知客户端剩余回合更新
                    emit('holy_heart_turn_updated', {
                        'remaining_turns': remaining_turns
                    }, room=room_id)

                    # 当剩余回合归0时，执行无暇圣心结算
                    if remaining_turns <= 0:
                        # 执行无暇圣心效果：施法者获胜
                        winner = check['caster']

                        # 直接结束游戏
                        room.state = 'game_over'
                        room.winner = winner

                        # 广播游戏结束
                        emit('game_state', {
                            'state': 'game_over',
                            'winner': winner,
                            'reason': '无暇圣心笼罩大地 愿这方世界不再有战争'
                        }, room=room_id)
                        return {'status': 'success', 'game_over': True, 'winner': winner}

                    # 更新game_effects中的剩余回合
                    room.game_effects['holy_heart'] = check

            room.state = 'rock_paper_scissors'
            room.rps_choices = {}
            room.rps_processed = False

            # 神机妙算: 检查沉船数是否增加了x（击沉不从ships移除，用沉船差值判定）
            for p_id in room.players:
                player = room.players[p_id]
                pred = getattr(player.effect_flags, 'prediction', 0)
                if pred and isinstance(pred, int) and pred > 0:
                    # 从game_effects中读取初始快照
                    if f'prediction_initial_{p_id}' in room.game_effects:
                        saved = room.game_effects[f'prediction_initial_{p_id}']
                        diff = len(player.sunken_ships) - saved['sunken']
                        if diff == pred:
                            # 预测成功：把减少的船恢复（仍在ships中的不重复加入）
                            _revive_sunken_ships(room, player, pred)
                            del room.game_effects[f'prediction_initial_{p_id}']
                        room.players[p_id].effect_flags.prediction = 0

            # 重置所有临时效果标志，包括no_draw标志
            for p_id in room.players:
                # 保留场地魔法等永久效果，清除所有临时效果（包括no_draw）
                permanent_flags = ['holy_heart']  # 永久效果白名单（reinforcement_check不是玩家效果）
                room.players[p_id].effect_flags.__dict__ = {k: v for k, v in
                                                                room.players[p_id].effect_flags.__dict__.items() if
                                                                k in permanent_flags}

            # 新一轮清空了所有临时效果，角标要跟着消失
            _emit_active_effects(room)

            # 广播进入猜拳阶段
            emit('game_state', {
                'state': 'rock_paper_scissors',
                'round': room.round
            }, room=room_id)
            # 新大回合开始，清掉上一回合残留的跳过标记。
            # 否则若 skip 未能匹配到目标，会一直留着并在后续回合误跳。
            room.skip_opponent_turn = None
            room.skip_next_turn = None
            return {'status': 'success', 'new_round': True}
        else:
            # 检查skip机制（Freezing！/神之宣告跳过对方回合）
            next_attacker = room.attack_order[next_index]
            if room.skip_opponent_turn and room.skip_opponent_turn == next_attacker:
                # 跳过这个玩家的整个回合
                room.skip_opponent_turn = False
                next_index = (next_index + 1) % len(room.attack_order)
                next_attacker = room.attack_order[next_index]

            if room.skip_next_turn and room.skip_next_turn == next_attacker:
                # 跳过这个玩家，切换到下一个人
                room.skip_next_turn = None
                next_index = (next_index + 1) % len(room.attack_order)
                next_attacker = room.attack_order[next_index]
                # 新回合也视为结束阶段，需要再次检查skip
                if room.skip_next_turn and room.skip_next_turn == next_attacker:
                    room.skip_next_turn = None
                    next_index = (next_index + 1) % len(room.attack_order)
                    next_attacker = room.attack_order[next_index]

            # 切换到下一个攻击者的准备阶段
            room.current_attacker = next_attacker
            room.current_phase = 'preparation'
            # 新回合伤害统计归零（见上：原重置点在死代码里）
            room.players[room.current_attacker].damage_dealt_this_turn = 0
            # 统一走 _recalc：伊甸园/教皇旨意下按场地规则计算
            _recalc_attacker_attacks(room)

            # 重置所有临时效果标志 - 但保留no_draw标志直到大回合结束
            for p_id in room.players:
                # 保留场地魔法等永久效果和no_draw标志，清除其他临时效果（prediction需存活到对方结束阶段）
                # 余音绕梁要活到"下一个回合自己的攻击阶段"，故一并保留
                permanent_flags = ['holy_heart', 'reinforcement_check', 'no_draw', 'prediction', 'forced_kill']
                room.players[p_id].effect_flags.__dict__ = {k: v for k, v in
                                                                room.players[p_id].effect_flags.__dict__.items() if
                                                                k in permanent_flags}

            # 标记刚被清了一批，角标要跟着消失（否则百亿补贴等会一直亮着）
            _emit_active_effects(room)

            # 广播回合和阶段更新
            emit('phase_updated', {
                'current_phase': room.current_phase,
                'current_attacker': room.current_attacker
            }, room=room_id)
            emit('turn_change', {
                'current_attacker': room.current_attacker,
                'attacks_remaining': room.attacks_remaining,
                'phase': room.current_phase
            }, room=room_id)
            # 轮到AI时自动驱动其回合
            _maybe_run_ai_turn(room)
            return {'status': 'success'}

    return {'status': 'error', 'message': '无法结束当前回合'}






# ---------------------------------------------------------------------------
# AI 对战驱动：AI 自动摆船/出拳/回合推进（仅 is_ai_room 房间生效）
# ---------------------------------------------------------------------------
def _ai_player_id(room):
    """返回房间内AI玩家ID；不存在返回None。"""
    for pid in room.players:
        if pid.startswith('ai-'):
            return pid
    return None


def _ai_place_ships(room, ai_id: str):
    """为AI随机摆放战舰——规则与人类玩家完全一致：
    单格船、数量取该玩家的 max_ships（默认6）、坐标 0-5 内不重叠。"""
    import random as _rnd
    player = room.players[ai_id]
    player.ships = []
    player.remaining_ships = 0
    # 与人类一致：默认 6 艘（或按 room/玩家已设定的 max_ships，如灵气复苏后）
    max_ships = int(getattr(player, 'max_ships', 6) or 6)
    all_positions = [(x, y) for x in range(6) for y in range(6)]
    _rnd.shuffle(all_positions)
    for (px, py) in all_positions[:max_ships]:
        player.ships.append(PlayerShip(positions=[Position(x=px, y=py)], hits=[]))
        player.remaining_ships += 1


def _maybe_run_ai_turn(room):
    """若当前攻击者是AI，后台驱动其完整回合。"""
    if not getattr(room, 'is_ai_room', False) or room.state == 'game_over':
        return
    ai_id = _ai_player_id(room)
    if not ai_id or room.current_attacker != ai_id:
        return
    socketio.start_background_task(_ai_turn_loop, room.id)


AI_DIFFICULTIES = ('easy', 'normal', 'hard')

# AI 可以安全打出的卡：无目标、无后续选择、也不需要「本回合刚命中/刚击沉」之类前置条件。
# 其余卡一律不打，原因有二：
#   ① 桃园结义 / 明智埋葬 / 神机妙算 / 仁王之盾 / 灵气复苏 / 增援 / 死者苏生 / 绝处逢生
#      会等待「施法者自己」点选或放置（temp_data_id / pending_placement），AI 无从响应，
#      打出去会把整局卡死在那一个回合；
#   ② 溅射 / 雷达子弹 / 饮血 / 越战越勇 需要刚命中或刚击沉，随机打出只是浪费牌。
# 要扩卡池，先在 pytest 里确认该卡分支不会留下待处理状态。
_AI_SAFE_CARDS = (
    '余音绕梁', '火力全开', '无中生有', '极限增援', '无暇圣心',
    '看破！', '五险一金', '八方来财', '百亿补贴',
)


def _ai_choose_magic_card(room, ai_id: str):
    """纯函数：挑一张 AI 能安全打出的手牌，返回下标；没有则 None。

    只做选择、不改状态，方便单测。按速阶从低到高挑（速阶 1 最便宜）。
    """
    player = room.players.get(ai_id)
    if not player or not player.magic_hand:
        return None
    candidates = []
    for idx, c in enumerate(player.magic_hand):
        if c.name not in _AI_SAFE_CARDS:
            continue
        if not can_play_magic_card(room, ai_id, c):
            continue
        candidates.append((int(c.speed), idx))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def _ai_maybe_play_magic(room, ai_id: str) -> bool:
    """AI 在自己回合打出一张安全的魔法卡；返回是否真的打出。

    每回合最多一张，避免把整手牌一次性倒光。简单难度（easy）不出牌。
    """
    if getattr(room, 'ai_difficulty', 'normal') == 'easy':
        return False
    idx = _ai_choose_magic_card(room, ai_id)
    if idx is None:
        return False
    card = room.players[ai_id].magic_hand[idx]
    resp = handle_use_magic_card({
        'room_id': room.id,
        'player_id': ai_id,
        'card': {'name': card.name, 'speed': card.speed, 'type': card.type,
                 'description': getattr(card, 'description', '')},
        'targets': {},
    })
    return bool(resp and resp.get('status') == 'success')


def _ai_turn_loop(room_id: str):
    """AI回合：进入战斗阶段→随机攻击至次数耗尽→结束阶段→交出回合。"""
    try:
        time.sleep(1)
        room = room_manager.get_room(room_id)
        if not room or room.state == 'game_over':
            return
        ai_id = _ai_player_id(room)
        if not ai_id or room.current_attacker != ai_id:
            return
        enter_battle_phase({'room_id': room_id, 'player_id': ai_id})

        # 先出一张安全卡（normal / hard 难度）。出牌可能打开连锁响应窗口，
        # 而连锁未结算时攻击会被 handle_attack 门禁拒绝 —— 必须等窗口关闭再开炮，
        # 否则 AI 的攻击会全军覆没、回合草草结束。
        _ai_maybe_play_magic(room, ai_id)
        for _ in range(40):
            room = room_manager.get_room(room_id)
            if not room or room.state == 'game_over' or room.current_attacker != ai_id:
                return
            if not (room.chain or room.chain_waiting):
                break
            time.sleep(0.3)

        for _ in range(40):
            room = room_manager.get_room(room_id)
            if not room or room.state == 'game_over' or room.current_attacker != ai_id:
                return
            if room.attacks_remaining <= 0:
                break
            attacked = {(a.x, a.y) for a in room.players[ai_id].attacks}
            candidates = [(x, y) for x in range(6) for y in range(6) if (x, y) not in attacked]
            if not candidates:
                break
            x, y = random.choice(candidates)
            handle_attack({'room_id': room_id, 'player_id': ai_id, 'x': x, 'y': y})
            time.sleep(0.3)
        room = room_manager.get_room(room_id)
        if not room or room.state == 'game_over' or room.current_attacker != ai_id:
            return

        # 收尾必须重试：连锁若还没结算完，enter_end_phase / end_turn 会被门禁拒绝，
        # 而 AI 回合没有别的触发点 —— 一旦这里失败，回合就会永远停在 AI 手上，
        # 真人只能干等（此前 AI 不出牌，所以碰不到这个竞态）。
        for _ in range(20):
            room = room_manager.get_room(room_id)
            if not room or room.state == 'game_over' or room.current_attacker != ai_id:
                return
            if room.chain or room.chain_waiting:
                time.sleep(0.5)
                continue
            resp = handle_enter_end_phase({'room_id': room_id, 'player_id': ai_id})
            if resp and resp.get('status') == 'success':
                break
            time.sleep(0.5)
        time.sleep(0.5)

        for _ in range(20):
            room = room_manager.get_room(room_id)
            if not room or room.state == 'game_over' or room.current_attacker != ai_id:
                return
            resp = end_turn({'room_id': room_id, 'player_id': ai_id})
            if resp and resp.get('status') == 'success':
                return
            time.sleep(0.5)
    except Exception as e:
        print(f'AI turn error: {e}')


# 教皇旨意弃卡攻击
@socketio.on('papal_attack')
@_require_live_room
def handle_papal_attack(data):
    room_id = data['room_id']
    player_id = data['player_id']
    target_x = data['x']
    target_y = data['y']
    discard_card_index = data.get('discard_card_index')

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    if room.state == 'game_over':
        return {'status': 'error', 'message': '对局已结束'}
    frz = _frozen_reason(room, player_id)
    if frz:
        return {'status': 'error', 'message': frz}

    # 弃卡攻击同样受回合/阶段约束（此前可在对手回合任意攻击）
    if room.current_attacker != player_id:
        return {'status': 'error', 'message': '还没到你的攻击回合'}
    if room.current_phase != 'battle':
        return {'status': 'error', 'message': '当前不是战斗阶段'}

    player = room.players[player_id]
    opponent_id = next(p for p in room.players if p != player_id)
    opponent = room.players[opponent_id]

    # 检查教皇旨意是否生效
    if room.game_effects.get('papal_edict') is not True and field_magic_name(room) != '教皇旨意':
        return {'status': 'error', 'message': '教皇旨意未生效'}

    # 必须有手牌才能弃卡攻击
    if not player.magic_hand:
        return {'status': 'error', 'message': '没有可弃置的魔法卡'}

    # 弃置指定的魔法卡（如果指定了）
    if discard_card_index is None:
        # 默认弃置第一张
        discarded = player.magic_hand.pop(0)
        room.magic_discard.append(discarded)
    else:
        try:
            discard_card_index = int(discard_card_index)
        except (TypeError, ValueError):
            return {'status': 'error', 'message': '无效的弃卡位置'}
        if not (0 <= discard_card_index < len(player.magic_hand)):
            # 越界索引：原先一张不弃却照打两次（零代价攻击），直接拒绝
            return {'status': 'error', 'message': '无效的弃卡位置'}
        discarded = player.magic_hand.pop(discard_card_index)
        room.magic_discard.append(discarded)

    # 执行两次攻击（因为教皇旨意每次弃卡攻击两次）
    results = []
    for _ in range(2):
        # 复用普通攻击逻辑
        result = _do_attack(room, room_id, player_id, target_x, target_y, opponent_id, opponent)
        results.append(result)
        # 如果第一次攻击已击杀所有船，停止第二次
        if opponent.remaining_ships <= 0:
            break

    return {'status': 'success', 'results': results}


# 普通攻击的提取函数
def _do_attack(room, room_id, attacker_id, target_x, target_y, defender_id, defender):
    """执行一次弃卡攻击（教皇旨意路径；不消耗常规攻击次数）。

    击沉副作用复用 _apply_ship_sunk_effects，与普通攻击路径保持一致。
    """
    defender_ships = defender.ships
    hit = False
    ship_sunk = False

    for i, ship in enumerate(defender_ships):
        if {'x': target_x, 'y': target_y} in ship.positions:
            hit = True
            if 'holy_heart' in room.game_effects and not ship.invincible:
                room.game_effects['holy_heart']['no_damage'] = False
            if not ship.invincible and not ship.shield:
                defender_ships[i].hits = defender_ships[i].hits + [Position(x=target_x, y=target_y)]
                if len(defender_ships[i].hits) == len(defender_ships[i].positions):
                    ship_sunk = True
                    _apply_ship_sunk_effects(room, room_id, attacker_id, defender_id,
                                             defender_ships[i], target_x, target_y)
                    if room.players[attacker_id].effect_flags.vampire:
                        room.draw_card(attacker_id)
                    if room.players[attacker_id].effect_flags.last_stand:
                        _finish_game_win(room, room_id, attacker_id, defender_id,
                                         f"第{room.round}回合 · {_log_name(room, attacker_id)} 触发绝处逢生并获胜")
                        return {'game_over': True}
                    if _check_last_chance(room, attacker_id, defender_id):
                        return {'game_over': True}
                    _emit_ships_updated(room)
            elif ship.shield:
                ship.shield = False
            break

    room.last_attack = {'attacker': attacker_id, 'x': target_x, 'y': target_y, 'hit': hit, 'ship_sunk': ship_sunk, 'round': room.round}
    attacker_attacks = room.players[attacker_id].attacks
    attacker_attacks.append(Position(**{'x': target_x, 'y': target_y, 'hit': hit, 'ship_sunk': ship_sunk}))
    emit('attack_result', {
        'attacker': attacker_id, 'x': target_x, 'y': target_y,
        'hit': hit, 'ship_sunk': ship_sunk,
        'remaining_attacks': room.attacks_remaining,
        'attacker_remaining_ships': room.players[attacker_id].remaining_ships,
        'defender_remaining_ships': room.players[defender_id].remaining_ships
    }, room=room_id)

    if (room.players[defender_id].remaining_ships <= 0
            and len(room.players[defender_id].ships) > 0):
        _finish_game_win(room, room_id, attacker_id, defender_id)
        return {'status': 'success', 'game_over': True}

    return {'status': 'success'}


def _sanitize_magic_targets(targets):
    """校验并归一化魔法卡目标坐标；返回 (targets, error_message)。

    仅处理 dict 形态的目标数据（前端 target_area/target_line/target_cells 等），
    数组/None 交由各卡牌分支自行处理。
    """
    if not isinstance(targets, dict):
        return targets, None

    area = targets.get('target_area')
    if isinstance(area, dict):
        for k in ('x1', 'y1', 'x2', 'y2'):
            if k not in area:
                return targets, '目标区域参数缺失'
            try:
                v = int(area[k])
            except (TypeError, ValueError):
                return targets, '目标区域坐标非法'
            if not (0 <= v <= 5):
                return targets, '目标区域坐标超出棋盘范围'
            area[k] = v

    line = targets.get('target_line')
    if isinstance(line, dict):
        if line.get('type') not in ('row', 'col'):
            return targets, '目标行列参数非法'
        try:
            idx = int(line.get('index'))
        except (TypeError, ValueError):
            return targets, '目标行列坐标非法'
        if not (0 <= idx <= 5):
            return targets, '目标行列坐标超出棋盘范围'
        line['index'] = idx

    for key in ('target_cells', 'selected_cells'):
        cells = targets.get(key)
        if isinstance(cells, list):
            for c in cells:
                if not isinstance(c, dict):
                    return targets, '目标格子格式错误'
                try:
                    cx, cy = int(c['x']), int(c['y'])
                except (KeyError, TypeError, ValueError):
                    return targets, '目标格子坐标非法'
                if not (0 <= cx <= 5 and 0 <= cy <= 5):
                    return targets, '目标格子坐标超出棋盘范围'
                c['x'], c['y'] = cx, cy

    return targets, None


def _pick_cell_from_target(target_data):
    """从目标数据里取出玩家点选的单个格子 (x, y)；取不到返回 None。

    兼容两种前端形态：
    - `{'target_area': {'x1': x, 'y1': y, ...}}`（single 选择器 → 1x1 区域）
    - `{'x': x, 'y': y}`
    """
    if not isinstance(target_data, dict):
        return None

    area = target_data.get('target_area')
    if isinstance(area, dict):
        try:
            return int(area['x1']), int(area['y1'])
        except (KeyError, TypeError, ValueError):
            return None

    if 'x' in target_data and 'y' in target_data:
        try:
            return int(target_data['x']), int(target_data['y'])
        except (TypeError, ValueError):
            return None

    return None


def _find_ship_at(player, cell):
    """返回该玩家在指定格子上的一艘船；没有则返回 None。"""
    if not cell:
        return None
    x, y = cell
    for ship in getattr(player, 'ships', []) or []:
        for pos in getattr(ship, 'positions', []) or []:
            if pos.x == x and pos.y == y:
                return ship
    return None


@socketio.on('use_magic_card')
@_require_live_room
def handle_use_magic_card(data):
    room_id = data['room_id']
    player_id = data['player_id']
    try:
        card = MagicCard(**data['card'])
    except (ValueError, TypeError, KeyError) as e:
        # 卡牌数据非法（未知卡名 / 非 dict / 缺字段）：返回错误而非让 handler 崩溃
        return {'status': 'error', 'message': f'魔法卡数据无效: {e}'}
    targets = data.get('targets', [])

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    targets, target_err = _sanitize_magic_targets(targets)
    if target_err:
        return {'status': 'error', 'message': target_err}
    frz = _frozen_reason(room, player_id)
    if frz:
        return {'status': 'error', 'message': frz}

    player = room.players[player_id]
    opponent_id = next(p for p in room.players if p != player_id)

    # 连锁响应窗口未关闭时，应通过 chain_response 响应，而不是再打出新牌
    if room.chain_waiting:
        return {'status': 'error', 'message': '连锁响应中，请先响应连锁'}

    # 看破！：被封锁的玩家本大回合无法使用魔法卡
    if player.magic_blocked:
        return {'status': 'error', 'message': '你的魔法卡已被看破，本回合无法使用'}

    # 检查卡牌是否在玩家手牌中
    if not any(c.name == card.name and c.speed == card.speed for c in player.magic_hand):
        return {'status': 'error', 'message': '你没有这张魔法卡'}

    # 检查是否可以在当前阶段使用
    if not can_play_magic_card(room, player_id, card):
        reason = None
        if card.name in END_PHASE_PLAYABLE:
            # 这类卡有专属条件，把具体原因告诉玩家，别只报「速阶2」
            reason = freezing_block_reason(room, player_id, card)
        elif card.name == '五险一金' and field_magic_name(room) == '教皇旨意':
            reason = '教皇旨意生效中，本回合攻击次数为0，五险一金无法发动'
        return {'status': 'error',
                'message': reason or f'当前阶段{room.current_phase}无法使用速阶{card.speed}的魔法卡'}

    # 找到并移除玩家手牌中的卡牌
    for i, c in enumerate(player.magic_hand):
        if c.name == card.name and c.speed == card.speed:
            player.magic_hand.pop(i)
            break
    if card.type != '场地':
        room.magic_discard.append(card)

    # 场地魔法卡不再在此预置：改由结算（apply_magic_effect 场地分支）实例入区，
    # 避免"打出即进弃牌堆 + 贴场"产生游离副本；被顶掉/被康时实例移入弃牌堆。

    # 统计"打出次数"（被康掉也算打出过，所以记在入链时刻而不是结算时刻）
    record_card_use(card)

    # 添加到连锁栈
    chain_item = ChainItem(player_id, card, targets, time.time())
    room.chain.append(chain_item)

    # 广播连锁更新
    emit('magic_chain_updated', {
        'chain': room.chain
    }, room=room_id)

    # 连锁响应窗口：先给对方；对方放弃后窗口回到最后压栈者（支持自连锁）
    room.chain_passes = 0
    _advance_chain_window(room, opponent_id)

    return {'status': 'success', 'message': f'魔法卡{card.name}已加入连锁'}


# 结束阶段默认禁止使用魔法卡，但以下卡设计上就在结束阶段发动。
# （前端 static/game.js 的 canPlayCard 有一份对应名单，改动需同步。）
END_PHASE_PLAYABLE = ('Freezing！',)


def freezing_block_reason(room, player_id, card):
    """Freezing！ 的专属发动条件；不满足时返回原因，满足返回 None。

    三条缺一不可：自己先手 / 结束阶段 / 本回合没让对方船数减少。
    """
    if room.attack_order and room.attack_order[0] != player_id:
        return 'Freezing！只能在自己先手的回合发动'
    if room.current_phase != 'end':
        return 'Freezing！只能在结束阶段发动'
    if room.players[player_id].damage_dealt_this_turn > 0:
        return '本回合已使对方船数减少，无法发动 Freezing！'
    return None


def can_play_magic_card(room, player_id, card):
    # 绝处逢生：生效回合内自己的其余魔法卡全部无效（last_stand 随回合标志重置自然过期）
    if room.players[player_id].effect_flags.last_stand:
        return False

    # Freezing！ 有专属条件（先手 / 结束阶段 / 未让对方减船），在此一并拦掉，
    # 避免"卡进了连锁、结算时才被拒"这种玩家看不到原因的失败。
    if card.name in END_PHASE_PLAYABLE:
        return freezing_block_reason(room, player_id, card) is None

    # 五险一金：教皇旨意优先级更高，它生效时本回合攻击次数恒为 0，这张牌一次都
    # 触发不了 —— 出牌前就拦掉，别让玩家白扔一张卡（结算时才拒的话卡已经没了）。
    if card.name == '五险一金' and field_magic_name(room) == '教皇旨意':
        return False

    # 确保speed是数字类型
    speed = int(card.speed)

    # 禁忌果实: 双方都无法使用任何魔法卡，除失灵！与其他场地魔法卡
    if field_magic_name(room) == '禁忌果实':
        if card.name != '失灵！' and card.type != '场地':
            return False

    if speed == 3:
        # 速阶3的卡牌可以在任何时候使用
        return True

    # 速阶1和速阶2只能在自己的回合使用
    if room.current_attacker != player_id:
        return False

    # 根据当前阶段和速阶检查
    if room.current_phase == 'preparation':
        # 准备阶段可以使用速阶1和速阶2的卡牌
        return speed in [1, 2]
    elif room.current_phase == 'battle':
        # 战斗阶段可以使用速阶1和速阶2的卡牌
        return speed in [1, 2]
    elif room.current_phase == 'end':
        # 结束阶段默认不能使用魔法卡；
        # 例外：Freezing！ 的设计就是「自己先手回合的结束阶段」发动。
        return card.name in END_PHASE_PLAYABLE
    return False


CHAIN_RESPONSE_SECONDS = 10

# 回合思考计时（秒）：0 = 关闭。此前只有连锁窗口有超时，炮击/准备阶段可以无限
# 长考，对手只能干等。超时只做一次「保底动作」，不判负：
#   准备阶段 → 自动进入战斗阶段；战斗阶段 → 随机开火一发；结束阶段 → 交出回合。
# 每做一次有效操作就重新计时（见 _require_live_room），只惩罚完全卡住不动的人。
TURN_TIMEOUT_SECONDS = int(os.environ.get('TURN_TIMEOUT_SECONDS', '90') or '0')


def _emit_player_ships(room, player_id):
    """只发给本人：同步己方棋盘（放置/原地复活后立刻显示新船）。"""
    player = room.players.get(player_id)
    if not player:
        return
    emit('player_ships_updated', {
        'ships': [{
            'positions': [{'x': p.x, 'y': p.y} for p in sh.positions],
            'hits': [],
            # 冻结状态必须一起下发：冻结的船不提供攻击次数，
            # 玩家此前在棋盘上完全看不出哪几艘被冻住了。
            'frozen': bool(getattr(sh, 'frozen', None)),
        } for sh in player.ships]
    }, to=player.sid)


def _emit_ships_updated(room):
    """按每个收件人自己的视角下发船数。

    原先统一以施法者/攻击者视角 room 广播，导致对手界面上
    "你的船数" 与 "对手船数" 互换。
    """
    for pid, player in room.players.items():
        opp_id = _opponent_of(room, pid)
        opp = room.players.get(opp_id) if opp_id else None
        emit('ships_updated', {
            'player_remaining_ships': player.remaining_ships,
            'opponent_remaining_ships': opp.remaining_ships if opp else 0,
        }, to=player.sid)


# 前端「当前生效效果」角标的数据源。
# 角标以前是前端自己 `innerHTML +=` 挂上去的，挂上就再没人摘 —— 百亿补贴明明
# 每回合切换就被清掉了，角标却一直亮着，玩家以为效果是永久的。
# 现在改成服务端在状态变化后广播真相，前端只负责照着画，不会再出现「贴上就下不来」。
_EFFECT_BADGES = (
    ('subsidy', '百亿补贴'),
    ('wuxian', '五险一金'),
    ('vampire', '饮血'),
    ('treasure_hunter', '八方来财'),
    ('prediction', '神机妙算'),
    ('double_attacks', '火力全开'),
    ('battle_spirit', '越战越勇'),
    ('last_stand', '绝处逢生'),
    ('no_draw', '无中生有'),
)


def _effect_badges(player):
    """返回该玩家当前仍然生效的效果名（用于前端角标）。"""
    flags = getattr(player, 'effect_flags', None)
    if flags is None:
        return []
    return [label for attr, label in _EFFECT_BADGES if getattr(flags, attr, None)]


def _emit_active_effects(room):
    """把「当前生效效果」分别推给本人 —— 角标是给自己看的状态，不广播给对方。"""
    for player in room.players.values():
        if not getattr(player, 'sid', None):
            continue
        emit('active_effects', {'effects': _effect_badges(player)}, to=player.sid)


def _maybe_trigger_wuxian_yijin(room, player_id):
    """五险一金：本回合攻击次数【第一次归零】且那时没让对方减船 → 攻击次数 +3。

    卡面：「这一回合自己的攻击次数第一次用尽时，若自己未曾对对方造成一点伤害，
    则自己的攻击次数再加3」。关键是「什么时候结算」：出牌只是挂上保险
    （effect_flags.wuxian），真正的 +3 要等攻击次数第一次变成 0 才结算 ——
    不是一打出就白送 3 次。触发后立刻清标记，保证只生效一次。

    所有会让攻击次数归零的入口都要调它（攻击结算 / 进入战斗阶段 / 出牌瞬间已经是 0），
    否则会出现「已经 0 次了却永远等不到触发」的漏网情况。

    ⚠️ 教皇旨意优先级更高：它生效时双方攻击次数被压成 0 是**场地规则**，
    不是「你把攻击打光了」，所以这里绝不能给它补次数。

    返回 True 表示这次真的触发了。
    """
    player = room.players.get(player_id)
    if player is None or not getattr(player.effect_flags, 'wuxian', False):
        return False

    # 教皇旨意 > 五险一金：场地规则优先，补次数等于直接掀掉这张场地魔法
    if field_magic_name(room) == '教皇旨意':
        return False

    # 只有「当前攻击者」的攻击次数才是他自己的
    if room.current_attacker != player_id:
        return False
    if room.attacks_remaining > 0:
        return False
    # 这一回合让对方减过船就不给
    if player.damage_dealt_this_turn > 0:
        return False

    player.effect_flags.wuxian = False   # 只触发一次
    room.attacks_remaining += 3

    add_game_log(room, f'第{room.round}回合 · {_log_name(room, player_id)} 触发五险一金，攻击次数 +3',
                 'magic', {'player': player_id, 'card': '五险一金'})
    emit('message', {'text': '五险一金生效：攻击次数已用尽且未造成伤害，攻击次数 +3'},
         to=player.sid)
    emit('attacks_updated', {
        'current_attacker': room.current_attacker,
        'attacks_remaining': room.attacks_remaining
    }, room=room.id)
    # 标记已消耗，角标要跟着消失
    _emit_active_effects(room)
    return True


def _revive_sunken_ships(room, player, count):
    """把 count 艘已沉没的战舰放回棋盘（神机妙算 / 复活类效果）。

    关键：必须清空 hits 并把原位置从双方攻击历史里移除。
    否则 hits 已等于 positions（船已沉），且这些格子谁都"已经打过"，
    该船将永远无法被击沉 → remaining_ships 永远 > 0 → 对手永远无法获胜。
    """
    revived_any = 0
    for _ in range(min(int(count), len(player.sunken_ships))):
        revived = player.sunken_ships.pop()
        if revived not in player.ships:
            player.ships.append(revived)
        # 注意：被击沉的船通常仍留在 ships 列表里，所以清空命中要无条件执行
        revived.hits = []
        for pos in revived.positions:
            pos.hit = False
        cells = {(p.x, p.y) for p in revived.positions}
        for pid in room.players:
            room.players[pid].attacks = [
                a for a in room.players[pid].attacks if (a.x, a.y) not in cells
            ]
        player.remaining_ships += 1
        revived_any += 1
    return revived_any


def _opponent_of(room, player_id):
    """返回房间内另一名玩家的 id；找不到则 None。"""
    for pid in room.players:
        if pid != player_id:
            return pid
    return None


def _speed3_cards(room, player_id):
    player = room.players.get(player_id)
    if not player:
        return []
    return [c for c in player.magic_hand if int(c.speed) == 3]


def _ai_can_negate_chain_top(room, ai_id: str) -> bool:
    """困难难度下，AI 只在「康得动」时才开窗：不能康自己打的牌，
    也不能康看破！/加百列之光（这两条是卡面写明的规则，硬康只会被服务端拒绝、
    白白把窗口拖到超时）。"""
    if not room.chain:
        return False
    top = room.chain[-1]
    if getattr(top, 'player_id', None) == ai_id:
        return False
    return getattr(getattr(top, 'card', None), 'name', None) not in ('看破！', '加百列之光')


def _can_respond_chain(room, player_id):
    """该玩家此刻能否打出速阶3响应连锁。

    AI 默认不参与；只有「困难」难度、手里有【失灵！】、且当前连锁康得动时才参与。
    """
    if not player_id:
        return False
    player = room.players.get(player_id)
    if not player or player.magic_blocked:
        return False
    if player_id.startswith('ai-'):
        if getattr(room, 'ai_difficulty', 'normal') != 'hard':
            return False
        if not any(c.name == '失灵！' for c in player.magic_hand):
            return False
        return _ai_can_negate_chain_top(room, player_id)
    return bool(_speed3_cards(room, player_id))


def _advance_chain_window(room, player_id):
    """把响应窗口交给 player_id；无法响应者自动记为放弃并顺延。
    连续两次放弃（含自动放弃）后结算连锁。"""
    while True:
        if not player_id or player_id not in room.players:
            return resolve_chain(room)
        if _can_respond_chain(room, player_id):
            room.chain_window = player_id
            room.chain_waiting = True
            room.chain_timer += 1
            emit('chain_request', {
                'card': room.chain[-1].card,
                # 告诉客户端这张卡是谁打的：响应窗口会绕回最后压栈者自己
                # （自连锁），此时前端不能再写「对方发动了」。
                'caster': room.chain[-1].player_id,
                'speed3_cards': _speed3_cards(room, player_id),
                'countdown': CHAIN_RESPONSE_SECONDS,
            }, to=room.players[player_id].sid)
            _schedule_chain_timeout(room.id, room.chain_timer)
            if player_id.startswith('ai-'):
                # 窗口落在 AI 头上：让它自己响应，别干等到超时
                socketio.start_background_task(_ai_chain_respond, room.id, room.chain_timer)
            return
        # 无法响应：视为放弃
        room.chain_passes += 1
        if room.chain_passes >= 2:
            return resolve_chain(room)
        player_id = _opponent_of(room, player_id)


def resolve_chain(room):
    """结算连锁：栈顶先出（后发先至）。被无效化的项跳过效果。"""
    results = []

    while room.chain:
        chain_item = room.chain.pop()
        player_id = chain_item.player_id
        card = chain_item.card
        targets = chain_item.targets

        # 已被上方某张无效化卡标记：跳过其效果
        if chain_item.negated:
            result = ChainResult(card=card, caster=player_id, success=False,
                                 message=f'{card.name}被无效化')
            result.negated_skip = True
            log_magic(room, player_id, card, '但被无效化')
            # 被无效化的场地卡：只进弃牌堆，绝不能顶掉/拆掉场上已有的场地。
            # （原实现用 _place_field_magic "贴了再拆"，会把场上另一张场地
            #   连带扫进弃牌堆 —— 一次无效化同时干掉两张场地。）
            if getattr(card, 'type', None) == '场地':
                if room.field_magic is not card:
                    room.magic_discard.append(card)
            results.append(result)
            continue

        # 应用卡牌效果
        result = apply_magic_effect(room, player_id, card, targets)
        result.caster = player_id
        log_magic(room, player_id, card, result.message if getattr(result, 'success', False) else '')

        # 无效化类效果：把“正下方那一项”（下一个待结算项）标记为无效
        if getattr(result, 'negate_target', False) and room.chain:
            room.chain[-1].negated = True

        results.append(result)
        # 记录魔法使用历史（盗亦有道等读取）
        if result.success:
            room.magic_history.append({'card': card, 'caster': player_id,
                                       'timestamp': time.time(), 'round': room.round})

    # 广播连锁结算结果
    emit('chain_resolved', {
        'results': results
    }, room=room.id)

    # 重置连锁状态
    room.chain = []
    room.chain_waiting = False
    room.chain_window = None
    room.chain_passes = 0

    # 这一批卡的效果刚落地，双方的 effect_flags 可能变了 —— 刷新角标
    _emit_active_effects(room)

    return results


def _ai_chain_respond(room_id: str, token: int):
    """困难难度：AI 在连锁响应窗口里用【失灵！】康掉对方的卡。

    响应不了（没牌 / 康不动）时明确放弃，避免把窗口拖到 10 秒超时。
    代际令牌保证过期窗口不会被旧任务误响应。
    """
    try:
        time.sleep(0.8)
        room = room_manager.get_room(room_id)
        if not room or room.state == 'game_over':
            return
        if not room.chain_waiting or room.chain_timer != token:
            return
        ai_id = room.chain_window
        if not ai_id or not ai_id.startswith('ai-'):
            return
        player = room.players.get(ai_id)
        if not player:
            return

        card = next((c for c in player.magic_hand if c.name == '失灵！'), None)
        if card is None or not _ai_can_negate_chain_top(room, ai_id):
            chain_response({'room_id': room_id, 'player_id': ai_id, 'chain': False})
            return

        resp = chain_response({
            'room_id': room_id,
            'player_id': ai_id,
            'chain': True,
            'card': {'name': card.name, 'speed': card.speed, 'type': card.type},
            'targets': [],
        })
        if not (resp and resp.get('status') == 'success'):
            # 万一被规则拒绝（例如窗口已过期），明确放弃而不是留个半开窗口
            chain_response({'room_id': room_id, 'player_id': ai_id, 'chain': False})
    except Exception as e:
        print(f'AI chain respond error: {e}')


def _schedule_chain_timeout(room_id: str, token: int):
    """连锁超时兜底：窗口玩家长时间未响应时视为放弃并顺延/结算。
    代际令牌使旧定时器自动作废，防止与玩家正常响应竞态双重结算。"""
    def _timeout():
        time.sleep(CHAIN_RESPONSE_SECONDS)
        room = room_manager.get_room(room_id)
        if room and room.chain_waiting and room.chain_timer == token:
            window_player = room.chain_window
            room.chain_waiting = False
            room.chain_window = None
            room.chain_passes += 1
            if room.chain_passes >= 2 or window_player is None:
                resolve_chain(room)
            else:
                _advance_chain_window(room, _opponent_of(room, window_player))
    socketio.start_background_task(_timeout)


# ============ 掉线宽限 / 重连 / 超时判负（2026-09-07 新增） ============
DISCONNECT_GRACE_SECONDS = 30


def _start_disconnect_grace(room_id: str, player_id: str):
    """玩家掉线：启动 30s 重连窗口并通知对手。由后台任务调用（避免在
    disconnect 处理器内同步 emit 导致 eventlet hub 卡死）。"""
    time.sleep(0.2)  # 让 disconnect 收尾完成
    room = room_manager.get_room(room_id)
    if not room or room.state == 'game_over' or player_id in room.disconnected:
        return
    room.disconnect_seq += 1
    deadline = time.time() + DISCONNECT_GRACE_SECONDS
    room.disconnected[player_id] = {'deadline': deadline, 'token': room.disconnect_seq}
    for pid, p in list(room.players.items()):
        if pid != player_id:
            emit('opponent_disconnected', {
                'player_id': player_id,
                'seconds': DISCONNECT_GRACE_SECONDS,
                'deadline': deadline,
            }, to=p.sid)
    socketio.start_background_task(_disconnect_timeout, room_id, player_id, room.disconnect_seq)


def _disconnect_timeout(room_id: str, player_id: str, token: int):
    """掉线宽限到期结算：未重连则按房间阶段决定取消对局或判对手胜利。"""
    time.sleep(DISCONNECT_GRACE_SECONDS)
    room = room_manager.get_room(room_id)
    if not room:
        return
    entry = room.disconnected.get(player_id)
    if not entry or entry.get('token') != token:
        return  # 已重连或已由其它路径处理
    room.disconnected.pop(player_id, None)

    other = next((p for p in room.players if p != player_id), None)
    ai_room = getattr(room, 'is_ai_room', False)
    pre_battle = room.state in ('placing_ships', 'rock_paper_scissors')

    if ai_room or pre_battle or other is None or other in room.disconnected or room.state == 'game_over':
        # 人机房 / 未开战 / 双方都不在场：取消对局，不计战绩
        emit('game_canceled', {
            'reason': 'opponent_disconnected',
            'message': '对局已取消（对手掉线）',
        }, room=room_id)
        room_manager.delete_room(room_id)
        return

    # 正式对局：在场方判胜，正常计入战绩（无特殊标签）
    room.state = 'game_over'
    room.winner = other
    room.game_over_reason = 'opponent_disconnected'
    try:
        winner_user_id = room.players[other].user_id
        loser_user_id = room.players[player_id].user_id
        if winner_user_id or loser_user_id:
            db.record_match(winner_user_id or other, loser_user_id or player_id,
                            getattr(room, 'game_logs', None), count_stats=_count_stats_for(room))
    except Exception:
        pass
    emit('game_over', {'winner': other, 'reason': 'opponent_disconnected'}, room=room_id)
    # 房间保留约 2 分钟：让掉线者重连时收到一次性警告
    socketio.start_background_task(_cleanup_ended_room, room_id, 120)


def _cleanup_ended_room(room_id: str, delay: float):
    time.sleep(delay)
    room_manager.delete_room(room_id)


# 已结束房间的回收：所有自然胜负/投降路径都会把 state 置为 game_over，
# 但并非每条路径都显式调度清理，因此用一个后台任务统一兜底，
# 避免 rooms 字典只增不减导致内存泄漏。
_ROOM_GRACE_SECONDS = 120
# 建房后一直没人入座（含人机房只坐了 AI）的房间：此前只回收 game_over 房，
# 这类房间会永久驻留 —— 每误点一次「创建房间/人机对战」就泄漏一个 GameRoom
# （含整副牌堆实例）。超过 TTL 直接回收。
_WAITING_ROOM_TTL = 3600
_reaper_started = False


def _reap_ended_rooms(now: float = None):
    """扫描并回收已结束且超过宽限期的房间（供后台任务与单测调用）。"""
    now = time.time() if now is None else now
    reaped = []
    for room_id, room in list(room_manager.get_all_rooms().items()):
        state = getattr(room, 'state', None)
        if state == 'waiting':
            created = getattr(room, 'created_at', None)
            if created is not None and now - created > _WAITING_ROOM_TTL:
                room_manager.delete_room(room_id)
                reaped.append(room_id)
            continue
        if state != 'game_over':
            room._game_over_since = None
            continue
        ended = getattr(room, '_game_over_since', None)
        if ended is None:
            # 首次观察到该房间已结束，开始计时
            room._game_over_since = now
            continue
        if now - ended > _ROOM_GRACE_SECONDS:
            room_manager.delete_room(room_id)
            reaped.append(room_id)
    return reaped


def _auto_act_on_timeouts(now: float = None):
    """对思考超时的真人玩家执行一次保底动作；返回被处理的房间 id 列表。

    做成"扫描式看门狗"而不是每人一个定时器：对局中的状态变化（换人、进阶段、
    开连锁、等待点选）太多，逐个排定时器容易漏排或重复触发。
    """
    if TURN_TIMEOUT_SECONDS <= 0:
        return []
    now = time.time() if now is None else now
    acted = []
    for room in list(room_manager.get_all_rooms().values()):
        if getattr(room, 'state', None) != 'attacking':
            continue
        if getattr(room, 'is_ai_room', False):
            continue                      # AI 自己会走完回合
        pid = room.current_attacker
        if not pid or pid not in room.players:
            continue
        # 换人/刚开局 → 重新计时
        if getattr(room, '_timer_attacker', None) != pid:
            room._timer_attacker = pid
            room.turn_started_at = now
            continue
        if now - getattr(room, 'turn_started_at', now) < TURN_TIMEOUT_SECONDS:
            continue
        # 这些状态下不该催：连锁有它自己的 10 秒窗口；等待点选是玩家正在操作
        if room.chain or room.chain_waiting:
            continue
        if getattr(room, 'disconnected', None):
            continue                      # 有人掉线宽限中
        temp = room.magic_temp_data or {}
        if temp.get('pending_placement') or temp.get('pending_sacrifice') or temp.get('pending_shenji'):
            continue

        try:
            if room.current_phase == 'preparation':
                enter_battle_phase({'room_id': room.id, 'player_id': pid})
                note = '思考超时：已自动进入战斗阶段'
            elif room.current_phase == 'battle':
                attacked = {(a.x, a.y) for a in room.players[pid].attacks}
                candidates = [(x, y) for x in range(6) for y in range(6)
                              if (x, y) not in attacked]
                if not candidates or room.attacks_remaining <= 0:
                    handle_enter_end_phase({'room_id': room.id, 'player_id': pid})
                    note = '思考超时：已自动进入结束阶段'
                else:
                    x, y = random.choice(candidates)
                    handle_attack({'room_id': room.id, 'player_id': pid, 'x': x, 'y': y})
                    note = f'思考超时：已自动开火 ({x},{y})'
            elif room.current_phase == 'end':
                end_turn({'room_id': room.id, 'player_id': pid})
                note = '思考超时：已自动交出回合'
            else:
                continue
        except Exception as e:
            print(f'Turn timeout auto-action error: {e}')
            room.turn_started_at = now
            continue

        emit('message', {'text': note}, to=room.players[pid].sid)
        emit('game_message', {'message': note, 'type': 'warning'}, room=room.id)
        room.turn_started_at = now
        acted.append(room.id)
    return acted


_TURN_TIMER_STARTED = False


def _turn_timer_loop():
    """后台看门狗：每 5 秒检查一次是否有人思考超时。"""
    while True:
        time.sleep(5)
        try:
            _auto_act_on_timeouts()
        except Exception:
            # 单个房间异常不应中断整个看门狗
            pass


def _ensure_turn_timer():
    global _TURN_TIMER_STARTED
    if _TURN_TIMER_STARTED or TURN_TIMEOUT_SECONDS <= 0:
        return
    _TURN_TIMER_STARTED = True
    socketio.start_background_task(_turn_timer_loop)


def _room_reaper():
    """后台清理任务：定期回收已结束且超过宽限期的房间。"""
    while True:
        time.sleep(30)
        try:
            _reap_ended_rooms()
        except Exception:
            # 单个房间异常不应中断回收任务
            pass


def _ensure_reaper():
    """惰性启动回收任务（只启动一次），避免在 import 期产生后台任务。"""
    global _reaper_started
    if _reaper_started:
        return
    _reaper_started = True
    socketio.start_background_task(_room_reaper)


def _frozen_reason(room, player_id: str):
    """对方处于掉线宽限期时返回拒绝文案；否则返回 None（可继续行动）。"""
    for pid in room.disconnected:
        if pid != player_id:
            return '对手已掉线，等待重连中'
    return None


def _issue_reconnect_token(room, player_id: str) -> str:
    tok = secrets.token_hex(16)
    room.reconnect_tokens[player_id] = tok
    return tok


def _build_room_sync(room, player_id: str) -> dict:
    """重连后下发整局快照，供前端重建界面。"""
    p = room.players[player_id]
    opp = next((room.players[o] for o in room.players if o != player_id), None)
    return {
        'room_id': room.id,
        'state': room.state,
        'current_phase': getattr(room, 'current_phase', None),
        'current_attacker': room.current_attacker,
        'attacks_remaining': room.attacks_remaining,
        'round': room.round,
        'attack_order': room.attack_order,
        'player_id': player_id,
        'player_name': p.name,
        'opponent_name': opp.name if opp else None,
        'is_ai_room': getattr(room, 'is_ai_room', False),
        'winner': room.winner,
        'game_over_reason': getattr(room, 'game_over_reason', None),
        'field_magic': (room.field_magic.name if hasattr(room.field_magic, 'name') else room.field_magic) or "",
        'remaining_ships': p.remaining_ships,
        'ships': [{'positions': [{'x': pos.x, 'y': pos.y} for pos in sh.positions],
                   'frozen': bool(getattr(sh, 'frozen', None))} for sh in p.ships],
        'hand': [{'name': c.name, 'speed': c.speed, 'type': c.type, 'description': c.description} for c in p.magic_hand],
        'attacks': [{'x': a.x, 'y': a.y, 'hit': a.hit} for a in getattr(p, 'attacks', [])],
        # 对手打在我方棋盘上的格：前端自己棋盘的伤损/沉船只认这份数据，
        # 此前快照不带它，重连后自己棋盘上被打过的格子会全部「复原」。
        'opponent_attacks': [
            {'x': a.x, 'y': a.y, 'hit': a.hit}
            for a in (getattr(opp, 'attacks', []) if opp else [])
        ],
        'opponent_remaining_ships': opp.remaining_ships if opp else 0,
        'shenwei_holes': list(room.game_effects.get('shenwei_holes') or []),
        # 连锁窗口：重连后能看到当前连锁栈与响应窗口，避免缺上下文无法操作
        'chain': [
            {
                'card': ({
                    'name': it.card.name, 'speed': it.card.speed,
                    'type': it.card.type, 'description': it.card.description,
                } if getattr(it, 'card', None) else None),
                'caster': getattr(it, 'player_id', None),
                'negated': getattr(it, 'negated', False),
            }
            for it in getattr(room, 'chain', [])
        ],
        'chain_waiting': getattr(room, 'chain_waiting', False),
        'chain_window': getattr(room, 'chain_window', None),
        # 生效中的房间级效果（仅名称，避免下发复杂对象）
        'active_effects': sorted(room.game_effects.keys()) if isinstance(room.game_effects, dict) else [],
        # 复活/增援放置中途：仅下发给正在放置的玩家
        'pending_placement': (
            room.magic_temp_data.get('pending_placement')
            if isinstance(room.magic_temp_data, dict)
            and (room.magic_temp_data.get('pending_placement') or {}).get('caster') == player_id
            else None
        ),
        'pending_placement_blocked': (
            _placement_blocked_cells(room, player_id)
            if isinstance(room.magic_temp_data, dict)
            and (room.magic_temp_data.get('pending_placement') or {}).get('caster') == player_id
            else []
        ),
        # 绝处逢生的合法格（只允许放在原本有战舰的位置）
        'pending_placement_allowed': (
            room.game_effects.get('last_stand_cells') or []
            if isinstance(room.magic_temp_data, dict)
            and (room.magic_temp_data.get('pending_placement') or {}).get('caster') == player_id
            else []
        ),
        # 玩家级状态标记：重连后 UI 需要知道"被看破 / 无中生有 / 余音绕梁"等
        'magic_blocked': bool(getattr(p, 'magic_blocked', False)),
        'effect_flags': {k: v for k, v in vars(p.effect_flags).items() if v},
        # 待自己点选的战舰（恶魔契约 / 神之宣告 / 克苏鲁之眼）
        'pending_sacrifice': (
            room.magic_temp_data.get('pending_sacrifice')
            if isinstance(room.magic_temp_data, dict)
            and (room.magic_temp_data.get('pending_sacrifice') or {}).get('player') == player_id
            else None
        ),
        'pending_sacrifice_ships': (
            [{'positions': [{'x': q.x, 'y': q.y} for q in sh.positions]} for sh in p.ships]
            if isinstance(room.magic_temp_data, dict)
            and (room.magic_temp_data.get('pending_sacrifice') or {}).get('player') == player_id
            else []
        ),
        # 猜拳阶段：重连后需要知道该出拳
        'rps_choices': dict(room.rps_choices) if room.state == 'rock_paper_scissors' else {},
    }


@socketio.on('get_reconnect_token')
def handle_get_reconnect_token(data):
    room = room_manager.get_room(data.get('room_id'))
    pid = data.get('player_id')
    if not room or pid not in room.players or not _identity_ok(room, pid):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    return {'status': 'success', 'token': _issue_reconnect_token(room, pid)}


@socketio.on('rejoin_room')
def handle_rejoin_room(data):
    """掉线重连：校验 token/会话身份后重绑 sid，取消宽限并下发整局快照。"""
    room_id = data.get('room_id')
    pid = data.get('player_id')
    token = data.get('token')
    room = room_manager.get_room(room_id)
    if not room or pid not in room.players:
        return {'status': 'error', 'message': '房间不存在'}
    # 令牌必须真实发放且非空：None == None 曾导致无凭据重绑座位（座位劫持）
    stored_token = room.reconnect_tokens.get(pid)
    ok = bool(stored_token) and bool(token) and secrets.compare_digest(str(stored_token), str(token))
    if not ok:
        try:
            ok = bool(session.get('user_id') == pid)
        except Exception:
            ok = False
    if not ok:
        return {'status': 'error', 'message': '身份校验失败'}

    if room.state == 'game_over':
        # 掉线超时结束：给败方一次警告，房间稍后清理
        if room.game_over_reason == 'opponent_disconnected' and room.winner != pid:
            emit('reconnect_warning', {'message': '对局已因你掉线超时结束，请勿中途掉线'}, to=request.sid)
            socketio.start_background_task(_cleanup_ended_room, room_id, 3)
        else:
            emit('error', {'message': '对局已结束'}, to=request.sid)
        return {'status': 'success'}

    room.players[pid].sid = request.sid
    join_room(room_id, request.sid)
    was_reconnect = pid in room.disconnected
    if was_reconnect:
        room.disconnected.pop(pid, None)
    for opid, op in room.players.items():
        if opid != pid:
            emit('opponent_reconnected', {'player_id': pid}, to=op.sid)
    if was_reconnect:
        emit('room_sync', _build_room_sync(room, pid), to=request.sid)
    return {'status': 'success', 'reconnected': was_reconnect}


def _apply_shenji_prediction(room, caster_id, x, result=None):
    """神机妙算宣言落效：记录预测值并保存船数快照。"""
    player = room.players[caster_id]
    player.effect_flags = player.effect_flags
    player.effect_flags.prediction = x
    room.game_effects[f'prediction_initial_{caster_id}'] = {
        'ships': player.remaining_ships,
        'sunken': len(getattr(player, 'sunken_ships', []) or []),
    }
    room.magic_temp_data.pop('prediction', None)
    room.magic_temp_data.pop('pending_shenji', None)
    if result is not None:
        result.message = f'宣言船数减少{x}，若预测成功则不会减少'


@socketio.on('confirm_shenji_declare')
@_require_live_room
def handle_confirm_shenji_declare(data):
    """神机妙算宣言确认：写入预测值并生效。"""
    room_id = data.get('room_id')
    pid = data.get('player_id')
    room = room_manager.get_room(room_id)
    if not room or pid not in room.players or not _identity_ok(room, pid):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    pending = room.magic_temp_data.get('pending_shenji')
    if not pending or pending.get('caster') != pid:
        return {'status': 'error', 'message': '没有待宣言的神机妙算'}
    try:
        x = max(0, min(6, int(data.get('prediction', 0))))
    except Exception:
        return {'status': 'error', 'message': '宣言数值无效'}
    _apply_shenji_prediction(room, pid, x)
    for opid, op in room.players.items():
        if opid != pid:
            emit('message', {'text': f'对方宣言神机妙算：船数减少{x}时生效'}, to=op.sid)
    return {'status': 'success', 'message': f'已宣言：船数减少{x}时不减少'}


def _recalc_attacker_attacks(room):
    """按当前攻击者在准备阶段结算攻击次数：伊甸园生效时 = 6-自身船数；否则按剩余船数-冻结。"""
    pid = room.current_attacker
    if not pid or pid not in room.players:
        return
    # 百亿补贴累计的额外次数（属于持卡者自己，跨回合保留）
    bonus = int(getattr(room.players[pid].effect_flags, 'subsidy_bonus', 0) or 0)
    if field_magic_name(room) == '教皇旨意':
        room.attacks_remaining = 0
    elif field_magic_name(room) == '伊甸园':
        room.attacks_remaining = max(0, 6 - room.players[pid].remaining_ships) + bonus
    else:
        # 用 remaining_ships：ships 列表含已沉没的战舰，不能直接取长度
        room.attacks_remaining = max(
            0, room.players[pid].remaining_ships - frozen_ship_count(room.players[pid])) + bonus


# 添加处理连锁响应
@socketio.on('chain_response')
@_require_live_room
def chain_response(data):
    room_id = data['room_id']
    player_id = data['player_id']
    chain = data.get('chain', False)
    card = data.get('card')
    targets = data.get('targets', [])

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    targets, target_err = _sanitize_magic_targets(targets)
    if target_err:
        return {'status': 'error', 'message': target_err}

    if not room.chain_waiting:
        return {'status': 'error', 'message': '没有待处理的连锁请求'}

    # 只有当前响应窗口的玩家可以响应
    if room.chain_window and room.chain_window != player_id:
        return {'status': 'error', 'message': '当前不是你的连锁响应窗口'}

    # 关闭当前窗口
    room.chain_waiting = False
    room.chain_window = None

    if chain and card:
        try:
            card = MagicCard(**card)
        except (ValueError, TypeError, KeyError) as e:
            return {'status': 'error', 'message': f'魔法卡数据无效: {e}'}
        player = room.players[player_id]
        # 防御：被看破者不能连锁（正常流程不会进入）
        if player.magic_blocked:
            room.chain_passes += 1
            if room.chain_passes >= 2:
                resolve_chain(room)
            else:
                _advance_chain_window(room, _opponent_of(room, player_id))
            return {'status': 'error', 'message': '你的魔法卡已被看破，无法连锁'}

        # 卡牌在手且为速阶3
        # 安全：改用服务端手牌里的真实实例，忽略客户端伪造的 speed/type，
        # 同时避免为同一张卡 new 出第二个实例（会导致抽到重名卡时崩溃）。
        hand_card = next((c for c in player.magic_hand
                          if c.name == card.name and c.speed == card.speed), None)
        if hand_card is None:
            return {'status': 'error', 'message': '你没有这张魔法卡'}
        card = hand_card
        if int(card.speed) != 3:
            return {'status': 'error', 'message': '只能使用速阶3的卡牌进行连锁'}

        # 与主动出牌一致地校验使用限制（禁忌果实 / 绝处逢生）。
        # 原先连锁路径完全跳过 can_play_magic_card，可绕过上述封锁；
        # 校验不通过按"放弃"处理，避免连锁窗口卡死。
        if not can_play_magic_card(room, player_id, card):
            room.chain_passes += 1
            if room.chain_passes >= 2:
                resolve_chain(room)
            else:
                _advance_chain_window(room, _opponent_of(room, player_id))
            return {'status': 'error', 'message': '当前无法使用这张魔法卡'}

        # 从手牌移除并进弃牌堆
        for i, c in enumerate(player.magic_hand):
            if c.name == card.name and c.speed == card.speed:
                player.magic_hand.pop(i)
                break
        room.magic_discard.append(card)

        room.chain.append(ChainItem(player_id, card, targets, time.time()))
        emit('magic_chain_updated', {'chain': room.chain}, room=room_id)

        # 打出新牌：放弃计数清零，窗口交给对方（对方放弃后回到自己，支持自连锁）
        room.chain_passes = 0
        _advance_chain_window(room, _opponent_of(room, player_id))
        return {'status': 'success', 'message': f'魔法卡{card.name}已加入连锁'}
    else:
        # 放弃：连续两次放弃即结算
        room.chain_passes += 1
        if room.chain_passes >= 2:
            resolve_chain(room)
        else:
            _advance_chain_window(room, _opponent_of(room, player_id))
        return {'status': 'success', 'message': '放弃连锁'}


@socketio.on('remove_field_magic')
@_require_live_room
def handle_remove_field_magic(data):
    room_id = data['room_id']
    player_id = data['player_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    if room and player_id in room.players:
        # 只能拆自己的场地（原先任意客户端可随时拆掉对手的场地）
        owner = getattr(room, 'field_magic_owner', None)
        if room.field_magic and owner is not None and owner != player_id:
            return {'status': 'error', 'message': '只能移除自己的场地魔法'}
        # 将场地魔法加入弃牌堆并清除场地（旧卡不在手牌，不能用 discard_card）
        if room.field_magic:
            room.magic_discard.append(room.field_magic)
            _clear_field_magic_effects(room)
            room.field_magic = None
            room.field_magic_owner = None
        # 广播场地魔法更新
        emit('field_magic_updated', {
            'player_id': player_id,
            'card': None
        }, room=room_id)

    return {'status': 'success'}


@socketio.on('confirm_reinforcement_position')
@_require_live_room
def handle_confirm_reinforcement(data):
    """确认放置一艘（增援/复活）战舰。"""
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    position = data.get('position') or {}
    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    pending = room.magic_temp_data.get('pending_placement') if room.magic_temp_data else None
    if not pending or pending.get('caster') != player_id:
        return {'status': 'error', 'message': '没有等待放置的战舰'}

    x, y = position.get('x'), position.get('y')
    if x is None or y is None:
        return {'status': 'error', 'message': '请选择放置位置'}
    try:
        x, y = int(x), int(y)
    except (TypeError, ValueError):
        return {'status': 'error', 'message': '请选择放置位置'}

    if pending['kind'] == 'last_stand':
        # 绝处逢生：只能放在"原本有自己战舰"的格子上（这些格子对方多半打过，
        # 因此不走 _placement_error 的"未被对方打过"规则）
        allowed = {(int(a[0]), int(a[1]))
                   for a in (room.game_effects.get('last_stand_cells') or [])}
        if (x, y) not in allowed:
            return {'status': 'error', 'message': '只能放在原本有自己战舰的格子上'}
    else:
        err = _placement_error(room, player_id, x, y)
        if err:
            return {'status': 'error', 'message': err}

    caster = room.players[player_id]
    if pending['kind'] == 'revive':
        if not caster.sunken_ships:
            _finish_placement(room, player_id, 'revive')
            return {'status': 'error', 'message': '没有可复活的战舰'}
        revived = caster.sunken_ships.pop()
        # 关键修复：清空命中并移到新位置，否则复活后打不沉（幽灵船）
        revived.positions = [Position(x=x, y=y)]
        revived.hits = []
        revived.shield = False
        revived.invincible = False
        caster.ships.append(revived)
        caster.remaining_ships += 1
        msg = f'复活战舰已部署到 ({x},{y})'
    elif pending['kind'] == 'last_stand':
        # 绝处逢生的"唯一一艘战舰"：牺牲掉的船留在沉船堆，这里放一艘新的
        caster.ships.append(PlayerShip(positions=[Position(x=x, y=y)], hits=[]))
        caster.remaining_ships += 1
        msg = f'绝处逢生：唯一一艘战舰已部署到 ({x},{y})'
    else:
        caster.ships.append(PlayerShip(positions=[Position(x=x, y=y)], hits=[]))
        caster.remaining_ships += 1
        msg = f'增援战舰已部署到 ({x},{y})'

    pending['remaining'] -= 1
    pending['placed'] += 1

    opponent_id = _opponent_of(room, player_id)
    _emit_ships_updated(room)
    # 同步放置后的己方棋盘（只发给本人），让新船立刻显示
    _emit_player_ships(room, player_id)
    emit('message', {'text': msg}, to=room.players[player_id].sid)

    if pending['remaining'] > 0:
        _emit_placement_request(room, player_id)
    else:
        _finish_placement(room, player_id, pending['kind'])
    return {'status': 'success', 'message': msg}


@socketio.on('confirm_sacrifice')
@_require_live_room
def handle_confirm_sacrifice(data):
    """恶魔契约：玩家在自己的棋盘上点选要牺牲的战舰。"""
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    position = data.get('position') or {}
    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    pending = room.magic_temp_data.get('pending_sacrifice') if room.magic_temp_data else None
    if not pending or pending.get('player') != player_id:
        return {'status': 'error', 'message': '当前没有待牺牲的战舰'}
    reason = pending.get('reason') or 'demon_contract'

    try:
        cell = (int(position.get('x')), int(position.get('y')))
    except (TypeError, ValueError):
        return {'status': 'error', 'message': '请选择一艘自己的战舰'}

    ship = _find_ship_at(room.players[player_id], cell)
    if ship is None:
        return {'status': 'error', 'message': '必须选择自己战舰所在的格子'}

    if reason == 'kraken_eye':
        # 克苏鲁之眼：只把位置暴露给对方，不摧毁这艘船
        if room.magic_temp_data:
            room.magic_temp_data.pop('pending_sacrifice', None)
        other_id = _opponent_of(room, player_id)
        positions = ship.positions
        if other_id and other_id in room.players:
            room.players[other_id].revealed_positions.extend(positions)
            emit('revealed_positions', {'positions': positions}, to=room.players[other_id].sid)
        return {'status': 'success', 'message': '已暴露一艘战舰的位置'}

    _do_demon_contract_sacrifice(room, player_id, ship, reason)
    return {'status': 'success', 'message': '已选择一艘战舰'}


@socketio.on('cancel_placement')
@_require_live_room
def handle_cancel_placement(data):
    """放弃剩余放置（防止无空格时卡死）。已放置的保留，未放置的作废。"""
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    pending = room.magic_temp_data.get('pending_placement') if room.magic_temp_data else None
    if not pending or pending.get('caster') != player_id:
        return {'status': 'error', 'message': '没有等待放置的战舰'}

    if pending['kind'] == 'last_stand':
        # 绝处逢生放弃放置会把玩家变成"0 艘船"无法继续，改为替其随机落一格
        cells = room.game_effects.get('last_stand_cells') or []
        if cells:
            cell = random.choice(cells)
            handle_confirm_reinforcement({'room_id': room_id, 'player_id': player_id,
                                          'position': {'x': cell[0], 'y': cell[1]}})
            return {'status': 'success', 'message': '已随机放置唯一一艘战舰'}

    _finish_placement(room, player_id, pending['kind'])
    emit('message', {'text': '已放弃剩余放置'}, to=room.players[player_id].sid)
    return {'status': 'success'}


@socketio.on('request_revealed_positions')
def handle_request_revealed_positions(data):
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    positions = room.players[player_id].revealed_positions
    # 只发送给请求者
    emit('revealed_positions', {'positions': positions}, to=room.players[player_id].sid)
    return {'status': 'success'}


@socketio.on('get_magic_temp_data')
def get_magic_temp_data(data):
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 只下发「等待你自己处理」的临时数据。此前对任何房内玩家原样 emit，
    # 对手只要手动 emit 一次就能读到桃园结义抽出的候选牌 ——
    # 而那张卡面明确写着「对方不可见被抽出来的所有 n 张牌」。
    temp = room.magic_temp_data or {}
    owners = {
        temp.get('caster'),
        temp.get('caster_id'),
        (temp.get('pending_placement') or {}).get('caster'),
        (temp.get('pending_sacrifice') or {}).get('player'),
        (temp.get('pending_shenji') or {}).get('caster'),
    }
    if player_id not in owners:
        return {'status': 'error', 'message': '没有等待你处理的魔法卡选择'}
    return {'status': 'success', 'data': temp}


@socketio.on('confirm_magic_target')
@_require_live_room
def confirm_magic_target(data):
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    temp_data_id = data.get('temp_data_id')
    target_data = data.get('target_data', {})

    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    if temp_data_id == 'taoyuan_choice':
        # 处理桃园结义的选择
        caster_choice = target_data['caster_choice']

        # 分配卡牌
        caster = room.players[player_id]
        opponent_id = next(p for p in room.players if p != player_id)
        opponent = room.players[opponent_id]

        if 'cards' not in room.magic_temp_data:
            return {'status': 'error', 'message': '没有可分配的卡牌'}

        cards = room.magic_temp_data['cards']

        # 确保选择有效
        if 0 <= caster_choice < len(cards):
            # 给自己分配卡牌
            caster.magic_hand.append(cards[caster_choice])

            # 给对方分配卡牌（如果有剩余卡牌）
            opponent_choice = -1
            if len(cards) > 1:
                # 优先采用对方自己挑的那张（前端 showTaoyuanChoice 会把
                # opponent_choice 一起回传）。此前这里忽略该字段、固定取
                # 「第一张不是施法者选的」，导致卡面上「对方再选 1 张」
                # 这一步形同虚设。
                requested = -1
                if isinstance(target_data, dict):
                    try:
                        requested = int(target_data.get('opponent_choice', -1))
                    except (TypeError, ValueError):
                        requested = -1
                if 0 <= requested < len(cards) and requested != caster_choice:
                    opponent_choice = requested
                else:
                    for i in range(len(cards)):
                        if i != caster_choice:
                            opponent_choice = i
                            break

                if 0 <= opponent_choice < len(cards):
                    opponent.magic_hand.append(cards[opponent_choice])

            # 剩余卡牌放回牌堆
            remaining_cards = []
            for i, card in enumerate(cards):
                if i != caster_choice and i != opponent_choice:
                    remaining_cards.append(card)

            room.magic_deck += remaining_cards

            # 清除临时数据
            room.magic_temp_data = {}

            # 通知双方手牌更新
            emit('hand_updated', {
                'hand': caster.magic_hand
            }, to=room.players[player_id].sid)

            emit('hand_updated', {
                'hand': opponent.magic_hand
            }, to=room.players[opponent_id].sid)

            # 通知对手等待结束
            emit('taoyuan_complete', {
                'message': '对方桃园结义结算完成'
            }, to=room.players[opponent_id].sid)

            return {'status': 'success', 'message': '桃园结义选择完成'}
        else:
            return {'status': 'error', 'message': '无效的卡牌选择'}
    elif temp_data_id == 'lingqi_choice':
        # 处理灵气复苏的船数选择
        target_ships = target_data['target_ships']

        # 获取施法者和对手
        caster = room.players[player_id]
        opponent_id = next(p for p in room.players if p != player_id)
        opponent = room.players[opponent_id]

        # 验证选择是否有效
        if 'max_ships' not in room.magic_temp_data:
            return {'status': 'error', 'message': '没有可选择的船数范围'}

        max_ships = room.magic_temp_data['max_ships']
        if target_ships < 1 or target_ships > max_ships:
            return {'status': 'error', 'message': f'无效的船数选择，应在1-{max_ships}之间'}

        # 重置双方的战舰数据
        for p_id in room.players:
            player = room.players[p_id]
            player.ships = []
            player.attacks = []
            player.remaining_ships = 0
            player.needs_reset = True
            player.revealed_positions = []
            # 设置新的船数限制
            player.max_ships = target_ships

        # 清除临时数据
        room.magic_temp_data = {}

        # 记录当前对局进度：灵气复苏只重置棋盘与船数，
        # 先后手、阶段、回合数都按原对局继续 —— 不重新猜拳。
        room.lingqi_saved_state = {
            'attack_order': list(room.attack_order),
            'current_attacker': room.current_attacker,
            'current_phase': room.current_phase,
            'round': room.round,
            'attacks_remaining': room.attacks_remaining,
        }

        # 只切到摆放阶段；attack_order / current_attacker / current_phase 保留不动，
        # 待双方重新摆放完成后再回到攻击阶段（见 handle_place_ships）。
        room.state = 'placing_ships'

        # 添加灵气复苏应用标记，用于后续广播
        room.lingqi_resurgence_applied = True

        # 通知双方进入重新摆放阶段，并发送新的船数限制
        # ⚠️ to= 要的是 socket sid，不是 room.players 的 key。
        # 自定义房/人机房里登录用户的 key 是 user_id（≠ sid），传 p_id 会石沉大海 ——
        # 玩家那边界面毫无反应，只能手动刷新才发现要重新摆船。
        for p_id in room.players:
            emit('reset_gameboard', {
                'new_max_ships': target_ships,
                'message': f'灵气复苏生效，双方需要重新摆放{target_ships}艘战舰'
            }, to=room.players[p_id].sid)

        # 通知对手等待结束
        emit('lingqi_complete', {
            'message': '对方灵气复苏结算完成'
        }, to=room.players[opponent_id].sid)

        return {'status': 'success', 'message': '灵气复苏船数选择完成'}

    elif temp_data_id == 'bury_choice':
        # 明智埋葬：把选中的牌（牌堆中或对方手牌中的那张）放进弃牌堆，
        # 施法者再摸一张牌。
        #
        # ⚠️ 原实现把 card_index 当成「施法者自己手牌的下标」：
        #   手牌为空（刚把明智埋葬打出去后的常见情况）时直接报「无效的选择」，
        #   既不埋牌也不摸牌；手牌非空时埋掉的是自己的牌，而选中的那张
        #   从头到尾没进弃牌堆。这里改为与 select_magic_target 共用同一实现。
        temp = room.magic_temp_data or {}
        if temp.get('type') != 'bury_choice' or temp.get('caster') != player_id:
            return {'status': 'error', 'message': '当前没有待处理的明智埋葬选择'}
        return _apply_bury_choice(room, player_id, target_data)

    elif temp_data_id == 'shield_choice':
        # 仁王之盾：至多 3 艘己方战舰进入护盾状态（同样补上真实链路）
        caster = room.players[player_id]
        raw_indices = target_data.get('ship_indices') or []
        if not isinstance(raw_indices, list) or not raw_indices:
            return {'status': 'error', 'message': '请至少选择一艘战舰'}
        applied = 0
        for idx in raw_indices[:3]:
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(caster.ships):
                caster.ships[idx].shield = True
                applied += 1
        if applied == 0:
            return {'status': 'error', 'message': '无效的选择'}
        room.magic_temp_data = {}
        return {'status': 'success', 'message': f'为{applied}艘战舰添加了护盾'}

    return {'status': 'error', 'message': '无效的临时数据ID'}


@socketio.on('cancel_magic_selection')
@_require_live_room
def handle_cancel_magic_selection(data):
    """放弃当前待选择状态（桃园结义 / 明智埋葬 / 仁王之盾 / 神机妙算宣言）。

    桃园结义：已抽出的牌放回牌堆，不产生任何效果。
    放置流程（增援/复活/绝处逢生）请用 cancel_placement，这里只做拒绝。
    """
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    temp = room.magic_temp_data or {}
    pending = temp.get('pending_placement')
    if pending and pending.get('caster') == player_id:
        return {'status': 'error', 'message': '放置尚未完成，请用放置面板的「放弃」'}
    if temp.get('caster') and temp.get('caster') != player_id:
        return {'status': 'error', 'message': '当前不是你的选择'}

    cards = temp.get('cards')
    if isinstance(cards, list):
        # 只放回真正的卡牌实例（明智埋葬的候选是纯数据，混进牌堆会污染牌堆）
        room.magic_deck.extend(c for c in cards if isinstance(c, MagicCard))
    room.magic_temp_data = {}
    emit('message', {'text': '已取消本次选择'}, to=room.players[player_id].sid)
    return {'status': 'success', 'message': '已取消本次选择'}


@socketio.on('get_discard_pile')
def get_discard_pile(data):
    """获取玩家的弃牌堆数据（返回全局弃牌堆）"""
    room_id = data.get('room_id')
    player_id = data.get('player_id')

    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 获取全局弃牌堆数据
    discard_pile = room.magic_discard

    # 过滤掉重复的非"失灵！"卡牌（场上仅存在一张）
    unique_discard = []
    seen = set()
    for card in discard_pile:
        if card.name == '失灵！' or card.name not in seen:
            unique_discard.append(card)
            if card.name != '失灵！':
                seen.add(card.name)

    return {'status': 'success', 'discard_pile': json.loads(json.dumps(unique_discard, default=lambda o: o.__dict__))}


# 添加辅助函数


def find_safe_position(room: GameRoom, player_id: str):
    """寻找未被攻击过的安全位置"""
    opponent_id = next(p for p in room.players if p != player_id)
    opponent_attacks = [(a.x, a.y) for a in room.players[opponent_id].attacks]

    for y in range(6):
        for x in range(6):
            if (x, y) not in opponent_attacks:
                return {'x': x, 'y': y}
    return None


# ============ 神威！“扣掉”区域（2026-09-10） ============
def _shenwei_holes(room):
    return room.game_effects.setdefault('shenwei_holes', [])


def _add_shenwei_hole(room, player_id, area, return_turn):
    """把某玩家棋盘上的一块 3x3 区域标记为“扣掉”。"""
    _shenwei_holes(room).append({
        'player': player_id,
        'x1': area['x1'], 'y1': area['y1'],
        'x2': area['x2'], 'y2': area['y2'],
        'return_turn': return_turn,
    })


def _cell_in_shenwei_hole(room, player_id, x, y):
    """该格子是否位于某玩家被扣掉的区域内。"""
    for hole in _shenwei_holes(room):
        if hole['player'] != player_id:
            continue
        if hole['x1'] <= x <= hole['x2'] and hole['y1'] <= y <= hole['y2']:
            return True
    return False


def _clear_due_shenwei_holes(room, current_round):
    """清除到期的扣洞标记，返回被恢复的区域列表。"""
    holes = _shenwei_holes(room)
    due = [h for h in holes if h['return_turn'] <= current_round]
    for h in due:
        holes.remove(h)
    return due


def _restore_due_shenwei(room, current_round):
    """到期回归：恢复被扣掉的区域，并把除外的战舰放回原位。"""
    entries = room.game_effects.get('excluded_ships') or []
    due = [e for e in entries if e['return_turn'] <= current_round]
    for entry in due:
        entries.remove(entry)
        owner = room.players[entry['player']]
        for ship in entry['ships']:
            owner.ships.append(ship)
            owner.remaining_ships += 1
    if not entries:
        room.game_effects.pop('excluded_ships', None)
    for hole in _clear_due_shenwei_holes(room, current_round):
        emit('shenwei_hole_restored', {'player': hole['player']}, room=room.id)


def _apply_ship_loss_linkage(room, caster_id, lost_player_id, count=1):
    """船数减少时的通用联动：无暇圣心 / 百亿补贴 / 八方来财 / 恶魔契约。

    与击沉路径保持一致，供神威！除外复用。
    """
    lost_player = room.players[lost_player_id]

    # 无暇圣心：造成船数变化即视为“有伤害”，中断效果
    if 'holy_heart' in room.game_effects:
        room.game_effects['holy_heart']['no_damage'] = False

    # 百亿补贴：自己的船被击败时，自己的攻击次数 +3
    _grant_subsidy_bonus(room, lost_player_id)

    # 八方来财：战舰数目变化时抽一张牌
    if lost_player.effect_flags.treasure_hunter:
        room.draw_card(lost_player_id)
        emit('message', {'text': '八方来财生效，摸一张牌'}, to=lost_player.sid)

    # 恶魔契约：一方船数减少，另一方也要牺牲一艘 —— 由该玩家自己点选（不再随机）
    if room.game_effects.get('demon_contract'):
        _request_demon_contract_sacrifice(room, lost_player_id)


def _request_ship_pick(room, chooser_id, reason, message):
    """让指定玩家在自己的棋盘上点选一艘战舰（恶魔契约 / 神之宣告 / 克苏鲁之眼 共用）。

    AI 不参与交互：直接返回替它选中的那艘；人类玩家则挂起等待 confirm_sacrifice。
    """
    chooser = room.players.get(chooser_id) if chooser_id else None
    if not chooser or not chooser.ships:
        return None

    if getattr(room, 'is_ai_room', False) and chooser_id == _ai_player_id(room):
        return random.choice(list(chooser.ships))

    room.magic_temp_data['pending_sacrifice'] = {
        'player': chooser_id,
        'reason': reason,
    }
    emit('sacrifice_request', {
        'reason': reason,
        'message': message,
        'ships': [
            {'positions': [{'x': p.x, 'y': p.y} for p in sh.positions]}
            for sh in chooser.ships
        ],
    }, to=chooser.sid)
    return None


def _request_demon_contract_sacrifice(room, lost_player_id):
    """恶魔契约触发：让另一方自己选择要牺牲的战舰（在其自方棋盘上点选）。"""
    sacrifice_id = _opponent_of(room, lost_player_id)
    picked = _request_ship_pick(room, sacrifice_id, 'demon_contract',
                                '恶魔契约生效：请点选一艘自己的战舰牺牲')
    if picked is not None:
        _do_demon_contract_sacrifice(room, sacrifice_id, picked)


def _do_demon_contract_sacrifice(room, player_id, ship, reason='demon_contract'):
    """执行"牺牲一艘船"：移除该船并公开广播，使双方都能看到沉没位置。

    reason 用于日志/广播文案：demon_contract / divine_decree。
    """
    player = room.players.get(player_id)
    if not player or ship is None or ship not in player.ships:
        return

    if room.magic_temp_data:
        room.magic_temp_data.pop('pending_sacrifice', None)

    player.ships.remove(ship)
    player.sunken_ships.append(ship)
    player.remaining_ships = max(0, player.remaining_ships - 1)

    positions = [{'x': p.x, 'y': p.y} for p in ship.positions]
    reason_text = '神之宣告' if reason == 'divine_decree' else '恶魔契约'
    add_game_log(room,
                 f'第{room.round}回合 · {_log_name(room, player_id)} 因{reason_text}牺牲一艘战舰',
                 'magic',
                 {'player': player_id, 'reason': reason, 'positions': positions})

    # 公开广播：自己与对手都能看到这艘船被划掉
    emit('ship_sacrificed', {
        'player': player_id,
        'positions': positions,
        'reason': reason,
    }, room=room.id)

    # 船数按各自视角分别推送（广播同一份数据会导致双方看到的数字颠倒）
    _emit_ships_updated(room)


def _finish_game(room, winner_id, loser_id, reason):
    """统一结算：设置胜利者、记战绩、广播 game_over。"""
    room.state = 'game_over'
    room.winner = winner_id
    add_game_log(room, f"第{room.round}回合 · {_log_name(room, winner_id)} 获胜，游戏结束",
                 'result', {'winner': winner_id, 'loser': loser_id, 'reason': reason})
    try:
        winner_user_id = room.players[winner_id].user_id
        loser_user_id = room.players[loser_id].user_id
        if winner_user_id or loser_user_id:
            db.record_match(winner_user_id or winner_id, loser_user_id or loser_id,
                            getattr(room, 'game_logs', None), count_stats=_count_stats_for(room))
    except Exception:
        pass
    emit('game_over', {'winner': winner_id, 'reason': reason}, room=room.id)


# ============ 复活 / 增援 统一放置流程（2026-09-10） ============
def _placement_error(room, player_id, x, y):
    """返回该格子不可放置的原因；None 表示可放置。
    规则：棋盘内、未被对方打过、不在神威扣洞内、未被己方船占用。"""
    if not (0 <= x <= 5 and 0 <= y <= 5):
        return '坐标超出棋盘范围'
    opponent_id = _opponent_of(room, player_id)
    if opponent_id:
        opp_attacks = [(a.x, a.y) for a in room.players[opponent_id].attacks]
        if (x, y) in opp_attacks:
            return '该位置已被对方攻击过，不能放置'
    if _cell_in_shenwei_hole(room, player_id, x, y):
        return '该区域已被神威！扣掉，不能放置'
    for ship in room.players[player_id].ships:
        for pos in ship.positions:
            if pos.x == x and pos.y == y:
                return '该位置已被己方战舰占用'
    return None


def _placement_blocked_cells(room, player_id):
    """列出该玩家棋盘上不可放置的格子（已被攻击 / 己方占用 / 神威扣洞）。"""
    blocked = set()
    opponent_id = _opponent_of(room, player_id)
    if opponent_id:
        for a in room.players[opponent_id].attacks:
            blocked.add((a.x, a.y))
    for ship in room.players[player_id].ships:
        for pos in ship.positions:
            blocked.add((pos.x, pos.y))
    for h in _shenwei_holes(room):
        if h['player'] == player_id:
            for x in range(h['x1'], h['x2'] + 1):
                for y in range(h['y1'], h['y2'] + 1):
                    blocked.add((x, y))
    return [{'x': x, 'y': y} for (x, y) in sorted(blocked)]


def _emit_placement_request(room, player_id):
    p = room.magic_temp_data.get('pending_placement')
    if not p:
        return
    payload = {
        'kind': p['kind'],
        'remaining': p['remaining'],
        'total': p['total'],
        'placed': p['placed'],
        'blocked': _placement_blocked_cells(room, player_id),
    }
    if p['kind'] == 'last_stand':
        # 只允许放在原本有战舰的格子：交给前端做高亮/禁点
        payload['allowed'] = room.game_effects.get('last_stand_cells') or []
    emit('placement_request', payload, to=room.players[player_id].sid)


def _start_placement(room, caster_id, kind, count):
    """开启放置流程：kind='reinforce' 增援 / 'revive' 复活。"""
    room.magic_temp_data['pending_placement'] = {
        'caster': caster_id, 'kind': kind,
        'remaining': count, 'total': count, 'placed': 0,
    }
    _emit_placement_request(room, caster_id)


def _finish_placement(room, player_id, kind):
    pending = room.magic_temp_data.get('pending_placement') or {}
    placed = int(pending.get('placed') or 0)
    room.magic_temp_data.pop('pending_placement', None)
    if kind == 'last_stand':
        room.game_effects.pop('last_stand_cells', None)
    emit('placement_done', {'kind': kind}, to=room.players[player_id].sid)

    # 增援/复活改变了自己的船数，攻击次数要按【增量】跟着变：
    # 例：绝境中增援一艘船 = 多一条命，同时本回合还多一次攻击。
    # 注意不能用 _recalc_attacker_attacks 从头算——那会把已经用掉的次数退还。
    _sync_attacks_after_ship_change(room, player_id, placed)


def _sync_attacks_after_ship_change(room, player_id, ships_added=1):
    """己方船数变化后按增量同步攻击次数（仅当当前攻击者是本人时）。

    伊甸园（次数 = 6 - 船数）与教皇旨意（次数恒 0，靠弃卡攻击）的换算
    规则不同，这里按每艘船的增减量换算，保留已消耗的次数。
    """
    if room.state != 'attacking':
        return
    if room.current_attacker != player_id:
        return
    if ships_added <= 0:
        return
    field = field_magic_name(room)
    if field == '教皇旨意':
        per_ship = 0
    elif field == '伊甸园':
        per_ship = -1
    else:
        per_ship = 1
    if per_ship:
        room.attacks_remaining = max(0, room.attacks_remaining + per_ship * ships_added)
    emit('attacks_updated', {
        'current_attacker': room.current_attacker,
        'attacks_remaining': room.attacks_remaining
    }, room=room.id)


def apply_magic_effect(room: GameRoom, caster_id: str, card: MagicCard, target_data):
    result = ChainResult(card=card, caster=caster_id, success=True, message='')
    opponent_id = next(p for p in room.players if p != caster_id)
    caster = room.players[caster_id]
    opponent = room.players[opponent_id]
    print(f"Applying magic effect: {card.name} target {target_data}")


    # ==== 速阶1 魔法卡 ====
    if card.name == '余音绕梁':
        # 卡面：只能在自己的准备阶段使用；接下来的「自己的攻击阶段」与
        # 「下一个回合自己的攻击阶段」造成伤害即强制击杀。
        # 因此 forced_kill 是【剩余攻击阶段数】，不是击杀次数：
        # 在 handle_attack 里只判断 >0，进入结束阶段时消耗一次。
        if room.current_phase != 'preparation' or room.current_attacker != caster_id:
            result['success'] = False
            result['message'] = '只能在自己的准备阶段使用'
            return result
        room.players[caster_id].effect_flags.forced_kill = 2
        result.message = '接下来两个攻击阶段（本回合与下一回合）将造成强制击杀'
    elif card.name == '桃园结义':
        # 无中生有生效期间双方都不能以任何方式获得魔法卡（原实现直接 pop 牌堆绕过）
        if caster.effect_flags.no_draw or room.players[opponent_id].effect_flags.no_draw:
            result['success'] = False
            result['message'] = '无中生有生效期间，双方无法获得魔法卡'
            return result
        # 从牌堆抽取n张牌(n为自己的战舰数)，自己选1张，再给对方选1张，已修复
        n = caster.remaining_ships
        drawn_cards = []

        # 只抽取牌堆中实际存在的牌
        for i in range(min(n, len(room.magic_deck))):
            drawn_cards.append(room.magic_deck.pop(0))

        if drawn_cards:
            # 记录待选择的牌
            room.magic_temp_data = {
                'type': 'taoyuan_choice',
                'caster': caster_id,
                'opponent': opponent_id,
                'cards': drawn_cards,
                'player_deck_backup': []  # 备份，用于记录放回的牌
            }
            result.message = f'抽了{len(drawn_cards)}张牌，请选择'
            result.temp_data_id = 'taoyuan_choice'
            result['cards'] = [{'name': c.name, 'speed': c.speed, 'type': c.type, 'description': c.description} for c in drawn_cards]
            # 通知对手等待
            emit('taoyuan_waiting', {
                'message': '对方正在结算桃园结义效果 请等待'
            }, to=room.players[opponent_id].sid)
        else:
            result.success = False
            result.message = '无法抽取卡牌'

    elif card.name == '无中生有':
        # 抽两张牌，本回合双方无法获得魔法卡
        card1 = room.draw_card(caster_id)
        card2 = room.draw_card(caster_id)
        # 设置禁止抽卡标记
        room.players[caster_id].effect_flags.no_draw = True
        room.players[opponent_id].effect_flags.no_draw = True
        result.message = '抽了2张牌，本回合双方无法获得魔法卡'

    elif card.name == '极限增援':
        # 两个大回合后，船少的一方获胜，已修复
        total_turns = 2
        room.game_effects["reinforcement_check"] = {
            'turn': room.round + total_turns,
            'caster': caster_id,
            'remaining_turns': total_turns,  # 添加剩余回合计数
            # 卡面：不算他生效的这个大回合 → 计数从下一个大回合才开始递减
            'activated_round': room.round,
        }
        # 通知双方客户端，极限增援已激活并显示剩余回合
        emit('reinforcement_activated', {
            'remaining_turns': total_turns
        }, room=room.id)
        result.message = '极限增援已激活，剩余2回合后结算'

    elif card.name == '无暇圣心':
        # 两个大回合后如果双方都没造成伤害，施法者获胜，已修复
        total_turns = 2
        room.game_effects['holy_heart'] = {
            'turn': room.round + total_turns,
            'caster': caster_id,
            'remaining_turns': total_turns,  # 剩余回合计数
            'no_damage': True  # 初始状态：双方都未造成伤害
        }
        # 通知双方客户端，无暇圣心已激活并显示剩余回合
        emit('holy_heart_activated', {
            'remaining_turns': total_turns
        }, room=room.id)
        result.message = '无暇圣心已激活，剩余2回合后结算'

    elif card.name == '火力全开':
        # 本回合攻击次数翻倍
        # （真实结算在 enter_battle_phase 读取 double_attacks 标记，此处只设标记）
        room.players[caster_id].effect_flags.double_attacks = True
        result.message = '本回合攻击次数翻倍'

    elif card.name == '灵气复苏':
        # 计算双方最大船数，已修复
        max_ships = max(caster.remaining_ships, opponent.remaining_ships)
        if max_ships < 1:
            max_ships = 1

        # 存储临时数据，等待玩家选择船数
        room.magic_temp_data = {
            'type': 'lingqi_choice',
            'caster': caster_id,
            'opponent': opponent_id,
            'max_ships': max_ships
        }

        # 设置结果，只发送给施法者
        result.message = '请选择灵气复苏的船数'
        result.temp_data_id = 'lingqi_choice'
        result.max_ships = max_ships

        # 通知对手等待
        emit('lingqi_waiting', {
            'message': '对方正在结算灵气复苏效果 请等待'
        }, to=room.players[opponent_id].sid)
    
    elif card.name == '教皇旨意':
        # 场地魔法，攻击次数变为0，通过弃置魔法卡攻击
        _place_field_magic(room, caster_id, card)
        room.game_effects['papal_edict'] = True
        result['message'] = '教皇旨意已生效，双方攻击次数变为0，通过弃置魔法卡攻击对方两次'

    elif card.name == '败者食尘':
        # 记录败者食尘打出前双方的船数，已修复
        original_caster_ships = caster.remaining_ships
        original_opponent_ships = opponent.remaining_ships
        
        # 交换双方的船数限制：将双方的max_ships设置为对方的原始船数
        caster.max_ships = original_opponent_ships
        opponent.max_ships = original_caster_ships

        # 重置房间状态，进入重新摆放阶段
        room.state = 'placing_ships'
        room.attack_order = []
        room.current_attacker = ""
        room.attacks_remaining = 0

        # 完全初始化棋盘，使其像刚开局那样干净
        for p_id in room.players:
            player = room.players[p_id]
            # 重置战舰数据
            player.ships = []
            player.remaining_ships = 0
            # 清除攻击记录
            player.attacks = []
            # 清除被攻击记录
            if hasattr(player, 'opponent_attacks'):
                player.opponent_attacks = []
            # 清除其他相关状态
            player.needs_reset = True
            player.revealed_positions = []
            # 清除所有与棋盘相关的状态

        # 添加败者食尘标记，用于设置攻击次数为0
        room.polar_reversal_applied = True

        # 通知双方进入重新摆放阶段，并发送新的船数限制
        # ⚠️ 同灵气复苏：必须发到 player.sid。以前传的是 room.players 的 key（登录用户
        # 就是 user_id ≠ sid），事件根本没送到 —— 玩家只能手动刷新游戏才会开始重新摆放。
        for p_id in room.players:
            player = room.players[p_id]
            emit('reset_gameboard', {
                'new_max_ships': player.max_ships,
                'message': '败者食尘生效，立即重启正常对局但保留双方的手牌'
            }, to=player.sid)

        # 设置结果
        result['message'] = '败者食尘生效，立即重启正常对局但保留双方的手牌'
        # 立即返回：败者食尘已清空双方战舰并重置为布船阶段，
        # 不能落入末尾“对手剩余船数<=0 则游戏结束”的兜底判断（会误判 game_over）
        return result

    # ==== 速阶2 魔法卡 ===
    elif card.name == '溅射':
        # 对击中格子的上下左右四格造成伤害
        if not room.last_attack or room.last_attack['attacker'] != caster_id or not room.last_attack.get('hit'):
            result['success'] = False
            result['message'] = '必须在击中对方后使用'
            return result

        x, y = room.last_attack["x"], room.last_attack["y"]
        splash_positions = [
            {'x': x, 'y': y - 1},  # 上
            {'x': x, 'y': y + 1},  # 下
            {'x': x - 1, 'y': y},  # 左
            {'x': x + 1, 'y': y}  # 右
        ]

        # 过滤有效位置
        valid_positions = [p for p in splash_positions if 0 <= p['x'] < 6 and 0 <= p['y'] < 6]
        hit_count = 0
        ships_changed = False

        affected_positions = []
        for pos in valid_positions:
            # 检查是否击中
            hit = False
            ship_sunk = False
            for i, ship in enumerate(opponent.ships):
                if Position(**pos) in ship.positions and Position(**pos) not in ship.hits:
                    # 溅射伤害不受无敌影响（文本），但受护盾影响（护盾抵挡一次）
                    # 造成伤害：解除无暇圣心"双方未受伤"判定
                    if 'holy_heart' in room.game_effects:
                        room.game_effects['holy_heart']['no_damage'] = False
                    if ship.shield:
                        hit = True
                        ship.shield=False
                        ship_sunk = False
                    else:
                        hit = True
                        ship.hits.append(Position(**pos))
                        if len(ship.hits) == len(ship.positions):
                            ship_sunk = True
                            opponent.remaining_ships -= 1
                            ships_changed = True
                            # 记录本回合造成的伤害（五险一金/Freezing! 判定）
                            caster.damage_dealt_this_turn += 1

                            # 保存被击沉的船到sunken_ships
                            opponent.sunken_ships.append(ship)

                            # 平等条约快照 + 百亿补贴 + 无暇圣心中断（与普通攻击共用）
                            _on_ship_destroyed(room, opponent_id, ship, [Position(**pos)])

                            # 八方来财
                            if opponent.effect_flags.treasure_hunter:
                                room.draw_card(opponent_id)
                                emit('message', {'text': '八方来财生效，摸一张牌'}, to=room.players[opponent_id].sid)

                            # 恶魔契约（由牺牲方自己点选，AI 自动）：
                            # 一次结算里多艘沉没时只请求一次，否则后一次会覆盖前一次的待牺牲
                            if (room.game_effects.get('demon_contract')
                                    and not (room.magic_temp_data or {}).get('pending_sacrifice')):
                                _request_demon_contract_sacrifice(room, opponent_id)
                                ships_changed = True

                            # 检查回光返照效果（统一走 helper：置状态 / 记日志 / 记战绩 / 广播）
                            # 注意必须返回 ChainResult：原实现返回普通 dict，
                            # resolve_chain 里对 result.caster 赋值会抛 AttributeError，
                            # 导致连锁不结算、残留连锁栈。
                            if _check_last_chance(room, caster_id, opponent_id):
                                result['game_over'] = True
                                return result
                    hit_count += 1
                    break

            # 记录攻击（包括未命中）
            caster.attacks.append(Position(**{
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk,
                'is_splash': True
            }))

            # 发送单点攻击结果，保持与普通攻击一致的 UI 更新
            attack_result = {
                'attacker': caster_id,
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk,
                'remaining_attacks': room.attacks_remaining,
                'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                'defender_remaining_ships': opponent.remaining_ships
            }
            emit('attack_result', attack_result, room=room.id)

            affected_positions.append(Position(**{
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk
            }))

        # 若有船只数量变化，广播更新
        if ships_changed:
            _emit_ships_updated(room)

        result['message'] = f'溅射攻击命中{hit_count}个目标'
        result['affected_positions'] = affected_positions
        result['caster_id'] = caster_id

    elif card.name == '雷达子弹':
        # 显示击中位置周围八格的战舰
        if not room.last_attack or room.last_attack['attacker'] != caster_id or not room.last_attack['hit']:
            result['success'] = False
            result['message'] = '必须在击中对方战舰后使用'
            return result
        affected_positions = []
        x, y = room.last_attack["x"], room.last_attack["y"]
        # 记录需要显示的位置
        new_positions = []
        for dy in [-1, 0, 1]:
            for dx in [-1, 0, 1]:
                if dx == 0 and dy == 0: continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < 6 and 0 <= ny < 6:
                    pos = {'x': nx, 'y': ny}
                    room.players[caster_id].revealed_positions.append(Position(**pos))
                    new_positions.append(pos)
        for pos in new_positions:
            # 检查是否击中
            hit = False
            ship_sunk = False
            for i, ship in enumerate(opponent.ships):
                if Position(**pos) in ship.positions and Position(**pos) not in ship.hits:
                    hit=True
            if hit:continue 
            # 记录攻击（包括未命中）
            caster.attacks.append(Position(**{
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk,
                'is_splash': True
            }))

            # 发送单点攻击结果，保持与普通攻击一致的 UI 更新
            attack_result = {
                'attacker': caster_id,
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk,
                'remaining_attacks': room.attacks_remaining,
                'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                'defender_remaining_ships': opponent.remaining_ships
            }
            emit('attack_result', attack_result, room=room.id)

            affected_positions.append(Position(**{
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk
            }))
        # 立即将被揭示的位置发送给触发方
        emit('revealed_positions', {'positions': new_positions}, to=room.players[caster_id].sid)
        result['message'] = '已扫描周围八格战舰位置'
        result['affected_positions'] = affected_positions

    elif card.name == '越战越勇':
        # 每击沉一艘战舰，攻击次数净增加1
        if not room.last_attack or room.last_attack['attacker'] != caster_id or not room.last_attack['ship_sunk']:
            result['success'] = False
            result['message'] = '必须在击沉对方战舰后使用'
            return result

        # 添加越战越勇效果标记
        room.players[caster_id].effect_flags.battle_spirit = True
        result['message'] = '越战越勇效果生效，本回合击沉战舰时攻击次数净增加1'

    elif card.name == '神威！':
        # 选定己方/对方棋盘上的 3*3 区域：该区域从棋盘上“扣掉”，
        # 区域内战舰暂时除外，下一个大回合开始时回归原位、区域恢复。
        if 'target_area' not in target_data:
            result['success'] = False
            result['message'] = '需要选择目标区域'
            return result

        area = target_data['target_area']
        board = target_data.get('board', 'opponent')  # 'self' | 'opponent'
        target_id = caster_id if board == 'self' else opponent_id
        target_player = room.players[target_id]

        # 收集并移除区域内的战舰
        excluded_ships = []
        for i in range(len(target_player.ships) - 1, -1, -1):
            ship = target_player.ships[i]
            in_area = any(
                area['x1'] <= pos.x <= area['x2'] and
                area['y1'] <= pos.y <= area['y2']
                for pos in ship.positions
            )
            if in_area:
                excluded_ships.append(ship)
                del target_player.ships[i]
                target_player.remaining_ships -= 1

        # 把这片区域从棋盘上扣掉（下个大回合恢复）
        return_turn = room.round + 1
        _add_shenwei_hole(room, target_id, area, return_turn)
        emit('shenwei_hole', {
            'player': target_id, 'area': area, 'return_turn': return_turn
        }, room=room.id)

        # 卡面：仅当作用于对方棋盘且区域内恰好 1 艘船时，直接死亡
        if board != 'self' and len(excluded_ships) == 1:
            target_player.sunken_ships.append(excluded_ships[0])
            _apply_ship_loss_linkage(room, caster_id, opponent_id, count=1)
            result['message'] = '目标区域内1艘战舰被击沉'
        else:
            room.game_effects.setdefault('excluded_ships', []).append({
                'ships': excluded_ships,
                'player': target_id,
                'return_turn': return_turn,
            })
            if excluded_ships:
                _apply_ship_loss_linkage(room, caster_id, target_id,
                                         count=len(excluded_ships))
            result['message'] = f'目标区域内{len(excluded_ships)}艘战舰被暂时除外'

        _emit_ships_updated(room)

        # 斩杀线：对方船被清空直接获胜；己方自扣清空则判负
        if opponent.remaining_ships <= 0 and room.state != 'game_over':
            _finish_game(room, caster_id, opponent_id, '神威！清空对方棋盘')
            result['message'] += '，对方战舰全灭，直接获胜'
        elif caster.remaining_ships <= 0 and room.state != 'game_over':
            _finish_game(room, opponent_id, caster_id, '神威！清空己方棋盘')
            result['message'] += '，己方战舰全灭，判负'

    elif card.name == '冻结':
        # 冻结3*3区域内的船，使其无法攻击
        if 'target_area' not in target_data:
            result['success'] = False
            result['message'] = '需要选择目标区域'
            return result

        area = target_data['target_area']
        frozen_count = 0

        # 标记区域内的战舰
        for ship in opponent.ships:
            in_area = any(
                area['x1'] <= pos.x <= area['x2'] and
                area['y1'] <= pos.y <= area['y2']
                for pos in ship.positions
            )

            if in_area and getattr(ship, 'frozen', None) is None:
                ship.frozen = room.round + 1  # 冻结到下一回合
                frozen_count += 1

        if frozen_count:
            # 立刻把「哪几艘被冻住了」同步给被冻结的一方（画在ta自己的棋盘上）
            _emit_player_ships(room, opponent_id)
        result['message'] = f'冻结了{frozen_count}艘战舰'


    elif card.name == '轰炸':
        # 选定一行或一列进行轰炸
        if 'target_line' not in target_data:
            result['success'] = False
            result['message'] = '需要选择目标行或列'
            return result

        line = target_data['target_line']
        # 检查是行还是列
        if line["type"] == 'row':
            positions = [{'x': x, 'y': line['index']} for x in range(6)]
        else:
            positions = [{'x': line['index'], 'y': y} for y in range(6)]

        # 找出所有与该行/列相交的船只，整艘摧毁
        to_remove = [ship for ship in opponent.ships if len(ship.hits) < len(ship.positions) and any(pos in ship.positions for pos in positions)]
        sunk_count = 0
        ships_changed = False
        removed_positions = set()

        # 移除受影响的船只，并为其所有格子生成命中事件
        for ship in to_remove:
            if ship in opponent.ships:
                # 保存被摧毁的船到sunken_ships
                opponent.sunken_ships.append(ship)
                opponent.ships.remove(ship)
                opponent.remaining_ships -= 1
                ships_changed = True
                sunk_count += 1
                # 记录本回合伤害（五险一金/Freezing!）
                caster.damage_dealt_this_turn += 1

                # 平等条约快照 + 百亿补贴 + 无暇圣心中断（与普通攻击共用）
                _on_ship_destroyed(room, opponent_id, ship)

                # 恶魔契约：一次结算里多艘沉没时只请求一次
                if (room.game_effects.get('demon_contract')
                        and not (room.magic_temp_data or {}).get('pending_sacrifice')):
                    _request_demon_contract_sacrifice(room, opponent_id)
                    ships_changed = True

                # 八方来财
                if opponent.effect_flags.treasure_hunter:
                    room.draw_card(opponent_id)
                    emit('message', {'text': '八方来财生效，摸一张牌'}, to=room.players[opponent_id].sid)
                for ship_pos in ship.positions:
                    removed_positions.add((ship_pos.x, ship_pos.y))
                    caster.attacks.append(Position(**{
                        'x': ship_pos.x,
                        'y': ship_pos.y,
                        'hit': True,
                        'ship_sunk': True,
                        'is_bomb': True
                    }))
                    attack_result = {
                        'attacker': caster_id,
                        'x': ship_pos.x,
                        'y': ship_pos.y,
                        'hit': True,
                        'ship_sunk': True,
                        'remaining_attacks': room.attacks_remaining,
                        'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                        'defender_remaining_ships': opponent.remaining_ships
                    }
                    emit('attack_result', attack_result, room=room.id)

        # 对于该行/列中未命中的格子也发出未命中事件，以保持 UI 一致性
        for pos in positions:
            if (pos['x'], pos['y']) not in removed_positions:
                caster.attacks.append(Position(**{
                    'x': pos['x'],
                    'y': pos['y'],
                    'hit': False,
                    'ship_sunk': False,
                    'is_bomb': True
                }))
                attack_result = {
                    'attacker': caster_id,
                    'x': pos['x'],
                    'y': pos['y'],
                    'hit': False,
                    'ship_sunk': False,
                    'remaining_attacks': room.attacks_remaining,
                    'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                    'defender_remaining_ships': opponent.remaining_ships
                }
                emit('attack_result', attack_result, room=room.id)

        # 若有船只数量变化，广播更新
        if ships_changed:
            _emit_ships_updated(room)

        result['message'] = f'轰炸成功击沉{sunk_count}艘战舰'

    elif card.name == '硫磺火焰':
        # 对选定的连续6格释放硫磺火焰，强制击杀这些格子上所属的所有战舰（无视护盾/无敌）
        if 'target_cells' not in target_data:
            result['success'] = False
            result['message'] = '需要选择6个连续的目标格子'
            return result
        positions = target_data['target_cells']
        if not isinstance(positions, list) or len(positions) != 6:
            result['success'] = False
            result['message'] = '需要选择恰好6个连续的格子'
            return result

        # 找出所有与这些格子相交的船只，并整艘摧毁
        to_remove = [ship for ship in opponent.ships if len(ship.hits) < len(ship.positions) and any(pos in ship.positions for pos in positions)]
        sunk_count = 0
        ships_changed = False
        removed_positions = set()
        affected_positions: list[Position] = []
        for ship in to_remove:
            if ship in opponent.ships:
                # 保存被摧毁的船到sunken_ships
                opponent.sunken_ships.append(ship)
                opponent.ships.remove(ship)
                opponent.remaining_ships -= 1
                ships_changed = True
                sunk_count += 1
                # 记录本回合伤害（五险一金/Freezing!）
                caster.damage_dealt_this_turn += 1

                # 八方来财: 战舰数目变化时抽一张牌
                if opponent.effect_flags.treasure_hunter:
                    room.draw_card(opponent_id)
                    emit('message', {'text': '八方来财生效，摸一张牌'}, to=room.players[opponent_id].sid)

                # 平等条约快照 + 百亿补贴 + 无暇圣心中断（与普通攻击共用）
                _on_ship_destroyed(room, opponent_id, ship)

                # 恶魔契约：一次结算里多艘沉没时只请求一次
                if (room.game_effects.get('demon_contract')
                        and not (room.magic_temp_data or {}).get('pending_sacrifice')):
                    _request_demon_contract_sacrifice(room, opponent_id)
                    ships_changed = True
                for ship_pos in ship.positions:
                    removed_positions.add((ship_pos.x, ship_pos.y))
                    caster.attacks.append(Position(**{
                        'x': ship_pos.x,
                        'y': ship_pos.y,
                        'hit': True,
                        'ship_sunk': True,
                        'is_sulfur': True
                    }))
                    attack_result = {
                        'attacker': caster_id,
                        'x': ship_pos.x,
                        'y': ship_pos.y,
                        'hit': True,
                        'ship_sunk': True,
                        'remaining_attacks': room.attacks_remaining,
                        'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                        'defender_remaining_ships': opponent.remaining_ships
                    }
                    emit('attack_result', attack_result, room=room.id)
                    affected_positions.append(Position(**{
                        'x': ship_pos.x,
                        'y': ship_pos.y,
                        'hit': True,
                        'ship_sunk': True
                    }))

        # 对于选定格子中未命中的格子，发送未命中事件
        for pos in positions:
            if (pos["x"], pos["y"]) not in removed_positions:
                caster.attacks.append(Position(**{
                    'x': pos["x"],
                    'y': pos["y"],
                    'hit': False,
                    'ship_sunk': False,
                    'is_sulfur': True
                }))
                attack_result = {
                    'attacker': caster_id,
                    'x': pos["x"],
                    'y': pos["y"],
                    'hit': False,
                    'ship_sunk': False,
                    'remaining_attacks': room.attacks_remaining,
                    'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                    'defender_remaining_ships': opponent.remaining_ships
                }
                emit('attack_result', attack_result, room=room.id)
                affected_positions.append(Position(**{
                    'x': pos["x"],
                    'y': pos["y"],
                    'hit': False,
                    'ship_sunk': False
                }))

        # 广播被摧毁舰只更新
        if ships_changed:
            _emit_ships_updated(room)

        result['message'] = f'硫磺火焰成功击杀{sunk_count}艘战舰'
        result['affected_positions'] = affected_positions
        result['caster_id'] = caster_id
        
        # 添加游戏日志
        add_game_log(room, f"第{room.round}回合 · {_log_name(room, caster_id)} 使用了【硫磺火焰】，击杀了{sunk_count}艘战舰", 'magic', {
            'caster_id': caster_id,
            'card_name': card.name,
            'sunk_count': sunk_count,
            'affected_positions': affected_positions
        })

    elif card.name == '探测雷达':
        # 显示2*2区域内的战舰
        if 'target_area' not in target_data:
            result['success'] = False
            result['message'] = '需要选择目标区域'
            return result

        area = target_data['target_area']
        positions = []
        room.players[caster_id].revealed_positions = room.players[caster_id].revealed_positions
        affected_positions = []
        # 添加需要显示的位置
        for y in range(area['y1'], area['y2'] + 1):
            for x in range(area['x1'], area['x2'] + 1):
                pos = {'x': x, 'y': y}
                room.players[caster_id].revealed_positions.append(Position(**pos))
                positions.append(pos)
        for pos in positions:
            # 检查是否击中
            hit = False
            ship_sunk = False
            for i, ship in enumerate(opponent.ships):
                if Position(**pos) in ship.positions and Position(**pos) not in ship.hits:
                    hit=True
            if hit:continue 
            # 记录攻击（包括未命中）
            caster.attacks.append(Position(**{
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk,
                'is_splash': True
            }))

            # 发送单点攻击结果，保持与普通攻击一致的 UI 更新
            attack_result = {
                'attacker': caster_id,
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk,
                'remaining_attacks': room.attacks_remaining,
                'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                'defender_remaining_ships': opponent.remaining_ships
            }
            emit('attack_result', attack_result, room=room.id)

            affected_positions.append(Position(**{
                'x': pos['x'],
                'y': pos['y'],
                'hit': hit,
                'ship_sunk': ship_sunk
            }))
        # 立即发送给触发者
        emit('revealed_positions', {'positions': positions}, to=room.players[caster_id].sid)
        result['message'] = '已探测目标区域战舰位置'
        result['affected_positions'] = affected_positions

    elif card.name == '饮血':
        # 卡面："可在击中对方后选择使用" → 必须有自己上一次击中对方的记录
        last = getattr(room, 'last_attack', None) or {}
        if not (last.get('attacker') == caster_id and last.get('hit')):
            result['success'] = False
            result['message'] = '需要在击中对方战舰后才能使用'
            return result
        # 每击杀一艘船，抽一张牌
        room.players[caster_id].effect_flags.vampire = True
        result['message'] = '接下来自己的攻击，每击杀一艘船，自己摸一张牌。'

    elif card.name == '克苏鲁之眼':
        # 双方各暴露一艘船。施法者必须点选一艘【自己的船】所在格，不能选空格。
        if not caster.ships or not opponent.ships:
            result['success'] = False
            result['message'] = '双方都必须有战舰才能使用'
            return result

        cell = _pick_cell_from_target(target_data)
        if cell is None:
            result['success'] = False
            result['message'] = '请选择一艘自己的战舰'
            return result

        caster_ship = _find_ship_at(caster, cell)
        if caster_ship is None:
            result['success'] = False
            result['message'] = '必须选择自己战舰所在的格子'
            return result

        caster_positions = caster_ship.positions
        # 先把自己的位置暴露给对方
        room.players[opponent_id].revealed_positions.extend(caster_positions)
        emit('revealed_positions', {'positions': caster_positions}, to=room.players[opponent_id].sid)

        # 卡面：然后【对方也选择一艘船】暴露位置（AI 由服务端代选）
        picked = _request_ship_pick(
            room, opponent_id, 'kraken_eye',
            '克苏鲁之眼生效：请点选一艘自己的战舰暴露位置')
        opponent_positions = picked.positions if picked is not None else []
        if picked is not None:
            room.players[caster_id].revealed_positions.extend(picked.positions)
            emit('revealed_positions', {'positions': picked.positions}, to=room.players[caster_id].sid)
        emit('revealed_positions', {'positions': caster_positions}, to=room.players[opponent_id].sid)

        result['message'] = '双方各暴露一艘战舰位置'

    elif card.name == 'Freezing！':
        # 发动条件（三条缺一不可）：
        #   1. 自己先手（attack_order[0]）
        #   2. 当前是结束阶段
        #   3. 本回合没有让对方船数减少
        if room.attack_order and room.attack_order[0] != caster_id:
            result['success'] = False
            result['message'] = 'Freezing！只能在自己先手的回合发动'
            return result

        if room.current_phase != 'end':
            result['success'] = False
            result['message'] = 'Freezing！只能在结束阶段发动'
            return result

        # damage_dealt_this_turn 只在击沉对方战舰时累加，等价于「让对方船数减少」
        if caster.damage_dealt_this_turn > 0:
            result['success'] = False
            result['message'] = '本回合已使对方船数减少，无法发动 Freezing！'
            return result

        # 跳过对方本回合的所有阶段
        room.skip_opponent_turn = opponent_id
        result['message'] = 'Freezing！生效，跳过对方本回合的所有阶段'

    elif card.name == '五险一金':
        # 教皇旨意生效中本回合任何人都没有攻击次数（场地规则），这张牌一次都触发不了，
        # 直接拒绝出牌，别让它白白浪费。
        if field_magic_name(room) == '教皇旨意':
            result['success'] = False
            result['message'] = '教皇旨意生效中，本回合攻击次数为0，五险一金无法发动'
            return result

        # 本回合已经让对方减过船 → 这张牌无论如何都不会再触发了，直接拒绝，别浪费一张卡
        if caster.damage_dealt_this_turn > 0:
            result['success'] = False
            result['message'] = '本回合已造成伤害，无法发动'
            return result

        # 只「挂上保险」：真正的 +3 要等本回合攻击次数第一次归零时才结算，
        # 不是一打出就白送 3 次（见 _maybe_trigger_wuxian_yijin）。
        caster.effect_flags.wuxian = True
        if _maybe_trigger_wuxian_yijin(room, caster_id):
            # 出牌时攻击次数本来就已是 0：条件当场成立
            result['message'] = '攻击次数已用尽且未造成伤害，攻击次数 +3'
        else:
            result['message'] = '五险一金已生效：用完本回合所有攻击次数且未造成伤害时，攻击次数 +3'

    elif card.name == '明智埋葬':
        # 埋葬对象 = 牌堆中的卡 + 对方手牌（可埋葬对方手里的牌）
        deck = room.magic_deck or []
        opp_hand = opponent.magic_hand or []
        if not deck and not opp_hand:
            result['success'] = False
            result['message'] = '牌堆与对方手牌均为空，无法发动'
            return result

        # 候选池：先牌堆，后对方手牌（扁平下标 = 前端展示顺序）。
        # 只存纯数据、不存 MagicCard 实例：magic_temp_data 会被
        # get_magic_temp_data 原样 emit，实例无法 JSON 序列化。
        candidates = []
        for source, pile in (('deck', deck), ('opponent_hand', opp_hand)):
            for i, c in enumerate(pile):
                candidates.append({
                    'source': source, 'index': i, 'name': c.name, 'speed': c.speed,
                    'type': c.type, 'description': c.description,
                })

        room.magic_temp_data = {
            'type': 'bury_choice',
            'caster': caster_id,
            'candidates': candidates,
        }
        # index 是该卡在自己来源列表内的下标，前端回传 source_index 用它精确定位
        result['cards'] = [dict(c) for c in candidates]
        result['message'] = '请选择要埋葬的卡牌（牌堆或对方手牌）'
        result['temp_data_id'] = 'bury_choice'

    elif card.name == '仁王之盾':
        # 选择至多3艘船进入盾牌状态
        if caster.remaining_ships == 0:
            result['success'] = False
            result['message'] = '没有战舰可保护'
            return result

        # 记录需要选择的船
        room.magic_temp_data = {
            'type': 'shield_choice',
            'caster': caster_id,
            'ships': caster.ships
        }
        result['message'] = '请选择要保护的战舰'
        result['temp_data_id'] = 'shield_choice'

    # ==== 速阶3 魔法卡 ====
    elif card.name == '八方来财':
        # 战舰数目主动变化时抽一张牌
        room.players[caster_id].effect_flags = room.players[caster_id].effect_flags
        room.players[caster_id].effect_flags.treasure_hunter = True
        result['message'] = '战舰数目变化时抽一张牌'

    elif card.name == '平等条约':
        # 船数改变时无效化导致改变的【魔法卡】（攻击造成的不在此列）
        if 'last_ship_change' not in room.game_effects:
            result['success'] = False
            result['message'] = '没有可无效化的船数改变效果'
            return result

        # 卡面"立即发动"：超过本大回合的快照不允许回滚
        # （原先无过期点，第 9 回合还能回滚第 1 回合的击沉）
        if room.game_effects['last_ship_change'].get('round', room.round) != room.round:
            room.game_effects.pop('last_ship_change', None)
            result['success'] = False
            result['message'] = '船数改变发生在上一个大回合，无法再无效化'
            return result

        # 卡面只允许无效化【魔法卡】造成的船数改变；普通炮击/教皇旨意造成的击沉
        # 无法被无效化。这里必须保留快照（不能 pop）—— 否则接着摸到一张魔法卡
        # 造成船数变化时，玩家会因为快照被提前消费而莫名其妙地无效化不了。
        if room.game_effects['last_ship_change'].get('source') == 'attack':
            result['success'] = False
            result['message'] = '平等条约只能无效化魔法卡造成的船数减少，无法无效化炮击造成的击沉'
            return result

        # 无效化最后一次船数改变
        last_change = room.game_effects.pop('last_ship_change')
        # 恢复船数和被移除的ship
        affected_player_id = last_change['player']
        affected_player = room.players[affected_player_id]
        count = last_change['count']
        affected_player.remaining_ships += count

        # 完全回滚: 把ship重新加回列表，从sunken_ships中移除（防重复：击沉时船仍留在ships中）
        if 'ship' in last_change and last_change['ship'] is not None:
            if last_change['ship'] not in affected_player.ships:
                affected_player.ships.append(last_change['ship'])
            # 从sunken_ships中移除
            if last_change['ship'] in affected_player.sunken_ships:
                affected_player.sunken_ships.remove(last_change['ship'])
            # 撤销本次击沉：移除击中格，避免回滚后成为打不死的幽灵船
            for h in last_change.get('hits_added', []):
                if h in last_change['ship'].hits:
                    last_change['ship'].hits.remove(h)

        # 回滚连带撤销百亿补贴为这次击沉发放的 +3
        if last_change.get('subsidy_granted'):
            flags = affected_player.effect_flags
            flags.subsidy_bonus = max(0, int(getattr(flags, 'subsidy_bonus', 0) or 0) - 3)

        # 广播更新
        _emit_ships_updated(room)

        result['message'] = '成功无效化船数改变效果'

    elif card.name == '百亿补贴':
        # 船被击败时攻击次数加3
        room.players[caster_id].effect_flags = room.players[caster_id].effect_flags
        room.players[caster_id].effect_flags.subsidy = True
        result['message'] = '船被击败时攻击次数加3'

    elif card.name == '神之宣告':
        # 牺牲两艘船，选择一个效果
        if caster.remaining_ships < 2:
            result['success'] = False
            result['message'] = '需要至少2艘战舰才能发动'
            return result

        # 牺牲两艘船：优先采用玩家点选的两艘（前端 own_ships → selected_cells），
        # 非法/不足时用随机补齐（AI 与老客户端仍可出牌）。
        chosen = []
        cells = target_data.get('selected_cells') if isinstance(target_data, dict) else None
        if isinstance(cells, list):
            for c in cells:
                try:
                    pos = (int(c.get('x')), int(c.get('y')))
                except (AttributeError, TypeError, ValueError):
                    continue
                ship_at = _find_ship_at(caster, pos)
                if (ship_at is not None and ship_at not in chosen
                        and ship_at not in caster.sunken_ships):
                    chosen.append(ship_at)
        if len(chosen) < 2:
            # 只从"还活着"的船里补：已沉的船在 ships 里仍占位，不排除会把
            # 牺牲变成零代价（沉船堆还会出现重复条目）
            pool = [s for s in caster.ships
                    if s not in chosen and s not in caster.sunken_ships]
            random.shuffle(pool)
            chosen.extend(pool[:2 - len(chosen)])
        if len(chosen) < 2:
            result['success'] = False
            result['message'] = '需要至少2艘战舰才能发动'
            return result

        # 逐个走统一结算：移船 + 记日志 + 公开广播 ship_sacrificed + 按视角刷船数。
        # 以前这里是自己 remove/append 就完事，结果对方完全看不到这两艘船沉了。
        for sacr in chosen[:2]:
            _do_demon_contract_sacrifice(room, caster_id, sacr, 'divine_decree')

        # 获取选择的效果：优先采用出牌时携带的 effect_choice（前端出牌前选择），
        # 其次回退到临时数据，缺省为 1（摧毁对方一艘战舰）。
        if isinstance(target_data, dict) and target_data.get('effect_choice'):
            try:
                effect_choice = int(target_data['effect_choice'])
            except (TypeError, ValueError):
                effect_choice = 1
        else:
            try:
                effect_choice = int(room.magic_temp_data.get('effect_choice', 1))
            except (TypeError, ValueError):
                effect_choice = 1
        if effect_choice == 1:
            # 卡面：让对方【自己选择】一艘船使其死亡（AI 由服务端代选）
            picked = _request_ship_pick(
                room, opponent_id, 'divine_decree',
                '神之宣告生效：请点选一艘自己的战舰，使其阵亡')
            if picked is not None:
                _do_demon_contract_sacrifice(room, opponent_id, picked, 'divine_decree')
                result['message'] = '牺牲两艘战舰，对方一艘战舰被摧毁'
            else:
                result['message'] = '牺牲两艘战舰，等待对方选择阵亡的战舰'
        else:
            # 跳过对方本回合所有阶段（存玩家ID，与 end_turn 的比较语义一致）
            room.skip_opponent_turn = opponent_id
            result['message'] = '牺牲两艘战舰，跳过对方本回合所有阶段'

    elif card.name == '绝处逢生':
        # 卡面：牺牲自己所有的战舰，然后在"所有原本有战舰的地方"选一格，
        # 放置唯一一艘战舰；此后击杀对方任何一艘船直接获胜。
        if caster.remaining_ships < 3:
            result['success'] = False
            result['message'] = '需要至少3艘战舰才能发动'
            return result

        original_cells = [(p.x, p.y) for sh in caster.ships for p in sh.positions]
        # 牺牲全部：进沉船堆（可被复活类卡牌回收），而不是凭空消失。
        # 已沉的船不重复入堆，否则复活类卡牌会把已沉的船再恢复一次。
        for sh in list(caster.ships):
            if sh not in caster.sunken_ships:
                caster.sunken_ships.append(sh)
        caster.ships = []
        caster.remaining_ships = 0

        # 神机妙算按"沉船差值"判定，牺牲不是被击沉，需同步快照避免误判
        snap = room.game_effects.get(f'prediction_initial_{caster_id}')
        if isinstance(snap, dict):
            snap['sunken'] = len(caster.sunken_ships)

        room.game_effects['last_stand_cells'] = original_cells
        # 生效回合内其余魔法卡无效 + 击杀任何船直接获胜
        room.players[caster_id].effect_flags.last_stand = True
        _start_placement(room, caster_id, 'last_stand', 1)
        result.temp_data_id = 'last_stand_choice'
        result['message'] = '已牺牲全部战舰，请在所有原本有战舰的格子上选择一格放置唯一一艘战舰'

    elif card.name == '死者苏生':
        # 复活一艘船：必须有已阵亡的战舰，否则不可用
        if caster.remaining_ships >= 6:
            result['success'] = False
            result['message'] = '战舰数量已达上限'
            return result

        if not caster.sunken_ships:
            result['success'] = False
            result['message'] = '没有可复活的战舰'
            return result

        _start_placement(room, caster_id, 'revive', 1)
        result.temp_data_id = 'revive_choice'
        result['message'] = '请选择复活战舰的部署位置（未被攻击过的空格）'

    elif card.name == '疗愈':
        # 复活至多两艘被击杀的船：必须有沉船，逐艘选择位置
        if caster.remaining_ships >= 6:
            result['success'] = False
            result['message'] = '战舰数量已达上限'
            return result

        if not caster.sunken_ships:
            result['success'] = False
            result['message'] = '没有可复活的战舰'
            return result

        # 卡面："选定自己至多两艘被击杀的船并将他们在原地复活。"
        # 原先走的是"选一个未被打过的新格子"的放置流程，与卡面不符。
        count = min(2, len(caster.sunken_ships), 6 - caster.remaining_ships)
        revived = _revive_sunken_ships(room, caster, count)
        _emit_ships_updated(room)
        _emit_player_ships(room, caster_id)
        result['message'] = f'疗愈生效，{revived} 艘战舰在原地复活'

    elif card.name == '盗亦有道':
        # 获取对方打出的上一张魔法卡
        if not room.magic_history or room.magic_history[-1]['caster'] == caster_id:
            result['success'] = False
            result['message'] = '对方没有使用过魔法卡'
            return result

        stolen_entry = room.magic_history[-1]
        stolen_card = stolen_entry['card']
        # 同一条历史只能被偷一次，否则可反复盗取同一张卡造成卡牌增殖
        if stolen_entry.get('stolen'):
            result['success'] = False
            result['message'] = '该魔法卡已被盗取过'
            return result

        # 从弃牌堆中移除对应卡牌，保证是"转移"而非"复制"
        # （非场地卡在出牌时即进入弃牌堆，不移除会出现弃牌堆与手牌同时存在的副本）
        for i, c in enumerate(room.magic_discard):
            if c is stolen_card or (c.name == stolen_card.name and c.speed == stolen_card.speed):
                room.magic_discard.pop(i)
                break

        stolen_entry['stolen'] = True
        caster.magic_hand.append(stolen_card)

        result['message'] = f'成功盗取对方的{stolen_card.name}'

    elif card.name == '回光返照':
        # 只能在自己先手时发动
        if room.attack_order and room.attack_order[0] != caster_id:
            result['success'] = False
            result['message'] = '只能在自己先手时发动'
            return result

        # 清空棋盘重新摆放6艘船
        caster.ships = []
        caster.attacks = []
        caster.remaining_ships = 0
        # 标记需要重新摆放
        room.players[caster_id].needs_reset = True
        # 清空对方视角
        room.players[opponent_id].revealed_positions = []
        
        # 跳过自己的战斗阶段
        room.current_phase = 'end'
        
        # 设置效果：如果对方在这一大回合内对自己的船造成伤害，自己直接判负
        room.game_effects['last_chance'] = {
            'caster': caster_id,
            'active': True,
            'round': room.round,
        }

        result['message'] = '已清空棋盘，请重新摆放战舰，本回合战斗阶段跳过。若对方在本大回合内对您的船造成伤害，您将直接判负'

    elif card.name == '加百列之光':
        # 无效化对方上一张魔法卡（连锁中=栈顶下方那一项）和当前生效的场地魔法
        negated_count = 0
        if room.chain and room.chain[-1].player_id != caster_id:
            result.negate_target = True
            negated_count += 1
        elif not room.chain and room.magic_history and room.magic_history[-1]['caster'] != caster_id:
            room.magic_history.pop()
            negated_count += 1

        # 无效化当前已生效的场地魔法（只针对对方的场地，不能拆自己的）
        if room.field_magic and getattr(room, 'field_magic_owner', None) != caster_id:
            negated_count += 1
            room.magic_discard.append(room.field_magic)
            _clear_field_magic_effects(room)
            room.field_magic = None
            room.field_magic_owner = None
            emit('field_magic_updated', {'player_id': caster_id, 'card': None}, room=room.id)

        result['message'] = f'成功无效化{negated_count}个效果'

    elif card.name == '钢筋铁骨':
        # 牺牲一艘船，其他船进入无敌状态
        if caster.remaining_ships < 2:
            result['success'] = False
            result['message'] = '需要至少2艘战舰才能发动'
            return result

        # 牺牲一艘船（进入沉船堆，可被复活类卡牌回收）。
        # 注意：普通击沉只减 remaining_ships、不会把船从 ships 里移除，
        # 所以不能直接 pop 列表末尾 —— 那可能是一艘已沉的船，等于零代价发动，
        # 还会让沉船堆出现重复条目（复活类卡牌按 len(sunken_ships) 恢复时
        # 会把船数算多，产生幽灵船）。
        alive_ships = [sh for sh in caster.ships if sh not in caster.sunken_ships]
        if not alive_ships:
            result['success'] = False
            result['message'] = '没有可牺牲的战舰'
            return result
        popped = alive_ships[-1]
        caster.ships.remove(popped)
        if popped not in caster.sunken_ships:
            caster.sunken_ships.append(popped)
        caster.remaining_ships -= 1

        # 其他船进入无敌状态
        for ship in caster.ships:
            ship.invincible = True

        result['message'] = '牺牲一艘战舰，其他战舰进入无敌状态'

    elif card.name == '神机妙算':
        # 宣言x：若结束阶段自己船数减少恰好x，那些船不减少。
        # 尚未宣言 → 请求玩家宣言；已宣言（confirm 落临时数据）→ 直接生效。
        if 'prediction' not in room.magic_temp_data:
            room.magic_temp_data['pending_shenji'] = {'caster': caster_id}
            result.temp_data_id = 'shenji_declare'
            result.message = '请宣言预测减少的船数（0-6）'
        else:
            x = room.magic_temp_data.get('prediction')
            try:
                x = max(0, min(6, int(x)))
            except Exception:
                x = 0
            _apply_shenji_prediction(room, caster_id, x, result)

    # ==== 场地魔法卡 ====
    elif card.type == '场地':
        # 场地魔法处理 - 全场只能有一张场地魔法卡生效。
        # 将实例放入场地区域；被顶掉的旧卡实例移入弃牌堆（不造副本）。
        _place_field_magic(room, caster_id, card)

        if card.name == '恶魔契约':
            room.game_effects['demon_contract'] = True
            result.message = '恶魔契约生效，双方船数增减绑定'
        elif card.name == '禁忌果实':
            result.message = '禁忌果实生效，双方只能使用失灵！和场地魔法'
        elif card.name == '伊甸园':
            result.message = '伊甸园生效，攻击次数变为6-n'
            if room.state == 'attacking' and getattr(room, 'current_phase', None) == 'preparation' and room.current_attacker in room.players:
                # 场地变更需要整体重算（不是"船数增减"），用 _recalc
                _recalc_attacker_attacks(room)
                emit('attacks_updated', {
                    'current_attacker': room.current_attacker,
                    'attacks_remaining': room.attacks_remaining
                }, room=room.id)
        # 注意：教皇旨意在上面的场地魔法分支之前就被 elif card.name 捕获，
        # 这里原本还有一份重复分支，永远不可达，已删除。

    # ==== 已实现的魔法卡 ====
    elif card.name == '失灵！':
        # 连锁结算中：康紧邻下方那一项（对方打出的“上一张”）
        if room.chain:
            target = room.chain[-1]
            if target.player_id == caster_id:
                result.success = False
                result.message = '没有可无效化的魔法卡'
                return result
            tname = getattr(target.card, 'name', None)
            if tname == '看破！':
                result.success = False
                result.message = '看破！优先于失灵！，无法无效化'
                return result
            if tname == '加百列之光':
                result.success = False
                result.message = '加百列之光免疫失灵！'
                return result
            result.negate_target = True
            result.message = f'将无效化{target.card.name}'
            return result
        # 直接调用（无连锁栈）时回退历史记录。
        # 卡面："无效化对方使用的上一张魔法卡，被影响的魔法卡必须为当前时段刚使用的。"
        if room.magic_history and room.magic_history[-1]['caster'] != caster_id:
            last_magic = room.magic_history[-1]
            if getattr(last_magic.get('card'), 'name', None) in ('看破！', '加百列之光'):
                result.success = False
                result.message = '该魔法免疫失灵！'
                return result
            # 只允许无效化本大回合内刚使用的卡（老条目没有 round 时按旧行为放行）
            if last_magic.get('round', room.round) != room.round:
                result.success = False
                result.message = '对方上一张魔法卡不是本回合使用的，失灵！无法无效化'
                return result
            room.magic_history.pop()
            result.message = f'无效化了{last_magic["card"].name}（若其效果已结算则不会回滚）'
            result.negated = last_magic
        else:
            result.success = False
            result.message = '没有可无效化的魔法卡'

    elif card.name == '看破！':
        # 无效化对方本回合所有魔法卡
        room.players[opponent_id].magic_blocked = True
        result.message = '本回合对方魔法卡被无效化'

    elif card.name == '增援':
        # 召唤一艘战舰：等待玩家选择放置位置
        if caster.remaining_ships >= 6:
            result.success = False
            result.message = '战舰数量已达上限'
        else:
            _start_placement(room, caster_id, 'reinforce', 1)
            result.temp_data_id = 'reinforcement_choice'
            result.message = '请选择增援战舰的部署位置（未被攻击过的空格）'

    else:
        result.success = False
        result.message = f'未实现的魔法卡: {card.name}'



    
    #result['success'] = False
    #result['message'] = f'魔法效果应用失败: {str(e)}'

    # 魔法卡消灭对方最后一艘船时也判定游戏结束（与攻击路径一致）
    # 注意：对方从未布船（ships 为空，如测试构造态/未开局）不算被消灭，
    # 否则在空房间出任何一张卡都会直接判胜。
    if (opponent and opponent.remaining_ships <= 0 and len(opponent.ships) > 0
            and room.state != 'game_over'):
        room.state = 'game_over'
        room.winner = caster_id
        add_game_log(room, f"第{room.round}回合 · {_log_name(room, caster_id)} 获胜，游戏结束", 'result', {'winner': caster_id, 'loser': opponent_id})
        try:
            winner_user_id = room.players[caster_id].user_id
            loser_user_id = room.players[opponent_id].user_id
            if winner_user_id or loser_user_id:
                db.record_match(winner_user_id or caster_id, loser_user_id or opponent_id,
                                getattr(room, 'game_logs', None), count_stats=_count_stats_for(room))
        except Exception:
            pass
        emit('game_over', {'winner': caster_id}, room=room.id)

    return result


def get_uuid() -> str:
    return str(uuid.uuid4())[:4]


@socketio.on('surrender')
@_require_live_room
def handle_surrender(data):
    # 处理投降请求
    player_id = data.get('player_id') or session.get('user_id', request.sid)
    room_id = data.get('room_id')
    room = room_manager.get_room(room_id)
    if not room:
        return {'status': 'error', 'message': '房间不存在'}

    # 必须通过身份校验：避免他人凭 room_id+player_id 替对手投降
    if player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '你不在这个房间'}

    # 设置游戏结束状态
    room.state = 'game_over'

    # 投降玩家失败，对手获胜
    opponent_id = next(p for p in room.players if p != player_id)
    room.winner = opponent_id

    # 记录战绩（若为已登录用户）
    try:
        winner_user_id = room.players[opponent_id].user_id
        loser_user_id = room.players[player_id].user_id
        # 只有当至少有一个是已登录用户时才记录
        if winner_user_id or loser_user_id:
            db.record_match(winner_user_id or opponent_id, loser_user_id or player_id,
                            getattr(room, 'game_logs', None), count_stats=_count_stats_for(room))
    except Exception:
        pass
    # 向房间发送游戏结束事件
    emit('game_over', {
        'winner': opponent_id,
        'reason': 'surrender'  # 添加投降原因标记
    }, room=room_id)
    return {'status': 'success'}


if __name__ == '__main__':
    # 初始化数据库
    db.init_db()
    # 添加详细日志输出

    logging.basicConfig(level=logging.DEBUG)
    # 启动服务器
    # 默认关闭调试模式（Werkzeug 调试器可被用于远程代码执行）；
    # 本地需要时设置环境变量 FLASK_DEBUG=1。
    socketio.run(
        app,
        debug=os.environ.get('FLASK_DEBUG') == '1',
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
    )
