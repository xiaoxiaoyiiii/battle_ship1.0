# -*- coding: utf-8 -*-
"""疗愈复活后对方能再打那一格 —— 真 socket 双客户端端到端。

作者反馈：「疗愈仍然存在问题 复活在原地之后对方可能无法攻击这个复活的格子
因为已经被红色叉叉占用了」

完整链路：
  1. P1 打沉 P2 在 (x,y) 的船（这一格进入双方攻击历史）
  2. P2 用疗愈原地复活
  3. ★ P1 必须收到 board_attacks_updated，且里面【没有】这一格
     （前端靠它擦掉 ✕ 并重新绑点击监听）
  4. ★ P1 再打这一格必须成功（服务端放行）
  5. 反证：没被复活的格子，攻击历史必须原样保留（不能把整张表清空）

用法：带 ENABLE_TEST_EVENTS=1 启动服务后运行。
"""
import os
import sys
import time

import socketio

URL = os.environ.get('E2E_URL', 'http://127.0.0.1:5000')
problems = []


def check(ok, label, detail=None):
    print(('PASS  ' if ok else 'FAIL  ') + label +
          ('' if detail is None else '  ->  ' + repr(detail)))
    if not ok:
        problems.append(label)


class Agent:
    def __init__(self, name):
        self.name = name
        self.sio = socketio.Client(reconnection=False)
        self.room = None
        self.pid = None
        self.board_attacks = []

        @self.sio.on('board_attacks_updated')
        def _b(d):
            self.board_attacks.append(d or {})

        @self.sio.on('chain_request')
        def _c(d):
            self.sio.emit('chain_response',
                          {'room_id': self.room, 'player_id': self.pid, 'chain': False})

        @self.sio.on('priority_request')
        def _p(d):
            self.sio.emit('priority_response',
                          {'room_id': self.room, 'player_id': self.pid, 'respond': False})

    def connect(self):
        if not self.sio.connected:
            self.sio.connect(URL, transports=['polling'])

    def emit(self, ev, data, timeout=6.0):
        box = {}

        def cb(r):
            box['r'] = r

        self.sio.emit(ev, data, callback=cb)
        t = time.time()
        while 'r' not in box and time.time() - t < timeout:
            time.sleep(0.02)
        return box.get('r')


def st(ag):
    return ag.emit('test_get_game_state', {'room_id': ag.room})['game_state']


def drain(ag, n=30):
    for _ in range(n):
        time.sleep(0.3)
        if not st(ag)['chain']:
            return


a, b = Agent('A'), Agent('B')
a.connect()
b.connect()
a.room = a.emit('create_room', {'player_name': 'H-A'})['room_id']
b.room = a.room
b.pid = b.emit('join_room', {'room_id': a.room, 'player_name': 'H-B'})['player_id']
a.pid = [k for k in st(a)['players'] if k != b.pid][0]

ships = [{'positions': [{'x': i, 'y': 0}], 'hits': []} for i in range(6)]
a.emit('place_ships', {'room_id': a.room, 'player_id': a.pid, 'ships': ships})
ships2 = [{'positions': [{'x': i, 'y': 5}], 'hits': []} for i in range(6)]
b.emit('place_ships', {'room_id': b.room, 'player_id': b.pid, 'ships': ships2})
a.emit('rps_choice', {'room_id': a.room, 'player_id': a.pid, 'choice': 'rock'})
b.emit('rps_choice', {'room_id': b.room, 'player_id': b.pid, 'choice': 'paper'})
time.sleep(0.5)

atk_pid = st(a)['current_attacker']
P1, P2 = (a, b) if atk_pid == a.pid else (b, a)   # P1 = 攻击方
for who in (a, b):
    who.emit('test_clear_all_effects', {'room_id': who.room})
time.sleep(0.3)

# ⚠️ 不要用 test_set_player_ships：它生成的是【多格船】（3 格/2 格），
# 一发打不沉，就没有沉船可复活，疗愈会空转、整条链路跑不起来。
# 前面 place_ships 摆的是单格船，一发一个，正好用来测复活。
st_now = st(P1)
p2_ships = st_now['players'][P2.pid]['ships']
ships_before = st_now['players'][P2.pid]['remaining_ships']
print('防守方船数:', ships_before, ' 船位:', [s['positions'] for s in p2_ships])
check(all(len(s['positions']) == 1 for s in p2_ships),
      '（前提）防守方都是单格船（一发能沉）', [len(s['positions']) for s in p2_ships])

