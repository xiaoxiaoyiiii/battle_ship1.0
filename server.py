import json
import random
import time
import uuid
from typing import Any, Callable
import logging
from flask import render_template, request, session, jsonify
from flask_socketio import SocketIO, join_room, emit as semit

import db  # local database helpers for users and matches
from api import app
from file import read_json


def emit(event, data, to=None, room: str | None = None):
    json_data = json.dumps(data, default=lambda o: o.__dict__)
    return semit(event, json.loads(json_data), to=to, room=room)


# 在线人数统计
online_users = set()
magic_cards: list[MagicCard]
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
        self.positions = positions
        self.hits = hits


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


class CateredMagicCard:
    caster_id: str
    card: MagicCard
    target_data: Any

    def __init__(self, caster_id: str, card: MagicCard, target_data):
        self.caster_id = caster_id
        self.card = card
        self.target_data = target_data


class EffectFlags:
    treasure_hunter: bool = False
    prediction: bool = False
    subsidy: bool = False
    no_draw: bool = False
    forced_kill: int = 0  # 强制击杀次数
    vampire: bool = False  # 饮血效果
    last_stand: bool = False  # 绝处逢生效果
    double_attacks: bool = False

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

    def __init__(self, name: str, ships: list[PlayerShip], attacks: list[Position], remaining_ships: int):
        self.magic_blocked = None
        self.damage_dealt_this_turn = 0
        self.magic_hand = []
        self.effect_flags = EffectFlags()
        self.name = name
        self.ships = ships
        self.attacks = attacks
        self.remaining_ships = remaining_ships
        self.needs_reset = False
        self.revealed_positions = []
        self.max_ships = None


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
    last_magic: dict[str, Any] | None
    magic_temp_data: dict[str, Any]
    pending_magic: CateredMagicCard | None
    magic_discard: list[MagicCard]
    magic_deck: list[MagicCard]
    chain: list[dict[str, Any]]
    chain_waiting: bool
    chain_timer: float
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
        self.field_magic = ""  # 场地魔法 card
        self.magic_history = []  # 魔法卡使用历史
        self.game_effects = {}  # 游戏效果跟踪
        self.current_phase = 'preparation'  # 当前阶段
        self.last_magic = None  # 上一张使用的魔法卡
        self.pending_magic = None  # 待处理的魔法卡（等待对方是否使用失灵）
        self.magic_temp_data = {}  # 魔法卡临时数据
        self.magic_discard = []  # 全局弃牌堆（所有玩家使用过的魔法卡）
        self.magic_deck = []  # 全局共享魔法卡堆
        # 连锁相关状态
        self.chain = []  # 连锁栈
        self.chain_waiting = False  # 是否正在等待玩家回应连锁
        self.chain_timer = -1  # 连锁回应计时器
        self.effects=[]
        self.last_attack = None  # 记录最后一次攻击的信息

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
        emit('hand_updated', {
            'hand': self.players[player_id].magic_hand
        }, room=player_id)

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
        attack_result = {
            'attacker': attacker_id,
            'x': target.x,
            'y': target.y,
            'hit': hit,
            'ship_sunk': ship_sunk,
            'remaining_attacks': self.attacks_remaining,
            'attacker_remaining_ships': self.players[attacker_id].remaining_ships,
            'defender_remaining_ships': self.players[defender_id].remaining_ships
        }

        emit('attack_result', attack_result, room=self.id)

        # 检查游戏是否结束
        if self.players[defender_id].remaining_ships == 0:
            self.state = 'game_over'
            self.winner = attacker_id
            # 记录战绩（若为已登录用户）
            try:
                db.record_match(attacker_id, defender_id)
            except Exception:
                pass
            emit('game_over', {'winner': attacker_id}, room=self.id)


# 添加魔法卡牌数据定义（与客户端 magic_cards.js 保持一致）
magic_cards = list(map(lambda x: MagicCard(**x), read_json('./static/magic_card.json')))

socketio = SocketIO(app, cors_allowed_origins="*")

# 游戏房间数据结构
rooms: dict[str, GameRoom] = {}
# 匹配队列
match_queue: list[list[str], list[str]] = [[], []]

# 聊天消息最大长度
MAX_CHAT_MSG_LEN = 100

# 大厅匹配队列（简单 FIFO 队列）
lobby_queue = []

# 简单的 lobby 成员列表（用于显示）
lobby_members = set()




# 测试功能：添加所有魔法卡到手牌
@socketio.on('test_add_all_magic_cards')
def test_add_all_magic_cards(data):
    room_id = data['room_id']
    player_id = data['player_id']

    if room_id not in rooms or player_id not in rooms[room_id].players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    room = rooms[room_id]

    # 将所有魔法卡添加到玩家手牌
    room.players[player_id].magic_hand = magic_cards.copy()

    # 通知客户端手牌更新
    emit('hand_updated', {
        'hand': room.players[player_id].magic_hand
    }, room=player_id)

    return {'status': 'success', 'message': f'已添加 {len(magic_cards)} 张魔法卡到手牌'}



@app.route('/lobby')
def lobby():
    # SPA entry point for lobby view
    return render_template('index.html', username=session.get('username'))

@socketio.on('create_room')
def handle_create_room(data):
    room_id = str(uuid.uuid4())[:6]
    rooms[room_id] = GameRoom(room_id)
    # 优先使用登录后的 user_id，否则使用 sid（游客模式）
    join_room(room_id)
    player_id = request.sid
    player_name = session.get('username', data.get('player_name', '匿名玩家'))
    rooms[room_id].players[player_id] = Player(**{
        'name': player_name,
        'ships': [],
        'attacks': [],
        'remaining_ships': 0  # 初始化剩余战舰数量
    })
    return {'status': 'success', 'room_id': room_id}

@socketio.on('join_room')
def handle_join_room(data):
    room_id = data['room_id']
    # 优先使用登录后的 user_id，否则使用 sid（游客模式）
    player_id = request.sid
    player_name = session.get('username', data.get('player_name', '匿名玩家'))

    if room_id not in rooms:
        emit('error', {'message': '房间不存在'}, room=request.sid)
        return {'status': 'error', 'message': '房间不存在'}

    room = rooms[room_id]
    if len(room.players) >= 2:
        emit('error', {'message': '房间已满'}, room=request.sid)
        return {'status': 'error', 'message': '房间已满'}

    # 添加玩家到房间（key 为 user_id 或 sid）
    room.players[player_id] = Player(**{
        'name': player_name,
        'ships': [],
        'attacks': [],
        'remaining_ships': 0  # 初始化剩余战舰数量
    })

    # 添加玩家到Socket.IO房间
    join_room(room_id)
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
            emit('game_state', {
                **game_state_data,
                'player_name': room.players[player_id].name,
                'opponent_name': room.players[opponent_id].name
            }, to=player_id)

    # 返回响应给客户端，包含player_id
    return {'status': 'success', 'player_id': player_id}


