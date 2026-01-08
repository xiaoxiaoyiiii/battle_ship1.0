from flask import Flask, render_template, request, session, redirect, url_for, flash
from flask_socketio import SocketIO, join_room, leave_room, emit
import random
import uuid
import os
import time
from werkzeug.security import generate_password_hash, check_password_hash
import db  # local database helpers for users and matches

# 添加魔法卡牌数据定义（与客户端 magic_cards.js 保持一致）
magic_cards = [
    # 基础魔法卡 - 3张失灵！
    {"name": "失灵！", "speed": 3, "type": "普通", "description": "无效化对方使用的上一张魔法卡，被影响的魔法卡必须为当前时段刚使用的。这张牌会受'看破'影响，但是不会影响看破。"},
    {"name": "失灵！", "speed": 3, "type": "普通", "description": "无效化对方使用的上一张魔法卡，被影响的魔法卡必须为当前时段刚使用的。这张牌会受'看破'影响，但是不会影响看破。"},
    {"name": "失灵！", "speed": 3, "type": "普通", "description": "无效化对方使用的上一张魔法卡，被影响的魔法卡必须为当前时段刚使用的。这张牌会受'看破'影响，但是不会影响看破。"},

    # 其他魔法卡
    {"name": "溅射", "speed": 2, "type": "普通", "description": "可在击中对方后选择使用。这次攻击若击中对方的战舰，则对这个格子的上下左右周围四格造成同等伤害。这次伤害不受状态'无敌'影响。"},
    {"name": "雷达子弹", "speed": 2, "type": "普通", "description": "可在击中对方后选择使用。本回合的这一下攻击若击中对方的战舰，则对其周围八格进行扫描并且显形出对方的战舰。"},
    {"name": "越战越勇", "speed": 2, "type": "普通", "description": "可在击中对方后选择使用。本回合自己的战斗阶段每对对方造成一次伤害，攻击次数加2。命中状态'盾牌'不算造成伤害，其他技能触发的伤害也会触发这张牌的效果。"},
    {"name": "余音绕梁", "speed": 1, "type": "普通", "description": "这张牌只能在自己的准备阶段使用。这张牌成功生效之后，接下来的自己的攻击阶段和下一个回合自己的攻击阶段造成的伤害将会强制击杀那个被造成伤害的格子上的船，可以直接击杀状态'无敌'和状态'盾牌'的战舰。"},
    {"name": "神威！", "speed": 2, "type": "普通", "description": "选定己方或者对方棋盘上的3*3的区域格子，将这些格子中的战舰全部从这场游戏中暂时除外，并在下一个大回合开始时回归到原本的地方。若选定的是对方的棋盘并且在3*3的格子中只有一艘船，那么那艘船直接死亡。"},
    {"name": "增援", "speed": 3, "type": "普通", "description": "召唤一艘战舰并选择部署在没有被对方打过的一个格子上。"},
    {"name": "恶魔契约", "speed": 2, "type": "场地", "description": "这张牌作为场地魔法卡使用。接下来，双方的船数增减将会绑定。对方的一艘船被击杀了，我也要选择一艘我自己的船让他死亡。我的船少了一艘，对方也要选择一艘船让他死亡。'恶魔契约'的效果在每一次攻击生效后只结算一次，不会出现双方在一次攻击后一至少一至少的情况。"},
    {"name": "八方来财", "speed": 3, "type": "普通", "description": "只可以在双方的准备阶段使用。接下来如果场上的战舰数目主动发生了变化，每发生一次变化，自己摸一张牌。己方击败对方的船不算主动发生变化。"},
    {"name": "平等条约", "speed": 3, "type": "普通", "description": "在双方场上有船数改变的场合可以立即发动，使那个使船数改变的攻击/魔法卡无效化。"},
    {"name": "禁忌果实", "speed": 1, "type": "场地", "description": "这张牌作为场地魔法卡使用。接下来，双方都无法使用任何魔法卡，除去'失灵！'与其他场地魔法卡。"},
    {"name": "硫磺火焰", "speed": 2, "type": "普通", "description": "选定可以连续连接的6个格子，对这6个格子释放硫磺火焰并强制击杀上面的所有战舰，可以直接击杀状态'无敌'和状态'盾牌'的战舰。"},
    {"name": "百亿补贴", "speed": 3, "type": "普通", "description": "在这张牌成功生效之后，接下来如果自己的船被对方不管用什么手段击败了，自己的攻击次数每有一艘船死亡就加3。"},
    {"name": "看破！", "speed": 2, "type": "普通", "description": "这张牌生效后，这一个大回合内，对方所有魔法卡都无效化。这张牌不受'失灵！'影响，但是会影响'失灵！'。"},
    {"name": "冻结", "speed": 2, "type": "普通", "description": "选定对方场上的3*3区域，将其上的船冻结。被冻结的船这一个大回合的攻击阶段和下一个大回合的攻击都被删除，就是总攻击次数减去被冻结的船数。"},
    {"name": "轰炸", "speed": 2, "type": "普通", "description": "选定对方场上的一行或一列进行轰炸，这一行或这一列的船全部死亡。"},
    {"name": "探测雷达", "speed": 2, "type": "普通", "description": "选定对方场上的2*2区域并对其进行探测，被探测出来的船直接显形。"},
    {"name": "伊甸园", "speed": 1, "type": "场地", "description": "这张牌作为场地魔法卡使用。接下来双方的攻击次数都变为（6-n），n为自己的战舰数目。"},
    {"name": "神之宣告", "speed": 3, "type": "普通", "description": "选定自己的两艘船死亡并选择接下来两个效果其一发动：1.让对方选择自己的一艘船并使他死亡；2.跳过这一个大回合内对方的所有阶段。"},
    {"name": "五险一金", "speed": 2, "type": "普通", "description": "如果这一回合自己没有对对方造成一点伤害，那么自己的攻击次数再加3。"},
    {"name": "绝处逢生", "speed": 3, "type": "普通", "description": "在自己的战舰数目大于等于3时才可以发动。牺牲自己所有的战舰并在所有原本有战舰的地方选择一个放置唯一一艘战舰。接下来，只要自己击杀对方的任何一艘船，自己直接获胜。在绝处逢生生效的回合，自己的其余魔法卡全部无效。"},
    {"name": "死者苏生", "speed": 3, "type": "普通", "description": "复活自己的一艘船并将他摆放在对方没有打过的格子上。"},
    {"name": "疗愈", "speed": 3, "type": "普通", "description": "选定自己至多两艘被击杀的船并将他们在原地复活。"},
    {"name": "军备竞赛", "speed": 1, "type": "普通", "description": "将对方的战舰数变得和自己一样。如果对方多于自己，则要对方主动挑选牺牲多出去的船。如果对方少于自己，则对方只可在没有被打过的格子中放置少了的船。"},
    {"name": "桃园结义", "speed": 1, "type": "普通", "description": "从牌堆中抽取n张牌，n为自己的战舰数。在这一堆牌中优先为自己挑选一张，然后再在剩余的里面挑选一张给对方。对方不可见被抽出来的所有n张牌。如果n为1，则优先给自己被摸出来的那张牌。"},
    {"name": "无中生有", "speed": 1, "type": "普通", "description": "从牌堆中摸两张牌。接下来这一个大回合内，双方都无法以任何方式获得魔法卡。"},
    {"name": "饮血", "speed": 2, "type": "普通", "description": "可在击中对方后选择使用。接下来自己的攻击，每击杀一艘船，自己摸一张牌。"},
    {"name": "极限增援", "speed": 1, "type": "普通", "description": "这张牌生效后，后来两个大回合（不算他生效的这个大回合）结束时，判断双方的船数，船数少的一方直接获胜。"},
    {"name": "教皇旨意", "speed": 1, "type": "场地", "description": "这张牌作为场地魔法卡使用。接下来双方的攻击次数都变为0，攻击方式改为弃置一张魔法卡攻击对方两次。魔法卡没有被无效化依旧可以使用。"},
    {"name": "无暇圣心", "speed": 1, "type": "普通", "description": "这张牌生效后，在接下来两个大回合之后（生效的这一个大回合也算在内），如果双方都没有造成过伤害，那么打出这张魔法卡的一方直接获胜。"},
    {"name": "盗亦有道", "speed": 3, "type": "普通", "description": "这张牌生效后，立即获取对方打出的上一张魔法卡。"},
    {"name": "克苏鲁之眼", "speed": 2, "type": "普通", "description": "选择自己的一艘船向对方暴露他的位置，然后对方也选择一艘船暴露他的位置。"},
    {"name": "Freezing！", "speed": 2, "type": "普通", "description": "在这回合自己没有对对方造成过任何伤害的场合可以发动，跳过对方这回合的所有阶段。这张牌只可以在自己先手的场合发动。"},
    {"name": "回光返照", "speed": 1, "type": "普通", "description": "这张牌只可以在自己先手的场合发动。立即清空自己的棋盘，并在其上重新摆放6艘船。跳过自己的战斗阶段。接下来如果对方在这一个大回合内对任何一艘自己的船造成了伤害，那么自己直接判负。在使用回光返照后，也会清空对方视角中自己的棋盘。"},
    {"name": "明智埋葬", "speed": 2, "type": "普通", "description": "选择一张不在弃牌堆中的魔法卡，将那张牌放到弃牌堆中，自己再摸一张牌。"},
    {"name": "火力全开", "speed": 1, "type": "普通", "description": "在这一个大回合内自己的攻击阶段时，自己的攻击次数翻倍。"},
    {"name": "加百列之光", "speed": 3, "type": "普通", "description": "无效化对方使用的上一张魔法卡和当前正在生效的一张场地魔法卡。这张牌不受'失灵'影响，但受'看破'影响。"},
    {"name": "仁王之盾", "speed": 1, "type": "普通", "description": "这张牌生效后，选择自己的至多3艘船并使他们进入状态'盾牌'。状态'盾牌'会帮住这艘船抵挡一次伤害。如果对方打到了状态'盾牌'的船，将会提醒对方。"},
    {"name": "钢筋铁骨", "speed": 3, "type": "普通", "description": "这张牌生效后，选择自己的一艘船主动死亡，接下来所有船进入状态'无敌'。状态'无敌'的船被打普通中后不会死亡，但是会显形给双方。"},
    {"name": "神机妙算", "speed": 3, "type": "普通", "description": "只可在对方的准备阶段以及自己的所有阶段使用。宣言一个数目x，如果对方的结束阶段结束之后自己的船数减少了x，那么那些原本会减少的船不会减少并在原位置或者对方没有打过的位置重新部署。"},
    {"name": "灵气复苏", "speed": 1, "type": "普通", "description": "调整双方的船数都变为x，x为不大于双方最大船数的任意非零整数。调整时只可以在自己原本有战舰的地方进行调整。"}
]

