# -*- coding: utf-8 -*-
"""第四批修复：AI 房间（create_ai_room + 自动行为钩子）与 user_stats 兜底。
每处锚点必须恰好命中一次。"""
import base64
import io
import os

SERVER = r'd:\develop\battle_ship1.0\server.py'
API = r'd:\develop\battle_ship1.0\api.py'

text = io.open(SERVER, encoding='utf-8').read()

def rep(old, new, count=1, label=''):
    global text
    c = text.count(old)
    assert c == count, f'{label}: expected {count}, found {c}'
    text = text.replace(old, new, count)

# ---------------------------------------------------------------- 1. create_ai_room 方法
rep(
    """    def join_room(self, room_id: str, player_id: str, player_name: str, sid: str) -> bool:""",
    """    def create_ai_room(self, player_id: str, player_name: str, player_user_id=None) -> str:
        \"\"\"创建人机对战房间：预置AI玩家，真人随后 join_room 走正常双人开局流程\"\"\"
        room_id = str(uuid.uuid4())[:6]
        room = GameRoom(room_id)
        room.is_ai_room = True
        self.rooms[room_id] = room
        ai_id = 'ai-' + room_id
        room.players[ai_id] = Player(name='AI', ships=[], attacks=[], remaining_ships=0, user_id=None, sid=ai_id)
        room.init_player_magic(ai_id, magic_cards)
        return room_id

    def join_room(self, room_id: str, player_id: str, player_name: str, sid: str) -> bool:""",
    label='create_ai_room')

# ---------------------------------------------------------------- 2. AI 驱动函数（插在 end_turn 之后）
AI_HELPERS = '''

# ---------------------------------------------------------------------------
# AI 对战驱动：AI 自动摆船/出拳/回合推进（仅 is_ai_room 房间生效）
# ---------------------------------------------------------------------------
def _ai_player_id(room):
    \"\"\"返回房间内AI玩家ID；不存在返回None。\"\"\"
    for pid in room.players:
        if pid.startswith('ai-'):
            return pid
    return None


def _ai_place_ships(room, ai_id: str):
    \"\"\"为AI随机摆放6艘战舰（布局规则与测试桩一致）。\"\"\"
    from random import sample
    player = room.players[ai_id]
    player.ships = []
    player.remaining_ships = 0
    used_positions = set()
    for ship_size in [3, 2, 2, 1, 1, 1]:
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
            if not any(pos in used_positions for pos in positions):
                ship_positions = [Position(x=px, y=py) for px, py in positions]
                player.ships.append(PlayerShip(positions=ship_positions, hits=[]))
                player.remaining_ships += 1
                used_positions.update(positions)
                placed = True


def _maybe_run_ai_turn(room):
    \"\"\"若当前攻击者是AI，后台驱动其完整回合。\"\"\"
    if not getattr(room, 'is_ai_room', False) or room.state == 'game_over':
        return
    ai_id = _ai_player_id(room)
    if not ai_id or room.current_attacker != ai_id:
        return
    socketio.start_background_task(_ai_turn_loop, room.id)


def _ai_turn_loop(room_id: str):
    \"\"\"AI回合：进入战斗阶段→随机攻击至次数耗尽→结束阶段→交出回合。\"\"\"
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


# 教皇旨意弃卡攻击'''

rep('# 教皇旨意弃卡攻击', AI_HELPERS, label='ai_helpers')

# ---------------------------------------------------------------- 3. place_ships 钩子：人类摆完后AI自动摆船
rep(
    """    room.players[player_id].ships = list(map(lambda x: PlayerShip(**x), ships))

    # 新增：计算并设置剩余战舰数量（攻击次数）""",
    """    room.players[player_id].ships = list(map(lambda x: PlayerShip(**x), ships))

    # AI房间：人类摆完后为AI自动摆船
    if getattr(room, 'is_ai_room', False):
        ai_id = _ai_player_id(room)
        if ai_id and player_id != ai_id and not room.players[ai_id].ships:
            _ai_place_ships(room, ai_id)

    # 新增：计算并设置剩余战舰数量（攻击次数）""",
    label='ai_place_hook')

