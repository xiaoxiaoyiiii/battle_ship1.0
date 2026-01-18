import json
import random
import time
import uuid
from typing import Any, Callable
import logging
from flask import render_template, request, session, jsonify
from flask_socketio import SocketIO, join_room, emit as semit
import threading
import db  # local database helpers for users and matches
from api import app
from file import read_json


def emit(event, data, to=None, room: str | None = None):
    json_data = json.dumps(data, default=lambda o: o.__dict__)
    return semit(event, json.loads(json_data), to=to, room=room)


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


def add_game_log(room, text: str, event_type: str = 'info', payload: dict | None = None):
    """Append a lightweight battle log entry for later history queries."""
    if not hasattr(room, 'game_logs'):
        room.game_logs = []
    entry = GameLog(text, event_type, payload)
    room.game_logs.append(entry)


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
        self.game_logs: list[dict[str, Any]] = []
        self.rps_processed = False  # 记录猜拳结果是否已经处理过

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

        add_game_log(self, f"{attacker_id} 攻击 ({target.x},{target.y}) - {'命中' if hit else '未命中'}{'，击沉战舰' if ship_sunk else ''}",
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
            add_game_log(self, f"{attacker_id} 获胜，游戏结束", 'result', {'winner': attacker_id, 'loser': defender_id})
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
    
    def join_room(self, room_id: str, player_id: str, player_name: str, sid: str) -> bool:
        """玩家加入房间，返回是否成功"""
        if room_id not in self.rooms:
            return False
        
        room = self.rooms[room_id]
        
        # 检查是否是人机对战房间（包含AI玩家）
        ai_players = [p_id for p_id in room.players if p_id.startswith('AI_')]
        has_ai_player = len(ai_players) > 0
        
        # 如果是人机对战房间
        if has_ai_player:
            # 检查玩家是否已经在房间中
            if player_id in room.players:
                # 如果玩家已经在房间中，更新sid
                room.players[player_id].sid = sid
                return True
            # 如果是人机对战房间，允许真实玩家加入，即使房间中已经有两个玩家（一个真实玩家和一个AI玩家）
            # 但只允许一个真实玩家
            real_players = [p_id for p_id in room.players if not p_id.startswith('AI_')]
            if len(real_players) >= 1:
                return False
        # 如果是普通房间，检查玩家数量
        elif len(room.players) >= 2:
            return False
        
        # 添加玩家到房间
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
        
    def create_ai_room(self, player_id: str, player_name: str, player_user_id: str = None) -> str:
        """创建人机对战房间，返回房间ID"""
        # 创建新房间
        room_id = str(uuid.uuid4())[:6]
        room = GameRoom(room_id)
        self.rooms[room_id] = room
        
        # 添加真实玩家到房间
        room.players[player_id] = Player(**{
            'name': player_name,
            'ships': [],
            'attacks': [],
            'remaining_ships': 0,
            'user_id': player_user_id,
            'sid': player_id
        })
        
        # 创建AI玩家ID
        ai_player_id = f"AI_{room_id}"
        ai_name = "AI对手"
        
        # 添加AI玩家到房间
        room.players[ai_player_id] = Player(**{
            'name': ai_name,
            'ships': [],
            'attacks': [],
            'remaining_ships': 0,
            'user_id': ai_player_id,
            'sid': ai_player_id  # AI玩家不需要真实的sid
        })
        
        # 初始化魔法卡牌系统
        room.init_player_magic(player_id, magic_cards)
        room.init_player_magic(ai_player_id, magic_cards)
        
        # 设置房间状态为放置船只
        room.state = 'placing_ships'
        
        return room_id

# 创建RoomManager实例
room_manager = RoomManager()


class AIPlayer:
    """AI玩家类，用于实现人机对战的AI逻辑"""
    
    @staticmethod
    def place_ships(ship_count=6):
        """自动放置船只，返回船只列表"""
        from random import sample
        all_positions = [(x, y) for x in range(6) for y in range(6)]
        used_positions = set()
        ships = []
        
        # 船只大小顺序：3, 2, 2, 1, 1, 1
        for ship_size in [3, 2, 2, 1, 1, 1][:ship_count]:
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
                    ships.append(PlayerShip(positions=ship_positions, hits=[]))
                    
                    # 更新已用位置
                    used_positions.update(positions)
                    placed = True
        
        return ships
    
    @staticmethod
    def choose_attack_position(room, ai_player_id):
        """AI选择攻击位置，返回(x, y)坐标"""
        # 获取玩家已攻击过的位置
        player = room.players[ai_player_id]
        attacked_positions = set((a.x, a.y) for a in player.attacks)
        
        # 获取所有可能的位置
        all_positions = set((x, y) for x in range(6) for y in range(6))
        
        # 找出未攻击过的位置
        available_positions = all_positions - attacked_positions
        
        # 如果没有可用位置（理论上不会发生），返回随机位置
        if not available_positions:
            return (random.randint(0, 5), random.randint(0, 5))
        
        # 检查是否有击中但未击沉的位置，优先攻击这些位置周围
        hit_but_not_sunk = []
        for attack in player.attacks:
            if attack.hit and not attack.ship_sunk:
                hit_but_not_sunk.append((attack.x, attack.y))
        
        # 如果有击中但未击沉的位置，尝试攻击其周围
        if hit_but_not_sunk:
            # 收集所有击中位置周围的未攻击位置
            surrounding_positions = []
            for (x, y) in hit_but_not_sunk:
                # 检查上下左右四个方向
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    new_x, new_y = x + dx, y + dy
                    # 确保位置在棋盘内且未被攻击
                    if 0 <= new_x < 6 and 0 <= new_y < 6:
                        if (new_x, new_y) in available_positions:
                            surrounding_positions.append((new_x, new_y))
            
            # 如果有周围位置可选，随机选择一个
            if surrounding_positions:
                return random.choice(surrounding_positions)
        
        # 否则随机选择一个未攻击过的位置
        return random.choice(list(available_positions))

    @staticmethod
    def execute_turn(room, ai_player_id):
        """执行AI玩家的回合，包括攻击和结束阶段"""
        import time
        
        # 延迟执行，让玩家有时间看到AI的行动
        time.sleep(1)
        
        # 进入战斗阶段
        if room.current_phase == 'preparation':
            room.current_phase = 'battle'
            
            # 设置攻击次数
            player = room.players[ai_player_id]
            available_ships = len(player.ships)
            room.attacks_remaining = available_ships
            
            # 检查是否有攻击次数翻倍效果
            if player.effect_flags.double_attacks:
                room.attacks_remaining = available_ships * 2
                player.effect_flags.double_attacks = False
        
        # 进行攻击直到攻击次数用完
        while room.attacks_remaining > 0 and room.state == 'attacking' and room.current_attacker == ai_player_id:
            # 选择攻击位置
            x, y = AIPlayer.choose_attack_position(room, ai_player_id)
            
            # 执行攻击
            handle_attack({
                'room_id': room.id,
                'player_id': ai_player_id,
                'x': x,
                'y': y
            })
            
            # 攻击后延迟
            time.sleep(1)
        
        # 如果攻击次数用完，进入结束阶段
        if room.attacks_remaining == 0 and room.state == 'attacking':
            # 这里可以添加结束阶段的逻辑
            pass




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
    room.field_magic = ""
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
                'hits': [(p.x, p.y) for p in ship.hits],
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
    room.field_magic = ""
    room.game_effects = {}
    room.polar_reversal_applied = False
    room.last_attack = None
    room.magic_temp_data = {}
    room.chain = []
    room.chain_waiting = False

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


@socketio.on('disconnect')
def handle_disconnect():
    """处理客户端断开连接事件"""
    sid = request.sid
    if sid in online_users:
        online_users.remove(sid)
    print(f"Client disconnected: {sid}, online users: {len(online_users)}")
    
    # 清理相关数据
    if sid in room_manager.match_queue[0]:
        i = room_manager.match_queue[0].index(sid)
        room_manager.match_queue[0].pop(i)
        room_manager.match_queue[1].pop(i)
    
    # 从房间中移除断开连接的玩家
    for room_id, room in room_manager.rooms.items():
        # 查找使用该sid的玩家
        to_remove = None
        for player_id, player in room.players.items():
            if player.sid == sid:
                to_remove = player_id
                break
        
        if to_remove:
            # 移除玩家
            del room.players[to_remove]
            print(f"Removed player {to_remove} from room {room_id}")
            
            # 如果房间为空，删除房间
            if not room.players:
                room_manager.delete_room(room_id)
                print(f"Deleted empty room {room_id}")
            else:
                # 如果还有其他玩家，通知该玩家
                for remaining_player_id, remaining_player in room.players.items():
                    emit('player_disconnected', {
                        'message': '对手已断开连接，游戏结束' 
                    }, to=remaining_player.sid)
                # 也删除房间，因为游戏无法继续
                room_manager.delete_room(room_id)
                print(f"Deleted room {room_id} because a player disconnected")
            break


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
            }, room=pid)
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
    """处理玩家取消匹配请求"""
    socket_sid = session.get('user_id', request.sid)

    # 从匹配队列中移除玩家
    if socket_sid in room_manager.match_queue[0]:
        index = room_manager.match_queue[0].index(socket_sid)
        room_manager.match_queue[0].pop(index)
        room_manager.match_queue[1].pop(index)
        if index < len(room_manager.match_queue[2]):
            room_manager.match_queue[2].pop(index)

    emit('match_canceled', {'status': 'success', 'message': '已取消匹配'})

    return {'status': 'success', 'message': '已取消匹配'}