# 局内聊天事件
@socketio.on('connect')
def handle_connect():
    """处理客户端连接事件"""
    sid = request.sid
    online_users.add(sid)
    print(f"Client connected: {sid}, online users: {len(online_users)}")


@socketio.on('disconnect')
def handle_disconnect():
    """处理客户端断开连接事件"""
    sid = request.sid
    if sid in online_users:
        online_users.remove(sid)
    print(f"Client disconnected: {sid}, online users: {len(online_users)}")

    # 清理相关数据
    if sid in match_queue[0]:
        i = match_queue[0].index(sid)
        match_queue[0].pop(i)
        match_queue[1].pop(i)


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
    if room_id and room_id in rooms:
        for pid in rooms[room_id].players:
            is_me = (rooms[room_id].players[pid].name == username)
            emit('chat_message', {
                'username': username,
                'message': msg,
                'isMe': is_me
            }, room=pid)
        # 标记自己和对手
    else:
        # fallback: 仅回发给自己
        emit('chat_message', {'username': username, 'message': msg, 'isMe': True}, room=request.sid)


@socketio.on('find_match')
def handle_find_match(data):
    """处理玩家匹配请求"""
    player_id = request.sid
    player_name = data.get('player_name', '匿名玩家')

    # 检查玩家是否已经在匹配队列中
    if player_id in match_queue[0]:
        return {'status': 'error', 'message': '你已经在匹配队列中'}

    # 将玩家添加到匹配队列
    match_queue[0].append(player_id)
    match_queue[1].append(player_name)
    emit('match_queued', {'status': 'success', 'message': '已加入匹配队列'})

    # 尝试匹配
    while len(match_queue[0]) >= 2:
        # 从队列中取出前两个玩家
        player1 = match_queue[0].pop(0)
        player2 = match_queue[0].pop(0)

        # 再次检查是否是同一个玩家，确保不会匹配到自己
        if player1 == player2:
            # 将玩家放回队列末尾
            match_queue[0].append(player1)
            continue

        # 创建新房间
        room_id = str(uuid.uuid4())[:6]
        room = GameRoom(room_id)
        rooms[room_id] = room

        # 获取玩家名称
        player1_name = match_queue[1].pop(0)
        player2_name = match_queue[1].pop(0)

        # 添加玩家到房间
        room.players[player1] = Player(**{
            'name': player1_name,
            'ships': [],
            'attacks': [],
            'remaining_ships': 0
        })

        room.players[player2] = Player(**{
            'name': player2_name,
            'ships': [],
            'attacks': [],
            'remaining_ships': 0
        })

        # 初始化魔法卡牌系统
        room.init_player_magic(player1, magic_cards)
        room.init_player_magic(player2, magic_cards)

        # 将玩家添加到Socket.IO房间
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
        for player_id in [player1, player2]:
            opponent_id = player2 if player_id == player1 else player1
            emit('game_state', {
                **game_state_data,
                'player_name': room.players[player_id].name,
                'opponent_name': room.players[opponent_id].name
            }, to=player_id)
    return {'status': 'success', 'message': '开始寻找匹配'}


@socketio.on('cancel_match')
def handle_cancel_match(data):
    """处理玩家取消匹配请求"""
    player_id = request.sid

    # 从匹配队列中移除玩家
    if player_id in match_queue[0]:
        index = match_queue[0].index(player_id)
        match_queue[0].pop(index)
        match_queue[1].pop(index)

    emit('match_canceled', {'status': 'success', 'message': '已取消匹配'})

    return {'status': 'success', 'message': '已取消匹配'}



@socketio.on('place_ships')
def handle_place_ships(data):
    room_id = data['room_id']
    player_id = data['player_id']
    ships = data['ships']
    if room_id not in rooms or player_id not in rooms[room_id].players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    room = rooms[room_id]
    room.players[player_id].ships = list(map(lambda x: PlayerShip(**x), ships))

    # 新增：计算并设置剩余战舰数量（攻击次数）
    room.players[player_id].remaining_ships = len(ships)

    # 检查是否所有玩家都已放置战舰
    all_placed = all(len(p.ships) > 0 for p in room.players.values())
    if all_placed:
        room.state = 'rock_paper_scissors'
        # 重置猜拳选择，确保新的猜拳阶段从空开始
        room.rps_choices = {}

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

    if room_id not in rooms or player_id not in rooms[room_id].players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    room = rooms[room_id]
    room.rps_choices[player_id] = choice

    # 检查是否所有玩家都已做出选择
    if len(room.rps_choices) == len(room.players):
        # 决定猜拳结果
        result = determine_rps_winner(room)
        emit('rps_result', result, room=room_id)
        # 设置攻击顺序
        room.attack_order = result['order']
        winner = room.attack_order[0]  # 先手
        loser = room.attack_order[1]  # 后手
        room.current_attacker = winner

        # 初始化攻击次数 - 如果是败者食尘生效的回合，攻击次数为0
        if hasattr(room, 'polar_reversal_applied') and room.polar_reversal_applied:
            room.attacks_remaining = 0
            # 清除败者食尘标记
            room.polar_reversal_applied = False
        else:
            room.attacks_remaining = room.players[winner].remaining_ships

        # 猜拳后抽卡逻辑：先手1张，后手2张
        # 先手抽1张
        winner_card = room.draw_card(winner)
        # 后手抽2张
        loser_card1 = room.draw_card(loser)
        loser_card2 = room.draw_card(loser)

        room.state = 'attacking'
        # 设置当前阶段为准备阶段
        room.current_phase = 'preparation'
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


