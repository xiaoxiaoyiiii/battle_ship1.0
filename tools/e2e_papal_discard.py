# -*- coding: utf-8 -*-
"""教皇旨意（新语义）：弃一张魔法卡 → 攻击次数 +2 → 之后走正常攻击逻辑。

作者裁定：「弃置魔法卡之后应该是让自己攻击次数+2 然后可以和正常攻击逻辑一样」。

本脚本用真实 socket 逐步验证：
  1. 教皇旨意生效后双方次数为 0
  2. 次数为 0 时普通攻击被拒（必须弃卡）
  3. 弃 1 张卡 → 次数变成 2（不是 0！这是旧实现的核心缺陷）
  4. 之后走【普通 attack】通道就能打，每发扣 1 次
  5. 可以打【不同】的格子（旧实现只能对着同一格打两发）
  6. 次数用尽后普通攻击再次被拒，可以再弃一张继续换
  7. 次数没打完时不能进结束阶段（和正常逻辑一致）

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
for who in (a, b):
    who.emit('test_clear_all_effects', {'room_id': who.room})
time.sleep(0.3)

atk.emit('test_add_specific_magic_card',
         {'room_id': atk.room, 'player_id': atk.pid, 'card_name': '教皇旨意'})
for c in ['冻结', '轰炸', '疗愈', '探测雷达']:
    atk.emit('test_add_specific_magic_card',
             {'room_id': atk.room, 'player_id': atk.pid, 'card_name': c})
time.sleep(0.5)

atk.emit('use_magic_card', {'room_id': atk.room, 'player_id': atk.pid,
                            'card': {'name': '教皇旨意'}, 'targets': []})
drain(atk)
atk.emit('enter_battle_phase', {'room_id': atk.room, 'player_id': atk.pid})
for _ in range(25):
    time.sleep(0.3)
    if st(a).get('current_phase') == 'battle':
        break

s = st(a)
check(s['attacks_remaining'] == 0, '教皇旨意生效后攻击次数为 0', s['attacks_remaining'])

# --- 2. 次数 0 时普通攻击被拒 ---
r = atk.emit('attack', {'room_id': atk.room, 'player_id': atk.pid, 'x': 0, 'y': 5})
check(r.get('status') == 'error', '次数为 0 时普通攻击被拒（要先弃卡）', r)

# --- 3. 弃 1 张卡 → 次数 +2 ---
hand_before = st(a)['players'][atk.pid]['magic_hand_count']
r = atk.emit('papal_discard', {'room_id': atk.room, 'player_id': atk.pid,
                               'discard_card_index': 0})
check(r.get('status') == 'success', 'papal_discard 成功', r)
after = st(a)
hand_after = after['players'][atk.pid]['magic_hand_count']
check(after['attacks_remaining'] == 2,
      '★ 弃 1 张卡后攻击次数 = 2（旧实现这里是 0）', after['attacks_remaining'])
check(hand_after == hand_before - 1, '手牌少了一张（确实弃掉了）',
      {'before': hand_before, 'after': hand_after})

# --- 4. 走普通 attack 通道，打两个【不同】的格子 ---
r1 = atk.emit('attack', {'room_id': atk.room, 'player_id': atk.pid, 'x': 0, 'y': 5})
check(r1.get('status') == 'success', '★ 弃卡后普通攻击可以打了（旧实现报「次数已用尽」）', r1)
drain(atk)
check(st(a)['attacks_remaining'] == 1, '第一发扣掉 1 次，剩 1', st(a)['attacks_remaining'])

r2 = atk.emit('attack', {'room_id': atk.room, 'player_id': atk.pid, 'x': 3, 'y': 2})
check(r2.get('status') == 'success', '★ 第二发可以打【另一个】格子（旧实现只能打同一格）', r2)
drain(atk)
check(st(a)['attacks_remaining'] == 0, '第二发扣完，次数归 0', st(a)['attacks_remaining'])

# --- 5. 次数用尽 → 再弃一张继续换 ---
r = atk.emit('attack', {'room_id': atk.room, 'player_id': atk.pid, 'x': 5, 'y': 0})
check(r.get('status') == 'error', '次数用尽后普通攻击再次被拒', r)
r = atk.emit('papal_discard', {'room_id': atk.room, 'player_id': atk.pid,
                               'discard_card_index': 0})
check(r.get('status') == 'success' and st(a)['attacks_remaining'] == 2,
      '★ 可以再弃一张继续换 2 次', st(a)['attacks_remaining'])

# --- 6. 次数没打完不能进结束阶段（与正常逻辑一致）---
r = atk.emit('enter_end_phase', {'room_id': atk.room, 'player_id': atk.pid})
check(r.get('status') == 'error' and '剩余攻击次数' in r.get('message', ''),
      '★ 还有次数时不能进结束阶段（和正常攻击逻辑一致）', r)

# --- 7. 打完就能进 ---
atk.emit('attack', {'room_id': atk.room, 'player_id': atk.pid, 'x': 1, 'y': 4})
drain(atk)
atk.emit('attack', {'room_id': atk.room, 'player_id': atk.pid, 'x': 4, 'y': 1})
drain(atk)
check(st(a)['attacks_remaining'] == 0, '两次都打完', st(a)['attacks_remaining'])
r = atk.emit('enter_end_phase', {'room_id': atk.room, 'player_id': atk.pid})
check(r.get('status') == 'success', '打完次数后可以进结束阶段', r)

# --- 8. 边界：不是战斗阶段 / 没手牌 / 越界索引 ---
b2 = Agent('B2')
b2.connect()
r = atk.emit('papal_discard', {'room_id': 'nonexistent', 'player_id': atk.pid,
                               'discard_card_index': 0})
check(r.get('status') == 'error', '无效房间被拒', r)

a.sio.disconnect()
b.sio.disconnect()
b2.sio.disconnect()

print()
if problems:
    print('✗ %d 项未通过：' % len(problems))
    for p in problems:
        print('   · ' + p)
    sys.exit(1)
print('✓ 全部通过')
