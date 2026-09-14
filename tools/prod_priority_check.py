# -*- coding: utf-8 -*-
"""直接在生产环境上验「优先权询问」到底会不会出现。

本地全绿但玩家看不到，就必须在生产上按【真实玩家路径】走一遍：
不依赖 test_* 调试事件（线上是关的），只用正常事件：
  create_room / join_room / place_ships / rps_choice / enter_battle_phase

用法：
  python tools/prod_priority_check.py                     # 打线上
  E2E_URL=http://127.0.0.1:5000 python tools/prod_priority_check.py   # 打本地
"""
import os
import sys
import time

import socketio

URL = os.environ.get('E2E_URL', 'http://8.133.180.159:5000')
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
        self.priority_reqs = []
        self.errors = []
        self.events = []

        @self.sio.on('*')
        def _all(event, data=None):
            self.events.append(event)
            if event == 'priority_request':
                self.priority_reqs.append(data or {})
            elif event == 'error':
                self.errors.append(data)
            elif event == 'chain_request':
                # 别让连锁窗口把流程卡住
                self.sio.emit('chain_response',
                              {'room_id': self.room, 'player_id': self.pid, 'chain': False})

    def connect(self):
        if not self.sio.connected:
            self.sio.connect(URL, transports=['polling'])

    def emit(self, ev, data, timeout=8.0):
        box = {}

        def cb(r):
            box['r'] = r

        self.sio.emit(ev, data, callback=cb)
        t = time.time()
        while 'r' not in box and time.time() - t < timeout:
            time.sleep(0.02)
        return box.get('r')


print('目标:', URL)
a, b = Agent('A'), Agent('B')
a.connect()
b.connect()
check(a.sio.connected and b.sio.connected, '两个客户端都连上了')

r = a.emit('create_room', {'player_name': 'PC-A'})
check(r and r.get('status') == 'success', 'A 建房', r)
a.room = r['room_id']
# ⚠️ 创建者的座位 key 由【服务端】决定（游客 = 服务端那侧的 request.sid），
# 它和客户端本地看到的 sio.sid 不是同一个字符串 —— 实测：
#   客户端 a.sid = s58gdEnQmXSMaH8wAABo
#   座位 key      = BlX8e8_0gVfRW3OdAABp
# 所以必须像前端那样紧跟着再 join 一次，从回执里取真实 pid。
# 服务端 handle_join_room 对同一 key 是覆盖写入，所以这步是幂等的。
rj = a.emit('join_room', {'room_id': a.room, 'player_name': 'PC-A'})
check(rj and rj.get('status') == 'success', 'A 拿到自己的真实 pid（走 join 回执）', rj)
a.pid = rj['player_id'] if rj else None

r = b.emit('join_room', {'room_id': a.room, 'player_name': 'PC-B'})
check(r and r.get('status') == 'success', 'B 入座', r)
b.room = a.room
b.pid = r['player_id']

ships = [{'positions': [{'x': i, 'y': i}], 'hits': []} for i in range(6)]
r1 = a.emit('place_ships', {'room_id': a.room, 'player_id': a.pid, 'ships': ships})
ships2 = [{'positions': [{'x': i, 'y': 5 - i}], 'hits': []} for i in range(6)]
r2 = b.emit('place_ships', {'room_id': b.room, 'player_id': b.pid, 'ships': ships2})
check(r1 and r1.get('status') == 'success', 'A 摆船', r1)
check(r2 and r2.get('status') == 'success', 'B 摆船', r2)

for _ in range(12):
    a.emit('rps_choice', {'room_id': a.room, 'player_id': a.pid, 'choice': 'rock'})
    b.emit('rps_choice', {'room_id': b.room, 'player_id': b.pid, 'choice': 'paper'})
    time.sleep(0.6)
    if any(e == 'turn_change' or e == 'phase_updated' for e in a.events + b.events):
        break
time.sleep(0.5)
check('rps_result' in (a.events + b.events), '猜拳已结算', a.events[-5:])

# 先手判定：custom 房下 A 出 rock、B 出 paper → 本实现先手为 A
# 但别假设，直接两个都试：谁先手谁去推进阶段
a.priority_reqs.clear()
b.priority_reqs.clear()
before_a = len(a.events)
before_b = len(b.events)

resp_a = a.emit('enter_battle_phase', {'room_id': a.room, 'player_id': a.pid})
time.sleep(1.2)
resp_b = b.emit('enter_battle_phase', {'room_id': b.room, 'player_id': b.pid})
time.sleep(1.5)

print()
print('A enter_battle_phase ->', resp_a)
print('B enter_battle_phase ->', resp_b)
print('A 收到 priority_request 次数:', len(a.priority_reqs))
print('B 收到 priority_request 次数:', len(b.priority_reqs))
print()
print('A 最近事件:', a.events[before_a:][:12])
print('B 最近事件:', b.events[before_b:][:12])

got = bool(a.priority_reqs or b.priority_reqs)
check(got, '★ 至少有一方收到了 priority_request（生产上真的会弹询问）',
      {'A': len(a.priority_reqs), 'B': len(b.priority_reqs)})
if a.priority_reqs or b.priority_reqs:
    req = (a.priority_reqs or b.priority_reqs)[-1]
    check('action' in req and 'countdown' in req, '载荷带 action / countdown', req)
    check('speed3_cards' in req, '载荷带 speed3_cards', list(req.keys()))

# 顺手确认服务端两个新事件在生产上是活的
who = b if a.priority_reqs else a
r = who.emit('set_decline_priority',
             {'room_id': who.room, 'player_id': who.pid, 'decline': True})
check(r and r.get('status') == 'success', 'set_decline_priority 线上可用', r)
r = who.emit('set_decline_priority',
             {'room_id': who.room, 'player_id': who.pid, 'decline': False})
check(r and r.get('status') == 'success', '开关可以关回去', r)

a.sio.disconnect()
b.sio.disconnect()

print()
if problems:
    print('✗ %d 项未通过：' % len(problems))
    for p in problems:
        print('   · ' + p)
    sys.exit(1)
print('✓ 全部通过')