def determine_rps_winner(room: GameRoom):
    players = list(room.players.keys())
    p1, p2 = players[0], players[1]
    c1, c2 = room.rps_choices[p1], room.rps_choices[p2]

    # 处理平局情况
    if c1 == c2:
        room.rps_choices = {}
        return {'status': 'tie', 'message': '平局，重新猜拳'}

    # 判断胜负
    win_conditions = {
        'rock': 'scissors',
        'paper': 'rock',
        'scissors': 'paper'
    }

    # 正确逻辑：判断c1是否克制c2
    if win_conditions[c1] == c2:
        winner, loser = p2, p1
    else:
        winner, loser = p1, p2

    return {
        'status': 'win',
        'winner': winner,
        'loser': loser,
        'choices': {p1: c1, p2: c2},
        'order': [winner, loser]  # 攻击顺序
    }


# 添加新的Socket事件处理
@socketio.on('select_magic_target')
def handle_magic_target(data):
    room_id = data['room_id']
    player_id = data['player_id']
    target_data = data['target_data']
    temp_data_id = data['temp_data_id']

    if room_id not in rooms or player_id not in rooms[room_id].players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    room = rooms[room_id]
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
@socketio.on('attack')
def handle_attack(data):
    room_id = data['room_id']
    attacker_id = data['player_id']
    target_x = data['x']
    target_y = data['y']

    if room_id not in rooms or attacker_id not in rooms[room_id].players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    room = rooms[room_id]

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

    # 检查是否击中
    hit = False
    ship_sunk = False
    for i, ship in enumerate(defender_ships):
        if {'x': target_x, 'y': target_y} in ship.positions:
            hit = True

            # 检查攻击者是否有强制击杀效果
            has_forced_kill = room.players[attacker_id].effect_flags.forced_kill > 0

            if has_forced_kill:
                # 强制击杀效果，忽略无敌和盾牌状态，直接击杀
                # 记录击中位置
                defender_ships[i].hits = defender_ships[i].hits + [{'x': target_x, 'y': target_y}]

                # 直接击沉，不管当前击中次数
                ship_sunk = True
                defender_remaining_before = room.players[defender_id].remaining_ships
                room.players[defender_id].remaining_ships -= 1
                defender_remaining_after = room.players[defender_id].remaining_ships

                # 记录船数变化（用于平等条约）
                room.game_effects['last_ship_change'] = {
                    'player': defender_id,
                    'count': defender_remaining_before - defender_remaining_after
                }

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
                    emit('message', {'text': '饮血效果发动，抽一张卡'}, to=attacker_id)

                # 检查绝处逢生效果
                if room.players[attacker_id].effect_flags.last_stand:
                    # 直接获胜
                    room.state = 'game_over'
                    room.winner = attacker_id
                    # 记录战绩（若为已登录用户）
                    try:
                        # 如果是游客（sid），db.record_match 会忽略不存在的用户
                        opponent_id = next(p for p in room.players if p != attacker_id)
                        db.record_match(attacker_id, opponent_id)
                    except Exception:
                        pass
                    emit('game_over', {'winner': attacker_id}, room=room_id)
                    return {'status': 'success', 'game_over': True}

                # 发送战舰数更新事件
                emit('ships_updated', {
                    'player_remaining_ships': room.players[attacker_id].remaining_ships,
                    'opponent_remaining_ships': room.players[defender_id].remaining_ships
                }, room=room_id)

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
                    defender_ships[i].hits = defender_ships[i].hits + [{'x': target_x, 'y': target_y}]

                    # 检查船是否被击沉
                    if len(defender_ships[i].hits) == len(defender_ships[i].positions):
                        ship_sunk = True
                        defender_remaining_before = room.players[defender_id].remaining_ships
                        room.players[defender_id].remaining_ships -= 1
                        defender_remaining_after = room.players[defender_id].remaining_ships

                        # 记录船数变化（用于平等条约）
                        room.game_effects['last_ship_change'] = {
                            'player': defender_id,
                            'count': defender_remaining_before - defender_remaining_after
                        }

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
                            emit('message', {'text': '饮血效果发动，抽一张卡'}, to=attacker_id)

                        # 检查绝处逢生效果
                        if room.players[attacker_id].effect_flags.last_stand:
                            # 直接获胜
                            room.state = 'game_over'
                            room.winner = attacker_id
                            # 记录战绩（若为已登录用户）
                            try:
                                # 如果是游客（sid），db.record_match 会忽略不存在的用户
                                opponent_id = next(p for p in room.players if p != attacker_id)
                                db.record_match(attacker_id, opponent_id)
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

    # 准备攻击结果
    attack_result = {
        'attacker': attacker_id,
        'x': target_x,
        'y': target_y,
        'hit': hit,
        'ship_sunk': ship_sunk,
        'remaining_attacks': room.attacks_remaining,
        'attacker_remaining_ships': room.players[attacker_id].remaining_ships,
        'defender_remaining_ships': room.players[defender_id].remaining_ships
    }

    emit('attack_result', attack_result, room=room_id)

    # 检查游戏是否结束
    if room.players[defender_id].remaining_ships == 0:
        room.state = 'game_over'
        room.winner = attacker_id
        # 记录战绩（若为已登录用户）
        try:
            db.record_match(attacker_id, defender_id)
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

    if room_id not in rooms or player_id not in rooms[room_id].players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    room = rooms[room_id]
    # 检查是否是当前攻击者的准备阶段
    if room.current_attacker == player_id and room.current_phase == 'preparation':
        # 切换到战斗阶段
        room.current_phase = 'battle'
        if room.field_magic == "伊甸园":
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
        if room.field_magic == "教皇旨意":
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

    if room_id not in rooms or player_id not in rooms[room_id].players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    room = rooms[room_id]
    # 检查是否是当前攻击者的战斗阶段
    if room.current_attacker == player_id and room.current_phase == 'battle':
        # 检查是否还有剩余攻击次数
        if room.attacks_remaining > 0:
            return {'status': 'error', 'message': '你还有剩余攻击次数，无法进入结束阶段'}
        
        # 进入结束阶段
        room.current_phase = 'end'
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
    room.attacks_remaining = len(room.players[opponent_id].ships)  # 根据战舰数量设置攻击次数
    room.current_phase = 'preparation'

    # 广播回合变化 - 移除了回合切换时的额外抽卡
    emit('turn_change', {
        'current_attacker': opponent_id,
        'attacks_remaining': room.attacks_remaining,
        'phase': 'preparation'
    }, room=room.id)


