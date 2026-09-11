import json
import random
import time
import uuid
import secrets
from typing import Any, Callable
import logging
from flask import render_template, request, session, jsonify
from flask_socketio import SocketIO, join_room, emit as semit

import db  # local database helpers for users and matches
from api import app
from file import read_json

# eventlet 下必须先 monkey_patch：否则后台任务里的 time.sleep 会阻塞整个
# 单线程 hub（掉线宽限 30s / 连锁超时 10s 都会让服务器假死）。
try:
    import eventlet
    eventlet.monkey_patch()
except ImportError:
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
        card = list(filter(lambda x: x.name == name, magic_cards))[0]
        self.speed = card.speed
        self.type = card.type
        self.description = card.description


class EffectFlags:
    treasure_hunter: bool = False
    prediction: bool = False
    subsidy: bool = False
    no_draw: bool = False
    forced_kill: int = 0  # 强制击杀次数
    vampire: bool = False  # 饮血效果
    last_stand: bool = False  # 绝处逢生效果
    double_attacks: bool = False
    battle_spirit: bool = False 

class Effect:
    name:str
    phase:str
    end_phase:str
    priority:int
    func:Callable[...,None]
    def __init__(self,name,phase,end_phase,priority,func):
        self.name=name
        self.phase = phase
        self.priority = priority
        self.func = func
        self.end_phase=end_phase


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
    effects:list[Effect]
    def __init__(self, room_id):
        self.id = room_id
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
        self.magic_discard = []  # 全局弃牌堆（所有玩家使用过的魔法卡）
        self.magic_deck = []  # 全局共享魔法卡堆
        # 连锁相关状态
        self.chain = []  # 连锁栈
        self.chain_waiting = False  # 是否有待响应的连锁窗口
        self.chain_timer = -1  # 连锁回应计时器（代际令牌）
        self.chain_window = None  # 当前响应窗口归属的玩家
        self.chain_passes = 0  # 连续放弃次数（达 2 即结算）
        self.effects=[]
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
    def pop_effect(self,name:str):
        for i in self.effects:
            if i.name == name:
                self.effects.remove(i)
    def apply_effect(self,end_phase:str):
        #效果结束判定
        for i in self.effects:
            if i.end_phase == end_phase:
                self.pop_effect(i.name)
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
        """将卡牌放入玩家的弃牌堆"""
        self.magic_discard.append(card)
        card_index = self.players[player_id].magic_hand.index(card)
        self.players[player_id].magic_hand.pop(card_index)
    
    def attack(self,target:Position,attacker_id="",enable_effects=True):
        # 找到对手
        if not attacker_id:
            attacker_id = self.current_attacker
        defender_id = next(p for p in self.players if p != attacker_id)
        defender_ships = self.players[defender_id].ships
        for effect in self.effects:
            if effect.phase== "before_attack":
                effect.func(self,attacker_id)
        # 检查是否击中
        hit = False
        ship_sunk = False
        for i, ship in enumerate(defender_ships):
            if target in ship.positions:
                hit = True
                ship_sunk = True
                defender_ships[i].hits.append(target)
        self.players[attacker_id].attacks.append(Position(**{
            "hit":hit,
            "ship_sunk":ship_sunk,
            **target
        }))
        for effect in self.effects:
            if effect.phase== "after_attack":
                effect.func(self,attacker_id,defender_id)
        attack=self.players[attacker_id].attacks[-1]
        self.players[attacker_id].remaining_ships-=attack.hit
        emit('ships_updated', {
            'player_remaining_ships': self.players[attacker_id].remaining_ships,
            'opponent_remaining_ships': self.players[defender_id].remaining_ships
        }, room=self.id)

        # 准备攻击结果
        attack_result = AttackResult(
            attacker=attacker_id,
            x=target.x,
            y=target.y,
            hit=hit,
            ship_sunk=ship_sunk,
            remaining_attacks=self.attacks_remaining,
            attacker_remaining_ships=self.players[attacker_id].remaining_ships,
            defender_remaining_ships=self.players[defender_id].remaining_ships
        )

        add_game_log(self, f"第{self.round}回合 · {_log_name(self, attacker_id)} 攻击 ({target.x},{target.y}) — {'命中' if hit else '未命中'}{'，击沉战舰' if ship_sunk else ''}",
                     'attack', {
                         'attacker': attacker_id,
                         'target': {'x': target.x, 'y': target.y},
                         'hit': hit,
                         'ship_sunk': ship_sunk
                     })

        emit('attack_result', attack_result, room=self.id)

        # 检查游戏是否结束
        if self.players[defender_id].remaining_ships == 0:
            self.state = 'game_over'
            self.winner = attacker_id
            add_game_log(self, f"第{self.round}回合 · {_log_name(self, attacker_id)} 获胜，游戏结束", 'result', {'winner': attacker_id, 'loser': defender_id})
            # 记录战绩（若为已登录用户）
            try:
                winner_user_id = self.players[attacker_id].user_id
                loser_user_id = self.players[defender_id].user_id
                # 只有当至少有一个是已登录用户时才记录
                if winner_user_id or loser_user_id:
                    db.record_match(winner_user_id or attacker_id, loser_user_id or defender_id, getattr(self, 'game_logs', None))
            except Exception:
                pass
            emit('game_over', {'winner': attacker_id}, room=self.id)


# 添加魔法卡牌数据定义（与客户端 magic_cards.js 保持一致）
magic_cards = list(map(lambda x: MagicCard(**x), read_json('./static/magic_card.json')))

socketio = SocketIO(app, cors_allowed_origins="*")

# 聊天消息最大长度
MAX_CHAT_MSG_LEN = 100

class RoomManager:
    def __init__(self):
        # 游戏房间数据结构
        self.rooms: dict[str, GameRoom] = {}
        # 匹配队列 [socket_ids, player_names, user_ids]
        self.match_queue: list[list[str], list[str], list[str]] = [[], [], []]
        # 大厅匹配队列（简单 FIFO 队列）
        self.lobby_queue = []
        # 简单的 lobby 成员列表（用于显示）
        self.lobby_members = set()
    
    # 房间管理方法
    def create_room(self, room_id: str = None) -> str:
        """创建新房间，返回房间ID"""
        if not room_id:
            room_id = str(uuid.uuid4())[:6]
        self.rooms[room_id] = GameRoom(room_id)
        return room_id
    
    def create_ai_room(self, player_id: str, player_name: str, player_user_id=None) -> str:
        """创建人机对战房间：预置AI玩家，真人随后 join_room 走正常双人开局流程"""
        room_id = str(uuid.uuid4())[:6]
        room = GameRoom(room_id)
        room.is_ai_room = True
        self.rooms[room_id] = room
        ai_id = 'ai-' + room_id
        room.players[ai_id] = Player(name='AI', ships=[], attacks=[], remaining_ships=0, user_id=None, sid=ai_id)
        room.init_player_magic(ai_id, magic_cards)
        return room_id

    def join_room(self, room_id: str, player_id: str, player_name: str, sid: str) -> bool:
        """玩家加入房间，返回是否成功"""
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
        if room_id in self.rooms:
            del self.rooms[room_id]
            return True
        return False
    
    def get_all_rooms(self) -> dict[str, GameRoom]:
        """获取所有房间"""
        return self.rooms
    
    # 匹配功能方法
    def add_to_match_queue(self, player_id: str, player_name: str) -> bool:
        """添加玩家到匹配队列，返回是否成功"""
        if player_id in self.match_queue[0]:
            return False
        
        self.match_queue[0].append(player_id)
        self.match_queue[1].append(player_name)
        return True
    
    def remove_from_match_queue(self, player_id: str) -> bool:
        """从匹配队列移除玩家，返回是否成功"""
        if player_id in self.match_queue[0]:
            index = self.match_queue[0].index(player_id)
            self.match_queue[0].pop(index)
            self.match_queue[1].pop(index)
            if len(self.match_queue[2]) > index:
                self.match_queue[2].pop(index)
            return True
        return False
    
    def has_player_in_match_queue(self, player_id: str) -> bool:
        """检查玩家是否在匹配队列中"""
        return player_id in self.match_queue[0]
    
    def get_match_queue_size(self) -> int:
        """获取匹配队列大小"""
        return len(self.match_queue[0])
    
    def process_match_queue(self, magic_cards: list[MagicCard]) -> list[dict]:
        """处理匹配队列，返回匹配结果列表"""
        matches = []
        
        while len(self.match_queue[0]) >= 2:
            # 从队列中取出前两个玩家
            player1 = self.match_queue[0].pop(0)
            player2 = self.match_queue[0].pop(0)
            
            # 再次检查是否是同一个玩家，确保不会匹配到自己
            if player1 == player2:
                # 将玩家放回队列末尾
                self.match_queue[0].append(player1)
                # 也要放回其他队列的数据
                if len(self.match_queue[1]) > 0:
                    self.match_queue[1].append(self.match_queue[1].pop(0))
                if len(self.match_queue[2]) > 0:
                    self.match_queue[2].append(self.match_queue[2].pop(0))
                continue
            
            # 创建新房间
            room_id = str(uuid.uuid4())[:6]
            room = GameRoom(room_id)
            self.rooms[room_id] = room
            
            # 获取玩家名称和user_id
            player1_name = self.match_queue[1].pop(0)
            player2_name = self.match_queue[1].pop(0)
            player1_user_id = self.match_queue[2].pop(0)
            player2_user_id = self.match_queue[2].pop(0)
            
            # 添加玩家到房间
            room.players[player1] = Player(**{
                'name': player1_name,
                'ships': [],
                'attacks': [],
                'remaining_ships': 0,
                'user_id': player1_user_id,
                'sid': player1  # 传递sid给Player构造函数
            })

            room.players[player2] = Player(**{
                'name': player2_name,
                'ships': [],
                'attacks': [],
                'remaining_ships': 0,
                'user_id': player2_user_id,
                'sid': player2  # 传递sid给Player构造函数
            })
            
            # 初始化魔法卡牌系统
            room.init_player_magic(player1, magic_cards)
            room.init_player_magic(player2, magic_cards)
            
            matches.append({
                'room_id': room_id,
                'players': [player1, player2],
                'room': room
            })
        
        return matches
    
    # 大厅功能方法
    def add_lobby_member(self, member_id: str) -> bool:
        """添加成员到大厅，返回是否成功"""
        if member_id in self.lobby_members:
            return False
        self.lobby_members.add(member_id)
        return True
    
    def remove_lobby_member(self, member_id: str) -> bool:
        """从大厅移除成员，返回是否成功"""
        if member_id in self.lobby_members:
            self.lobby_members.remove(member_id)
            return True
        return False
    
    def get_lobby_members(self) -> set[str]:
        """获取大厅成员列表"""
        return self.lobby_members

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