@socketio.on('place_ships')
def handle_place_ships(data):
    room_id = data['room_id']
    player_id = data['player_id']
    ships = data['ships']
    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    room.players[player_id].ships = list(map(lambda x: PlayerShip(**x), ships))

    # 新增：计算并设置剩余战舰数量（攻击次数）
    room.players[player_id].remaining_ships = len(ships)

    # 检查是否有AI玩家需要自动放置船只
    ai_players = [p_id for p_id in room.players if p_id.startswith('AI_')]
    for ai_player_id in ai_players:
        if len(room.players[ai_player_id].ships) == 0:
            # 为AI玩家自动放置船只
            ai_ships = AIPlayer.place_ships()
            room.players[ai_player_id].ships = ai_ships
            room.players[ai_player_id].remaining_ships = len(ai_ships)
            
            # 记录AI放置的船只信息到日志
            add_game_log(room, f"AI对手已自动放置 {len(ai_ships)} 艘战舰", 'info', {
                'player_id': ai_player_id,
                'ship_count': len(ai_ships)
            })

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
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    room.rps_choices[player_id] = choice
    
    # 为所有AI玩家自动做出猜拳选择
    ai_players = [p_id for p_id in room.players if p_id.startswith('AI_') and p_id not in room.rps_choices]
    for ai_player_id in ai_players:
        # AI随机选择猜拳
        ai_choice = random.choice(['rock', 'paper', 'scissors'])
        room.rps_choices[ai_player_id] = ai_choice
        
        # 记录AI的猜拳选择到日志
        add_game_log(room, f"AI对手选择了 {ai_choice}", 'info', {
            'player_id': ai_player_id,
            'choice': ai_choice
        })
    
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
    
    def to_dict(self):
        return {
            'player_id': self.player_id,
            'card': self.card,
            'targets': self.targets,
            'timestamp': self.timestamp
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
        winner, loser = p2, p1
    else:
        winner, loser = p1, p2

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
    if not room or player_id not in room.players:
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
        card_key = target_data.get('card_key')
        caster = room.players[player_id]
        opponent_id = next(p for p in room.players if p != player_id)
        opponent = room.players[opponent_id]
        
        # 验证选择
        if card_key is None:
            return {'status': 'error', 'message': '未选择卡牌'}
        
        # 从不同来源查找并移除选中的卡牌
        card_to_remove = None
        card_source = None
        
        # 1. 检查施法者的手牌
        for i, card in enumerate(caster.magic_hand):
            if f"{card.name}_{card.speed}" == card_key:
                card_to_remove = card
                card_source = 'caster_hand'
                caster.magic_hand.pop(i)
                break
        
        # 2. 如果不在施法者的手牌中，检查对方的手牌
        if card_to_remove is None:
            for i, card in enumerate(opponent.magic_hand):
                if f"{card.name}_{card.speed}" == card_key:
                    card_to_remove = card
                    card_source = 'opponent_hand'
                    opponent.magic_hand.pop(i)
                    break
        
        # 3. 如果不在对方的手牌中，检查牌堆
        if card_to_remove is None:
            for i, card in enumerate(room.magic_deck):
                if f"{card.name}_{card.speed}" == card_key:
                    card_to_remove = card
                    card_source = 'deck'
                    room.magic_deck.pop(i)
                    break
        
        if card_to_remove is None:
            return {'status': 'error', 'message': '卡牌不存在'}
        
        # 将选中的卡放入弃牌堆
        room.magic_discard.append(card_to_remove)
        # 抽一张新卡
        room.draw_card(player_id)
        room.magic_temp_data = {}
        
        # 通知双方手牌更新
        emit('hand_updated', {
            'hand': caster.magic_hand
        }, to=player_id)
        
        emit('hand_updated', {
            'hand': opponent.magic_hand
        }, to=opponent_id)
        
        # 通知弃牌堆更新
        emit('discard_pile_updated', {
            'discard': room.magic_discard
        }, room=room.id)
        
        return {'status': 'success', 'message': '埋葬完成'}

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



@socketio.on('enter_battle_phase')
def enter_battle_phase(data):
    room_id = data['room_id']
    player_id = data['player_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 检查是否是当前攻击者的准备阶段
    if room.current_attacker == player_id and room.current_phase == 'preparation':
        # 切换到战斗阶段
        room.current_phase = 'battle'
        
        # 检查船只冻结状态
        player_ships = room.players[player_id].ships
        frozen_ships = 0
        
        for ship in player_ships:
            if hasattr(ship, 'frozen') and ship.frozen > room.round:
                frozen_ships += 1
            elif hasattr(ship, 'frozen') and ship.frozen <= room.round:
                # 冻结效果已过期，移除冻结状态
                delattr(ship, 'frozen')
        
        # 计算可用的攻击次数（未冻结的船只数）
        available_ships = len(player_ships) - frozen_ships
        
        if room.field_magic == "伊甸园":
            room.attacks_remaining = 6 - room.players[player_id].remaining_ships
        elif room.field_magic == "教皇旨意":
            room.attacks_remaining = 0
        else:
            # 默认攻击次数为可用船只数
            room.attacks_remaining = available_ships

        # 检查是否有攻击次数翻倍效果
        if room.players[player_id].effect_flags.double_attacks:
            # 翻倍当前攻击次数
            room.attacks_remaining = available_ships * 2
            # 广播攻击次数更新
            emit('attacks_updated', {
                'current_attacker': room.current_attacker,
                'attacks_remaining': room.attacks_remaining
            }, room=room_id)
            # 移除翻倍效果，因为它只持续一个大回合
            room.players[player_id].effect_flags.double_attacks = False
        # 广播阶段更新
        emit('phase_updated', {
            'current_phase': room.current_phase,
            'current_attacker': room.current_attacker
        }, room=room_id)
        return {'status': 'success'}

    return {'status': 'error', 'message': '无法进入战斗阶段'}


# 添加结束战斗阶段，进入结束阶段
def handle_attack(data):
    """处理玩家攻击请求，重构后的版本更具可扩展性"""
    room_id = data['room_id']
    attacker_id = data['player_id']
    target_x = data['x']
    target_y = data['y']

    room = room_manager.get_room(room_id)
    if not room or attacker_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    # 检查攻击条件
    attack_check_result = _check_attack_conditions(room, attacker_id, target_x, target_y)
    if attack_check_result['status'] == 'error':
        return attack_check_result

    # 找到对手
    defender_id = next(p for p in room.players if p != attacker_id)
    
    # 执行攻击
    attack_result = _execute_attack(room, room_id, attacker_id, defender_id, target_x, target_y)
    
    # 处理攻击结果
    _process_attack_result(room, room_id, attacker_id, defender_id, attack_result)
    
    # 检查游戏是否结束
    if room.players[defender_id].remaining_ships == 0:
        return _handle_game_over(room, room_id, attacker_id, defender_id)

    # 处理攻击次数更新
    _update_attack_count(room, room_id, attacker_id)

    return {'status': 'success'}


def _check_attack_conditions(room, attacker_id, target_x, target_y):
    """检查攻击条件是否满足"""
    # 检查是否是当前攻击者
    if attacker_id != room.current_attacker:
        return {'status': 'error', 'message': '还没到你的攻击回合'}

    # 检查当前是否为战斗阶段
    if room.current_phase != 'battle':
        return {'status': 'error', 'message': '当前不是战斗阶段'}

    # 检查是否已经攻击过这个位置
    if any(a.x == target_x and a.y == target_y for a in room.players[attacker_id].attacks):
        return {'status': 'error', 'message': '你已经攻击过这个位置了'}

    return {'status': 'success'}


def _execute_attack(room, room_id, attacker_id, defender_id, target_x, target_y):
    """执行攻击逻辑"""
    hit = False
    ship_sunk = False
    ship_index = -1
    
    defender_ships = room.players[defender_id].ships
    target_pos = Position(x=target_x, y=target_y)
    
    # 检查是否击中船只
    for i, ship in enumerate(defender_ships):
        if target_pos in ship.positions:
            hit = True
            ship_index = i
            break
    
    if hit:
        ship = defender_ships[ship_index]
        
        # 更新无暇圣心效果：如果有伤害，标记no_damage为False
        if 'holy_heart' in room.game_effects and not ship.invincible:  # 无敌状态不算造成伤害
            room.game_effects['holy_heart']['no_damage'] = False
        
        # 检查攻击者是否有强制击杀效果
        has_forced_kill = hasattr(room.players[attacker_id].effect_flags, 'forced_kill') and \
                         room.players[attacker_id].effect_flags.forced_kill > 0
        
        if has_forced_kill:
            ship_sunk = _handle_forced_kill(room, room_id, attacker_id, defender_id, ship_index)
        else:
            ship_sunk = _handle_normal_attack(room, room_id, attacker_id, defender_id, ship_index, target_pos)
    
    # 记录攻击信息
    room.players[attacker_id].attacks.append(Position(**{
        'x': target_x,
        'y': target_y,
        'hit': hit,
        'ship_sunk': ship_sunk
    }))
    
    return {
        'hit': hit,
        'ship_sunk': ship_sunk,
        'target_x': target_x,
        'target_y': target_y
    }


def _handle_forced_kill(room, room_id, attacker_id, defender_id, ship_index):
    """处理强制击杀效果"""
    defender_ships = room.players[defender_id].ships
    ship = defender_ships[ship_index]
    
    # 直接击沉船只
    defender_remaining_before = room.players[defender_id].remaining_ships
    room.players[defender_id].remaining_ships -= 1
    defender_remaining_after = room.players[defender_id].remaining_ships
    
    # 记录船数变化
    room.game_effects['last_ship_change'] = {
        'player': defender_id,
        'count': defender_remaining_before - defender_remaining_after
    }
    
    # 处理船只被击沉时的效果
    _handle_ship_sunk_effects(room, room_id, attacker_id, defender_id)
    
    # 减少强制击杀效果次数
    room.players[attacker_id].effect_flags.forced_kill -= 1
    if room.players[attacker_id].effect_flags.forced_kill <= 0:
        delattr(room.players[attacker_id].effect_flags, 'forced_kill')
    
    return True


def _handle_normal_attack(room, room_id, attacker_id, defender_id, ship_index, target_pos):
    """处理普通攻击"""
    defender_ships = room.players[defender_id].ships
    ship = defender_ships[ship_index]
    
    # 检查船只特殊状态
    if ship.invincible:
        # 无敌状态，只显形不造成伤害
        return False
    elif ship.shield:
        # 盾牌状态，抵挡一次伤害
        ship.shield = False
        return False
    else:
        # 记录击中位置
        defender_ships[ship_index].hits.append(target_pos)
        
        # 检查船是否被击沉
        if len(defender_ships[ship_index].hits) == len(defender_ships[ship_index].positions):
            # 记录船数变化
            defender_remaining_before = room.players[defender_id].remaining_ships
            room.players[defender_id].remaining_ships -= 1
            defender_remaining_after = room.players[defender_id].remaining_ships
            
            room.game_effects['last_ship_change'] = {
                'player': defender_id,
                'count': defender_remaining_before - defender_remaining_after
            }
            
            # 处理击沉效果
            _handle_ship_sunk_effects(room, room_id, attacker_id, defender_id)
            
            return True
        else:
            # 未击沉但造成了伤害
            _handle_damage_effects(room, room_id, attacker_id)
            return False

def _handle_ship_sunk_effects(room, room_id, attacker_id, defender_id):
    """处理船只被击沉时的效果"""
    # 检查无暇圣心效果
    if 'holy_heart' in room.game_effects:
        del room.game_effects['holy_heart']
        emit('holy_heart_interrupted', {
            'reason': '有战舰被击沉，无暇圣心效果中断'
        }, room=room_id)
    
    # 检查饮血效果
    if hasattr(room.players[attacker_id].effect_flags, 'vampire') and room.players[attacker_id].effect_flags.vampire:
        room.draw_card(attacker_id)
        emit('message', {'text': '饮血效果发动，抽一张卡'}, to=attacker_id)
        
    # 检查越战越勇效果
    if hasattr(room.players[attacker_id].effect_flags, 'battle_spirit') and room.players[attacker_id].effect_flags.battle_spirit:
        room.attacks_remaining += 2
        emit('message', {'text': '越战越勇效果发动，攻击次数增加2次'}, room=room_id)


def _handle_damage_effects(room, room_id, attacker_id):
    """处理造成伤害时的效果"""
    defender_id = next(p for p in room.players if p != attacker_id)
    
    # 检查越战越勇效果
    if hasattr(room.players[attacker_id].effect_flags, 'battle_spirit') and room.players[attacker_id].effect_flags.battle_spirit:
        room.attacks_remaining += 2
        emit('message', {'text': '越战越勇效果发动，攻击次数增加2次'}, room=room_id)
    
    # 更新本回合伤害统计
    room.players[attacker_id].damage_dealt_this_turn += 1
    
    # 检查绝处逢生效果
    if hasattr(room.players[attacker_id].effect_flags, 'last_stand') and room.players[attacker_id].effect_flags.last_stand:
        # 触发绝处逢生效果，直接获胜
        _handle_game_over(room, room_id, attacker_id, defender_id)
        return True
    
    return False


def _process_attack_result(room, room_id, attacker_id, defender_id, attack_result):
    """处理攻击结果"""
    hit = attack_result['hit']
    ship_sunk = attack_result['ship_sunk']
    target_x = attack_result['target_x']
    target_y = attack_result['target_y']
    
    # 检查回光返照效果
    if hit and room.game_effects.get('last_chance') and room.game_effects['last_chance']['caster'] == defender_id:
        # 对使用回光返照的玩家造成了伤害，回光返照使用者直接判负
        _handle_game_over(room, room_id, attacker_id, defender_id)
    
    # 记录最后一次攻击
    room.last_attack = {
        'attacker': attacker_id,
        'x': target_x,
        'y': target_y,
        'hit': hit,
        'ship_sunk': ship_sunk,
        'round': room.round
    }
    
    # 发送攻击结果
    attack_result_obj = AttackResult(
        attacker=attacker_id,
        x=target_x,
        y=target_y,
        hit=hit,
        ship_sunk=ship_sunk,
        remaining_attacks=room.attacks_remaining,
        attacker_remaining_ships=room.players[attacker_id].remaining_ships,
        defender_remaining_ships=room.players[defender_id].remaining_ships
    )
    
    emit('attack_result', attack_result_obj, room=room_id)
    
    # 记录攻击日志
    add_game_log(room, f"{room.players[attacker_id].name or attacker_id} 攻击 ({target_x},{target_y}) - {'命中' if hit else '未命中'}{'，击沉战舰' if ship_sunk else ''}",
                 'attack', {
                     'attacker': attacker_id,
                     'target': {'x': target_x, 'y': target_y},
                     'hit': hit,
                     'ship_sunk': ship_sunk
                 })
    
    # 如果船只被击沉，发送战舰数更新
    if ship_sunk:
        emit('ships_updated', {
            'player_remaining_ships': room.players[attacker_id].remaining_ships,
            'opponent_remaining_ships': room.players[defender_id].remaining_ships
        }, room=room_id)


def _handle_game_over(room, room_id, winner_id, loser_id):
    """处理游戏结束"""
    room.state = 'game_over'
    room.winner = winner_id
    
    add_game_log(room, f"{room.players[winner_id].name or winner_id} 获胜，游戏结束", 'result', {
        'winner': winner_id,
        'loser': loser_id
    })
    
    # 记录战绩
    try:
        winner_user_id = room.players[winner_id].user_id
        loser_user_id = room.players[loser_id].user_id
        if winner_user_id or loser_user_id:
            db.record_match(winner_user_id or winner_id, loser_user_id or loser_id, getattr(room, 'game_logs', None))
    except Exception:
        pass
    
    emit('game_over', {'winner': winner_id}, room=room_id)
    return {'status': 'success', 'game_over': True}


def _update_attack_count(room, room_id, attacker_id):
    """更新攻击次数"""
    room.attacks_remaining = max(0, room.attacks_remaining - 1)
    
    # 如果是AI玩家，自动结束回合
    if attacker_id.startswith('AI_') and room.attacks_remaining == 0:
        _auto_end_ai_turn(room, room_id, attacker_id)


def _auto_end_ai_turn(room, room_id, ai_player_id):
    """AI玩家自动结束回合"""
    # 模拟结束阶段处理时间
    threading.Thread(target=_end_ai_turn, args=(room, room_id, ai_player_id)).start()


def _end_ai_turn(room, room_id, ai_player_id):
    """结束AI玩家的回合"""
    time.sleep(1)  # 延迟，让玩家有时间看到AI的行动
    
    # 调用结束阶段处理
    handle_enter_end_phase({
        'room_id': room_id,
        'player_id': ai_player_id
    })


@socketio.on('attack')
def handle_attack_wrapper(data):
    """攻击处理的包装函数，保持与原代码兼容"""
    return handle_attack(data)


def handle_area_attack(room_id, caster_id, positions, attack_type, attack_name, target_data=None):
    """处理区域攻击的主函数，遵循与普通攻击相同的处理流程
    
    Args:
        room_id: 房间ID
        caster_id: 施法者ID
        positions: 攻击位置列表
        attack_type: 攻击类型 ('bomb' 或 'sulfur')
        attack_name: 攻击名称（用于日志）
        target_data: 额外的目标数据（如轰炸的目标行/列）
    
    Returns:
        dict: 攻击结果
    """
    room = room_manager.get_room(room_id)
    if not room or caster_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}
    
    # 找到对手
    defender_id = next(p for p in room.players if p != caster_id)
    opponent = room.players[defender_id]
    
    # 执行区域攻击
    sunk_count, affected_positions = _handle_area_attack(room, caster_id, opponent, positions, attack_type, attack_name)
    
    # 检查游戏是否结束
    if opponent.remaining_ships == 0:
        return _handle_game_over(room, room_id, caster_id, defender_id)
    
    # 处理攻击次数更新
    _update_attack_count(room, room_id, caster_id)
    
    return {'status': 'success', 'sunk_count': sunk_count, 'affected_positions': affected_positions}


@socketio.on('enter_end_phase')
def handle_enter_end_phase(data):
    room_id = data['room_id']
    player_id = data['player_id']

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
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

        # 找到对手ID
        opponent_id = next(p for p in room.players if p != player_id)
        
        # 如果对手是AI玩家，自动切换回合并执行AI的行动
        if opponent_id.startswith('AI_'):
            import threading
            # 在后台线程中执行AI的回合，避免阻塞
            threading.Thread(target=switch_turn_and_ai_action, args=(room, opponent_id)).start()
        else:
            # 真实玩家，正常切换回合
            import threading
            threading.Thread(target=switch_turn_after_end_phase, args=(room, opponent_id)).start()

        return {'status': 'success', 'message': '已进入结束阶段'}


def switch_turn_and_ai_action(room, ai_player_id):
    """切换到AI回合并执行AI的行动"""
    # 模拟结束阶段处理时间
    time.sleep(2)

    # 切换到AI回合
    room.current_attacker = ai_player_id
    room.attacks_remaining = len(room.players[ai_player_id].ships)  # 根据战舰数量设置攻击次数
    room.current_phase = 'preparation'
    
    # 重置本回合伤害统计
    room.players[ai_player_id].damage_dealt_this_turn = 0

    # 广播回合变化
    emit('turn_change', {
        'current_attacker': ai_player_id,
        'attacks_remaining': room.attacks_remaining,
        'phase': 'preparation'
    }, room=room.id)
    
    # 执行AI的行动
    AIPlayer.execute_turn(room, ai_player_id)
    
    # AI行动完成后，自动结束回合
    if room.state == 'attacking' and room.current_attacker == ai_player_id:
        # 模拟AI结束回合的延迟
        time.sleep(1)
        
        # 调用handle_enter_end_phase函数结束AI的回合
        handle_enter_end_phase({
            'room_id': room.id,
            'player_id': ai_player_id
        })


def switch_turn_after_end_phase(room, opponent_id):
    # 模拟结束阶段处理时间
    time.sleep(2)

    # 切换到对方回合
    room.current_attacker = opponent_id
    room.attacks_remaining = len(room.players[opponent_id].ships)  # 根据战舰数量设置攻击次数
    room.current_phase = 'preparation'
    
    # 重置本回合伤害统计
    room.players[opponent_id].damage_dealt_this_turn = 0

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

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

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
            room.rps_processed = False

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
            
            # 检查新攻击者的船只冻结状态，清除过期效果
            new_attacker_ships = room.players[room.current_attacker].ships
            for ship in new_attacker_ships:
                if hasattr(ship, 'frozen') and ship.frozen <= room.round:
                    # 冻结效果已过期，移除冻结状态
                    delattr(ship, 'frozen')
            
            # 初始攻击次数设置为剩余船只数，在进入战斗阶段时会重新计算（考虑冻结效果）
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

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    player = room.players[player_id]
    opponent_id = next(p for p in room.players if p != player_id)

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
    chain_item = ChainItem(player_id, card, targets, time.time())
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
        return speed in [1, 2]
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
        player_id = chain_item.player_id
        card = chain_item.card
        targets = chain_item.targets

        # 应用卡牌效果
        result = apply_magic_effect(room, player_id, card, targets)
        # 添加施法者信息到结果中
        result.caster = player_id
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

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

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
        chain_item = ChainItem(player_id, card, targets, time.time())
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

    room = room_manager.get_room(room_id)
    if not room or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

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

    room = room_manager.get_room(room_id)
    if room and player_id in room.players:
        # 将场地魔法加入弃牌堆
        if room.field_magic:
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
    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}
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
    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}
    positions = room.players[player_id].revealed_positions
    # 只发送给请求者
    emit('revealed_positions', {'positions': positions}, to=player_id)
    return {'status': 'success'}