# 添加结束结束阶段，切换到对方准备阶段
@socketio.on('end_turn')
def end_turn(data):
    room_id = data['room_id']
    player_id = data['player_id']

    if room_id not in rooms or player_id not in rooms[room_id].players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    room = rooms[room_id]
    # 检查是否是当前攻击者的结束阶段
    if room.current_attacker == player_id and room.current_phase == 'end':
        current_index = room.attack_order.index(room.current_attacker)
        next_index = (current_index + 1) % len(room.attack_order)

        # 如果是最后一个玩家结束回合，开始新的大回合
        if next_index == 0:
            # 进入新回合，重置状态
            room.round += 1

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
                    player1_ships = len(room.players[player1_id].ships)
                    player2_ships = len(room.players[player2_id].ships)

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
            # 切换到下一个攻击者的准备阶段
            room.current_attacker = room.attack_order[next_index]
            room.current_phase = 'preparation'
            room.attacks_remaining = room.players[room.current_attacker].remaining_ships

            # 重置所有临时效果标志 - 但保留no_draw标志直到大回合结束
            for p_id in room.players:
                # 保留场地魔法等永久效果和no_draw标志，清除其他临时效果
                permanent_flags = ['holy_heart', 'reinforcement_check', 'no_draw']  # 永久效果白名单
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
            return {'status': 'success'}

    return {'status': 'error', 'message': '无法结束当前回合'}


@socketio.on('use_magic_card')
def handle_use_magic_card(data):
    room_id = data['room_id']
    player_id = data['player_id']
    card = MagicCard(**data['card'])
    targets = data.get('targets', [])

    if room_id not in rooms or player_id not in rooms[room_id].players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    room = rooms[room_id]
    player = room.players[player_id]
    opponent_id = next(p for p in room.players if p != player_id)

    # 将客户端传来的字典转换为MagicCard对象
    try:
        card = MagicCard(
            name=card_dict.get('name', ''),
            speed=card_dict.get('speed', ''),
            type=card_dict.get('type', ''),
            description=card_dict.get('description', '')
        )
    except Exception as e:
        return {'status': 'error', 'message': f'无效的魔法卡数据: {str(e)}'}

    # 检查卡牌是否在玩家手牌中
    if not any(c.name == card.name and c.speed == card.speed for c in player.magic_hand):
        return {'status': 'error', 'message': '你没有这张魔法卡'}

    # 检查是否可以在当前阶段使用
    if not can_play_magic_card(room, player_id, card):
        return {'status': 'error', 'message': f'当前阶段{room.current_phase}无法使用速阶{card.speed}的魔法卡'}

    # 从手牌中移除并添加到弃牌堆
    room.magic_discard.append(card)

    # 记录最后使用的魔法卡
    room.last_magic = card

    # 处理场地魔法 - 全场只能有一张场地魔法卡生效
    if card.type == '场地':
        # 设置新的场地魔法卡
        room.field_magic = card
        # 广播新的场地魔法卡
        emit('field_magic_updated', {
            'player_id': player_id,
            'card': card
        }, room=room_id)

    # 添加到连锁栈
    chain_item = {
        'player_id': player_id,
        'card': card,
        'targets': targets,
        'timestamp': time.time()
    }
    room.chain.append(chain_item)

    # 广播连锁更新
    emit('magic_chain_updated', {
        'chain': room.chain
    }, room=room_id)

    # 新的连锁逻辑：检查对方是否有速阶3的卡牌
    opponent = room.players[opponent_id]
    opponent_has_speed3 = any(int(c.speed) == 3 for c in opponent.magic_hand)

    if opponent_has_speed3:
        # 对方有速阶3的卡牌，开启连锁请求
        room.chain_waiting = True
        # 获取对方的速阶3卡牌列表
        opponent_speed3_cards = [c for c in opponent.magic_hand if int(c.speed) == 3]
        # 发送连锁请求，包含倒计时
        emit('chain_request', {
            'card': card,
            'speed3_cards': opponent_speed3_cards,
            'countdown': 10
        }, to=opponent_id)
    else:
        # 对方没有速阶3的卡牌，直接结算连锁
        resolve_chain(room)

    return {'status': 'success', 'message': f'魔法卡{card.name}已加入连锁'}


def can_play_magic_card(room, player_id, card):
    # 确保speed是数字类型
    speed = int(card.speed)

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
        return speed == 2
    elif room.current_phase == 'end':
        # 结束阶段不能使用魔法卡
        return False

    return False


def resolve_chain(room):
    """结算连锁"""
    results = []

    # 按照连锁顺序结算（从后往前）
    while room.chain:
        chain_item = room.chain.pop()
        player_id = chain_item['player_id']
        card = chain_item['card']
        targets = chain_item['targets']

        # 应用卡牌效果
        result = apply_magic_effect(room, player_id, card, targets)
        # 添加施法者信息到结果中
        result['caster'] = player_id
        results.append(result)

    # 广播连锁结算结果
    emit('chain_resolved', {
        'results': results
    }, room=room.id)

    # 重置连锁状态
    room.chain = []
    room.chain_waiting = False

    return results


# 添加处理连锁响应
@socketio.on('chain_response')
def chain_response(data):
    room_id = data['room_id']
    player_id = data['player_id']
    chain = data.get('chain', False)
    card = data.get('card')
    targets = data.get('targets', [])

    if room_id not in rooms or player_id not in rooms[room_id].players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    room = rooms[room_id]
    if not room.chain_waiting:
        return {'status': 'error', 'message': '没有待处理的连锁请求'}

    # 重置连锁等待状态
    room.chain_waiting = False

    if chain and card:
        card = MagicCard(**card)
        # 玩家选择连锁，处理新的魔法卡
        player = room.players[player_id]
        opponent_id = next(p for p in room.players if p != player_id)
        opponent = room.players[opponent_id]

        # 检查卡牌是否在玩家手牌中
        if not any(c.name == card.name and c.speed == card.speed for c in player.magic_hand):
            return {'status': 'error', 'message': '你没有这张魔法卡'}

        # 检查是否为速阶3卡牌
        if int(card.speed) != 3:
            return {'status': 'error', 'message': '只能使用速阶3的卡牌进行连锁'}

        room.magic_discard.append(card)

        # 记录最后使用的魔法卡
        room.last_magic = card

        # 添加到连锁栈
        chain_item = {
            'player_id': player_id,
            'card': card,
            'targets': targets,
            'timestamp': time.time()
        }
        room.chain.append(chain_item)

        # 广播连锁更新
        emit('magic_chain_updated', {
            'chain': room.chain
        }, room=room_id)

        # 检查对方是否有速阶3的卡牌可以继续连锁
        opponent_has_speed3 = any(int(c.speed) == 3 for c in opponent.magic_hand)

        if opponent_has_speed3:
            # 对方有速阶3的卡牌，发送连锁请求
            opponent_speed3_cards = [c for c in opponent.magic_hand if int(c.speed) == 3]
            emit('chain_request', {
                'card': card,
                'speed3_cards': opponent_speed3_cards,
                'countdown': 10
            }, to=opponent_id)
            # 继续等待连锁
            room.chain_waiting = True
        else:
            # 对方没有速阶3的卡牌，直接结算连锁
            resolve_chain(room)

        return {'status': 'success', 'message': f'魔法卡{card.name}已加入连锁'}
    else:
        # 玩家选择不连锁，结算当前连锁
        resolve_chain(room)
        return {'status': 'success', 'message': '连锁已结算'}


