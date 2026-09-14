# -*- coding: utf-8 -*-
"""教皇旨意：实测「现在」的行为，作为改动前的基线。

要验证的疑点（作者反馈"弃置魔法卡之后应该是让自己攻击次数+2
然后可以和正常攻击逻辑一样"）：
  1. 现在弃卡后 attacks_remaining 是多少？（怀疑仍是 0）
  2. 现在弃卡是不是只能对着【同一个格子】打两发、由服务端一次性执行？
  3. 现在弃卡后能不能走普通 attack 通道打别的格子？

用法：带 ENABLE_TEST_EVENTS=1 启动服务后运行。
"""
import os
import time

import socketio

URL = os.environ.get('E2E_URL', 'http://127.0.0.1:5000')


class Agent:
    def __init__(self, name):
        self.name = name
        self.sio = socketio.Client(reconnection=False)
        self.room = None
        self.pid = None

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
a.room = a.emit('create_room', {'player_name': 'P-A'})['room_id']
b.room = a.room
b.pid = b.emit('join_room', {'room_id': a.room, 'player_name': 'P-B'})['player_id']
a.pid = [k for k in st(a)['players'] if k != b.pid][0]

ships = [{'positions': [{'x': i, 'y': i}], 'hits': []} for i in range(6)]
a.emit('place_ships', {'room_id': a.room, 'player_id': a.pid, 'ships': ships})
ships2 = [{'positions': [{'x': i, 'y': 5 - i}], 'hits': []} for i in range(6)]
b.emit('place_ships', {'room_id': b.room, 'player_id': b.pid, 'ships': ships2})
a.emit('rps_choice', {'room_id': a.room, 'player_id': a.pid, 'choice': 'rock'})
b.emit('rps_choice', {'room_id': b.room, 'player_id': b.pid, 'choice': 'paper'})
time.sleep(0.5)

atk_pid = st(a)['current_attacker']
atk, dfn = (a, b) if atk_pid == a.pid else (b, a)
print('先手:', atk.name)

for who in (a, b):
    who.emit('test_clear_all_effects', {'room_id': who.room})
time.sleep(0.3)

# 先手拿教皇旨意 + 几张可弃的卡
atk.emit('test_add_specific_magic_card',
         {'room_id': atk.room, 'player_id': atk.pid, 'card_name': '教皇旨意'})
for c in ['冻结', '轰炸', '疗愈', '探测雷达']:
    atk.emit('test_add_specific_magic_card',
             {'room_id': atk.room, 'player_id': atk.pid, 'card_name': c})
time.sleep(0.5)

print()
print('--- 1. 先手打教皇旨意 ---')
r = atk.emit('use_magic_card', {'room_id': atk.room, 'player_id': atk.pid,
                                'card': {'name': '教皇旨意'}, 'targets': []})
print('  ', r)
drain(atk)
s = st(a)
print('  场地:', s['field_magic'], ' 攻击次数:', s['attacks_remaining'])

print()
print('--- 2. 进战斗阶段 ---')
atk.emit('enter_battle_phase', {'room_id': atk.room, 'player_id': atk.pid})
for _ in range(25):
    time.sleep(0.3)
    if st(a).get('current_phase') == 'battle':
        break
s = st(a)
print('  阶段:', s.get('current_phase'), ' 攻击次数:', s['attacks_remaining'])

print()
print('--- 3. 直接走普通 attack 通道（现在能不能打？）---')
r = atk.emit('attack', {'room_id': atk.room, 'player_id': atk.pid, 'x': 0, 'y': 5})
print('  普通 attack ->', r)
drain(atk)
print('  攻击次数:', st(a)['attacks_remaining'])

print()
print('--- 4. 走 papal_attack 弃一张卡打 (1,4) ---')
before_hand = len(st(a)['players'][atk.pid].get('magic_hand', []) or [])
r = atk.emit('papal_attack', {'room_id': atk.room, 'player_id': atk.pid,
                              'x': 1, 'y': 4, 'discard_card_index': 0})
print('  返回:', r)
drain(atk)
s = st(a)
print('  攻击次数【弃卡后】:', s['attacks_remaining'], '   <-- 关键：期望是 +2 而不是 0')
res = r.get('results') if isinstance(r, dict) else None
print('  这次返回了几发攻击结果:', len(res) if res else 0)
if res:
    for i, x in enumerate(res):
        print('    第%d发 -> 命中=%s 击沉=%s' % (i + 1, x.get('hit'), x.get('ship_sunk')))

print()
print('--- 5. 弃卡后能不能再走普通 attack 打【另一个】格子？---')
r = atk.emit('attack', {'room_id': atk.room, 'player_id': atk.pid, 'x': 5, 'y': 0})
print('  普通 attack ->', r)
drain(atk)
print('  攻击次数:', st(a)['attacks_remaining'])

print()
print('--- 6. 现在能不能进结束阶段？---')
r = atk.emit('enter_end_phase', {'room_id': atk.room, 'player_id': atk.pid})
print('  enter_end_phase ->', r)

a.sio.disconnect()
b.sio.disconnect()