@socketio.on('get_magic_temp_data')
def get_magic_temp_data(data):
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players:
        return {'status': 'error', 'message': '无效的房间或玩家'}
    return {'status': 'success', 'data': room.magic_temp_data}


@socketio.on('confirm_magic_target')
def confirm_magic_target(data):
    room_id = data.get('room_id')
    player_id = data.get('player_id')
    temp_data_id = data.get('temp_data_id')
    target_data = data.get('target_data', {})

    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players:
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

        return {'status': 'success', 'message': '灵气复苏船数选择完成'}
    elif temp_data_id == 'bury_choice':
        # 处理明智埋葬的选择
        card_key = target_data.get('card_key')
        caster = room.players[player_id]
        opponent_id = next(p for p in room.players if p != player_id)
        opponent = room.players[opponent_id]
        
        # 验证选择
        if card_key is None:
            return {'status': 'error', 'message': '未选择卡牌'}
        
        # 从不同来源查找并移除选中的卡牌
        card_to_remove = None
        card_source = None
        
        # 1. 检查施法者的手牌
        for i, card in enumerate(caster.magic_hand):
            if f"{card.name}_{card.speed}" == card_key:
                card_to_remove = card
                card_source = 'caster_hand'
                caster.magic_hand.pop(i)
                break
        
        # 2. 如果不在施法者的手牌中，检查对方的手牌
        if card_to_remove is None:
            for i, card in enumerate(opponent.magic_hand):
                if f"{card.name}_{card.speed}" == card_key:
                    card_to_remove = card
                    card_source = 'opponent_hand'
                    opponent.magic_hand.pop(i)
                    break
        
        # 3. 如果不在对方的手牌中，检查牌堆
        if card_to_remove is None:
            for i, card in enumerate(room.magic_deck):
                if f"{card.name}_{card.speed}" == card_key:
                    card_to_remove = card
                    card_source = 'deck'
                    room.magic_deck.pop(i)
                    break
        
        if card_to_remove is None:
            return {'status': 'error', 'message': '卡牌不存在'}
        
        # 将选中的卡放入弃牌堆
        room.magic_discard.append(card_to_remove)
        # 抽一张新卡
        room.draw_card(player_id)
        room.magic_temp_data = {}
        
        # 通知双方手牌更新
        emit('hand_updated', {
            'hand': caster.magic_hand
        }, to=player_id)
        
        emit('hand_updated', {
            'hand': opponent.magic_hand
        }, to=opponent_id)
        
        # 通知弃牌堆更新
        emit('discard_pile_updated', {
            'discard': room.magic_discard
        }, room=room.id)
        
        return {'status': 'success', 'message': '埋葬完成'}
    
    return {'status': 'error', 'message': '无效的临时数据ID'}