# 添加处理对方是否使用"失灵！"的响应
@socketio.on('counter_magic_response')
def counter_magic_response(data):
    room_id = data['room_id']
    player_id = data['player_id']
    use_counter = data['use_counter']

    if room_id not in rooms or player_id not in rooms[room_id].players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    room = rooms[room_id]
    if not room.pending_magic:
        return {'status': 'error', 'message': '没有待处理的魔法卡'}

    pending = room.pending_magic
    caster_id = pending.caster_id
    card = pending.card
    target_data = pending.target_data

    # 清除待处理魔法
    room.pending_magic = None

    if use_counter:
        # 对方使用了"失灵！"
        # 从对方手牌中移除"失灵！"
        opponent = room.players[player_id]
        for i, c in enumerate(opponent.magic_hand):
            if c.name == '失灵！':
                opponent.magic_hand.pop(i)
                break

        # 广播魔法被无效化
        emit('magic_negated', {
            'card': card,
            'negated_by': player_id
        }, room=room_id)
        return {'status': 'success', 'message': '魔法已被无效化'}
    else:
        # 对方不使用"失灵！"，直接应用魔法效果
        result = apply_magic_effect(room, caster_id, card, target_data)
        # 记录最后使用的魔法
        room.last_magic = {
            'card': card,
            'caster': caster_id,
            'timestamp': time.time()
        }
        # 只将带有temp_data_id的结果发送给施法者，其他结果广播给所有人
        if 'temp_data_id' in result:
            # 只发送给施法者
            emit('magic_applied', result, to=caster_id)
        else:
            # 广播给所有人
            emit('magic_applied', result, room=room_id)
        return {'status': 'success', 'result': result}


@socketio.on('remove_field_magic')
def handle_remove_field_magic(data):
    room_id = data['room_id']
    player_id = data['player_id']

    if room_id in rooms and player_id in rooms[room_id].players:
        room = rooms[room_id]
        # 将场地魔法加入弃牌堆
        for player_id in room.players:
            room.discard_card(player_id, MagicCard(room.field_magic))
        # 广播场地魔法更新
        emit('field_magic_updated', {
            'player_id': player_id,
            'card': None
        }, room=room_id)

    return {'status': 'success'}


@socketio.on('confirm_reinforcement_position')
def handle_confirm_reinforcement(data):
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    position = data.get('position')
    if not room_id or room_id not in rooms or not player_id or player_id not in rooms[room_id].players:
        return {'status': 'error', 'message': '无效的房间或玩家'}
    room = rooms[room_id]
    caster = room.players[player_id]

    # 验证是否存在等待的增援
    pending = room.magic_temp_data.get('pending_reinforcement') if room.magic_temp_data else None
    if not pending or pending.get('caster') != player_id:
        return {'status': 'error', 'message': '没有等待确认的增援'}

    # 验证位置合法且没有被对方攻击过
    opponent_id = next(p for p in room.players if p != player_id)
    opponent_attacks = [(a.x, a.y) for a in room.players[opponent_id].attacks]
    x, y = position.get('x'), position.get('y')
    if (x, y) in opponent_attacks:
        return {'status': 'error', 'message': '该位置已被对方攻击，无法放置'}

    # 验证没有和已有战舰冲突
    for ship in caster.ships:
        for pos in ship.positions:
            if pos.x == x and pos.y == y:
                return {'status': 'error', 'message': '该位置已被己方战舰占用'}

    # 放置战舰
    caster.ships.append(PlayerShip(**{
        'id': f'magic_{get_uuid()}',
        'positions': [Position(**{'x': x, 'y': y})],
        'hits': []
    }))
    caster.remaining_ships = caster.remaining_ships + 1

    # 清除临时数据
    room.magic_temp_data.pop('pending_reinforcement', None)

    # 广播更新
    emit('ships_updated', {
        'player_remaining_ships': caster.remaining_ships,
        'opponent_remaining_ships': room.players[opponent_id].remaining_ships
    }, room=room_id)

    emit('message', {'text': '增援放置完成'}, to=player_id)
    return {'status': 'success'}


@socketio.on('request_revealed_positions')
def handle_request_revealed_positions(data):
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    if not room_id or room_id not in rooms or not player_id or player_id not in rooms[room_id].players:
        return {'status': 'error', 'message': '无效的房间或玩家'}
    room = rooms[room_id]
    positions = room.players[player_id].revealed_positions
    # 只发送给请求者
    emit('revealed_positions', {'positions': positions}, to=player_id)
    return {'status': 'success'}


@socketio.on('get_magic_temp_data')
def get_magic_temp_data(data):
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    if not room_id or room_id not in rooms or not player_id or player_id not in rooms[room_id].players:
        return {'status': 'error', 'message': '无效的房间或玩家'}
    room = rooms[room_id]
    return {'status': 'success', 'data': room.magic_temp_data}


@socketio.on('confirm_magic_target')
def confirm_magic_target(data):
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    temp_data_id = data.get('temp_data_id')
    target_data = data.get('target_data', {})

    if not room_id or room_id not in rooms or not player_id or player_id not in rooms[room_id].players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    room = rooms[room_id]

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
            }, to=player_id)

            emit('hand_updated', {
                'hand': opponent.magic_hand
            }, to=opponent_id)

            # 通知对手等待结束
            emit('taoyuan_complete', {
                'message': '对方桃园结义结算完成'
            }, to=opponent_id)

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
        }, to=opponent_id)

        return {'status': 'success', 'message': f'灵气复苏船数选择完成'}

    return {'status': 'error', 'message': '无效的临时数据ID'}


@socketio.on('get_discard_pile')
def get_discard_pile(data):
    """获取玩家的弃牌堆数据（返回全局弃牌堆）"""
    room_id = data.get('room_id')
    player_id = data.get('player_id')

    if not room_id or room_id not in rooms or not player_id or player_id not in rooms[room_id].players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    room = rooms[room_id]

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