def _place_field_magic(room, caster_id, card):
    """将场地魔法卡实例放入场地区域；若已有不同名的旧卡，将其（实例）移入弃牌堆。
    返回被顶掉的旧卡（可能为 None）。"""
    old = room.field_magic
    room.field_magic = card
    if old and getattr(old, 'name', None) != card.name:
        room.magic_discard.append(old)
    emit('field_magic_updated', {'player_id': caster_id, 'card': card}, room=room.id)
    return old




# 测试功能：添加所有魔法卡到手牌
@socketio.on('test_add_all_magic_cards')
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
    emit('ships_updated', {
        'player_remaining_ships': player.remaining_ships,
        'opponent_remaining_ships': opponent.remaining_ships
    }, room=room_id)

    return {'status': 'success', 'message': f'已设置玩家船只数量为 {ship_count}'}


@socketio.on('test_clear_all_effects')
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
    
    # 创建人机对战房间
    room_id = room_manager.create_ai_room(player_id, player_name, player_user_id)
    
    # 让玩家加入房间
    join_room(room_id)
    
    # 返回房间信息
    return {
        'status': 'success',
        'room_id': room_id,
        'message': '人机对战房间创建成功'
    }


@socketio.on('test_set_opponent_ships')
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
    emit('ships_updated', {
        'player_remaining_ships': player.remaining_ships,
        'opponent_remaining_ships': opponent.remaining_ships
    }, room=room_id)

    return {'status': 'success', 'message': f'已设置对方船只数量为 {ship_count}'}


@socketio.on('test_end_turn')
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
    
    # 清理相关数据（连同 user_ids，避免匹配队列三列错位）
    if sid in room_manager.match_queue[0]:
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
    if socket_sid in room_manager.match_queue[0]:
        return {'status': 'error', 'message': '你已经在匹配队列中'}

    # 将玩家添加到匹配队列 (保存socket_id, player_name, user_id)
    room_manager.match_queue[0].append(socket_sid)
    room_manager.match_queue[1].append(player_name)
    room_manager.match_queue[2].append(user_id)
    emit('match_queued', {'status': 'success', 'message': '已加入匹配队列'})

    # 尝试匹配
    while len(room_manager.match_queue[0]) >= 2:
        # 从队列中取出前两个玩家
        player1 = room_manager.match_queue[0].pop(0)
        player2 = room_manager.match_queue[0].pop(0)
        player1_name = room_manager.match_queue[1].pop(0)
        player2_name = room_manager.match_queue[1].pop(0)
        player1_user_id = room_manager.match_queue[2].pop(0)
        player2_user_id = room_manager.match_queue[2].pop(0)

        # 再次检查是否是同一个玩家，确保不会匹配到自己
        if player1_user_id == player2_user_id:
            # 将玩家放回队列末尾
            room_manager.match_queue[0].append(player1)
            room_manager.match_queue[0].append(player2)
            room_manager.match_queue[1].append(player1_name)
            room_manager.match_queue[1].append(player2_name)
            room_manager.match_queue[2].append(player1_user_id)
            room_manager.match_queue[2].append(player2_user_id)
            continue

        # 创建新房间
        room_id = room_manager.create_room()
        room = room_manager.get_room(room_id)

        # 添加玩家到房间
        room.players[player1] = Player(**{
            'name': player1_name,
            'ships': [],
            'attacks': [],
            'remaining_ships': 0,
            'user_id': player1_user_id,
            'sid': player1  # 传递sid给Player构造函数
        })

        room.players[player2] = Player(**{
            'name': player2_name,
            'ships': [],
            'attacks': [],
            'remaining_ships': 0,
            'user_id': player2_user_id,
            'sid': player2  # 传递sid给Player构造函数
        })

        # 初始化魔法卡牌系统
        room.init_player_magic(player1, magic_cards)
        room.init_player_magic(player2, magic_cards)

        # 将玩家添加到Socket.IO房间（使用Socket会话ID）
        join_room(room_id, player1)
        join_room(room_id, player2)

        # 设置房间状态为放置战舰
        room.state = 'placing_ships'

        # 准备发送给两个玩家的游戏状态
        game_state_data = {
            'state': 'placing_ships',
            'room_id': room_id
        }

        # 为每个玩家添加对方的名字
        for player_sid in [player1, player2]:
            opponent_sid = player2 if player_sid == player1 else player1
            emit('game_state', {
                **game_state_data,
                'player_id': player_sid,
                'player_name': room.players[player_sid].name,
                'opponent_name': room.players[opponent_sid].name
            }, to=player_sid)
    return {'status': 'success', 'message': '开始寻找匹配'}


@socketio.on('cancel_match')
def handle_cancel_match(data):
    """处理玩家取消匹配请求：队列以 socket sid 为 key（find_match 存 request.sid），
    按当前连接的 request.sid 出队，兼容旧 user_id 形式兜底。"""
    sid = request.sid
    q = room_manager.match_queue
    removed = False
    if sid in q[0]:
        idx = q[0].index(sid)
        q[0].pop(idx); q[1].pop(idx)
        if idx < len(q[2]): q[2].pop(idx)
        removed = True
    else:
        # 兜底：按 user_id 列查找
        try:
            uid = session.get('user_id')
        except Exception:
            uid = None
        if uid and uid in q[2]:
            idx = q[2].index(uid)
            q[0].pop(idx); q[1].pop(idx); q[2].pop(idx)
            removed = True
    emit('match_canceled', {'status': 'success', 'message': '已取消匹配'}, to=sid)
    return {'status': 'success', 'message': '已取消匹配'}



@socketio.on('place_ships')
def handle_place_ships(data):
    room_id = data['room_id']
    player_id = data['player_id']
    ships = data['ships']
    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

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
        room.state = 'rock_paper_scissors'
        # 重置猜拳选择和处理标记，确保新的猜拳阶段从空开始
        room.rps_choices = {}
        room.rps_processed = False

        # 检查是否是灵气复苏或两极反转后的重新摆放
        if hasattr(room, 'lingqi_resurgence_applied') and room.lingqi_resurgence_applied:
            # 发送双方船数已调整的广播
            emit('game_message', {
                'message': '双方船数已调整，进入猜拳阶段',
                'type': 'info'
            }, room=room_id)
            # 清除标记
            room.lingqi_resurgence_applied = False

        emit('game_state', {'state': 'rock_paper_scissors'}, room=room_id)

    return {'status': 'success'}