app = Flask(__name__,static_folder=os.path.join(os.path.dirname(__file__), 'static'),
            template_folder=os.path.join(os.path.dirname(__file__), 'templates'))
app.config['SECRET_KEY'] = 'battleship_secret_key'
socketio = SocketIO(app, cors_allowed_origins="*")

# 游戏房间数据结构
rooms = {}
# 匹配队列
match_queue = []

# 大厅匹配队列（简单 FIFO 队列）
lobby_queue = []

# 简单的 lobby 成员列表（用于显示）
lobby_members = set()
class GameRoom:
    def __init__(self, room_id):
        self.id = room_id
        self.players = {}
        self.state = 'waiting'  # waiting, placing_ships, rock_paper_scissors, attacking, game_over
        self.rps_choices = {}
        self.attack_order = []
        self.current_attacker = None
        self.attacks_remaining = 0
        self.round = 1
        self.winner = None
        # 魔法卡相关状态
        self.field_magics = {}  # 场地魔法 {player_id: card}
        self.magic_history = []  # 魔法卡使用历史
        self.game_effects = {}  # 游戏效果跟踪
        self.current_phase = 'preparation'  # 当前阶段
        self.last_magic = None  # 上一张使用的魔法卡
        self.pending_magic = None  # 待处理的魔法卡（等待对方是否使用失灵）
        self.magic_temp_data = {}  # 魔法卡临时数据
        # 连锁相关状态
        self.chain = []  # 连锁栈
        self.chain_waiting = False  # 是否正在等待玩家回应连锁
        self.chain_timer = None  # 连锁回应计时器

    def init_player_magic(self, player_id, magic_cards):
        """初始化玩家魔法卡牌堆"""
        # 复制并洗牌
        deck = magic_cards.copy()
        random.shuffle(deck)
        self.players[player_id]['magic_deck'] = deck
        self.players[player_id]['magic_hand'] = []  # 初始手牌为空
        self.players[player_id]['magic_discard'] = []
        # 移除初始抽卡逻辑
        # ... existing code ...

    def draw_card(self, player_id):
        """抽卡逻辑，返回抽到的卡牌"""
        if not self.players[player_id]['magic_deck']:
            # 牌堆为空，从弃牌堆重新洗牌
            # 过滤掉重复的非"失灵！"卡牌
            unique_discard = []
            seen = set()
            for card in self.players[player_id]['magic_discard']:
                if card['name'] == '失灵！' or card['name'] not in seen:
                    unique_discard.append(card)
                    if card['name'] != '失灵！':
                        seen.add(card['name'])
            self.players[player_id]['magic_deck'] = unique_discard
            random.shuffle(self.players[player_id]['magic_deck'])
            self.players[player_id]['magic_discard'] = []
        
        if self.players[player_id]['magic_deck']:
            card = self.players[player_id]['magic_deck'].pop(0)
            # 检查手牌中是否已有相同卡牌（除了"失灵！"）
            if card['name'] != '失灵！' and any(c['name'] == card['name'] and c['speed'] == card['speed'] for c in self.players[player_id]['magic_hand']):
                # 避免重复卡牌，放入弃牌堆并重新抽一张
                self.players[player_id]['magic_discard'].append(card)
                return self.draw_card(player_id)
            self.players[player_id]['magic_hand'].append(card)
            # 通知客户端手牌更新
            emit('hand_updated', {
                'hand': self.players[player_id]['magic_hand']
            }, room=player_id)
            return card  # 返回抽到的卡牌
        return None

@socketio.on('create_room')
def handle_create_room(data):
    room_id = str(uuid.uuid4())[:6]
    rooms[room_id] = GameRoom(room_id)
    return {'status': 'success', 'room_id': room_id}