def apply_magic_effect(room: GameRoom, caster_id: str, card: MagicCard, target_data):
    result = {'card': card, 'caster': caster_id, 'success': True, 'message': ''}
    opponent_id = next(p for p in room.players if p != caster_id)
    caster = room.players[caster_id]
    opponent = room.players[opponent_id]
    print(f"Applying magic effect: {card.name} target {target_data}")


    # ==== 速阶1 魔法卡 ====
    if card.name == '余音绕梁':
        # 标记接下来两个攻击阶段造成的伤害将强制击杀，已修复
        room.players[caster_id].effect_flags = room.players[caster_id].effect_flags
        room.players[caster_id].effect_flags.forced_kill = 2  # 持续2个攻击阶段
        result['message'] = '接下来两个攻击阶段将造成强制击杀'
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
        n = len(caster.ships)
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
            result['message'] = f'抽了{len(drawn_cards)}张牌，请选择'
            result['temp_data_id'] = 'taoyuan_choice'
            # 通知对手等待
            emit('taoyuan_waiting', {
                'message': '对方正在结算桃园结义效果 请等待'
            }, to=opponent_id)
        else:
            result['success'] = False
            result['message'] = '无法抽取卡牌'

    elif card.name == '无中生有':
        # 抽两张牌，本回合双方无法获得魔法卡，已修复
        card1 = room.draw_card(caster_id)
        card2 = room.draw_card(caster_id)
        # 设置禁止抽卡标记
        room.players[caster_id].effect_flags = room.players[caster_id].effect_flags
        room.players[opponent_id].effect_flags = room.players[opponent_id].effect_flags
        room.players[caster_id].effect_flags.no_draw = True
        room.players[opponent_id].effect_flags.no_draw = True
        result['message'] = '抽了2张牌，本回合双方无法获得魔法卡'

    elif card.name == '极限增援':
        # 两个大回合后，船少的一方获胜，已修复
        total_turns = 2
        room.game_effects.reinforcement_check = {
            'turn': room.round + total_turns,
            'caster': caster_id,
            'remaining_turns': total_turns  # 添加剩余回合计数
        }
        # 通知双方客户端，极限增援已激活并显示剩余回合
        emit('reinforcement_activated', {
            'remaining_turns': total_turns
        }, room=room.id)
        result['message'] = '极限增援已激活，剩余2回合后结算'

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
        result['message'] = '无暇圣心已激活，剩余2回合后结算'

    elif card.name == '火力全开':
        # 本回合攻击次数翻倍，已修复
        room.players[caster_id].effect_flags = room.players[caster_id].effect_flags
        room.players[caster_id].effect_flags.double_attacks = True
        result['message'] = '本回合攻击次数翻倍'
        def func(room:GameRoom):
            room.attacks_remaining*=2
            room.pop_effect(card.name)
        room.effects.append(Effect(card.name,"before_attack","",999,func))

    elif card.name == '灵气复苏':
        # 计算双方最大船数，已修复
        max_ships = max(len(caster.ships), len(opponent.ships))
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
        result['message'] = '请选择灵气复苏的船数'
        result['temp_data_id'] = 'lingqi_choice'
        result['max_ships'] = max_ships

        # 通知对手等待
        emit('lingqi_waiting', {
            'message': '对方正在结算灵气复苏效果 请等待'
        }, to=opponent_id)
    
    elif card.name == '败者食尘':
        # 记录败者食尘打出前双方的船数，已修复
        original_caster_ships = len(caster['ships'])
        original_opponent_ships = len(opponent['ships'])
        
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
            if 'opponent_attacks' in player:
                player.opponent_attacks = []
            # 清除其他相关状态
            player.needs_reset = True
            player.revealed_positions = []
            # 清除所有与棋盘相关的状态

        # 标记这是败者食尘效果，用于后续处理
        room.lingqi_resurgence_applied = True
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

    # ==== 速阶2 魔法卡 ===
    elif card.name == '溅射':
        # 对击中格子的上下左右四格造成伤害
        if not room.last_attack or room.last_attack['attacker'] != caster_id:
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
                    # 溅射伤害不受无敌影响，但受护盾影响（护盾抵挡一次）
                    if ship.shield:
                        hit = True
                        ship.shield=False
                        ship_sunk = False
                    elif ship.invincible:
                        # 无敌：显形但不伤害（依然记录为命中）
                        hit = True
                        ship_sunk = False
                    else:
                        hit = True
                        ship.hits.append(Position(**pos))
                        if len(ship.hits) == len(ship.positions):
                            ship_sunk = True
                            opponent.remaining_ships -= 1
                            ships_changed = True
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
        emit('revealed_positions', {'positions': new_positions}, to=caster_id)
        result['message'] = '已扫描周围八格战舰位置'
        result['affected_positions'] = affected_positions

    elif card.name == '越战越勇':
        # 每造成一次伤害，攻击次数加2
        if not room.last_attack or room.last_attack['attacker'] != caster_id or not room.last_attack['hit']:
            result['success'] = False
            result['message'] = '必须在击中对方战舰后使用'
            return result

        # 增加攻击次数
        room.attacks_remaining += 2
        result['message'] = '攻击次数增加2次'

    elif card.name == '神威！':
        # 选定3*3区域，暂时除外区域内战舰
        if 'target_area' not in target_data:
            result['success'] = False
            result['message'] = '需要选择目标区域'
            return result

        area = target_data['target_area']
        excluded_ships = []

        # 收集区域内的战舰
        for i in range(len(opponent.ships) - 1, -1, -1):
            ship = opponent.ships[i]
            in_area = any(
                area['x1'] <= pos.x <= area['x2'] and
                area['y1'] <= pos.y <= area['y2']
                for pos in ship.positions
            )

            if in_area:
                excluded_ships.append(ship)
                del opponent.ships[i]
                opponent.remaining_ships -= 1

        # 如果只有一艘船被除外，直接击沉
        if len(excluded_ships) == 1:
            result['message'] = '目标区域内1艘战舰被击沉'
        else:
            # 记录暂时除外的战舰，下一回合回归
            room.game_effects['excluded_ships'] = {
                'ships': excluded_ships,
                'player': opponent_id,
                'return_turn': room.round + 1
            }
            result['message'] = f'目标区域内{len(excluded_ships)}艘战舰被暂时除外'

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

            if in_area and 'frozen' not in ship:
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
        if line.type == 'row':
            positions = [{'x': x, 'y': line['index']} for x in range(6)]
        else:
            positions = [{'x': line['index'], 'y': y} for y in range(6)]

        # 找出所有与该行/列相交的船只，整艘摧毁
        to_remove = [ship for ship in opponent.ships if any(pos in ship.positions for pos in positions)]
        sunk_count = 0
        ships_changed = False
        removed_positions = set()

        # 移除受影响的船只，并为其所有格子生成命中事件
        for ship in to_remove:
            if ship in opponent.ships:
                opponent.ships.remove(ship)
                opponent.remaining_ships -= 1
                ships_changed = True
                sunk_count += 1
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
        to_remove = [ship for ship in opponent.ships if any(pos in ship.positions for pos in positions)]
        sunk_count = 0
        ships_changed = False
        removed_positions = set()
        affected_positions: list[Position] = []
        for ship in to_remove:
            if ship in opponent.ships:
                affected_positions = []
                opponent.ships.remove(ship)
                opponent.remaining_ships -= 1
                ships_changed = True
                sunk_count += 1
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
            if (pos.x, pos.y) not in removed_positions:
                caster.attacks.append(Position(**{
                    'x': pos.x,
                    'y': pos.y,
                    'hit': False,
                    'ship_sunk': False,
                    'is_sulfur': True
                }))
                attack_result = {
                    'attacker': caster_id,
                    'x': pos.x,
                    'y': pos.y,
                    'hit': False,
                    'ship_sunk': False,
                    'remaining_attacks': room.attacks_remaining,
                    'attacker_remaining_ships': room.players[caster_id].remaining_ships,
                    'defender_remaining_ships': opponent.remaining_ships
                }
                emit('attack_result', attack_result, room=room.id)
                affected_positions.append(Position(**{
                    'x': pos.x,
                    'y': pos.y,
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

    elif card.name == '探测雷达':
        # 显示2*2区域内的战舰
        if 'target_area' not in target_data:
            result['success'] = False
            result['message'] = '需要选择目标区域'
            return result

        area = target_data['target_area']
        positions = []
        room.players[caster_id].revealed_positions = room.players[caster_id].revealed_positions

        # 添加需要显示的位置
        for y in range(area['y1'], area['y2'] + 1):
            for x in range(area['x1'], area['x2'] + 1):
                pos = {'x': x, 'y': y}
                room.players[caster_id].revealed_positions.append(Position(**pos))
                positions.append(pos)

        # 立即发送给触发者
        emit('revealed_positions', {'positions': positions}, to=caster_id)
        result['message'] = '已探测目标区域战舰位置'

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
        caster_positions = caster_ship['positions']
        opponent_positions = opponent_ship['positions']

        room.players[caster_id].revealed_positions = room.players[caster_id].revealed_positions
        room.players[opponent_id].revealed_positions = room.players[opponent_id].revealed_positions

        room.players[caster_id].revealed_positions.extend(opponent_positions)
        room.players[opponent_id].revealed_positions.extend(caster_positions)

        # 立即发送给双方对应玩家
        emit('revealed_positions', {'positions': opponent_positions}, to=caster_id)
        emit('revealed_positions', {'positions': caster_positions}, to=opponent_id)

        result['message'] = '双方各暴露一艘战舰位置'

    elif card.name == 'Freezing！':
        # 本回合未造成伤害时可发动，跳过对方回合
        if room.current_attacker != caster_id:
            result['success'] = False
            result['message'] = '必须在自己回合发动'
            return result

        # 检查是否造成过伤害
        has_damaged = any(a.hit for a in caster.attacks if a.round == room.round)
        if has_damaged:
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

        # 记录需要选择的牌
        room.magic_temp_data = {
            'type': 'bury_choice',
            'caster': caster_id,
            'cards': caster.magic_hand
        }
        result['message'] = '请选择要埋葬的卡牌'
        result['temp_data_id'] = 'bury_choice'

    elif card.name == '仁王之盾':
        # 选择至多3艘船进入盾牌状态
        if len(caster.ships) == 0:
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
        # 恢复船数
        if last_change['player'] == caster_id:
            caster.remaining_ships += last_change['count']
        else:
            opponent.remaining_ships += last_change['count']

        result['message'] = '成功无效化船数改变效果'

    elif card.name == '百亿补贴':
        # 船被击败时攻击次数加3
        room.players[caster_id].effect_flags = room.players[caster_id].effect_flags
        room.players[caster_id].effect_flags.subsidy = True
        result['message'] = '船被击败时攻击次数加3'

    elif card.name == '神之宣告':
        # 牺牲两艘船，选择一个效果
        if len(caster.ships) < 2:
            result['success'] = False
            result['message'] = '需要至少2艘战舰才能发动'
            return result

        # 牺牲两艘船
        caster.ships.pop()
        caster.ships.pop()
        caster.remaining_ships -= 2

        # 获取选择的效果
        effect_choice = room.magic_temp_data.get('effect_choice', 1)
        if effect_choice == 1:
            # 让对方选择一艘船死亡
            opponent.ships.pop()
            opponent.remaining_ships -= 1
            result['message'] = '牺牲两艘战舰，对方被迫选择一艘战舰摧毁'
        else:
            # 跳过对方所有阶段
            room.skip_opponent_turn = True
            result['message'] = '牺牲两艘战舰，跳过对方本回合所有阶段'

    elif card.name == '绝处逢生':
        # 牺牲所有船，只留一艘，之后击杀任何船直接获胜
        if len(caster.ships) < 3:
            result['success'] = False
            result['message'] = '需要至少3艘战舰才能发动'
            return result

        # 保存一艘船
        remaining_ship = random.choice(caster.ships)
        caster.ships = [remaining_ship]
        caster.remaining_ships = 1

        # 设置效果标记
        room.players[caster_id].effect_flags.last_stand = True
        # 无效化其他魔法卡
        caster.magic_hand = []

        result['message'] = '进入绝处逢生状态，击杀任何船直接获胜'

    elif card.name == '死者苏生':
        # 复活一艘船
        if len(caster.ships) >= 6:
            result['success'] = False
            result['message'] = '战舰数量已达上限'
            return result

        if caster.sunken_ships and len(caster.sunken_ships) > 0:
            # 从沉没的船中恢复最近一艘
            revived_ship = caster.sunken_ships.pop()
            caster.ships.append(revived_ship)
            caster.remaining_ships += 1
            result['message'] = '成功复活一艘战舰'
        else:
            result['success'] = False
            result['message'] = '没有可复活的战舰'

    elif card.name == '疗愈':
        # 复活至多两艘被击杀的船
        if len(caster.ships) >= 6:
            result['success'] = False
            result['message'] = '战舰数量已达上限'
            return result

        revived = 0
        # 尝试复活两艘船
        if caster.sunken_ships:
            while revived < 2 and caster.sunken_ships:
                revived_ship = caster.sunken_ships.pop()
                caster.ships.append(revived_ship)
                caster.remaining_ships += 1
                revived += 1

        result['message'] = f'成功复活{revived}艘战舰'

    elif card.name == '盗亦有道':
        # 获取对方打出的上一张魔法卡
        if not room.magic_history or room.magic_history[-1]['caster'] == caster_id:
            result['success'] = False
            result['message'] = '对方没有使用过魔法卡'
            return result

        # 获取对方上一张魔法卡
        stolen_card = room.magic_history[-1]['card']
        caster.magic_hand.append(stolen_card)
        caster.magic_hand.append(stolen_card)
        room.discard_card(caster_id, stolen_card)

        result['message'] = f'成功盗取对方的{stolen_card.name}'

    elif card.name == '回光返照':
        # 清空棋盘重新摆放6艘船
        caster.ships = []
        caster.attacks = []
        caster.remaining_ships = 0
        # 标记需要重新摆放
        room.players[caster_id].needs_reset = True
        # 清空对方视角
        room.players[opponent_id].revealed_positions = []

        result['message'] = '已清空棋盘，请重新摆放战舰'

    elif card.name == '加百列之光':
        # 无效化对方上一张魔法卡和当前场地魔法
        negated_count = 0
        # 无效化对方上一张魔法卡
        if room.magic_history and room.magic_history[-1]['caster'] != caster_id:
            room.magic_history.pop()
            negated_count += 1

        # 无效化场地魔法
        if room.field_magic:
            negated_count += 1
        room.field_magic = ""

        result['message'] = f'成功无效化{negated_count}个效果'

    elif card.name == '钢筋铁骨':
        # 牺牲一艘船，其他船进入无敌状态
        if len(caster.ships) < 2:
            result['success'] = False
            result['message'] = '需要至少2艘战舰才能发动'
            return result

        # 牺牲一艘船
        caster.ships.pop()
        caster.remaining_ships -= 1

        # 其他船进入无敌状态
        for ship in caster.ships:
            ship.invincible = True

        result['message'] = '牺牲一艘战舰，其他战舰进入无敌状态'

    elif card.name == '神机妙算':
        # 宣言x，如果结束阶段船数减少x，那些船不会减少
        if 'prediction' not in room.magic_temp_data:
            result['success'] = False
            result['message'] = '需要宣言减少的船数'
            return result

        x = room.magic_temp_data['prediction']
        room.players[caster_id].effect_flags = room.players[caster_id].effect_flags
        room.players[caster_id].effect_flags.prediction = x
        result['message'] = f'宣言船数减少{x}，若预测成功则不会减少'

    # ==== 场地魔法卡 ====
    elif card.type == '场地':
        # 场地魔法处理 - 全场只能有一张场地魔法卡生效
        # 移除所有玩家的场地魔法卡
        room.discard_card(caster_id, MagicCard(room.field_magic))
        emit('field_magic_updated', {
            'player_id': caster_id,
            'card': None
        }, room=room.id)
        # 设置新的场地魔法卡
        room.field_magic = card.name

        if card.name == '恶魔契约':
            result['message'] = '恶魔契约生效，双方船数增减绑定'
        elif card.name == '禁忌果实':
            result['message'] = '禁忌果实生效，双方只能使用失灵！和场地魔法'
        elif card.name == '伊甸园':
            result['message'] = '伊甸园生效，攻击次数变为6-n'
        elif card.name == '教皇旨意':
            result['message'] = '教皇旨意生效，攻击需要弃置魔法卡'

    # ==== 已实现的魔法卡 ====
    elif card.name == '失灵！':
        # 无效化对方上一张魔法卡
        if room.magic_history and room.magic_history[-1]['caster'] != caster_id:
            last_magic = room.magic_history.pop()
            result['message'] = f'无效化了{last_magic["card"]["name"]}'
            result['negated'] = last_magic
        else:
            result['success'] = False
            result['message'] = '没有可无效化的魔法卡'

    elif card.name == '看破！':
        # 无效化对方本回合所有魔法卡
        room.players[opponent_id].magic_blocked = True
        result['message'] = '本回合对方魔法卡被无效化'

    elif card.name == '增援':
        # 召唤一艘战舰：等待玩家选择放置位置
        if len(caster.ships) >= 6:
            result['success'] = False
            result['message'] = '战舰数量已达上限'
        else:
            # 存储临时数据以等待客户端确认位置
            room.magic_temp_data = room.magic_temp_data
            room.magic_temp_data['pending_reinforcement'] = {
                'caster': caster_id
            }
            result['temp_data_id'] = 'reinforcement_choice'
            result['message'] = '请选择增援放置位置'

    elif card.name == '桃园结义':
        # 从牌堆抽取n张牌(n为自己的战舰数)，自己选1张，再给对方选1张
        n = len(caster.ships)
        drawn_cards = []
        for _ in range(n):
            card = room.draw_card(caster_id)
            if card: drawn_cards.append(card)

        if drawn_cards:
            # 记录待选择的牌
            room.magic_temp_data = {
                'type': 'taoyuan_choice',
                'caster': caster_id,
                'opponent': opponent_id,
                'cards': drawn_cards
            }
            result['message'] = f'抽了{len(drawn_cards)}张牌，请选择'
            result['temp_data_id'] = 'taoyuan_choice'
        else:
            result['success'] = False
            result['message'] = '无法抽取卡牌'

    else:
        result['success'] = False
        result['message'] = f'未实现的魔法卡: {card.name}'



    
    #result['success'] = False
    #result['message'] = f'魔法效果应用失败: {str(e)}'
    return result


def get_uuid() -> str:
    return str(uuid.uuid4())[:4]


@socketio.on('surrender')
def handle_surrender(data):
    # 处理投降请求
    player_id = request.sid
    room_id = data.get('room_id')
    room = rooms.get(room_id)
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
    db.record_match(opponent_id, player_id)
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