@socketio.on('rps_choice')
def handle_rps_choice(data):
    room_id = data['room_id']
    player_id = data['player_id']
    choice = data['choice']  # 'rock', 'paper', 'scissors'

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

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
            'round': room.round
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


# 添加新的Socket事件处理
@socketio.on('select_magic_target')
def handle_magic_target(data):
    room_id = data['room_id']
    player_id = data['player_id']
    target_data = data['target_data']
    temp_data_id = data['temp_data_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 存储临时目标数据
    room.magic_temp_data = {**room.magic_temp_data, **target_data}

    # 如果是需要选择的操作，继续处理
    if temp_data_id == 'taoyuan_choice':
        # 处理桃园结义的选择
        caster_choice = target_data['caster_choice']
        opponent_choice = target_data['opponent_choice']

        # 分配卡牌
        caster = room.players[player_id]
        opponent = room.players[next(p for p in room.players if p != player_id)]

        caster.magic_hand.append(room.magic_temp_data['cards'][caster_choice])
        if opponent_choice < len(room.magic_temp_data['cards']) and opponent_choice != caster_choice:
            opponent.magic_hand.append(room.magic_temp_data['cards'][opponent_choice])

        # 剩余卡牌加入弃牌堆
        for i, card in enumerate(room.magic_temp_data['cards']):
            if i != caster_choice and i != opponent_choice:
                room.magic_discard.append(card)

        room.magic_temp_data = {}
        return {'status': 'success', 'message': '卡牌选择完成'}

    elif temp_data_id == 'bury_choice':
        # 处理明智埋葬的选择
        card_index = target_data['card_index']
        caster = room.players[player_id]

        if 0 <= card_index < len(caster.magic_hand):
            # 将选中的卡放入弃牌堆
            room.discard_card(player_id, caster.magic_hand[card_index])
            # 抽一张新卡
            room.draw_card(player_id)
            room.magic_temp_data = {}
            return {'status': 'success', 'message': '埋葬完成'}

        return {'status': 'error', 'message': '无效的选择'}

    elif temp_data_id == 'shield_choice':
        # 处理仁王之盾的选择
        ship_indices = target_data['ship_indices'][:3]  # 最多选择3艘
        caster = room.players[player_id]

        for idx in ship_indices:
            if 0 <= idx < len(caster.ships):
                caster.ships[idx].shield = True

        room.magic_temp_data = {}
        return {'status': 'success', 'message': f'为{len(ship_indices)}艘战舰添加了护盾'}

    return {'status': 'success'}


# 修改攻击处理函数，添加魔法效果检查
def frozen_ship_count(player) -> int:
    """统计处于冻结状态的战舰数（冻结的船不提供攻击次数）。"""
    return sum(1 for s in player.ships if getattr(s, 'frozen', None))


def _check_last_chance(room, attacker_id: str, defender_id: str) -> bool:
    """回光返照：对使用者的船造成伤害则其直接判负。返回是否触发。"""
    if room.game_effects.get('last_chance') and room.game_effects['last_chance']['caster'] == defender_id:
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
                db.record_match(winner_user_id or attacker_id, loser_user_id or defender_id, getattr(room, 'game_logs', None))
        except Exception:
            pass
        emit('game_over', {'winner': attacker_id}, room=room.id)
        return True
    return False


@socketio.on('attack')
def handle_attack(data):
    room_id = data['room_id']
    attacker_id = data['player_id']
    target_x = data['x']
    target_y = data['y']

    room = room_manager.get_room(room_id)
    if not room or attacker_id not in room.players or not _identity_ok(room, attacker_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    frz = _frozen_reason(room, attacker_id)
    if frz:
        return {'status': 'error', 'message': frz}

    # 检查是否是当前攻击者
    if attacker_id != room.current_attacker:
        return {'status': 'error', 'message': '还没到你的攻击回合'}

    # 新增：检查当前是否为战斗阶段
    if room.current_phase != 'battle':
        return {'status': 'error', 'message': '当前不是战斗阶段'}

    # 检查是否已经攻击过这个位置
    if any(a.x == target_x and a.y == target_y for a in room.players[attacker_id].attacks):
        return {'status': 'error', 'message': '你已经攻击过这个位置了'}

    # 找到对手
    defender_id = next(p for p in room.players if p != attacker_id)
    defender_ships = room.players[defender_id].ships

    # 神威！：被扣掉的区域不可攻击
    if _cell_in_shenwei_hole(room, defender_id, target_x, target_y):
        return {'status': 'error', 'message': '该区域已被神威！扣掉，无法攻击'}

    # 检查是否击中
    hit = False
    ship_sunk = False
    for i, ship in enumerate(defender_ships):
        if {'x': target_x, 'y': target_y} in ship.positions:
            hit = True
            
            # 更新无暇圣心效果：如果有伤害，标记no_damage为False
            if 'holy_heart' in room.game_effects and not ship.invincible:  # 无敌状态不算造成伤害
                room.game_effects['holy_heart']['no_damage'] = False

            # 检查攻击者是否有强制击杀效果
            has_forced_kill = room.players[attacker_id].effect_flags.forced_kill > 0

            if has_forced_kill:
                # 强制击杀效果，忽略无敌和盾牌状态，直接击杀
                # 记录击中位置
                defender_ships[i].hits = defender_ships[i].hits + [Position(x=target_x, y=target_y)]

                # 直接击沉，不管当前击中次数
                ship_sunk = True
                defender_remaining_before = room.players[defender_id].remaining_ships
                room.players[defender_id].remaining_ships -= 1
                defender_remaining_after = room.players[defender_id].remaining_ships

                # 记录被击沉的船到sunken_ships（用于死者苏生/疗愈）
                room.players[defender_id].sunken_ships.append(defender_ships[i])

                # 记录船数变化（用于平等条约），保存ship对象以便完全回滚
                room.game_effects['last_ship_change'] = {
                    'player': defender_id,
                    'count': defender_remaining_before - defender_remaining_after,
                    'ship': defender_ships[i],  # 保存ship引用用于平等条约回滚
                    'hits_added': [Position(x=target_x, y=target_y)]
                }

                # 恶魔契约: 绑定船数增减 - 任意一方船被击杀，另一方也要牺牲一艘
                if room.game_effects.get('demon_contract'):
                    # 被击沉的是 defender 的船，attacker 要牺牲一艘
                    sacrifice_player_id = attacker_id
                    sacrifice_player = room.players[sacrifice_player_id]
                    if sacrifice_player.ships:
                        sacr_ship = random.choice(sacrifice_player.ships)
                        sacrifice_player.ships.remove(sacr_ship)
                        sacrifice_player.sunken_ships.append(sacr_ship)
                        sacrifice_player.remaining_ships -= 1
                        emit('ships_updated', {
                            'player_remaining_ships': room.players[attacker_id].remaining_ships,
                            'opponent_remaining_ships': room.players[defender_id].remaining_ships
                        }, room=room_id)
                        emit('message', {'text': '恶魔契约生效，对方牺牲一艘战舰'}, to=room.players[defender_id].sid)

                # 检查无暇圣心效果：如果有战舰被击沉，中断效果
                if 'holy_heart' in room.game_effects:
                    # 移除无暇圣心效果
                    del room.game_effects['holy_heart']
                    # 通知客户端无暇圣心效果被中断
                    emit('holy_heart_interrupted', {
                        'reason': '有战舰被击沉，无暇圣心效果中断'
                    }, room=room_id)

                # 检查饮血效果
                if room.players[attacker_id].effect_flags.vampire:
                    room.draw_card(attacker_id)
                    emit('message', {'text': '饮血效果发动，抽一张卡'}, to=room.players[attacker_id].sid)

                # 检查越战越勇效果
                if room.players[attacker_id].effect_flags.battle_spirit:
                    room.attacks_remaining += 1
                    emit('message', {'text': '越战越勇效果发动，攻击次数净增加1'}, room=room_id)
                
                # 更新本回合伤害统计
                room.players[attacker_id].damage_dealt_this_turn += 1

                # 检查绝处逢生效果
                if room.players[attacker_id].effect_flags.last_stand:
                    # 直接获胜
                    room.state = 'game_over'
                    room.winner = attacker_id
                    add_game_log(room, f"第{room.round}回合 · {_log_name(room, attacker_id)} 触发绝处逢生并获胜", 'result', {
                        'winner': attacker_id,
                        'loser': defender_id
                    })
                    # 记录战绩（若为已登录用户）
                    try:
                        # 如果是游客（sid），db.record_match 会忽略不存在的用户
                        opponent_id = next(p for p in room.players if p != attacker_id)
                        winner_user_id = room.players[attacker_id].user_id
                        loser_user_id = room.players[opponent_id].user_id
                        # 只有当至少有一个是已登录用户时才记录
                        if winner_user_id or loser_user_id:
                            db.record_match(winner_user_id or attacker_id, loser_user_id or opponent_id, getattr(room, 'game_logs', None))
                    except Exception:
                        pass
                    emit('game_over', {'winner': attacker_id}, room=room_id)
                    return {'status': 'success', 'game_over': True}
                
                # 检查回光返照效果（统一走 _check_last_chance）
                if _check_last_chance(room, attacker_id, defender_id):
                    return {'status': 'success', 'game_over': True}

                # 发送战舰数更新事件
                if ship_sunk:
                    emit('ships_updated', {
                        'player_remaining_ships': room.players[attacker_id].remaining_ships,
                        'opponent_remaining_ships': room.players[defender_id].remaining_ships
                    }, room=room_id)

                    # 百亿补贴: 自己的船被击败时攻击次数+3
                    if room.players[defender_id].effect_flags.subsidy:
                        room.attacks_remaining += 3
                        emit('message', {'text': '百亿补贴生效，攻击次数增加3次'}, to=room.players[defender_id].sid)

                    # 八方来财: 战舰数目变化时抽一张牌
                    if room.players[defender_id].effect_flags.treasure_hunter:
                        room.draw_card(defender_id)
                        emit('message', {'text': '八方来财生效，摸一张牌'}, to=room.players[defender_id].sid)

                # 减少强制击杀效果的剩余次数
                room.players[attacker_id].effect_flags.forced_kill -= 1
                # 如果剩余次数为0，移除该效果
                if room.players[attacker_id].effect_flags.forced_kill <= 0:
                    del room.players[attacker_id].effect_flags.forced_kill
            else:
                # 没有强制击杀效果，检查目标船是否有特殊状态
                if ship.invincible:
                    # 无敌状态，只显形不造成伤害
                    ship_sunk = False
                elif ship.shield:
                    # 盾牌状态，抵挡一次伤害
                    ship_sunk = False
                    ship.shield = False
                else:
                    # 记录击中位置
                    defender_ships[i].hits = defender_ships[i].hits + [Position(x=target_x, y=target_y)]

                    # 检查回光返照效果：造成伤害即判负（与强制击杀分支一致）
                    if _check_last_chance(room, attacker_id, defender_id):
                        return {'status': 'success', 'game_over': True}

                    # 检查船是否被击沉
                    if len(defender_ships[i].hits) == len(defender_ships[i].positions):
                        ship_sunk = True
                        defender_remaining_before = room.players[defender_id].remaining_ships
                        room.players[defender_id].remaining_ships -= 1
                        defender_remaining_after = room.players[defender_id].remaining_ships

                        # 记录被击沉的船到sunken_ships（用于死者苏生/疗愈）
                        room.players[defender_id].sunken_ships.append(defender_ships[i])

                        # 记录船数变化（用于平等条约），保存ship对象以便完全回滚
                        room.game_effects['last_ship_change'] = {
                            'player': defender_id,
                            'count': defender_remaining_before - defender_remaining_after,
                            'ship': defender_ships[i],  # 保存ship引用用于平等条约回滚
                            'hits_added': [Position(x=target_x, y=target_y)]
                        }

                        # 百亿补贴: 自己的船被击败时攻击次数+3
                        if room.players[defender_id].effect_flags.subsidy:
                            room.attacks_remaining += 3
                            emit('message', {'text': '百亿补贴生效，攻击次数增加3次'}, to=room.players[defender_id].sid)

                        # 恶魔契约: 绑定船数增减
                        if room.game_effects.get('demon_contract'):
                            sacrifice_player_id = attacker_id
                            sacrifice_player = room.players[sacrifice_player_id]
                            if sacrifice_player.ships:
                                sacr_ship = random.choice(sacrifice_player.ships)
                                sacrifice_player.ships.remove(sacr_ship)
                                sacrifice_player.sunken_ships.append(sacr_ship)
                                sacrifice_player.remaining_ships -= 1
                                emit('ships_updated', {
                                    'player_remaining_ships': room.players[attacker_id].remaining_ships,
                                    'opponent_remaining_ships': room.players[defender_id].remaining_ships
                                }, room=room_id)
                                emit('message', {'text': '恶魔契约生效，对方牺牲一艘战舰'}, to=room.players[defender_id].sid)

                        # 八方来财: 战舰数目变化时抽一张牌
                        if room.players[defender_id].effect_flags.treasure_hunter:
                            room.draw_card(defender_id)
                            emit('message', {'text': '八方来财生效，摸一张牌'}, to=room.players[defender_id].sid)

                        # 检查无暇圣心效果：如果有战舰被击沉，中断效果
                        if 'holy_heart' in room.game_effects:
                            # 移除无暇圣心效果
                            del room.game_effects['holy_heart']
                            # 通知客户端无暇圣心效果被中断
                            emit('holy_heart_interrupted', {
                                'reason': '有战舰被击沉，无暇圣心效果中断'
                            }, room=room_id)

                        # 检查饮血效果
                        if room.players[attacker_id].effect_flags.vampire:
                            room.draw_card(attacker_id)
                            emit('message', {'text': '饮血效果发动，抽一张卡'}, to=room.players[attacker_id].sid)
                        
                        # 检查越战越勇效果（仅在击沉战舰时触发）
                        if room.players[attacker_id].effect_flags.battle_spirit:
                            room.attacks_remaining += 1
                            emit('message', {'text': '越战越勇效果发动，攻击次数净增加1'}, room=room.id)

                        # 更新本回合伤害统计
                        room.players[attacker_id].damage_dealt_this_turn += 1

                    # 检查绝处逢生效果
                    if room.players[attacker_id].effect_flags.last_stand:
                        # 直接获胜
                        room.state = 'game_over'
                        room.winner = attacker_id
                        add_game_log(room, f"第{room.round}回合 · {_log_name(room, attacker_id)} 触发绝处逢生并获胜", 'result', {
                            'winner': attacker_id,
                            'loser': defender_id
                        })
                        # 记录战绩（若为已登录用户）
                        try:
                            # 如果是游客（sid），db.record_match 会忽略不存在的用户
                            opponent_id = next(p for p in room.players if p != attacker_id)
                            winner_user_id = room.players[attacker_id].user_id
                            loser_user_id = room.players[opponent_id].user_id
                            # 只有当至少有一个是已登录用户时才记录
                            if winner_user_id or loser_user_id:
                                db.record_match(winner_user_id or attacker_id, loser_user_id or opponent_id, getattr(room, 'game_logs', None))
                        except Exception:
                            pass
                        emit('game_over', {'winner': attacker_id}, room=room_id)
                        return {'status': 'success', 'game_over': True}

                    # 发送战舰数更新事件
                    emit('ships_updated', {
                        'player_remaining_ships': room.players[attacker_id].remaining_ships,
                        'opponent_remaining_ships': room.players[defender_id].remaining_ships
                    }, room=room_id)
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

    # 检查游戏是否结束
    if room.players[defender_id].remaining_ships == 0:
        room.state = 'game_over'
        room.winner = attacker_id
        add_game_log(room, f"第{room.round}回合 · {_log_name(room, attacker_id)} 获胜，游戏结束", 'result', {
            'winner': attacker_id,
            'loser': defender_id
        })
        # 记录战绩（若为已登录用户）
        try:
            winner_user_id = room.players[attacker_id].user_id
            loser_user_id = room.players[defender_id].user_id
            # 只有当至少有一个是已登录用户时才记录
            if winner_user_id or loser_user_id:
                db.record_match(winner_user_id or attacker_id, loser_user_id or defender_id, getattr(room, 'game_logs', None))
        except Exception:
            pass
        emit('game_over', {'winner': attacker_id}, room=room_id)
        return {'status': 'success', 'game_over': True}

    # 攻击次数为0时，不自动切换攻击者，让玩家手动进入结束阶段
    # 玩家需要点击"进入结束阶段"按钮来结束当前回合
    if room.attacks_remaining == 0:
        # 只发送攻击次数更新，不切换攻击者
        emit('attacks_updated', {
            'current_attacker': room.current_attacker,
            'attacks_remaining': room.attacks_remaining
        }, room=room_id)

    return {'status': 'success'}


@socketio.on('enter_battle_phase')
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
            # 翻倍当前攻击次数
            room.attacks_remaining = room.players[player_id].remaining_ships * 2
            # 广播攻击次数更新
            emit('attacks_updated', {
                'current_attacker': room.current_attacker,
                'attacks_remaining': room.attacks_remaining
            }, room=room_id)
            # 移除翻倍效果，因为它只持续一个大回合
            room.players[player_id].effect_flags.double_attacks = False
        if field_magic_name(room) == "教皇旨意":
            room.attacks_remaining = 0
        # 广播阶段更新
        emit('phase_updated', {
            'current_phase': room.current_phase,
            'current_attacker': room.current_attacker
        }, room=room_id)
        return {'status': 'success'}

    return {'status': 'error', 'message': '无法进入战斗阶段'}


# 添加结束战斗阶段，进入结束阶段
@socketio.on('enter_end_phase')
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
        
        # 清除越战越勇效果
        room.players[player_id].effect_flags.battle_spirit=False
        
        emit('phase_updated', {
            'current_phase': room.current_phase,
            'current_attacker': room.current_attacker
        }, room=room_id)

        return {'status': 'success', 'message': '已进入结束阶段'}


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
def end_turn(data):
    room_id = data['room_id']
    player_id = data['player_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    frz = _frozen_reason(room, player_id)
    if frz:
        return {'status': 'error', 'message': frz}

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
                for s in room.players[p_id].ships:
                    if getattr(s, 'frozen', None) and s.frozen < room.round:
                        del s.frozen

            # 更新并检查极限增援效果
            if 'reinforcement_check' in room.game_effects:
                check = room.game_effects['reinforcement_check']
                # 更新剩余回合计数
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

                    # 直接结束游戏
                    room.state = 'game_over'
                    room.winner = winner

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
                            for _ in range(min(pred, len(player.sunken_ships))):
                                revived = player.sunken_ships.pop()
                                if revived not in player.ships:
                                    player.ships.append(revived)
                                player.remaining_ships += 1
                            del room.game_effects[f'prediction_initial_{p_id}']
                        room.players[p_id].effect_flags.prediction = 0

            # 重置所有临时效果标志，包括no_draw标志
            for p_id in room.players:
                # 保留场地魔法等永久效果，清除所有临时效果（包括no_draw）
                permanent_flags = ['holy_heart']  # 永久效果白名单（reinforcement_check不是玩家效果）
                room.players[p_id].effect_flags.__dict__ = {k: v for k, v in
                                                                room.players[p_id].effect_flags.__dict__.items() if
                                                                k in permanent_flags}

            # 广播进入猜拳阶段
            emit('game_state', {
                'state': 'rock_paper_scissors',
                'round': room.round
            }, room=room_id)
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
            room.attacks_remaining = max(0, room.players[room.current_attacker].remaining_ships - frozen_ship_count(room.players[room.current_attacker]))

            # 重置所有临时效果标志 - 但保留no_draw标志直到大回合结束
            for p_id in room.players:
                # 保留场地魔法等永久效果和no_draw标志，清除其他临时效果（prediction需存活到对方结束阶段）
                permanent_flags = ['holy_heart', 'reinforcement_check', 'no_draw', 'prediction']  # 永久效果白名单
                room.players[p_id].effect_flags.__dict__ = {k: v for k, v in
                                                                room.players[p_id].effect_flags.__dict__.items() if
                                                                k in permanent_flags}

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
        handle_enter_end_phase({'room_id': room_id, 'player_id': ai_id})
        time.sleep(0.5)
        end_turn({'room_id': room_id, 'player_id': ai_id})
    except Exception as e:
        print(f'AI turn error: {e}')


# 教皇旨意弃卡攻击
@socketio.on('papal_attack')
def handle_papal_attack(data):
    room_id = data['room_id']
    player_id = data['player_id']
    target_x = data['x']
    target_y = data['y']
    discard_card_index = data.get('discard_card_index')

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    frz = _frozen_reason(room, player_id)
    if frz:
        return {'status': 'error', 'message': frz}

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
    if discard_card_index is not None and 0 <= discard_card_index < len(player.magic_hand):
        discarded = player.magic_hand.pop(discard_card_index)
        room.magic_discard.append(discarded)
    elif discard_card_index is None:
        # 默认弃置第一张
        discarded = player.magic_hand.pop(0)
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
    """执行一次普通攻击（从handle_attack提取）"""
    defender_ships = defender.ships
    hit = False
    ship_sunk = False

    for i, ship in enumerate(defender_ships):
        if {'x': target_x, 'y': target_y} in ship.positions:
            hit = True
            if 'holy_heart' in room.game_effects and not ship.invincible:
                room.game_effects['holy_heart']['no_damage'] = False
            if not ship.invincible and not ship.shield:
                defender_ships[i].hits = defender_ships[i].hits + [{'x': target_x, 'y': target_y}]
                if len(defender_ships[i].hits) == len(defender_ships[i].positions):
                    ship_sunk = True
                    defender.remaining_ships -= 1
                    defender.sunken_ships.append(defender_ships[i])
                    room.game_effects['last_ship_change'] = {
                        'player': defender_id,
                        'count': 1,
                        'ship': defender_ships[i],
                        'hits_added': [Position(x=target_x, y=target_y)]
                    }
                    if room.game_effects.get('demon_contract'):
                        sacrifice_player = attacker_id
                        sacrifice_player_obj = room.players[sacrifice_player]
                        if sacrifice_player_obj.ships:
                            sacr_ship = random.choice(sacrifice_player_obj.ships)
                            sacrifice_player_obj.ships.remove(sacr_ship)
                            sacrifice_player_obj.sunken_ships.append(sacr_ship)
                            sacrifice_player_obj.remaining_ships -= 1
                            emit('ships_updated', {
                                'player_remaining_ships': room.players[list(room.players.keys())[0]].remaining_ships,
                                'opponent_remaining_ships': room.players[list(room.players.keys())[1]].remaining_ships
                            }, room=room_id)
                    if 'holy_heart' in room.game_effects:
                        del room.game_effects['holy_heart']
                        emit('holy_heart_interrupted', {'reason': '有战舰被击沉，无暇圣心效果中断'}, room=room_id)
                    if room.players[attacker_id].effect_flags.vampire:
                        room.draw_card(attacker_id)
                    if room.players[attacker_id].effect_flags.last_stand:
                        room.state = 'game_over'
                        room.winner = attacker_id
                        emit('game_over', {'winner': attacker_id}, room=room_id)
                        return {'game_over': True}
                    if _check_last_chance(room, attacker_id, defender_id):
                        return {'game_over': True}
                    if ship_sunk:
                        emit('ships_updated', {
                            'player_remaining_ships': room.players[attacker_id].remaining_ships,
                            'opponent_remaining_ships': room.players[defender_id].remaining_ships
                        }, room=room_id)
                        if room.players[attacker_id].effect_flags.subsidy:
                            room.attacks_remaining += 3
                        if defender.effect_flags.subsidy:
                            room.attacks_remaining += 3
                    break
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

    if room.players[defender_id].remaining_ships <= 0:
        room.state = 'game_over'
        room.winner = attacker_id
        emit('game_over', {'winner': attacker_id}, room=room_id)
        return {'status': 'success', 'game_over': True}

    return {'status': 'success'}


@socketio.on('use_magic_card')
def handle_use_magic_card(data):
    room_id = data['room_id']
    player_id = data['player_id']
    card = MagicCard(**data['card'])
    targets = data.get('targets', [])

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
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
        return {'status': 'error', 'message': f'当前阶段{room.current_phase}无法使用速阶{card.speed}的魔法卡'}

    # 找到并移除玩家手牌中的卡牌
    for i, c in enumerate(player.magic_hand):
        if c.name == card.name and c.speed == card.speed:
            player.magic_hand.pop(i)
            break
    if card.type != '场地':
        room.magic_discard.append(card)

    # 场地魔法卡不再在此预置：改由结算（apply_magic_effect 场地分支）实例入区，
    # 避免"打出即进弃牌堆 + 贴场"产生游离副本；被顶掉/被康时实例移入弃牌堆。

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


def can_play_magic_card(room, player_id, card):
    # 绝处逢生：生效回合内自己的其余魔法卡全部无效（last_stand 随回合标志重置自然过期）
    if room.players[player_id].effect_flags.last_stand:
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
        # 结束阶段不能使用魔法卡
        return False
    return False


CHAIN_RESPONSE_SECONDS = 10


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


def _can_respond_chain(room, player_id):
    """该玩家此刻能否打出速阶3响应连锁。AI 与已被看破者不参与。"""
    if not player_id or player_id.startswith('ai-'):
        return False
    player = room.players.get(player_id)
    if not player or player.magic_blocked:
        return False
    return bool(_speed3_cards(room, player_id))


def _chain_target_below(room, caster_id):
    """结算中：当前项已出栈，栈顶即“正下方那一项”（即将结算的下一张）。
    无效化类效果只能指向对方紧邻的下一张；没有/是自己牌则返回 None。"""
    if not room.chain:
        return None
    target = room.chain[-1]
    if target.player_id == caster_id:
        return None
    return target


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
                'speed3_cards': _speed3_cards(room, player_id),
                'countdown': CHAIN_RESPONSE_SECONDS,
            }, to=room.players[player_id].sid)
            _schedule_chain_timeout(room.id, room.chain_timer)
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
            # 场地魔法“贴了再拆”：先入场再被无效化拆除，避免凭空消失
            if getattr(card, 'type', None) == '场地':
                _place_field_magic(room, player_id, card)
                if room.field_magic is card:
                    room.magic_discard.append(card)
                    room.field_magic = None
                    emit('field_magic_updated',
                         {'player_id': player_id, 'card': None}, room=room.id)
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
            room.magic_history.append({'card': card, 'caster': player_id, 'timestamp': time.time()})

    # 广播连锁结算结果
    emit('chain_resolved', {
        'results': results
    }, room=room.id)

    # 重置连锁状态
    room.chain = []
    room.chain_waiting = False
    room.chain_window = None
    room.chain_passes = 0

    return results


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
            db.record_match(winner_user_id or other, loser_user_id or player_id, getattr(room, 'game_logs', None))
    except Exception:
        pass
    emit('game_over', {'winner': other, 'reason': 'opponent_disconnected'}, room=room_id)
    # 房间保留约 2 分钟：让掉线者重连时收到一次性警告
    socketio.start_background_task(_cleanup_ended_room, room_id, 120)


def _cleanup_ended_room(room_id: str, delay: float):
    time.sleep(delay)
    room_manager.delete_room(room_id)


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
        'ships': [{'positions': [{'x': s.x, 'y': s.y} for s in sh.positions]} for sh in p.ships],
        'hand': [{'name': c.name, 'speed': c.speed, 'type': c.type, 'description': c.description} for c in p.magic_hand],
        'attacks': [{'x': a.x, 'y': a.y, 'hit': a.hit} for a in getattr(p, 'attacks', [])],
        'opponent_remaining_ships': opp.remaining_ships if opp else 0,
        'shenwei_holes': list(room.game_effects.get('shenwei_holes') or []),
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
    ok = bool(room.reconnect_tokens.get(pid) == token)
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
    if field_magic_name(room) == '教皇旨意':
        room.attacks_remaining = 0
    elif field_magic_name(room) == '伊甸园':
        room.attacks_remaining = max(0, 6 - room.players[pid].remaining_ships)
    else:
        # 用 remaining_ships：ships 列表含已沉没的战舰，不能直接取长度
        room.attacks_remaining = max(0, room.players[pid].remaining_ships - frozen_ship_count(room.players[pid]))


# 添加处理连锁响应
@socketio.on('chain_response')
def chain_response(data):
    room_id = data['room_id']
    player_id = data['player_id']
    chain = data.get('chain', False)
    card = data.get('card')
    targets = data.get('targets', [])

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}

    if not room.chain_waiting:
        return {'status': 'error', 'message': '没有待处理的连锁请求'}

    # 只有当前响应窗口的玩家可以响应
    if room.chain_window and room.chain_window != player_id:
        return {'status': 'error', 'message': '当前不是你的连锁响应窗口'}

    # 关闭当前窗口
    room.chain_waiting = False
    room.chain_window = None

    if chain and card:
        card = MagicCard(**card)
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
        if not any(c.name == card.name and c.speed == card.speed for c in player.magic_hand):
            return {'status': 'error', 'message': '你没有这张魔法卡'}
        if int(card.speed) != 3:
            return {'status': 'error', 'message': '只能使用速阶3的卡牌进行连锁'}

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
def handle_remove_field_magic(data):
    room_id = data['room_id']
    player_id = data['player_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players or not _identity_ok(room, player_id):
        return {'status': 'error', 'message': '无效的房间或玩家'}
    if room and player_id in room.players:
        # 将场地魔法加入弃牌堆并清除场地（旧卡不在手牌，不能用 discard_card）
        if room.field_magic:
            room.magic_discard.append(room.field_magic)
            room.field_magic = None
        # 广播场地魔法更新
        emit('field_magic_updated', {
            'player_id': player_id,
            'card': None
        }, room=room_id)

    return {'status': 'success'}


@socketio.on('confirm_reinforcement_position')
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
    else:
        caster.ships.append(PlayerShip(positions=[Position(x=x, y=y)], hits=[]))
        caster.remaining_ships += 1
        msg = f'增援战舰已部署到 ({x},{y})'

    pending['remaining'] -= 1
    pending['placed'] += 1

    opponent_id = _opponent_of(room, player_id)
    emit('ships_updated', {
        'player_remaining_ships': caster.remaining_ships,
        'opponent_remaining_ships': room.players[opponent_id].remaining_ships if opponent_id else 0
    }, room=room.id)
    # 同步放置后的己方棋盘（只发给本人），让新船立刻显示
    emit('player_ships_updated', {
        'ships': [{'positions': [{'x': p.x, 'y': p.y} for p in sh.positions], 'hits': []}
                  for sh in caster.ships]
    }, to=room.players[player_id].sid)
    emit('message', {'text': msg}, to=room.players[player_id].sid)

    if pending['remaining'] > 0:
        _emit_placement_request(room, player_id)
    else:
        _finish_placement(room, player_id, pending['kind'])
    return {'status': 'success', 'message': msg}


@socketio.on('cancel_placement')
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
    return {'status': 'success', 'data': room.magic_temp_data}


@socketio.on('confirm_magic_target')
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
                # 如果有多张牌，给对方选一张（排除自己选的那张）
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

        # 重置房间状态，进入重新摆放阶段
        room.state = 'placing_ships'
        room.attack_order = []
        room.current_attacker = ""
        room.attacks_remaining = 0

        # 添加灵气复苏应用标记，用于后续广播
        room.lingqi_resurgence_applied = True

        # 通知双方进入重新摆放阶段，并发送新的船数限制
        for p_id in room.players:
            emit('reset_gameboard', {
                'new_max_ships': target_ships,
                'message': f'灵气复苏生效，双方需要重新摆放{target_ships}艘战舰'
            }, to=p_id)

        # 通知对手等待结束
        emit('lingqi_complete', {
            'message': '对方灵气复苏结算完成'
        }, to=room.players[opponent_id].sid)

        return {'status': 'success', 'message': '灵气复苏船数选择完成'}

    return {'status': 'error', 'message': '无效的临时数据ID'}


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

    # 百亿补贴：自己的船被击败时攻击次数 +3
    if lost_player.effect_flags.subsidy:
        room.attacks_remaining += 3
        emit('message', {'text': '百亿补贴生效，攻击次数增加3次'}, to=lost_player.sid)

    # 八方来财：战舰数目变化时抽一张牌
    if lost_player.effect_flags.treasure_hunter:
        room.draw_card(lost_player_id)
        emit('message', {'text': '八方来财生效，摸一张牌'}, to=lost_player.sid)

    # 恶魔契约：一方船数减少，另一方也牺牲一艘（一次结算只触发一次）
    if room.game_effects.get('demon_contract'):
        sacrifice_id = _opponent_of(room, lost_player_id)
        sacrifice_player = room.players.get(sacrifice_id) if sacrifice_id else None
        if sacrifice_player and sacrifice_player.ships:
            sacr_ship = random.choice(sacrifice_player.ships)
            sacrifice_player.ships.remove(sacr_ship)
            sacrifice_player.sunken_ships.append(sacr_ship)
            sacrifice_player.remaining_ships -= 1
            emit('message', {'text': '恶魔契约生效，对方牺牲一艘战舰'},
                 to=sacrifice_player.sid)


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
                            getattr(room, 'game_logs', None))
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
    emit('placement_request', {
        'kind': p['kind'],
        'remaining': p['remaining'],
        'total': p['total'],
        'placed': p['placed'],
        'blocked': _placement_blocked_cells(room, player_id),
    }, to=room.players[player_id].sid)