@socketio.on('get_discard_pile')
def get_discard_pile(data):
    """获取玩家的弃牌堆数据（返回全局弃牌堆）"""
    room_id = data.get('room_id')
    player_id = data.get('player_id')

    room = room_manager.get_room(room_id)
    if not room or not player_id or player_id not in room.players:
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


def apply_magic_effect(room: GameRoom, caster_id: str, card: MagicCard, target_data):
    result = ChainResult(card=card, caster=caster_id, success=True, message='')
    opponent_id = next(p for p in room.players if p != caster_id)
    caster = room.players[caster_id]
    opponent = room.players[opponent_id]
    print(f"Applying magic effect: {card.name} target {target_data}")
    
    # 通用魔法卡使用日志
    caster_name = caster.name or caster_id
    add_game_log(room, f"{caster_name} 使用了魔法卡 {card.name}", 'magic', {
        'caster_id': caster_id,
        'card_name': card.name,
        'card_type': card.type,
        'target_data': target_data
    })


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
        add_game_log(room, f"{caster_name} 使用余音绕梁，接下来两个攻击阶段将造成强制击杀", 'magic', {
            'effect': 'forced_kill',
            'duration': 2
        })
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
            result.message = f'抽了{len(drawn_cards)}张牌，请选择'
            result.temp_data_id = 'taoyuan_choice'
            # 通知对手等待
            emit('taoyuan_waiting', {
                'message': '对方正在结算桃园结义效果 请等待'
            }, to=opponent_id)
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
        add_game_log(room, f"{caster_name} 使用无中生有，抽了2张牌，本回合双方无法获得魔法卡", 'magic', {
            'drawn_cards': 2,
            'no_draw_effect': True
        })

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
        add_game_log(room, f"{caster_name} 使用极限增援，两个大回合后船少的一方获胜", 'magic', {
            'remaining_turns': total_turns
        })

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
        add_game_log(room, f"{caster_name} 使用无暇圣心，两个大回合后双方都未造成伤害则获胜", 'magic', {
            'remaining_turns': total_turns
        })

    elif card.name == '火力全开':
        # 本回合攻击次数翻倍
        room.players[caster_id].effect_flags.double_attacks = True
        result.message = '本回合攻击次数翻倍'
        def func(room:GameRoom):
            room.attacks_remaining*=2
            room.pop_effect(card.name)
        room.effects.append(Effect(card.name,"before_attack","",999,func))
        add_game_log(room, f"{caster_name} 使用火力全开，本回合攻击次数翻倍", 'magic', {
            'effect': 'double_attacks'
        })

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
        result.message = '请选择灵气复苏的船数'
        result.temp_data_id = 'lingqi_choice'
        result.max_ships = max_ships

        # 通知对手等待
        emit('lingqi_waiting', {
            'message': '对方正在结算灵气复苏效果 请等待'
        }, to=opponent_id)
    
    elif card.name == '教皇旨意':
        # 场地魔法，攻击次数变为0，通过弃置魔法卡攻击
        room.field_magic = card
        room.game_effects['papal_edict'] = True
        result['message'] = '教皇旨意已生效，双方攻击次数变为0，通过弃置魔法卡攻击对方两次'

    elif card.name == '败者食尘':
        # 记录败者食尘打出前双方的船数，已修复
        original_caster_ships = len(caster.ships)
        original_opponent_ships = len(opponent.ships)
        
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
                        
                        # 检查回光返照效果
                        if room.game_effects.get('last_chance') and room.game_effects['last_chance']['caster'] == opponent_id:
                            # 对使用回光返照的玩家造成了伤害，回光返照使用者直接判负
                            room.state = 'game_over'
                            room.winner = caster_id
                            add_game_log(room, f"{room.players[opponent_id].name or opponent_id} 触发回光返照失败并判负", 'result', {
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
            
            # 记录受影响的位置（仅记录攻击覆盖的位置）
            affected_positions.append(Position(x=x, y=y, hit=False, ship_sunk=False))

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
        add_game_log(room, f"{caster_name} 使用溅射，命中{hit_count}个目标", 'magic', {
            'affected_positions': affected_positions,
            'hit_count': hit_count
        })

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
        add_game_log(room, f"{caster_name} 使用雷达子弹，扫描了击中位置周围八格的战舰", 'magic', {
            'scanned_positions': new_positions
        })

    elif card.name == '越战越勇':
        # 每造成一次伤害，攻击次数加2
        if not room.last_attack or room.last_attack['attacker'] != caster_id or not room.last_attack['hit']:
            result['success'] = False
            result['message'] = '必须在击中对方战舰后使用'
            return result

        # 添加越战越勇效果标记
        room.players[caster_id].effect_flags.battle_spirit = True
        result['message'] = '越战越勇效果生效，本回合每造成一次伤害攻击次数加2'
        add_game_log(room, f"{caster_name} 使用越战越勇，本回合每造成一次伤害攻击次数加2", 'magic', {
            'effect': 'battle_spirit'
        })

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
            in_area = False
            
            # 安全检查：确保ship.positions是可迭代的
            if hasattr(ship, 'positions') and isinstance(ship.positions, (list, tuple, set)):
                in_area = any(
                    area['x1'] <= pos.x <= area['x2'] and
                    area['y1'] <= pos.y <= area['y2']
                    for pos in ship.positions
                )

            if in_area:
                excluded_ships.append(ship)
                del opponent.ships[i]
                opponent.remaining_ships -= 1

        # 确保excluded_ships始终是列表
        if not isinstance(excluded_ships, list):
            excluded_ships = [excluded_ships]

        # 如果只有一艘船被除外，直接击沉
        if len(excluded_ships) == 1:
            result['message'] = '目标区域内1艘战舰被击沉'
            add_game_log(room, f"{caster_name} 使用神威！，目标区域内1艘战舰被直接击沉", 'magic', {
                'target_area': area,
                'ships_affected': 1,
                'effect': 'sink'
            })
        else:
            # 记录暂时除外的战舰，下一回合回归
            # 只存储必要的信息，避免存储PlayerShip对象
            room.game_effects['excluded_ships'] = {
                'ships_count': len(excluded_ships),
                'player': opponent_id,
                'return_turn': room.round + 1
            }
            result['message'] = f'目标区域内{len(excluded_ships)}艘战舰被暂时除外'
            add_game_log(room, f"{caster_name} 使用神威！，目标区域内{len(excluded_ships)}艘战舰被暂时除外", 'magic', {
                'target_area': area,
                'ships_affected': len(excluded_ships),
                'effect': 'exclude',
                'return_turn': room.round + 1
            })

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
            in_area = False
            for pos in ship.positions:
                if area['x1'] <= pos.x <= area['x2'] and area['y1'] <= pos.y <= area['y2']:
                    in_area = True
                    break

            if in_area and not hasattr(ship, 'frozen'):
                ship.frozen = room.round + 1  # 冻结到下一回合
                frozen_count += 1

        result['message'] = f'冻结了{frozen_count}艘战舰'
        add_game_log(room, f"{caster_name} 使用冻结，冻结了{frozen_count}艘战舰", 'magic', {
            'target_area': area,
            'frozen_count': frozen_count,
            'effect': 'freeze'
        })



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

        # 调用通用函数处理区域攻击
        sunk_count, _ = _handle_area_attack(room, caster_id, opponent, positions, 'bomb', '轰炸')

        result['message'] = f'轰炸成功击沉{sunk_count}艘战舰'
        add_game_log(room, f"{caster_name} 使用轰炸，成功击沉{sunk_count}艘战舰", 'magic', {
            'target_line': line,
            'sunk_count': sunk_count,
            'effect': 'bombard'
        })

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

        # 调用通用函数处理区域攻击
        sunk_count, affected_positions = _handle_area_attack(room, caster_id, opponent, positions, 'sulfur', '硫磺火焰')

        result['message'] = f'硫磺火焰成功击杀{sunk_count}艘战舰'
        result['affected_positions'] = affected_positions
        result['caster_id'] = caster_id
        
        # 添加游戏日志
        add_game_log(room, f"{room.players[caster_id].name or caster_id} 使用了硫磺火焰，击杀了{sunk_count}艘战舰", 'magic', {
            'caster_id': caster_id,
            'card_name': card.name,
            'sunk_count': sunk_count,
            'affected_positions': affected_positions
        })
    elif card.name == '饮血':
        # 每击杀一艘船，抽一张牌
        room.players[caster_id].effect_flags = room.players[caster_id].effect_flags
        room.players[caster_id].effect_flags.vampire = True
        add_game_log(room, f"{caster_name} 使用饮血，每击杀一艘船将抽一张牌", 'magic', {
            'effect': 'vampire'
        })
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
        add_game_log(room, f"{caster_name} 使用克苏鲁之眼，双方各暴露一艘战舰位置", 'magic', {
            'effect': 'mutual_reveal'
        })

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
        add_game_log(room, f"{caster_name} 使用Freezing！，成功跳过对方回合", 'magic', {
            'effect': 'skip_turn',
            'skipped_player': opponent_id
        })

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
            add_game_log(room, f"{caster_name} 使用五险一金，未造成伤害，攻击次数+3", 'magic', {
                'effect': 'add_attacks',
                'attacks_added': 3
            })
        else:
            result['success'] = False
            result['message'] = '本回合已造成伤害，无法发动'

    elif card.name == '明智埋葬':
        # 选择一张不在弃牌堆中的魔法卡，将其放入弃牌堆并抽一张牌
        if not caster.magic_hand:
            result['success'] = False
            result['message'] = '手牌为空，无法发动'
            return result
        
        # 收集所有不在弃牌堆中的卡牌
        opponent_id = next(p for p in room.players if p != caster_id)
        opponent = room.players[opponent_id]
        
        # 收集所有可选卡牌：施法者的手牌 + 对方的手牌 + 牌堆中的牌
        available_cards = []
        
        # 添加施法者的手牌
        for card in caster.magic_hand:
            card_key = f"{card.name}_{card.speed}"
            if card_key not in [f"{c.name}_{c.speed}" for c in room.magic_discard]:
                available_cards.append({
                    'name': card.name,
                    'speed': card.speed,
                    'type': card.type,
                    'description': card.description,
                    'source': 'caster_hand',
                    'card_key': card_key
                })
        
        # 添加对方的手牌
        for card in opponent.magic_hand:
            card_key = f"{card.name}_{card.speed}"
            if card_key not in [f"{c.name}_{c.speed}" for c in room.magic_discard]:
                available_cards.append({
                    'name': card.name,
                    'speed': card.speed,
                    'type': card.type,
                    'description': card.description,
                    'source': 'opponent_hand',
                    'card_key': card_key
                })
        
        # 添加牌堆中的牌
        for card in room.magic_deck:
            card_key = f"{card.name}_{card.speed}"
            if card_key not in [f"{c.name}_{c.speed}" for c in room.magic_discard]:
                available_cards.append({
                    'name': card.name,
                    'speed': card.speed,
                    'type': card.type,
                    'description': card.description,
                    'source': 'deck',
                    'card_key': card_key
                })
        
        # 记录需要选择的牌
        room.magic_temp_data = {
            'type': 'bury_choice',
            'caster': caster_id,
            'cards': available_cards
        }
        result['message'] = '请选择要埋葬的卡牌'
        result['temp_data_id'] = 'bury_choice'
        
        # 发送选择界面事件给客户端
        emit('bury_choice_selection', {
            'caster': caster_id,
            'cards': available_cards
        }, room=room.id)

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
        add_game_log(room, f"{caster_name} 使用仁王之盾，准备选择要保护的战舰", 'magic', {
            'effect': 'shield_protection'
        })

    # ==== 速阶3 魔法卡 ====
    elif card.name == '八方来财':
        # 战舰数目主动变化时抽一张牌
        room.players[caster_id].effect_flags = room.players[caster_id].effect_flags
        room.players[caster_id].effect_flags.treasure_hunter = True
        result['message'] = '战舰数目变化时抽一张牌'
        add_game_log(room, f"{caster_name} 使用八方来财，战舰数目变化时将抽一张牌", 'magic', {
            'effect': 'treasure_hunter'
        })

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
        add_game_log(room, f"{caster_name} 使用平等条约，成功无效化船数改变效果", 'magic', {
            'effect': 'nullify_ship_change',
            'last_change': last_change
        })

    elif card.name == '百亿补贴':
        # 船被击败时攻击次数加3
        room.players[caster_id].effect_flags = room.players[caster_id].effect_flags
        room.players[caster_id].effect_flags.subsidy = True
        result['message'] = '船被击败时攻击次数加3'
        add_game_log(room, f"{caster_name} 使用百亿补贴，船被击败时攻击次数加3", 'magic', {
            'effect': 'subsidy'
        })

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
            add_game_log(room, f"{caster_name} 使用神之宣告，牺牲两艘战舰，对方被迫选择一艘战舰摧毁", 'magic', {
                'effect': 'sacrifice_destroy',
                'sacrificed_ships': 2,
                'destroyed_ships': 1
            })
        else:
            # 跳过对方所有阶段
            room.skip_opponent_turn = True
            result['message'] = '牺牲两艘战舰，跳过对方本回合所有阶段'
            add_game_log(room, f"{caster_name} 使用神之宣告，牺牲两艘战舰，跳过对方本回合所有阶段", 'magic', {
                'effect': 'sacrifice_skip',
                'sacrificed_ships': 2
            })

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
        add_game_log(room, f"{caster_name} 使用绝处逢生，进入绝处逢生状态，击杀任何船直接获胜", 'magic', {
            'effect': 'last_stand',
            'remaining_ships': 1
        })

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
            add_game_log(room, f"{caster_name} 使用死者苏生，成功复活一艘战舰", 'magic', {
                'effect': 'revive',
                'revived_count': 1
            })
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
        add_game_log(room, f"{caster_name} 使用疗愈，成功复活{revived}艘战舰", 'magic', {
            'effect': 'heal',
            'revived_count': revived
        })

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
        add_game_log(room, f"{caster_name} 使用盗亦有道，成功盗取对方的{stolen_card.name}", 'magic', {
            'effect': 'steal_card',
            'stolen_card': stolen_card.name
        })

    elif card.name == '回光返照':
        # 回光返照的日志将在效果触发时添加（如在溅射攻击中）
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
        add_game_log(room, f"{caster_name} 使用回光返照，清空棋盘重新摆放战舰", 'magic', {
            'effect': 'last_chance',
            'risky_move': True
        })

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
        add_game_log(room, f"{caster_name} 使用加百列之光，成功无效化{negated_count}个效果", 'magic', {
            'effect': 'negate_magic',
            'negated_count': negated_count
        })

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
        add_game_log(room, f"{caster_name} 使用钢筋铁骨，牺牲一艘战舰，其他战舰进入无敌状态", 'magic', {
            'effect': 'invincibility',
            'sacrificed_ships': 1,
            'invincible_ships': len(caster.ships)
        })

    elif card.name == '神机妙算':
        # 宣言x，如果结束阶段船数减少x，那些船不会减少
        if 'prediction' not in room.magic_temp_data:
            result.success = False
            result.message = '需要宣言减少的船数'
            return result

        x = room.magic_temp_data['prediction']
        room.players[caster_id].effect_flags = room.players[caster_id].effect_flags
        room.players[caster_id].effect_flags.prediction = x
        result.message = f'宣言船数减少{x}，若预测成功则不会减少'
        add_game_log(room, f"{caster_name} 使用神机妙算，宣言船数减少{x}", 'magic', {
            'effect': 'prediction',
            'predicted_value': x
        })

    # ==== 场地魔法卡 ====
    elif card.type == '场地':
        # 场地魔法处理 - 全场只能有一张场地魔法卡生效
        # 移除所有玩家的场地魔法卡
        discarded = None
        if room.field_magic:
            discarded = room.field_magic
            room.discard_card(caster_id, MagicCard(room.field_magic))
            emit('field_magic_updated', {
                'player_id': caster_id,
                'card': None
            }, room=room.id)
        # 设置新的场地魔法卡
        room.field_magic = card.name
        add_game_log(room, f"{caster_name} 使用场地魔法 {card.name}{f'，替换了{discarded}' if discarded else ''}", 'magic', {
            'effect': 'field_magic',
            'card_name': card.name,
            'replaced': discarded
        })

        # 根据具体场地魔法卡设置不同的消息
        if card.name == '恶魔契约':
            result.message = '恶魔契约生效，双方船数增减绑定'
        elif card.name == '禁忌果实':
            result.message = '禁忌果实生效，双方只能使用失灵！和场地魔法'
        elif card.name == '伊甸园':
            result.message = '伊甸园生效，攻击次数变为6-n'
        elif card.name == '教皇旨意':
            result.message = '教皇旨意生效，攻击需要弃置魔法卡'

    # ==== 已实现的魔法卡 ====
    elif card.name == '失灵！':
        # 无效化对方上一张魔法卡
        if room.magic_history and room.magic_history[-1]['caster'] != caster_id:
            last_magic = room.magic_history.pop()
            result.message = f'无效化了{last_magic["card"]["name"]}'
            result.negated = last_magic
            add_game_log(room, f"{caster_name} 使用失灵！，无效化了对方的{last_magic["card"]["name"]}", 'magic', {
                'effect': 'negate_last_magic',
                'negated_card': last_magic["card"]["name"]
            })
        else:
            result.success = False
            result.message = '没有可无效化的魔法卡'

    elif card.name == '看破！':
        # 无效化对方本回合所有魔法卡
        room.players[opponent_id].magic_blocked = True
        result.message = '本回合对方魔法卡被无效化'
        add_game_log(room, f"{caster_name} 使用看破！，本回合对方魔法卡被无效化", 'magic', {
            'effect': 'block_magic',
            'target_player': opponent_id
        })

    elif card.name == '增援':
        # 召唤一艘战舰：等待玩家选择放置位置
        if len(caster.ships) >= 6:
            result.success = False
            result.message = '战舰数量已达上限'
        else:
            # 存储临时数据以等待客户端确认位置
            room.magic_temp_data = room.magic_temp_data
            room.magic_temp_data['pending_reinforcement'] = {
                'caster': caster_id
            }
            result.temp_data_id = 'reinforcement_choice'
            result.message = '请选择增援放置位置'
            add_game_log(room, f"{caster_name} 使用增援，准备召唤一艘战舰", 'magic', {
                'effect': 'reinforce',
                'max_ships': 6,
                'current_ships': len(caster.ships)
            })

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
            result.message = f'抽了{len(drawn_cards)}张牌，请选择'
            result.temp_data_id = 'taoyuan_choice'
        else:
            result.success = False
            result.message = '无法抽取卡牌'

    else:
        result.success = False
        result.message = f'未实现的魔法卡: {card.name}'



    
    #result['success'] = False
    #result['message'] = f'魔法效果应用失败: {str(e)}'
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

def _handle_area_attack(room, caster_id, opponent, positions, attack_type, attack_name):
    """处理区域攻击的通用函数
    
    Args:
        room: GameRoom对象
        caster_id: 施法者ID
        opponent: 对手Player对象
        positions: 攻击位置列表
        attack_type: 攻击类型 ('bomb' 或 'sulfur')
        attack_name: 攻击名称（用于日志）
    
    Returns:
        tuple: (击沉的船只数量, 受影响的位置列表)
    """
    caster = room.players[caster_id]
    sunk_count = 0
    ships_changed = False
    removed_positions = set()
    affected_positions = []
    
    # 找出所有与这些格子相交的船只
    to_remove = [ship for ship in opponent.ships if any(pos in ship.positions for pos in positions)]
    
    # 移除受影响的船只，并为其所有格子生成命中事件
    for ship in to_remove:
        if ship in opponent.ships:
            opponent.ships.remove(ship)
            opponent.remaining_ships -= 1
            ships_changed = True
            sunk_count += 1
            
            for ship_pos in ship.positions:
                # 处理不同类型的位置对象（可能是字典或Position对象）
                x = ship_pos.x if hasattr(ship_pos, 'x') else ship_pos['x']
                y = ship_pos.y if hasattr(ship_pos, 'y') else ship_pos['y']
                
                removed_positions.add((x, y))
                
                # 创建攻击记录
                position_kwargs = {
                    'x': x,
                    'y': y,
                    'hit': True,
                    'ship_sunk': True
                }
                if attack_type == 'bomb':
                    position_kwargs['is_bomb'] = True
                elif attack_type == 'sulfur':
                    position_kwargs['is_sulfur'] = True
                
                caster.attacks.append(Position(**position_kwargs))
                
                # 创建攻击结果对象（与普通攻击保持一致的格式）
                attack_result_obj = AttackResult(
                    attacker=caster_id,
                    x=x,
                    y=y,
                    hit=True,
                    ship_sunk=True,
                    remaining_attacks=room.attacks_remaining,
                    attacker_remaining_ships=room.players[caster_id].remaining_ships,
                    defender_remaining_ships=opponent.remaining_ships
                )
                
                emit('attack_result', attack_result_obj, room=room.id)
                
                # 记录受影响的位置
                affected_positions.append(Position(x=x, y=y, hit=True, ship_sunk=True))
    
    # 对于该区域中未命中的格子也发出未命中事件，以保持 UI 一致性
    for pos in positions:
        x = pos['x'] if isinstance(pos, dict) else pos.x
        y = pos['y'] if isinstance(pos, dict) else pos.y
        
        if (x, y) not in removed_positions:
            # 创建攻击记录
            position_kwargs = {
                'x': x,
                'y': y,
                'hit': False,
                'ship_sunk': False
            }
            if attack_type == 'bomb':
                position_kwargs['is_bomb'] = True
            elif attack_type == 'sulfur':
                position_kwargs['is_sulfur'] = True
            
            caster.attacks.append(Position(**position_kwargs))
            
            # 创建攻击结果对象（与普通攻击保持一致的格式）
            attack_result_obj = AttackResult(
                attacker=caster_id,
                x=x,
                y=y,
                hit=False,
                ship_sunk=False,
                remaining_attacks=room.attacks_remaining,
                attacker_remaining_ships=room.players[caster_id].remaining_ships,
                defender_remaining_ships=opponent.remaining_ships
            )
            
            emit('attack_result', attack_result_obj, room=room.id)
            
            # 记录受影响的位置
            affected_positions.append(Position(x=x, y=y, hit=False, ship_sunk=False))
    
    # 广播被摧毁舰只更新
    if ships_changed:
        emit('ships_updated', {
            'player_remaining_ships': room.players[caster_id].remaining_ships,
            'opponent_remaining_ships': opponent.remaining_ships
        }, room=room.id)
    
    return sunk_count, affected_positions

if __name__ == '__main__':
    # 初始化数据库
    db.init_db()
    # 添加详细日志输出

    logging.basicConfig(level=logging.DEBUG)
    # 启动服务器
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