# ---------------------------------------------------------------- 4. rps 钩子：AI自动出拳 + 若AI先手则驱动回合
rep(
    """    room.rps_choices[player_id] = choice
    
    # 检查是否所有玩家都已做出选择""",
    """    # AI房间：AI自动出拳
    if getattr(room, 'is_ai_room', False):
        ai_id = _ai_player_id(room)
        if ai_id and ai_id not in room.rps_choices:
            room.rps_choices[ai_id] = random.choice(['rock', 'paper', 'scissors'])

    room.rps_choices[player_id] = choice
    
    # 检查是否所有玩家都已做出选择""",
    label='ai_rps_hook')

rep(
    """        room.state = 'attacking'
        # 设置当前阶段为准备阶段
        room.current_phase = 'preparation'
        emit('game_state', {
            'state': 'attacking',""",
    """        room.state = 'attacking'
        # 设置当前阶段为准备阶段
        room.current_phase = 'preparation'
        # AI先手时自动驱动其回合
        _maybe_run_ai_turn(room)
        emit('game_state', {
            'state': 'attacking',""",
    label='ai_rps_turn_hook')

# ---------------------------------------------------------------- 5. 回合切换钩子（end_turn else / switch_turn_after_end_phase）
rep(
    """            emit('turn_change', {
                'current_attacker': room.current_attacker,
                'attacks_remaining': room.attacks_remaining,
                'phase': room.current_phase
            }, room=room_id)
            return {'status': 'success'}""",
    """            emit('turn_change', {
                'current_attacker': room.current_attacker,
                'attacks_remaining': room.attacks_remaining,
                'phase': room.current_phase
            }, room=room_id)
            # 轮到AI时自动驱动其回合
            _maybe_run_ai_turn(room)
            return {'status': 'success'}""",
    label='ai_end_turn_hook')

rep(
    """    emit('turn_change', {
        'current_attacker': opponent_id,
        'attacks_remaining': room.attacks_remaining,
        'phase': 'preparation'
    }, room=room.id)""",
    """    emit('turn_change', {
        'current_attacker': opponent_id,
        'attacks_remaining': room.attacks_remaining,
        'phase': 'preparation'
    }, room=room.id)
    # 轮到AI时自动驱动其回合
    _maybe_run_ai_turn(room)""",
    label='ai_switch_turn_hook')

# ---------------------------------------------------------------- 6. AI 不参与连锁（两处）
rep(
    """    opponent_has_speed3 = any(int(c.speed) == 3 for c in opponent.magic_hand)

    if opponent_has_speed3:""",
    """    opponent_has_speed3 = any(int(c.speed) == 3 for c in opponent.magic_hand) and not opponent_id.startswith('ai-')

    if opponent_has_speed3:""",
    label='ai_chain_skip_1')

rep(
    """        opponent_has_speed3 = any(int(c.speed) == 3 for c in opponent.magic_hand)

        if opponent_has_speed3:""",
    """        opponent_has_speed3 = any(int(c.speed) == 3 for c in opponent.magic_hand) and not opponent_id.startswith('ai-')

        if opponent_has_speed3:""",
    label='ai_chain_skip_2')

with io.open(SERVER, 'w', encoding='utf-8', newline='') as f:
    f.write(text)
print('server.py: AI hooks applied')

# ---------------------------------------------------------------- api.py user_stats 兜底
api = io.open(API, encoding='utf-8').read()
old = """    if not stats:
        return jsonify({'error': '用户不存在'}), 404
    history = db.get_match_history(stats['id'], limit)"""
assert api.count(old) == 1, 'api anchor not unique'
api = api.replace(old, """    if not stats:
        # 用户不存在（如游客查询对手）时返回空战绩，避免前端轮询404
        return jsonify({'stats': None, 'history': []})
    history = db.get_match_history(stats['id'], limit)""", 1)
io.open(API, 'w', encoding='utf-8', newline='').write(api)
print('api.py: user_stats fallback applied')

# ---------------------------------------------------------------- 占位头像
PNG_B64 = ('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNg'
           'YGD4DwABBAEAfbLI3wAAAABJRU5ErkJggg==')
avatar_dir = r'd:\develop\battle_ship1.0\static\avatars'
os.makedirs(avatar_dir, exist_ok=True)
with open(os.path.join(avatar_dir, 'default.png'), 'wb') as f:
    f.write(base64.b64decode(PNG_B64))
print('default.png created')
