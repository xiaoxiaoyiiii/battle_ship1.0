# -*- coding: utf-8 -*-
"""真实 socket 双客户端 E2E：教皇旨意压次数后，火力全开不能还原。

作者实测场景：
  1. 我打出教皇旨意 → 本回合攻击次数归 0
  2. 对方使用火力全开 → 旧实现照样给 2×船数 的次数

用法：带 ENABLE_TEST_EVENTS=1 启动服务后运行本脚本。
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
        def _chain(d):
            self.sio.emit('chain_response',
                          {'room_id': self.room, 'player_id': self.pid, 'chain': False})

        @self.sio.on('priority_request')
        def _prio(d):
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


def state(ag):
    return ag.emit('test_get_game_state', {'room_id': ag.room})['game_state']


def drain_chain(ag, limit=30):
    for _ in range(limit):
        time.sleep(0.35)
        if not state(ag)['chain']:
            return True
    return False


a, b = Agent('A'), Agent('B')
a.connect()
b.connect()
a.room = a.emit('create_room', {'player_name': 'HL-A'})['room_id']
b.room = a.room
b.pid = b.emit('join_room', {'room_id': a.room, 'player_name': 'HL-B'})['player_id']
a.pid = [k for k in state(a)['players'] if k != b.pid][0]

ships = [{'positions': [{'x': i, 'y': i}], 'hits': []} for i in range(6)]
a.emit('place_ships', {'room_id': a.room, 'player_id': a.pid, 'ships': ships})
ships2 = [{'positions': [{'x': i, 'y': 5 - i}], 'hits': []} for i in range(6)]
b.emit('place_ships', {'room_id': b.room, 'player_id': b.pid, 'ships': ships2})
a.emit('rps_choice', {'room_id': a.room, 'player_id': a.pid, 'choice': 'rock'})
b.emit('rps_choice', {'room_id': b.room, 'player_id': b.pid, 'choice': 'paper'})
time.sleep(0.5)

atk_pid = state(a)['current_attacker']
atk, dfn = (a, b) if atk_pid == a.pid else (b, a)
print('先手:', atk.name, ' 后手:', dfn.name)

for who in (a, b):
    who.emit('test_clear_all_effects', {'room_id': who.room})
time.sleep(0.3)

# 先手拿教皇旨意（场地，把本回合攻击次数压成 0）
atk.emit('test_add_specific_magic_card',
         {'room_id': atk.room, 'player_id': atk.pid, 'card_name': '教皇旨意'})
# 后手拿火力全开
dfn.emit('test_add_specific_magic_card',
         {'room_id': dfn.room, 'player_id': dfn.pid, 'card_name': '火力全开'})
time.sleep(0.5)

print()
print('--- 步骤 1：先手在准备阶段打教皇旨意 ---')
r = atk.emit('use_magic_card', {'room_id': atk.room, 'player_id': atk.pid,
                                'card': {'name': '教皇旨意'}, 'targets': []})
print('  结果:', r)
drain_chain(atk)
st = state(a)
print('  场地魔法:', st['field_magic'])
print('  攻击次数:', st['attacks_remaining'])
check(st['attacks_remaining'] == 0, '教皇旨意把攻击次数压成 0', st['attacks_remaining'])

print()
print('--- 步骤 2：先手进战斗阶段 ---')
r = atk.emit('enter_battle_phase', {'room_id': atk.room, 'player_id': atk.pid})
for _ in range(25):
    time.sleep(0.3)
    if state(a).get('current_phase') == 'battle':
        break
st = state(a)
print('  阶段:', st.get('current_phase'), ' 攻击次数:', st['attacks_remaining'])
check(st['attacks_remaining'] == 0,
      '★ 进战斗阶段后攻击次数仍是 0（教皇旨意生效）', st['attacks_remaining'])

print()
print('--- 步骤 3：先手自己在战斗阶段打火力全开（关键断言）---')
# ⚠️ 速阶1 只能在自己的回合用，所以必须由【攻击方自己】打这张牌。
# 作者的原始场景是"对方使用火力全开"，但那是在对方自己的回合、
# 次数被自己的教皇旨意压成 0 的时候 —— 换成同一个人打等价。
atk.emit('test_add_specific_magic_card',
         {'room_id': atk.room, 'player_id': atk.pid, 'card_name': '火力全开'})
time.sleep(0.4)
r = atk.emit('use_magic_card', {'room_id': atk.room, 'player_id': atk.pid,
                                'card': {'name': '火力全开'}, 'targets': []})
print('  结果:', r)
drain_chain(atk)
st = state(a)
print('  先手攻击次数:', st['attacks_remaining'])
print('  先手剩余船数:', st['players'][atk.pid]['remaining_ships'])
check(st['attacks_remaining'] == 0,
      '★ 火力全开不能把教皇旨意压掉的次数还原（仍是 0）',
      {'attacks': st['attacks_remaining'], 'ships': st['players'][atk.pid]['remaining_ships']})
check(st['attacks_remaining'] != st['players'][atk.pid]['remaining_ships'] * 2,
      '★ 绝不能等于 2×船数（那就是旧实现的老 bug）',
      st['players'][atk.pid]['remaining_ships'] * 2)

print()
print('--- 步骤 4：反证：正常情况下火力全开确实翻倍 ---')
# 拆掉场地，重算次数，再打一张火力全开
dfn.emit('test_add_specific_magic_card',
         {'room_id': dfn.room, 'player_id': dfn.pid, 'card_name': '火力全开'})
time.sleep(0.4)
atk.emit('remove_field_magic', {'room_id': atk.room, 'player_id': atk.pid})
time.sleep(0.6)
atk.emit('test_add_specific_magic_card',
         {'room_id': atk.room, 'player_id': atk.pid, 'card_name': '火力全开'})
time.sleep(0.4)
st_before = state(a)
before = st_before['attacks_remaining']
print('  拆场地后攻击次数:', before)
if before > 0:
    r = atk.emit('use_magic_card', {'room_id': atk.room, 'player_id': atk.pid,
                                    'card': {'name': '火力全开'}, 'targets': []})
    print('  出牌结果:', r)
    drain_chain(atk)
    after = state(a)['attacks_remaining']
    print('  火力全开前:', before, ' 后:', after)
    check(after == before * 2, '★ 次数非 0 时确实翻倍', {'before': before, 'after': after})
else:
    print('  （次数仍为 0，跳过反证）')

a.sio.disconnect()
b.sio.disconnect()

print()
if problems:
    print('✗ %d 项未通过：' % len(problems))
    for p in problems:
        print('   · ' + p)
    sys.exit(1)
print('✓ 全部通过')