@app.route('/')
def index():
    # 渲染主页面并传递登录信息
    return render_template('index.html', username=session.get('username'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if not username or not password:
            flash('用户名和密码不能为空')
            return redirect(url_for('register'))
        if db.get_user_by_username(username):
            flash('用户名已存在')
            return redirect(url_for('register'))
        pw_hash = generate_password_hash(password)
        uid = db.create_user(username, pw_hash)
        if uid:
            session['user_id'] = uid
            session['username'] = username
            flash('注册成功')
            return redirect(url_for('index'))
        else:
            flash('注册失败')
            return redirect(url_for('register'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = db.get_user_by_username(username)
        if not user or not check_password_hash(user['password_hash'], password):
            flash('用户名或密码错误')
            return redirect(url_for('login'))
        session['user_id'] = user['id']
        session['username'] = user['username']
        flash('登录成功')
        return redirect(url_for('index'))
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    flash('已退出登录')
    return redirect(url_for('index'))


@app.route('/leaderboard')
def leaderboard():
    rows = db.get_leaderboard(20)
    return render_template('leaderboard.html', rows=rows)

@app.route('/lobby')
def lobby():
    # 渲染大厅页面，传递用户名以显示已登录用户（可为 None 表示游客）
    return render_template('lobby.html', username=session.get('username'))

@socketio.on('join_room')
def handle_join_room(data):
    room_id = data['room_id']
    # 优先使用登录后的 user_id，否则使用 sid（游客模式）
    player_id = session.get('user_id', request.sid)
    player_name = session.get('username', data.get('player_name', '匿名玩家'))
    
    if room_id not in rooms:
        emit('error', {'message': '房间不存在'})
        return {'status': 'error', 'message': '房间不存在'}
    
    room = rooms[room_id]
    if len(room.players) >= 2:
        emit('error', {'message': '房间已满'})
        return {'status': 'error', 'message': '房间已满'}
    
    # 添加玩家到房间（key 为 user_id 或 sid）
    room.players[player_id] = {
        'name': player_name,
        'ships': [],
        'attacks': [],
        'remaining_ships': 0  # 初始化剩余战舰数量
    }
    
    # 添加玩家到Socket.IO房间
    join_room(room_id)
    # 返回玩家 id 供前端记录
    return {'status': 'success', 'player_id': player_id}


# 大厅：加入匹配队列
@socketio.on('join_lobby')
def handle_join_lobby():
    player_id = session.get('user_id', request.sid)
    # 防止重复加入
    if player_id not in lobby_queue:
        lobby_queue.append(player_id)
        lobby_members.add(player_id)
        # 将当前 socket 加入一个以 player_id 命名的个人房间，方便推送
        try:
            join_room(player_id)
        except Exception:
            pass
        emit('lobby_joined', room=request.sid)
        # 发送带可显示名字的成员列表
        players_display = []
        for pid in list(lobby_members):
            u = db.get_user_by_id(pid)
            players_display.append(u['username'] if u else str(pid)[:6])
        emit('lobby_update', {'players': players_display}, broadcast=True)
        # 尝试匹配
        try_match()
    else:
        # 已在队列中：仅推送更新以同步 UI
        players_display = []
        for pid in list(lobby_members):
            u = db.get_user_by_id(pid)
            players_display.append(u['username'] if u else str(pid)[:6])
        emit('lobby_update', {'players': players_display}, room=request.sid)


@socketio.on('leave_lobby')
def handle_leave_lobby():
    player_id = session.get('user_id', request.sid)
    # 安全地移除
    try:
        while player_id in lobby_queue:
            lobby_queue.remove(player_id)
    except ValueError:
        pass
    lobby_members.discard(player_id)
    try:
        leave_room(player_id)
    except Exception:
        pass
    emit('lobby_left', room=request.sid)
    players_display = []
    for pid in list(lobby_members):
        u = db.get_user_by_id(pid)
        players_display.append(u['username'] if u else str(pid)[:6])
    emit('lobby_update', {'players': players_display}, broadcast=True)


def try_match():
    # 简单 FIFO：两两配对
    while len(lobby_queue) >= 2:
        p1 = lobby_queue.pop(0)
        p2 = lobby_queue.pop(0)
        lobby_members.discard(p1)
        lobby_members.discard(p2)
        # 创建房间并通知
        new_room_id = str(uuid.uuid4())[:6]
        rooms[new_room_id] = GameRoom(new_room_id)
        # 向双方发送匹配成功（使用个人房间）
        emit('match_found', {'room_id': new_room_id}, room=p1)
        emit('match_found', {'room_id': new_room_id}, room=p2)

    # Broadcast lobby update
    players_display = []
    for pid in list(lobby_members):
        u = db.get_user_by_id(pid)
        players_display.append(u['username'] if u else str(pid)[:6])
    emit('lobby_update', {'players': players_display}, broadcast=True)

    return {'status': 'ok'}
@socketio.on('find_match')
def handle_find_match(data):
    """处理玩家匹配请求"""
    player_id = request.sid
    player_name = data.get('player_name', '匿名玩家')
    
    # 检查玩家是否已经在匹配队列中
    if player_id in match_queue:
        return {'status': 'error', 'message': '你已经在匹配队列中'}
    
    # 将玩家添加到匹配队列
    match_queue.append(player_id)
    
    # 保存玩家名称到session或字典中
    if not hasattr(app, 'player_names'):
        app.player_names = {}
    app.player_names[player_id] = player_name
    
    emit('match_queued', {'status': 'success', 'message': '已加入匹配队列'})
    
    # 尝试匹配
    check_match_queue()
    
    return {'status': 'success', 'message': '开始寻找匹配'}

@socketio.on('cancel_match')
def handle_cancel_match(data):
    """处理玩家取消匹配请求"""
    player_id = request.sid
    
    # 从匹配队列中移除玩家
    if player_id in match_queue:
        match_queue.remove(player_id)
    
    # 从玩家名称字典中移除
    if hasattr(app, 'player_names') and player_id in app.player_names:
        del app.player_names[player_id]
    
    emit('match_canceled', {'status': 'success', 'message': '已取消匹配'})
    
    return {'status': 'success', 'message': '已取消匹配'}

def check_match_queue():
    """检查匹配队列，尝试为等待的玩家创建房间"""
    while len(match_queue) >= 2:
        # 从队列中取出前两个玩家
        player1 = match_queue.pop(0)
        player2 = match_queue.pop(0)
        
        # 创建新房间
        room_id = str(uuid.uuid4())[:6]
        room = GameRoom(room_id)
        rooms[room_id] = room
        
        # 获取玩家名称
        player1_name = app.player_names.get(player1, '匿名玩家1')
        player2_name = app.player_names.get(player2, '匿名玩家2')
        
        # 添加玩家到房间
        room.players[player1] = {
            'name': player1_name,
            'ships': [],
            'attacks': [],
            'remaining_ships': 0
        }
        
        room.players[player2] = {
            'name': player2_name,
            'ships': [],
            'attacks': [],
            'remaining_ships': 0
        }
        
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
                'player_name': room.players[player_id]['name'],
                'opponent_name': room.players[opponent_id]['name']
            }, to=player_id)
        
        # 从玩家名称字典中移除
        if hasattr(app, 'player_names'):
            if player1 in app.player_names:
                del app.player_names[player1]
            if player2 in app.player_names:
                del app.player_names[player2]

@socketio.on('place_ships')
def handle_place_ships(data):
    room_id = data['room_id']
    player_id = data['player_id']
    ships = data['ships']
    
    if room_id not in rooms or player_id not in rooms[room_id].players:
        return {'status': 'error', 'message': '无效的房间或玩家'}
    
    room = rooms[room_id]
    room.players[player_id]['ships'] = ships

    # 新增：计算并设置剩余战舰数量（攻击次数）
    room.players[player_id]['remaining_ships'] = len(ships)

    # 检查是否所有玩家都已放置战舰
    all_placed = all(len(p['ships']) > 0 for p in room.players.values())
    if all_placed:
        room.state = 'rock_paper_scissors'
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
        loser = room.attack_order[1]   # 后手
        room.current_attacker = winner
        
        # 初始化攻击次数
        room.attacks_remaining = room.players[winner]['remaining_ships']
        
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

def determine_rps_winner(room):
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
    
    # 修复前逻辑：if win_conditions[c1] == c2:
    # 修复后逻辑：判断c2是否克制c1
    if win_conditions[c2] == c1:
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
        
        caster['magic_hand'].append(room.magic_temp_data['cards'][caster_choice])
        if opponent_choice < len(room.magic_temp_data['cards']) and opponent_choice != caster_choice:
            opponent['magic_hand'].append(room.magic_temp_data['cards'][opponent_choice])
        
        # 剩余卡牌加入弃牌堆
        for i, card in enumerate(room.magic_temp_data['cards']):
            if i != caster_choice and i != opponent_choice:
                caster['magic_discard'].append(card)
        
        room.magic_temp_data = {}
        return {'status': 'success', 'message': '卡牌选择完成'}

    elif temp_data_id == 'bury_choice':
        # 处理明智埋葬的选择
        card_index = target_data['card_index']
        caster = room.players[player_id]
        
        if 0 <= card_index < len(caster['magic_hand']):
            # 将选中的卡放入弃牌堆
            buried_card = caster['magic_hand'].pop(card_index)
            caster['magic_discard'].append(buried_card)
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
            if 0 <= idx < len(caster['ships']):
                caster['ships'][idx]['shield'] = True
        
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
    if any(a['x'] == target_x and a['y'] == target_y for a in room.players[attacker_id]['attacks']):
        return {'status': 'error', 'message': '你已经攻击过这个位置了'}
    
    # 找到对手
    defender_id = next(p for p in room.players if p != attacker_id)
    defender_ships = room.players[defender_id]['ships']
    
    # 检查是否击中
    hit = False
    ship_sunk = False
    for i, ship in enumerate(defender_ships):
        if {'x': target_x, 'y': target_y} in ship['positions']:
            # 检查目标船是否有特殊状态
            if ship.get('invincible'):
                # 无敌状态，只显形不造成伤害
                hit = True
                ship_sunk = False
            elif ship.get('shield'):
                # 盾牌状态，抵挡一次伤害
                hit = True
                ship_sunk = False
                del ship['shield']
            else:
                hit = True
                # 记录击中位置
                defender_ships[i]['hits'] = defender_ships[i].get('hits', []) + [{'x': target_x, 'y': target_y}]
                
                # 检查船是否被击沉
                if len(defender_ships[i]['hits']) == len(defender_ships[i]['positions']):
                    ship_sunk = True
                    defender_remaining_before = room.players[defender_id]['remaining_ships']
                    room.players[defender_id]['remaining_ships'] -= 1
                    defender_remaining_after = room.players[defender_id]['remaining_ships']
                    
                    # 记录船数变化（用于平等条约）
                    room.game_effects['last_ship_change'] = {
                        'player': defender_id,
                        'count': defender_remaining_before - defender_remaining_after
                    }
                    
                    # 检查饮血效果
                    if room.players[attacker_id].get('effect_flags', {}).get('vampire'):
                        room.draw_card(attacker_id)
                        emit('message', {'text': '饮血效果发动，抽一张卡'}, to=attacker_id)
                    
                    # 检查绝处逢生效果
                    if room.players[attacker_id].get('effect_flags', {}).get('last_stand'):
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
                        'player_remaining_ships': room.players[attacker_id]['remaining_ships'],
                        'opponent_remaining_ships': room.players[defender_id]['remaining_ships']
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
        'attacker_remaining_ships': room.players[attacker_id]['remaining_ships'],
        'defender_remaining_ships': room.players[defender_id]['remaining_ships']
    }
    
    emit('attack_result', attack_result, room=room_id)
    
    # 检查游戏是否结束
    if room.players[defender_id]['remaining_ships'] == 0:
        room.state = 'game_over'
        room.winner = attacker_id
        # 记录战绩（若为已登录用户）
        try:
            db.record_match(attacker_id, defender_id)
        except Exception:
            pass
        emit('game_over', {'winner': attacker_id}, room=room_id)
        return {'status': 'success', 'game_over': True}
    
    # 检查是否需要切换攻击者
    if room.attacks_remaining == 0:
        current_index = room.attack_order.index(attacker_id)
        next_index = (current_index + 1) % len(room.attack_order)
        
        # 如果所有玩家都已攻击过，开始新的大回合
        if next_index == 0:
            room.round += 1
            room.state = 'rock_paper_scissors'
            room.rps_choices = {}
            emit('game_state', {'state': 'rock_paper_scissors', 'round': room.round}, room=room_id)
            return {'status': 'success', 'new_round': True}
        
        # 切换到下一个攻击者
        room.current_attacker = room.attack_order[next_index]
        room.current_phase = 'preparation'  # 设置为准备阶段
        room.attacks_remaining = room.players[room.current_attacker]['remaining_ships']
        # 发送阶段更新事件
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
    
    # 检查是否是当前攻击者
    if room.current_attacker != player_id:
        return {'status': 'error', 'message': '不是你的回合'}
    
    # 检查是否还有攻击次数
    if room.attacks_remaining > 0:
        return {'status': 'error', 'message': '还有剩余攻击次数'}
    
    # 进入结束阶段
    room.current_phase = 'end'
    emit('phase_updated', {'phase': 'end'}, room=room_id)
    
    # 延迟切换到对方回合，给结束阶段一些时间
    socketio.start_background_task(target=switch_turn_after_end_phase, room=room, opponent_id=next(p for p in room.players if p != player_id))
    
    return {'status': 'success', 'message': '已进入结束阶段'}

def switch_turn_after_end_phase(room, opponent_id):
    # 模拟结束阶段处理时间
    time.sleep(2)
    
    # 切换到对方回合
    room.current_attacker = opponent_id
    room.attacks_remaining = len(room.players[opponent_id]['ships'])  # 根据战舰数量设置攻击次数
    room.current_phase = 'preparation'
    
    # 抽卡阶段
    room.draw_card(opponent_id)
    
    # 广播回合变化
    socketio.emit('turn_change', {
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
        
        # 切换到下一个攻击者的准备阶段
        room.current_attacker = room.attack_order[next_index]
        room.current_phase = 'preparation'
        room.attacks_remaining = room.players[room.current_attacker]['remaining_ships']
        
        # 重置所有临时效果标志
        for p_id in room.players:
            if 'effect_flags' in room.players[p_id]:
                # 保留场地魔法等永久效果，清除临时效果
                permanent_flags = ['holy_heart', 'reinforcement_check']  # 永久效果白名单
                room.players[p_id]['effect_flags'] = {k: v for k, v in room.players[p_id]['effect_flags'].items() if k in permanent_flags}
        
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
    card = data['card']
    targets = data.get('targets', [])

    if room_id not in rooms or player_id not in rooms[room_id].players:
        return {'status': 'error', 'message': '无效的房间或玩家'}

    room = rooms[room_id]
    player = room.players[player_id]
    opponent_id = next(p for p in room.players if p != player_id)

    # 检查卡牌是否在玩家手牌中
    if not any(c['name'] == card['name'] and c['speed'] == card['speed'] for c in player['magic_hand']):
        return {'status': 'error', 'message': '你没有这张魔法卡'}

    # 检查是否可以在当前阶段使用
    if not can_play_magic_card(room, player_id, card):
        return {'status': 'error', 'message': f'当前阶段{room.current_phase}无法使用速阶{card["speed"]}的魔法卡'}

    # 从手牌中移除并添加到弃牌堆
    player['magic_hand'] = [c for c in player['magic_hand'] if not (c['name'] == card['name'] and c['speed'] == card['speed'])]
    player['magic_discard'].append(card)

    # 记录最后使用的魔法卡
    room.last_magic = card

    # 处理场地魔法 - 全场只能有一张场地魔法卡生效
    if card['type'] == '场地':
        # 移除所有玩家的场地魔法卡（全场只能有一张）
        for existing_player_id in list(room.field_magics.keys()):
            old_card = room.field_magics[existing_player_id]
            # 将旧的场地魔法卡加入弃牌堆
            room.players[existing_player_id]['magic_discard'].append(old_card)
            # 广播场地魔法移除
            emit('field_magic_updated', {
                'player_id': existing_player_id,
                'card': None
            }, room=room_id)
            # 从场地魔法字典中移除
            del room.field_magics[existing_player_id]
        
        # 设置新的场地魔法卡
        room.field_magics[player_id] = card
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
    
    # 检查对方是否可以连锁（速阶高于当前连锁卡）
    can_chain = False
    if len(room.chain) > 1:
        # 只有在有其他卡的情况下才能连锁
        last_chain_card_speed = room.chain[-2]['card']['speed']
        if card['speed'] > last_chain_card_speed:
            can_chain = True
    
    if can_chain:
        # 通知对方可以连锁
        room.chain_waiting = True
        emit('chain_request', {
            'card': card
        }, to=opponent_id)
    else:
        # 直接结算连锁
        resolve_chain(room)
    
    return {'status': 'success', 'message': f'魔法卡{card["name"]}已加入连锁'}

def can_play_magic_card(room, player_id, card):
    # 确保speed是数字类型
    speed = int(card['speed'])
    
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
        # 玩家选择连锁，处理新的魔法卡
        player = room.players[player_id]
        opponent_id = next(p for p in room.players if p != player_id)
        
        # 检查卡牌是否在玩家手牌中
        if not any(c['name'] == card['name'] and c['speed'] == card['speed'] for c in player['magic_hand']):
            return {'status': 'error', 'message': '你没有这张魔法卡'}
        
        # 检查速阶是否高于上一张连锁卡
        last_chain_card = room.chain[-1]['card']
        if card['speed'] <= last_chain_card['speed']:
            return {'status': 'error', 'message': f'连锁卡速阶必须高于上一张卡的速阶（{last_chain_card["speed"]}）'}
        
        # 从手牌中移除并添加到弃牌堆
        player['magic_hand'] = [c for c in player['magic_hand'] if not (c['name'] == card['name'] and c['speed'] == card['speed'])]
        player['magic_discard'].append(card)
        
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
        
        # 检查对方是否可以继续连锁
        can_chain = True
        emit('chain_request', {
            'card': card
        }, to=opponent_id)
        
        return {'status': 'success', 'message': f'魔法卡{card["name"]}已加入连锁'}
    else:
        # 玩家选择不连锁，结算当前连锁
        results = resolve_chain(room)
        return {'status': 'success', 'message': '连锁已结算', 'results': results}

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
    caster_id = pending['caster_id']
    card = pending['card']
    target_data = pending['target_data']

    # 清除待处理魔法
    room.pending_magic = None

    if use_counter:
        # 对方使用了"失灵！"
        # 从对方手牌中移除"失灵！"
        opponent = room.players[player_id]
        for i, c in enumerate(opponent['magic_hand']):
            if c['name'] == '失灵！':
                opponent['magic_hand'].pop(i)
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
        # 广播魔法效果
        emit('magic_applied', result, room=room_id)
        return {'status': 'success', 'result': result}

@socketio.on('remove_field_magic')
def handle_remove_field_magic(data):
    room_id = data['room_id']
    player_id = data['player_id']

    if room_id in rooms and player_id in rooms[room_id].players:
        room = rooms[room_id]
        if player_id in room.field_magics:
            # 将场地魔法加入弃牌堆
            room.players[player_id]['magic_discard'].append(room.field_magics[player_id])
            # 移除场地魔法
            del room.field_magics[player_id]
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
    pending = room.magic_temp_data.get('pending_reinforcement') if room.get('magic_temp_data') else None
    if not pending or pending.get('caster') != player_id:
        return {'status': 'error', 'message': '没有等待确认的增援'}

    # 验证位置合法且没有被对方攻击过
    opponent_id = next(p for p in room.players if p != player_id)
    opponent_attacks = [ (a['x'], a['y']) for a in room.players[opponent_id]['attacks'] ]
    x, y = position.get('x'), position.get('y')
    if (x, y) in opponent_attacks:
        return {'status': 'error', 'message': '该位置已被对方攻击，无法放置'}

    # 验证没有和已有战舰冲突
    for ship in caster['ships']:
        for pos in ship['positions']:
            if pos['x'] == x and pos['y'] == y:
                return {'status': 'error', 'message': '该位置已被己方战舰占用'}

    # 放置战舰
    new_ship = {
        'id': f'magic_{uuid.uuid4()[:4]}',
        'positions': [{'x': x, 'y': y}],
        'hits': []
    }
    caster['ships'].append(new_ship)
    caster['remaining_ships'] = caster.get('remaining_ships', 0) + 1

    # 清除临时数据
    room.magic_temp_data.pop('pending_reinforcement', None)

    # 广播更新
    emit('ships_updated', {
        'player_remaining_ships': caster['remaining_ships'],
        'opponent_remaining_ships': room.players[opponent_id]['remaining_ships']
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
    positions = room.players[player_id].get('revealed_positions', [])
    # 只发送给请求者
    emit('revealed_positions', {'positions': positions}, to=player_id)
    return {'status': 'success'}

# 添加辅助函数


def find_safe_position(room, player_id):
    """寻找未被攻击过的安全位置"""
    opponent_id = next(p for p in room.players if p != player_id)
    opponent_attacks = [ (a['x'], a['y']) for a in room.players[opponent_id]['attacks'] ]
    
    for y in range(6):
        for x in range(6):
            if (x, y) not in opponent_attacks:
                return {'x': x, 'y': y}
    return None


def apply_magic_effect(room, caster_id, card, target_data):
    result = {'card': card, 'caster': caster_id, 'success': True, 'message': ''}
    opponent_id = next(p for p in room.players if p != caster_id)
    caster = room.players[caster_id]
    opponent = room.players[opponent_id]
    print(f"Applying magic effect: {card['name']} target {target_data}")

    try:
        # ==== 速阶1 魔法卡 ====
        if card['name'] == '余音绕梁':
            # 标记接下来两个攻击阶段造成的伤害将强制击杀
            room.players[caster_id]['effect_flags'] = room.players[caster_id].get('effect_flags', {})
            room.players[caster_id]['effect_flags']['forced_kill'] = 2  # 持续2个攻击阶段
            result['message'] = '接下来两个攻击阶段将造成强制击杀'

        elif card['name'] == '桃园结义':
            # 从牌堆抽取n张牌(n为自己的战舰数)，自己选1张，再给对方选1张
            n = len(caster['ships'])
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

        elif card['name'] == '无中生有':
            # 抽两张牌，本回合双方无法获得魔法卡
            card1 = room.draw_card(caster_id)
            card2 = room.draw_card(caster_id)
            # 设置禁止抽卡标记
            room.players[caster_id]['effect_flags'] = room.players[caster_id].get('effect_flags', {})
            room.players[opponent_id]['effect_flags'] = room.players[opponent_id].get('effect_flags', {})
            room.players[caster_id]['effect_flags']['no_draw'] = True
            room.players[opponent_id]['effect_flags']['no_draw'] = True
            result['message'] = '抽了2张牌，本回合双方无法获得魔法卡'

        elif card['name'] == '极限增援':
            # 两个大回合后，船少的一方获胜
            room.game_effects = room.get('game_effects', {})
            room.game_effects['reinforcement_check'] = {
                'turn': room.round + 2,
                'caster': caster_id
            }
            result['message'] = '两个大回合后船少的一方获胜'

        elif card['name'] == '无暇圣心':
            # 两个大回合后如果双方都没造成伤害，施法者获胜
            room.game_effects = room.get('game_effects', {})
            room.game_effects['holy_heart'] = {
                'turn': room.round + 2,
                'caster': caster_id,
                'damage_check': True
            }
            result['message'] = '两个大回合后若双方都未造成伤害则你获胜'

        elif card['name'] == '火力全开':
            # 本回合攻击次数翻倍
            room.players[caster_id]['effect_flags'] = room.players[caster_id].get('effect_flags', {})
            room.players[caster_id]['effect_flags']['double_attacks'] = True
            result['message'] = '本回合攻击次数翻倍'

        elif card['name'] == '灵气复苏':
            # 调整双方船数为x(x为不大于双方最大船数的任意非零整数)
            max_ships = max(len(caster['ships']), len(opponent['ships']))
            target_ships = random.randint(1, max_ships) if max_ships > 0 else 1
            
            # 调整施法者船数
            while len(caster['ships']) > target_ships:
                caster['ships'].pop()
                caster['remaining_ships'] -= 1
            while len(caster['ships']) < target_ships:
                pos = find_safe_position(room, caster_id)
                if pos:
                    caster['ships'].append({'id': f'magic_{uuid.uuid4()[:4]}', 'positions': [pos], 'hits': []})
                    caster['remaining_ships'] += 1
                else:
                    break
            
            # 调整对手船数
            while len(opponent['ships']) > target_ships:
                opponent['ships'].pop()
                opponent['remaining_ships'] -= 1
            while len(opponent['ships']) < target_ships:
                pos = find_safe_position(room, opponent_id)
                if pos:
                    opponent['ships'].append({'id': f'magic_{uuid.uuid4()[:4]}', 'positions': [pos], 'hits': []})
                    opponent['remaining_ships'] += 1
                else:
                    break
            
            result['message'] = f'双方船数调整为{target_ships}'

        elif card['name'] == '军备竞赛':
            # 将对方的战舰数变得和自己一样
            caster_ship_count = len(caster['ships'])
            opponent_ship_count = len(opponent['ships'])
            
            if opponent_ship_count > caster_ship_count:
                # 对方多于自己，对方选择牺牲多出去的船
                extra_ships = opponent_ship_count - caster_ship_count
                # 直接移除多余的船（简化实现，实际应让对方选择）
                while len(opponent['ships']) > caster_ship_count:
                    opponent['ships'].pop()
                    opponent['remaining_ships'] -= 1
                result['message'] = f'对方船数过多，已移除{extra_ships}艘船'
            elif opponent_ship_count < caster_ship_count:
                # 对方少于自己，对方在未被打过的格子中放置少了的船
                missing_ships = caster_ship_count - opponent_ship_count
                added_ships = 0
                while len(opponent['ships']) < caster_ship_count:
                    pos = find_safe_position(room, opponent_id)
                    if pos:
                        opponent['ships'].append({'id': f'magic_{uuid.uuid4()[:4]}', 'positions': [pos], 'hits': []})
                        opponent['remaining_ships'] += 1
                        added_ships += 1
                    else:
                        break
                result['message'] = f'对方船数不足，已添加{added_ships}艘船'
            else:
                result['message'] = '双方船数相同，无需调整'

        # ==== 速阶2 魔法卡 ====
        elif card['name'] == '溅射':
            # 对击中格子的上下左右四格造成伤害
            if not room.last_attack or room.last_attack['attacker'] != caster_id:
                result['success'] = False
                result['message'] = '必须在击中对方后使用'
                return result
            
            x, y = room.last_attack['x'], room.last_attack['y']
            splash_positions = [
                {'x': x, 'y': y-1},  # 上
                {'x': x, 'y': y+1},  # 下
                {'x': x-1, 'y': y},  # 左
                {'x': x+1, 'y': y}   # 右
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
                for i, ship in enumerate(opponent['ships']):
                    if pos in ship['positions'] and pos not in ship.get('hits', []):
                        # 溅射伤害不受无敌影响，但受护盾影响（护盾抵挡一次）
                        if ship.get('shield'):
                            hit = True
                            del ship['shield']
                            ship_sunk = False
                        elif ship.get('invincible'):
                            # 无敌：显形但不伤害（依然记录为命中）
                            hit = True
                            ship_sunk = False
                        else:
                            hit = True
                            ship.setdefault('hits', []).append(pos)
                            if len(ship['hits']) == len(ship['positions']):
                                ship_sunk = True
                                opponent['remaining_ships'] -= 1
                                ships_changed = True
                        hit_count += 1
                        break
                
                # 记录攻击（包括未命中）
                caster['attacks'].append({
                    'x': pos['x'],
                    'y': pos['y'],
                    'hit': hit,
                    'ship_sunk': ship_sunk,
                    'is_splash': True
                })

                # 发送单点攻击结果，保持与普通攻击一致的 UI 更新
                attack_result = {
                    'attacker': caster_id,
                    'x': pos['x'],
                    'y': pos['y'],
                    'hit': hit,
                    'ship_sunk': ship_sunk,
                    'remaining_attacks': room.attacks_remaining,
                    'attacker_remaining_ships': room.players[caster_id]['remaining_ships'],
                    'defender_remaining_ships': opponent['remaining_ships']
                }
                emit('attack_result', attack_result, room=room.id)

                affected_positions.append({
                    'x': pos['x'],
                    'y': pos['y'],
                    'hit': hit,
                    'ship_sunk': ship_sunk
                })
            
            # 若有船只数量变化，广播更新
            if ships_changed:
                emit('ships_updated', {
                    'player_remaining_ships': room.players[caster_id]['remaining_ships'],
                    'opponent_remaining_ships': opponent['remaining_ships']
                }, room=room.id)

            result['message'] = f'溅射攻击命中{hit_count}个目标'
            result['affected_positions'] = affected_positions
            result['caster_id'] = caster_id

        elif card['name'] == '雷达子弹':
            # 显示击中位置周围八格的战舰
            if not room.last_attack or room.last_attack['attacker'] != caster_id or not room.last_attack['hit']:
                result['success'] = False
                result['message'] = '必须在击中对方战舰后使用'
                return result
            
            x, y = room.last_attack['x'], room.last_attack['y']
            # 记录需要显示的位置
            room.players[caster_id]['revealed_positions'] = room.players[caster_id].get('revealed_positions', [])
            new_positions = []
            for dy in [-1, 0, 1]:
                for dx in [-1, 0, 1]:
                    if dx == 0 and dy == 0: continue
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < 6 and 0 <= ny < 6:
                        pos = {'x': nx, 'y': ny}
                        room.players[caster_id]['revealed_positions'].append(pos)
                        new_positions.append(pos)
            
            # 立即将被揭示的位置发送给触发方
            emit('revealed_positions', {'positions': new_positions}, to=caster_id)
            result['message'] = '已扫描周围八格战舰位置'

        elif card['name'] == '越战越勇':
            # 每造成一次伤害，攻击次数加2
            if not room.last_attack or room.last_attack['attacker'] != caster_id or not room.last_attack['hit']:
                result['success'] = False
                result['message'] = '必须在击中对方战舰后使用'
                return result
            
            # 增加攻击次数
            room.attacks_remaining += 2
            result['message'] = '攻击次数增加2次'

        elif card['name'] == '神威！':
            # 选定3*3区域，暂时除外区域内战舰
            if 'target_area' not in target_data:
                result['success'] = False
                result['message'] = '需要选择目标区域'
                return result
            
            area = target_data['target_area']
            excluded_ships = []
            
            # 收集区域内的战舰
            for i in range(len(opponent['ships'])-1, -1, -1):
                ship = opponent['ships'][i]
                in_area = any(
                    area['x1'] <= pos['x'] <= area['x2'] and 
                    area['y1'] <= pos['y'] <= area['y2']
                    for pos in ship['positions']
                )
                
                if in_area:
                    excluded_ships.append(ship)
                    del opponent['ships'][i]
                    opponent['remaining_ships'] -= 1
            
            # 如果只有一艘船被除外，直接击沉
            if len(excluded_ships) == 1:
                result['message'] = '目标区域内1艘战舰被击沉'
            else:
                # 记录暂时除外的战舰，下一回合回归
                room.game_effects = room.get('game_effects', {})
                room.game_effects['excluded_ships'] = {
                    'ships': excluded_ships,
                    'player': opponent_id,
                    'return_turn': room.round + 1
                }
                result['message'] = f'目标区域内{len(excluded_ships)}艘战舰被暂时除外'

        elif card['name'] == '冻结':
            # 冻结3*3区域内的船，使其无法攻击
            if 'target_area' not in target_data:
                result['success'] = False
                result['message'] = '需要选择目标区域'
                return result
            
            area = target_data['target_area']
            frozen_count = 0
            
            # 标记区域内的战舰
            for ship in opponent['ships']:
                in_area = any(
                    area['x1'] <= pos['x'] <= area['x2'] and 
                    area['y1'] <= pos['y'] <= area['y2']
                    for pos in ship['positions']
                )
                
                if in_area and 'frozen' not in ship:
                    ship['frozen'] = room.round + 1  # 冻结到下一回合
                    frozen_count += 1
            
            result['message'] = f'冻结了{frozen_count}艘战舰'

        elif card['name'] == '轰炸':
            # 选定一行或一列进行轰炸
            if 'target_line' not in target_data:
                result['success'] = False
                result['message'] = '需要选择目标行或列'
                return result
            
            line = target_data['target_line']
            # 检查是行还是列
            if line['type'] == 'row':
                positions = [{'x': x, 'y': line['index']} for x in range(6)]
            else:
                positions = [{'x': line['index'], 'y': y} for y in range(6)]
            
            # 找出所有与该行/列相交的船只，整艘摧毁
            to_remove = [ship for ship in opponent['ships'] if any(pos in ship['positions'] for pos in positions)]
            sunk_count = 0
            ships_changed = False
            removed_positions = set()

            affected_positions = []
            # 移除这些船并为其每个格子生成命中事件（完整击沉）
            for ship in to_remove:
                if ship in opponent['ships']:
                    opponent['ships'].remove(ship)
                    opponent['remaining_ships'] -= 1
                    ships_changed = True
                    sunk_count += 1
                    for ship_pos in ship['positions']:
                        removed_positions.add((ship_pos['x'], ship_pos['y']))
                        caster['attacks'].append({
                            'x': ship_pos['x'],
                            'y': ship_pos['y'],
                            'hit': True,
                            'ship_sunk': True,
                            'is_bomb': True
                        })
                        attack_result = {
                            'attacker': caster_id,
                            'x': ship_pos['x'],
                            'y': ship_pos['y'],
                            'hit': True,
                            'ship_sunk': True,
                            'remaining_attacks': room.attacks_remaining,
                            'attacker_remaining_ships': room.players[caster_id]['remaining_ships'],
                            'defender_remaining_ships': opponent['remaining_ships']
                        }
                        emit('attack_result', attack_result, room=room.id)
                        affected_positions.append({
                            'x': ship_pos['x'],
                            'y': ship_pos['y'],
                            'hit': True,
                            'ship_sunk': True
                        })

            # 对于该行/列中未命中的格子也发出未命中事件，以保持 UI 一致性
            for pos in positions:
                if (pos['x'], pos['y']) not in removed_positions:
                    caster['attacks'].append({
                        'x': pos['x'],
                        'y': pos['y'],
                        'hit': False,
                        'ship_sunk': False,
                        'is_bomb': True
                    })
                    attack_result = {
                        'attacker': caster_id,
                        'x': pos['x'],
                        'y': pos['y'],
                        'hit': False,
                        'ship_sunk': False,
                        'remaining_attacks': room.attacks_remaining,
                        'attacker_remaining_ships': room.players[caster_id]['remaining_ships'],
                        'defender_remaining_ships': opponent['remaining_ships']
                    }
                    emit('attack_result', attack_result, room=room.id)
                    affected_positions.append({
                        'x': pos['x'],
                        'y': pos['y'],
                        'hit': False,
                        'ship_sunk': False
                    })

            # 若有船只数量变化，广播更新
            if ships_changed:
                emit('ships_updated', {
                    'player_remaining_ships': room.players[caster_id]['remaining_ships'],
                    'opponent_remaining_ships': opponent['remaining_ships']
                }, room=room.id)

            result['message'] = f'轰炸成功击沉{sunk_count}艘战舰'
            result['affected_positions'] = affected_positions
            result['caster_id'] = caster_id

            result['message'] = f'轰炸成功击沉{sunk_count}艘战舰'

        elif card['name'] == '探测雷达':
            # 冻结3*3区域内的船，使其无法攻击
            if 'target_area' not in target_data:
                result['success'] = False
                result['message'] = '需要选择目标区域'
                return result
            
            area = target_data['target_area']
            frozen_count = 0
            
            # 标记区域内的战舰
            for ship in opponent['ships']:
                in_area = any(
                    area['x1'] <= pos['x'] <= area['x2'] and 
                    area['y1'] <= pos['y'] <= area['y2']
                    for pos in ship['positions']
                )
                
                if in_area and 'frozen' not in ship:
                    ship['frozen'] = room.round + 1  # 冻结到下一回合
                    frozen_count += 1
            
            result['message'] = f'冻结了{frozen_count}艘战舰'

        elif card['name'] == '轰炸':
            # 选定一行或一列进行轰炸
            if 'target_line' not in target_data:
                result['success'] = False
                result['message'] = '需要选择目标行或列'
                return result
            
            line = target_data['target_line']
            # 检查是行还是列
            if line['type'] == 'row':
                positions = [{'x': x, 'y': line['index']} for x in range(6)]
            else:
                positions = [{'x': line['index'], 'y': y} for y in range(6)]
            
            # 找出所有与该行/列相交的船只，整艘摧毁
            to_remove = [ship for ship in opponent['ships'] if any(pos in ship['positions'] for pos in positions)]
            sunk_count = 0
            ships_changed = False
            removed_positions = set()

            # 移除受影响的船只，并为其所有格子生成命中事件
            for ship in to_remove:
                if ship in opponent['ships']:
                    opponent['ships'].remove(ship)
                    opponent['remaining_ships'] -= 1
                    ships_changed = True
                    sunk_count += 1
                    for ship_pos in ship['positions']:
                        removed_positions.add((ship_pos['x'], ship_pos['y']))
                        caster['attacks'].append({
                            'x': ship_pos['x'],
                            'y': ship_pos['y'],
                            'hit': True,
                            'ship_sunk': True,
                            'is_bomb': True
                        })
                        attack_result = {
                            'attacker': caster_id,
                            'x': ship_pos['x'],
                            'y': ship_pos['y'],
                            'hit': True,
                            'ship_sunk': True,
                            'remaining_attacks': room.attacks_remaining,
                            'attacker_remaining_ships': room.players[caster_id]['remaining_ships'],
                            'defender_remaining_ships': opponent['remaining_ships']
                        }
                        emit('attack_result', attack_result, room=room.id)

            # 对于该行/列中未命中的格子也发出未命中事件，以保持 UI 一致性
            for pos in positions:
                if (pos['x'], pos['y']) not in removed_positions:
                    caster['attacks'].append({
                        'x': pos['x'],
                        'y': pos['y'],
                        'hit': False,
                        'ship_sunk': False,
                        'is_bomb': True
                    })
                    attack_result = {
                        'attacker': caster_id,
                        'x': pos['x'],
                        'y': pos['y'],
                        'hit': False,
                        'ship_sunk': False,
                        'remaining_attacks': room.attacks_remaining,
                        'attacker_remaining_ships': room.players[caster_id]['remaining_ships'],
                        'defender_remaining_ships': opponent['remaining_ships']
                    }
                    emit('attack_result', attack_result, room=room.id)

            # 若有船只数量变化，广播更新
            if ships_changed:
                emit('ships_updated', {
                    'player_remaining_ships': room.players[caster_id]['remaining_ships'],
                    'opponent_remaining_ships': opponent['remaining_ships']
                }, room=room.id)

            result['message'] = f'轰炸成功击沉{sunk_count}艘战舰'

        elif card['name'] == '硫磺火焰':
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
            to_remove = [ship for ship in opponent['ships'] if any(pos in ship['positions'] for pos in positions)]
            sunk_count = 0
            ships_changed = False
            removed_positions = set()

            for ship in to_remove:
                if ship in opponent['ships']:
                    affected_positions = []
                    opponent['ships'].remove(ship)
                    opponent['remaining_ships'] -= 1
                    ships_changed = True
                    sunk_count += 1
                    for ship_pos in ship['positions']:
                        removed_positions.add((ship_pos['x'], ship_pos['y']))
                        caster['attacks'].append({
                            'x': ship_pos['x'],
                            'y': ship_pos['y'],
                            'hit': True,
                            'ship_sunk': True,
                            'is_sulfur': True
                        })
                        attack_result = {
                            'attacker': caster_id,
                            'x': ship_pos['x'],
                            'y': ship_pos['y'],
                            'hit': True,
                            'ship_sunk': True,
                            'remaining_attacks': room.attacks_remaining,
                            'attacker_remaining_ships': room.players[caster_id]['remaining_ships'],
                            'defender_remaining_ships': opponent['remaining_ships']
                        }
                        emit('attack_result', attack_result, room=room.id)
                        affected_positions.append({
                            'x': ship_pos['x'],
                            'y': ship_pos['y'],
                            'hit': True,
                            'ship_sunk': True
                        })

            # 对于选定格子中未命中的格子，发送未命中事件
            for pos in positions:
                if (pos['x'], pos['y']) not in removed_positions:
                    caster['attacks'].append({
                        'x': pos['x'],
                        'y': pos['y'],
                        'hit': False,
                        'ship_sunk': False,
                        'is_sulfur': True
                    })
                    attack_result = {
                        'attacker': caster_id,
                        'x': pos['x'],
                        'y': pos['y'],
                        'hit': False,
                        'ship_sunk': False,
                        'remaining_attacks': room.attacks_remaining,
                        'attacker_remaining_ships': room.players[caster_id]['remaining_ships'],
                        'defender_remaining_ships': opponent['remaining_ships']
                    }
                    emit('attack_result', attack_result, room=room.id)
                    affected_positions.append({
                        'x': pos['x'],
                        'y': pos['y'],
                        'hit': False,
                        'ship_sunk': False
                    })

            # 广播被摧毁舰只更新
            if ships_changed:
                emit('ships_updated', {
                    'player_remaining_ships': room.players[caster_id]['remaining_ships'],
                    'opponent_remaining_ships': opponent['remaining_ships']
                }, room=room.id)

            result['message'] = f'硫磺火焰成功击杀{sunk_count}艘战舰'
            result['affected_positions'] = affected_positions
            result['caster_id'] = caster_id

        elif card['name'] == '探测雷达':
            # 显示2*2区域内的战舰
            if 'target_area' not in target_data:
                result['success'] = False
                result['message'] = '需要选择目标区域'
                return result
            
            area = target_data['target_area']
            positions = []
            room.players[caster_id]['revealed_positions'] = room.players[caster_id].get('revealed_positions', [])
            
            # 添加需要显示的位置
            for y in range(area['y1'], area['y2']+1):
                for x in range(area['x1'], area['x2']+1):
                    pos = {'x': x, 'y': y}
                    room.players[caster_id]['revealed_positions'].append(pos)
                    positions.append(pos)

            # 立即发送给触发者
            emit('revealed_positions', {'positions': positions}, to=caster_id)
            result['message'] = '已探测目标区域战舰位置'

        elif card['name'] == '饮血':
            # 每击杀一艘船，抽一张牌
            room.players[caster_id]['effect_flags'] = room.players[caster_id].get('effect_flags', {})
            room.players[caster_id]['effect_flags']['vampire'] = True
            result['message'] = '接下来自己的攻击，每击杀一艘船，自己摸一张牌。'

        elif card['name'] == '克苏鲁之眼':
            # 双方各暴露一艘船的位置
            if not caster['ships'] or not opponent['ships']:
                result['success'] = False
                result['message'] = '双方都必须有战舰才能使用'
                return result
            
            # 随机选择一艘船暴露
            caster_ship = random.choice(caster['ships'])
            opponent_ship = random.choice(opponent['ships'])
            
            # 记录暴露的位置
            caster_positions = caster_ship['positions']
            opponent_positions = opponent_ship['positions']

            room.players[caster_id]['revealed_positions'] = room.players[caster_id].get('revealed_positions', [])
            room.players[opponent_id]['revealed_positions'] = room.players[opponent_id].get('revealed_positions', [])
            
            room.players[caster_id]['revealed_positions'].extend(opponent_positions)
            room.players[opponent_id]['revealed_positions'].extend(caster_positions)

            # 立即发送给双方对应玩家
            emit('revealed_positions', {'positions': opponent_positions}, to=caster_id)
            emit('revealed_positions', {'positions': caster_positions}, to=opponent_id)
            
            result['message'] = '双方各暴露一艘战舰位置'

        elif card['name'] == 'Freezing！':
            # 本回合未造成伤害时可发动，跳过对方回合
            if room.current_attacker != caster_id:
                result['success'] = False
                result['message'] = '必须在自己回合发动'
                return result
            
            # 检查是否造成过伤害
            has_damaged = any(a['hit'] for a in caster['attacks'] if a.get('round') == room.round)
            if has_damaged:
                result['success'] = False
                result['message'] = '本回合已造成伤害，无法发动'
                return result
            
            # 跳过对方回合
            room.skip_next_turn = opponent_id
            result['message'] = '成功跳过对方回合'

        elif card['name'] == '五险一金':
            # 本回合未造成伤害则增加攻击次数
            if caster.get('damage_dealt_this_turn', 0) == 0:
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

        elif card['name'] == '明智埋葬':
            # 选择一张不在弃牌堆中的魔法卡，将其放入弃牌堆并抽一张牌
            if not caster['magic_hand']:
                result['success'] = False
                result['message'] = '手牌为空，无法发动'
                return result
            
            # 记录需要选择的牌
            room.magic_temp_data = {
                'type': 'bury_choice',
                'caster': caster_id,
                'cards': caster['magic_hand']
            }
            result['message'] = '请选择要埋葬的卡牌'
            result['temp_data_id'] = 'bury_choice'

        elif card['name'] == '仁王之盾':
            # 选择至多3艘船进入盾牌状态
            if len(caster['ships']) == 0:
                result['success'] = False
                result['message'] = '没有战舰可保护'
                return result
            
            # 记录需要选择的船
            room.magic_temp_data = {
                'type': 'shield_choice',
                'caster': caster_id,
                'ships': caster['ships']
            }
            result['message'] = '请选择要保护的战舰'
            result['temp_data_id'] = 'shield_choice'

        # ==== 速阶3 魔法卡 ====
        elif card['name'] == '八方来财':
            # 战舰数目主动变化时抽一张牌
            room.players[caster_id]['effect_flags'] = room.players[caster_id].get('effect_flags', {})
            room.players[caster_id]['effect_flags']['treasure_hunter'] = True
            result['message'] = '战舰数目变化时抽一张牌'

        elif card['name'] == '平等条约':
            # 船数改变时无效化导致改变的攻击/魔法
            if 'last_ship_change' not in room.game_effects:
                result['success'] = False
                result['message'] = '没有可无效化的船数改变效果'
                return result
            
            # 无效化最后一次船数改变
            last_change = room.game_effects.pop('last_ship_change')
            # 恢复船数
            if last_change['player'] == caster_id:
                caster['remaining_ships'] += last_change['count']
            else:
                opponent['remaining_ships'] += last_change['count']
            
            result['message'] = '成功无效化船数改变效果'

        elif card['name'] == '百亿补贴':
            # 船被击败时攻击次数加3
            room.players[caster_id]['effect_flags'] = room.players[caster_id].get('effect_flags', {})
            room.players[caster_id]['effect_flags']['subsidy'] = True
            result['message'] = '船被击败时攻击次数加3'

        elif card['name'] == '神之宣告':
            # 牺牲两艘船，选择一个效果
            if len(caster['ships']) < 2:
                result['success'] = False
                result['message'] = '需要至少2艘战舰才能发动'
                return result
            
            # 牺牲两艘船
            caster['ships'].pop()
            caster['ships'].pop()
            caster['remaining_ships'] -= 2
            
            # 获取选择的效果
            effect_choice = room.magic_temp_data.get('effect_choice', 1)
            if effect_choice == 1:
                # 让对方选择一艘船死亡
                opponent['ships'].pop()
                opponent['remaining_ships'] -= 1
                result['message'] = '牺牲两艘战舰，对方被迫选择一艘战舰摧毁'
            else:
                # 跳过对方所有阶段
                room.skip_opponent_turn = True
                result['message'] = '牺牲两艘战舰，跳过对方本回合所有阶段'

        elif card['name'] == '绝处逢生':
            # 牺牲所有船，只留一艘，之后击杀任何船直接获胜
            if len(caster['ships']) < 3:
                result['success'] = False
                result['message'] = '需要至少3艘战舰才能发动'
                return result
            
            # 保存一艘船
            remaining_ship = random.choice(caster['ships'])
            caster['ships'] = [remaining_ship]
            caster['remaining_ships'] = 1
            
            # 设置效果标记
            room.players[caster_id]['effect_flags'] = room.players[caster_id].get('effect_flags', {})
            room.players[caster_id]['effect_flags']['last_stand'] = True
            # 无效化其他魔法卡
            caster['magic_hand'] = []
            
            result['message'] = '进入绝处逢生状态，击杀任何船直接获胜'

        elif card['name'] == '死者苏生':
            # 复活一艘船
            if len(caster['ships']) >= 6:
                result['success'] = False
                result['message'] = '战舰数量已达上限'
                return result
            
            if caster.get('sunken_ships') and len(caster['sunken_ships']) > 0:
                # 从沉没的船中恢复最近一艘
                revived_ship = caster['sunken_ships'].pop()
                caster['ships'].append(revived_ship)
                caster['remaining_ships'] += 1
                result['message'] = '成功复活一艘战舰'
            else:
                result['success'] = False
                result['message'] = '没有可复活的战舰'

        elif card['name'] == '疗愈':
            # 复活至多两艘被击杀的船
            if len(caster['ships']) >= 6:
                result['success'] = False
                result['message'] = '战舰数量已达上限'
                return result
            
            revived = 0
            # 尝试复活两艘船
            if caster.get('sunken_ships'):
                while revived < 2 and caster['sunken_ships']:
                    revived_ship = caster['sunken_ships'].pop()
                    caster['ships'].append(revived_ship)
                    caster['remaining_ships'] += 1
                    revived += 1
            
            result['message'] = f'成功复活{revived}艘战舰'

        elif card['name'] == '盗亦有道':
            # 获取对方打出的上一张魔法卡
            if not room.magic_history or room.magic_history[-1]['caster'] == caster_id:
                result['success'] = False
                result['message'] = '对方没有使用过魔法卡'
                return result
            
            # 获取对方上一张魔法卡
            stolen_card = room.magic_history[-1]['card']
            caster['magic_hand'].append(stolen_card)
            # 从对方弃牌堆移除
            if stolen_card in opponent['magic_discard']:
                opponent['magic_discard'].remove(stolen_card)
            
            result['message'] = f'成功盗取对方的{stolen_card["name"]}'

        elif card['name'] == '回光返照':
            # 清空棋盘重新摆放6艘船
            caster['ships'] = []
            caster['attacks'] = []
            caster['remaining_ships'] = 0
            # 标记需要重新摆放
            room.players[caster_id]['needs_reset'] = True
            # 清空对方视角
            room.players[opponent_id]['revealed_positions'] = []
            
            result['message'] = '已清空棋盘，请重新摆放战舰'

        elif card['name'] == '加百列之光':
            # 无效化对方上一张魔法卡和当前场地魔法
            negated_count = 0
            # 无效化对方上一张魔法卡
            if room.magic_history and room.magic_history[-1]['caster'] != caster_id:
                room.magic_history.pop()
                negated_count += 1
            
            # 无效化场地魔法
            if opponent_id in room.field_magics:
                del room.field_magics[opponent_id]
                negated_count += 1
            
            result['message'] = f'成功无效化{negated_count}个效果'

        elif card['name'] == '钢筋铁骨':
            # 牺牲一艘船，其他船进入无敌状态
            if len(caster['ships']) < 2:
                result['success'] = False
                result['message'] = '需要至少2艘战舰才能发动'
                return result
            
            # 牺牲一艘船
            caster['ships'].pop()
            caster['remaining_ships'] -= 1
            
            # 其他船进入无敌状态
            for ship in caster['ships']:
                ship['invincible'] = True
            
            result['message'] = '牺牲一艘战舰，其他战舰进入无敌状态'

        elif card['name'] == '神机妙算':
            # 宣言x，如果结束阶段船数减少x，那些船不会减少
            if 'prediction' not in room.magic_temp_data:
                result['success'] = False
                result['message'] = '需要宣言减少的船数'
                return result
            
            x = room.magic_temp_data['prediction']
            room.players[caster_id]['effect_flags'] = room.players[caster_id].get('effect_flags', {})
            room.players[caster_id]['effect_flags']['prediction'] = x
            result['message'] = f'宣言船数减少{x}，若预测成功则不会减少'

        # ==== 场地魔法卡 ====
        elif card['type'] == '场地':
            # 场地魔法处理 - 全场只能有一张场地魔法卡生效
            # 移除所有玩家的场地魔法卡
            for existing_player_id in list(room.field_magics.keys()):
                old_card = room.field_magics[existing_player_id]
                # 将旧的场地魔法卡加入弃牌堆
                room.players[existing_player_id]['magic_discard'].append(old_card)
                # 广播场地魔法移除
                emit('field_magic_updated', {
                    'player_id': existing_player_id,
                    'card': None
                }, room=room.id)
                # 从场地魔法字典中移除
                del room.field_magics[existing_player_id]
            
            # 设置新的场地魔法卡
            room.field_magics[caster_id] = card
            
            if card['name'] == '恶魔契约':
                result['message'] = '恶魔契约生效，双方船数增减绑定'
            elif card['name'] == '禁忌果实':
                result['message'] = '禁忌果实生效，双方只能使用失灵！和场地魔法'
            elif card['name'] == '伊甸园':
                result['message'] = '伊甸园生效，攻击次数变为6-n'
            elif card['name'] == '教皇旨意':
                result['message'] = '教皇旨意生效，攻击需要弃置魔法卡'

        # ==== 已实现的魔法卡 ====
        elif card['name'] == '失灵！':
            # 无效化对方上一张魔法卡
            if room.magic_history and room.magic_history[-1]['caster'] != caster_id:
                last_magic = room.magic_history.pop()
                result['message'] = f'无效化了{last_magic["card"]["name"]}'
                result['negated'] = last_magic
            else:
                result['success'] = False
                result['message'] = '没有可无效化的魔法卡'

        elif card['name'] == '看破！':
            # 无效化对方本回合所有魔法卡
            room.players[opponent_id]['magic_blocked'] = True
            result['message'] = '本回合对方魔法卡被无效化'

        elif card['name'] == '增援':
            # 召唤一艘战舰：等待玩家选择放置位置
            if len(caster['ships']) >= 6:
                result['success'] = False
                result['message'] = '战舰数量已达上限'
            else:
                # 存储临时数据以等待客户端确认位置
                room.magic_temp_data = room.get('magic_temp_data', {})
                room.magic_temp_data['pending_reinforcement'] = {
                    'caster': caster_id
                }
                result['temp_data_id'] = 'reinforcement_choice'
                result['message'] = '请选择增援放置位置'

        else:
            result['success'] = False
            result['message'] = f'未实现的魔法卡: {card["name"]}'



    except Exception as e:
        result['success'] = False
        result['message'] = f'魔法效果应用失败: {str(e)}'

    return result

if __name__ == '__main__':
    # 初始化数据库
    db.init_db()
    # 添加详细日志输出
    import logging
    logging.basicConfig(level=logging.DEBUG)
    # 启动服务器
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
    