def _start_placement(room, caster_id, kind, count):
    """开启放置流程：kind='reinforce' 增援 / 'revive' 复活。"""
    room.magic_temp_data['pending_placement'] = {
        'caster': caster_id, 'kind': kind,
        'remaining': count, 'total': count, 'placed': 0,
    }
    _emit_placement_request(room, caster_id)


def _finish_placement(room, player_id, kind):
    room.magic_temp_data.pop('pending_placement', None)
    emit('placement_done', {'kind': kind}, to=room.players[player_id].sid)

    # 增援/复活改变了自己的船数，而攻击次数是按船数算的，必须立刻重算。
    # 例：绝境中增援一艘船 = 多一条命，同时本回合还多一次攻击。
    # 只在轮到本人攻击时重算，避免改到对方的攻击次数。
    _sync_attacks_after_ship_change(room, player_id)


def _sync_attacks_after_ship_change(room, player_id):
    """己方船数变化后同步攻击次数（仅当当前攻击者是本人时）。

    伊甸园/教皇旨意下 attacks_remaining 的算法不同，统一交给
    _recalc_attacker_attacks 处理，这里只负责判断该不该算。
    """
    if room.state != 'attacking':
        return
    if room.current_attacker != player_id:
        return
    _recalc_attacker_attacks(room)
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
        # 标记接下来两个攻击阶段造成的伤害将强制击杀
        room.players[caster_id].effect_flags.forced_kill = 2  # 持续2个攻击阶段
        result.message = '接下来两个攻击阶段将造成强制击杀'
        def func(room:GameRoom,attacker_id:str,defender_id:str):
            attack=room.players[attacker_id].attacks.pop()
            attack.hit=True
            attack.ship_sunk=True
            room.players[attacker_id].attacks.append(attack)
            room.players[attacker_id].effect_flags.forced_kill-=1
            if room.players[attacker_id].effect_flags.forced_kill==0:
                room.pop_effect(card.name)
        room.effects.append(Effect(card.name,"after_attack","after_attack",999,func))
    elif card.name == '桃园结义':
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
            'remaining_turns': total_turns  # 添加剩余回合计数
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
        room.players[caster_id].effect_flags.double_attacks = True
        result.message = '本回合攻击次数翻倍'
        def func(room:GameRoom):
            room.attacks_remaining*=2
            room.pop_effect(card.name)
        room.effects.append(Effect(card.name,"before_attack","",999,func))

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
        for p_id in room.players:
            player = room.players[p_id]
            emit('reset_gameboard', {
                'new_max_ships': player.max_ships,
                'message': '败者食尘生效，立即重启正常对局但保留双方的手牌'
            }, to=p_id)

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

                            # 百亿补贴: 自己的船被击败时攻击次数+3
                            if opponent.effect_flags.subsidy:
                                room.attacks_remaining += 3
                                emit('message', {'text': '百亿补贴生效，攻击次数增加3次'}, room=room.id)

                            # 八方来财
                            if opponent.effect_flags.treasure_hunter:
                                room.draw_card(opponent_id)
                                emit('message', {'text': '八方来财生效，摸一张牌'}, to=room.players[opponent_id].sid)

                            # 恶魔契约
                            if room.game_effects.get('demon_contract'):
                                sacrifice_player = caster
                                if sacrifice_player.ships:
                                    sacr_ship = random.choice(sacrifice_player.ships)
                                    sacrifice_player.ships.remove(sacr_ship)
                                    sacrifice_player.sunken_ships.append(sacr_ship)
                                    sacrifice_player.remaining_ships -= 1
                                    ships_changed = True

                            # 检查回光返照效果
                            if room.game_effects.get('last_chance') and room.game_effects['last_chance']['caster'] == opponent_id:
                                # 对使用回光返照的玩家造成了伤害，回光返照使用者直接判负
                                room.state = 'game_over'
                                room.winner = caster_id
                                add_game_log(room, f"第{room.round}回合 · {_log_name(room, opponent_id)} 触发回光返照失败并判负", 'result', {
                                    'winner': caster_id,
                                    'loser': opponent_id
                                })
                                # 记录战绩（若为已登录用户）
                                try:
                                    # 如果是游客（sid），db.record_match 会忽略不存在的用户
                                    winner_user_id = room.players[caster_id].user_id
                                    loser_user_id = room.players[opponent_id].user_id
                                    # 只有当至少有一个是已登录用户时才记录
                                    if winner_user_id or loser_user_id:
                                        db.record_match(winner_user_id or caster_id, loser_user_id or opponent_id, getattr(room, 'game_logs', None))
                                except Exception:
                                    pass
                                emit('game_over', {'winner': caster_id}, room=room.id)
                                return {'status': 'success', 'game_over': True}
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
            emit('ships_updated', {
                'player_remaining_ships': room.players[caster_id].remaining_ships,
                'opponent_remaining_ships': opponent.remaining_ships
            }, room=room.id)

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

        emit('ships_updated', {
            'player_remaining_ships': caster.remaining_ships,
            'opponent_remaining_ships': opponent.remaining_ships
        }, room=room.id)

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
                # 造成伤害：解除无暇圣心；记录本回合伤害（五险一金/Freezing!）
                if 'holy_heart' in room.game_effects:
                    room.game_effects['holy_heart']['no_damage'] = False
                caster.damage_dealt_this_turn += 1

                # 百亿补贴: 自己的船被击败时攻击次数+3
                if opponent.effect_flags.subsidy:
                    room.attacks_remaining += 3
                    emit('message', {'text': '百亿补贴生效，攻击次数增加3次'}, room=room.id)

                # 恶魔契约
                if room.game_effects.get('demon_contract'):
                    sacrifice_player = caster
                    if sacrifice_player.ships:
                        sacr_ship = random.choice(sacrifice_player.ships)
                        sacrifice_player.ships.remove(sacr_ship)
                        sacrifice_player.sunken_ships.append(sacr_ship)
                        sacrifice_player.remaining_ships -= 1
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
            emit('ships_updated', {
                'player_remaining_ships': room.players[caster_id].remaining_ships,
                'opponent_remaining_ships': opponent.remaining_ships
            }, room=room.id)

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
                # 造成伤害：解除无暇圣心；记录本回合伤害（五险一金/Freezing!）
                if 'holy_heart' in room.game_effects:
                    room.game_effects['holy_heart']['no_damage'] = False
                caster.damage_dealt_this_turn += 1

                # 八方来财: 战舰数目变化时抽一张牌
                if opponent.effect_flags.treasure_hunter:
                    room.draw_card(opponent_id)
                    emit('message', {'text': '八方来财生效，摸一张牌'}, to=room.players[opponent_id].sid)

                # 百亿补贴: 自己的船被击败时攻击次数+3
                if opponent.effect_flags.subsidy:
                    room.attacks_remaining += 3
                    emit('message', {'text': '百亿补贴生效，攻击次数增加3次'}, room=room.id)

                # 恶魔契约
                if room.game_effects.get('demon_contract'):
                    sacrifice_player = caster
                    if sacrifice_player.ships:
                        sacr_ship = random.choice(sacrifice_player.ships)
                        sacrifice_player.ships.remove(sacr_ship)
                        sacrifice_player.sunken_ships.append(sacr_ship)
                        sacrifice_player.remaining_ships -= 1
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
            emit('ships_updated', {
                'player_remaining_ships': room.players[caster_id].remaining_ships,
                'opponent_remaining_ships': opponent.remaining_ships
            }, room=room.id)

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
        # 每击杀一艘船，抽一张牌
        room.players[caster_id].effect_flags = room.players[caster_id].effect_flags
        room.players[caster_id].effect_flags.vampire = True
        result['message'] = '接下来自己的攻击，每击杀一艘船，自己摸一张牌。'

    elif card.name == '克苏鲁之眼':
        # 双方各暴露一艘船的位置
        if not caster.ships or not opponent.ships:
            result['success'] = False
            result['message'] = '双方都必须有战舰才能使用'
            return result

        # 随机选择一艘船暴露
        caster_ship = random.choice(caster.ships)
        opponent_ship = random.choice(opponent.ships)

        # 记录暴露的位置
        caster_positions = caster_ship.positions
        opponent_positions = opponent_ship.positions

        room.players[caster_id].revealed_positions = room.players[caster_id].revealed_positions
        room.players[opponent_id].revealed_positions = room.players[opponent_id].revealed_positions

        room.players[caster_id].revealed_positions.extend(opponent_positions)
        room.players[opponent_id].revealed_positions.extend(caster_positions)

        # 立即发送给双方对应玩家
        emit('revealed_positions', {'positions': opponent_positions}, to=room.players[caster_id].sid)
        emit('revealed_positions', {'positions': caster_positions}, to=room.players[opponent_id].sid)

        result['message'] = '双方各暴露一艘战舰位置'

    elif card.name == 'Freezing！':
        # 本回合未造成伤害时可发动，跳过对方回合
        if room.current_attacker != caster_id:
            result['success'] = False
            result['message'] = '必须在自己回合发动'
            return result

        # 检查是否造成过伤害（使用damage_dealt_this_turn而非a.round，因为Position.round从未被赋值）
        if caster.damage_dealt_this_turn > 0:
            result['success'] = False
            result['message'] = '本回合已造成伤害，无法发动'
            return result

        # 跳过对方回合
        room.skip_next_turn = opponent_id
        result['message'] = '成功跳过对方回合'

    elif card.name == '五险一金':
        # 本回合未造成伤害则增加攻击次数
        if caster.damage_dealt_this_turn == 0:
            room.attacks_remaining += 3
            result['message'] = '未造成伤害，攻击次数+3'
            # 广播攻击次数更新
            emit('attacks_updated', {
                'current_attacker': room.current_attacker,
                'attacks_remaining': room.attacks_remaining
            }, room=room.id)
        else:
            result['success'] = False
            result['message'] = '本回合已造成伤害，无法发动'

    elif card.name == '明智埋葬':
        # 选择一张不在弃牌堆中的魔法卡，将其放入弃牌堆并抽一张牌
        if not caster.magic_hand:
            result['success'] = False
            result['message'] = '手牌为空，无法发动'
            return result

        # 记录需要选择的牌（下标与手牌一致，客户端确认用 card_index）
        room.magic_temp_data = {
            'type': 'bury_choice',
            'caster': caster_id,
            'cards': caster.magic_hand
        }
        result['cards'] = [{'name': c.name, 'speed': c.speed, 'type': c.type, 'description': c.description} for c in caster.magic_hand]
        result['message'] = '请选择要埋葬的卡牌'
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
        # 船数改变时无效化导致改变的攻击/魔法
        if 'last_ship_change' not in room.game_effects:
            result['success'] = False
            result['message'] = '没有可无效化的船数改变效果'
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

        # 广播更新
        emit('ships_updated', {
            'player_remaining_ships': room.players[list(room.players.keys())[0]].remaining_ships,
            'opponent_remaining_ships': room.players[list(room.players.keys())[1]].remaining_ships
        }, room=room.id)

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

        # 牺牲两艘船（随机选择，因为无交互选择）
        sacrificed_ships = []
        for _ in range(2):
            if caster.ships:
                sacr = random.choice(caster.ships)
                sacrificed_ships.append(sacr)
                caster.ships.remove(sacr)
                caster.sunken_ships.append(sacr)
                caster.remaining_ships -= 1

        # 获取选择的效果
        effect_choice = room.magic_temp_data.get('effect_choice', 1)
        if effect_choice == 1:
            # 让对方随机选择一艘船死亡
            if opponent.ships:
                sacr_opponent = random.choice(opponent.ships)
                opponent.ships.remove(sacr_opponent)
                opponent.sunken_ships.append(sacr_opponent)
                opponent.remaining_ships -= 1
                emit('ships_updated', {
                    'player_remaining_ships': room.players[list(room.players.keys())[0]].remaining_ships,
                    'opponent_remaining_ships': room.players[list(room.players.keys())[1]].remaining_ships
                }, room=room.id)
            result['message'] = '牺牲两艘战舰，对方一艘战舰被摧毁'
        else:
            # 跳过对方本回合所有阶段（存玩家ID，与 end_turn 的比较语义一致）
            room.skip_opponent_turn = opponent_id
            result['message'] = '牺牲两艘战舰，跳过对方本回合所有阶段'

    elif card.name == '绝处逢生':
        # 牺牲所有船，只留一艘，之后击杀任何船直接获胜
        if caster.remaining_ships < 3:
            result['success'] = False
            result['message'] = '需要至少3艘战舰才能发动'
            return result

        # 保存一艘船
        remaining_ship = random.choice(caster.ships)
        caster.ships = [remaining_ship]
        caster.remaining_ships = 1

        # 设置效果标记（生效回合内其余魔法卡无效，由 can_play_magic_card 拦截）
        room.players[caster_id].effect_flags.last_stand = True

        result['message'] = '进入绝处逢生状态，击杀任何船直接获胜'

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

        count = min(2, len(caster.sunken_ships), 6 - caster.remaining_ships)
        _start_placement(room, caster_id, 'revive', count)
        result.temp_data_id = 'revive_choice'
        result['message'] = f'请依次选择 {count} 艘复活战舰的部署位置（未被攻击过的空格）'

    elif card.name == '盗亦有道':
        # 获取对方打出的上一张魔法卡
        if not room.magic_history or room.magic_history[-1]['caster'] == caster_id:
            result['success'] = False
            result['message'] = '对方没有使用过魔法卡'
            return result

        # 获取对方上一张魔法卡
        stolen_card = room.magic_history[-1]['card']
        # 将偷到的卡加入手牌（只加一次）
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
            'active': True
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

        # 无效化当前已生效的场地魔法（贴了再拆）
        if room.field_magic:
            negated_count += 1
            room.magic_discard.append(room.field_magic)
        room.field_magic = None

        result['message'] = f'成功无效化{negated_count}个效果'

    elif card.name == '钢筋铁骨':
        # 牺牲一艘船，其他船进入无敌状态
        if caster.remaining_ships < 2:
            result['success'] = False
            result['message'] = '需要至少2艘战舰才能发动'
            return result

        # 牺牲一艘船（进入沉船堆，可被复活类卡牌回收）
        popped = caster.ships.pop()
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
                _sync_attacks_after_ship_change(room, room.current_attacker)
        elif card.name == '教皇旨意':
            result.message = '教皇旨意生效，攻击需要弃置魔法卡'

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
        # 直接调用（无连锁栈）时回退历史记录，保持单卡契约
        if room.magic_history and room.magic_history[-1]['caster'] != caster_id:
            last_magic = room.magic_history[-1]
            if getattr(last_magic.get('card'), 'name', None) in ('看破！', '加百列之光'):
                result.success = False
                result.message = '该魔法免疫失灵！'
                return result
            room.magic_history.pop()
            result.message = f'无效化了{last_magic["card"].name}'
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
    if opponent and opponent.remaining_ships <= 0 and room.state != 'game_over':
        room.state = 'game_over'
        room.winner = caster_id
        add_game_log(room, f"第{room.round}回合 · {_log_name(room, caster_id)} 获胜，游戏结束", 'result', {'winner': caster_id, 'loser': opponent_id})
        try:
            winner_user_id = room.players[caster_id].user_id
            loser_user_id = room.players[opponent_id].user_id
            if winner_user_id or loser_user_id:
                db.record_match(winner_user_id or caster_id, loser_user_id or opponent_id, getattr(room, 'game_logs', None))
        except Exception:
            pass
        emit('game_over', {'winner': caster_id}, room=room.id)

    return result


def get_uuid() -> str:
    return str(uuid.uuid4())[:4]


@socketio.on('surrender')
def handle_surrender(data):
    # 处理投降请求
    player_id = session.get('user_id', request.sid)
    room_id = data.get('room_id')
    room = room_manager.get_room(room_id)
    if not room:
        return {'status': 'error', 'message': '房间不存在'}

    if player_id not in room.players:
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
            db.record_match(winner_user_id or opponent_id, loser_user_id or player_id, getattr(room, 'game_logs', None))
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
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