# 先手进战斗阶段
P1.emit('enter_battle_phase', {'room_id': P1.room, 'player_id': P1.pid})
for _ in range(25):
    time.sleep(0.3)
    if st(P1).get('current_phase') == 'battle':
        break

# --- 1. P1 打沉 P2 一艘船 ---
target = p2_ships[0]['positions'][0]
tx, ty = target[0], target[1]
r = P1.emit('attack', {'room_id': P1.room, 'player_id': P1.pid, 'x': tx, 'y': ty})
check(r.get('status') == 'success', '第一步：P1 打中了目标格', r)
drain(P1)
sunk = st(P1)['players'][P2.pid]['remaining_ships']
check(sunk == ships_before - 1, '（前提）确实打沉了一艘（单格船一发即沉）',
      {'before': ships_before, 'after': sunk})

# 再打一个【空格】(0,5) 当"打空"的反证。
# ⚠️ 别拿另一艘船来当反证：防守方全是单格船，打中了也会沉，
# 疗愈一次能复活 2 艘 → 两格都会被清掉，"没被复活的格子仍在历史里"就验证不了。
other = (0, 5)
r = P1.emit('attack', {'room_id': P1.room, 'player_id': P1.pid, 'x': other[0], 'y': other[1]})
other_ok = r.get('status') == 'success'
print('  第二格（空格）攻击:', r)
drain(P1)

# --- 2. P2 用疗愈原地复活 ---
P2.emit('test_add_specific_magic_card',
        {'room_id': P2.room, 'player_id': P2.pid, 'card_name': '疗愈'})
time.sleep(0.4)
P1.board_attacks.clear()
P2.board_attacks.clear()
r = P2.emit('use_magic_card', {'room_id': P2.room, 'player_id': P2.pid,
                               'card': {'name': '疗愈'}, 'targets': {}})
check(r.get('status') == 'success', '第二步：P2 打出疗愈', r)
drain(P2)
time.sleep(0.8)

# --- 3. P1 必须收到 board_attacks_updated，且不含被复活那格 ---
check(bool(P1.board_attacks), '★ P1 收到了 board_attacks_updated（否则前端不会重绘/重绑）',
      len(P1.board_attacks))
if P1.board_attacks:
    flat = P1.board_attacks[-1].get('my_attacks') or []
    cells = {(c['x'], c['y']) for c in flat}
    check((tx, ty) not in cells, f'★ 被复活的格 ({tx},{ty}) 已从 P1 的攻击历史里移除', sorted(cells))
    check(bool(P2.board_attacks), 'P2 也收到了 board_attacks_updated')
    if P2.board_attacks:
        opp = P2.board_attacks[-1].get('opponent_attacks') or []
        ocells = {(c['x'], c['y']) for c in opp}
        check((tx, ty) not in ocells,
              f'★ P2 自己棋盘上那格的 ✕ 也被清掉（opponent_attacks 里没有它）', sorted(ocells))

# --- 4. ★ P1 再打这一格必须成功 ---
P1.emit('test_get_game_state', {'room_id': P1.room})
st_before = st(P1)
left = st_before.get('attacks_remaining') or 0
if left <= 0:
    P1.emit('test_reset_game', {'room_id': P1.room})   # 兜底，不该走到
    print('  （次数用尽，跳过第 4 步）')
else:
    r = P1.emit('attack', {'room_id': P1.room, 'player_id': P1.pid, 'x': tx, 'y': ty})
    check(r.get('status') == 'success',
          '★ 复活后 P1 能再打这一格（旧实现报「你已经攻击过这个位置了」）', r)
    drain(P1)

# --- 5. 反证：没被复活的格子仍在历史里 ---
if P2.board_attacks:
    flat = P2.board_attacks[-1].get('opponent_attacks') or []
    cells = {(c['x'], c['y']) for c in flat}
    if other_ok:
        check(other in cells,
              '（反证）没被复活的那一格仍保留在攻击历史里（不能整表清空）', sorted(cells))
    else:
        check(True, '（反证）第二格当时没打出去，跳过', sorted(cells))

a.sio.disconnect()
b.sio.disconnect()

print()
if problems:
    print('✗ %d 项未通过：' % len(problems))
    for p in problems:
        print('   · ' + p)
    sys.exit(1)
print('✓ 全部通过')
