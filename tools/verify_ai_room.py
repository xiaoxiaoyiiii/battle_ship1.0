# -*- coding: utf-8 -*-
"""验证人机对战房间全流程与静态资源兜底。"""
import sys
import time

import requests
import socketio

URL = 'http://127.0.0.1:5000'

# ---------------- 1. 静态资源兜底 ----------------
r = requests.get(URL + '/static/avatars/default.png', timeout=5)
assert r.status_code == 200 and len(r.content) > 0, f'default.png {r.status_code}'
print('PASS default.png 200')

r = requests.get(URL + '/user_stats', params={'username': '不存在的用户xyz'}, timeout=5)
data = r.json()
assert r.status_code == 200 and data.get('stats') is None and data.get('history') == [], (r.status_code, data)
print('PASS user_stats 不存在用户返回 200 空战绩')

# ---------------- 2. 人机对战流程 ----------------
sio = socketio.Client(reconnection=False)
sio.connect(URL, transports=['polling'])

state = {'room': None, 'pid': None, 'gs': [], 'phase': None}

@sio.on('game_state')
def _gs(data=None):
    state['gs'].append(data)

@sio.on('*')
def _any(event, data=None):
    if event in ('phase_updated', 'turn_change'):
        state['phase'] = data

resp = {}
sio.emit('create_ai_room', {'player_name': '人类'}, callback=lambda r: resp.update(r))
deadline = time.time() + 5
while not resp and time.time() < deadline:
    time.sleep(0.05)
assert resp.get('status') == 'success', f'create_ai_room failed: {resp}'
state['room'] = resp['room_id']
print(f'PASS create_ai_room 返回房间 {state["room"]}')

join = {}
sio.emit('join_room', {'room_id': state['room'], 'player_name': '人类'}, callback=lambda r: join.update(r))
deadline = time.time() + 5
while not join and time.time() < deadline:
    time.sleep(0.05)
assert join.get('status') == 'success', f'join failed: {join}'
state['pid'] = join['player_id']

# 人类摆船
ships = [{'positions': [{'x': i, 'y': i}], 'hits': []} for i in range(6)]
ps = {}
sio.emit('place_ships', {'room_id': state['room'], 'player_id': state['pid'], 'ships': ships},
         callback=lambda r: ps.update(r))
deadline = time.time() + 5
while not ps and time.time() < deadline:
    time.sleep(0.05)
assert ps.get('status') == 'success'
print('PASS 人类摆船，进入猜拳')

# 猜拳（AI 自动出拳；平局时自动重新出拳，直到进入对战）
for _ in range(6):
    sio.emit('rps_choice', {'room_id': state['room'], 'player_id': state['pid'], 'choice': 'rock'})
    time.sleep(2)
    st = {}
    sio.emit('test_get_game_state', {'room_id': state['room']}, callback=lambda r: st.update(r))
    deadline = time.time() + 3
    while not st and time.time() < deadline:
        time.sleep(0.05)
    if st.get('game_state', {}).get('state') != 'rock_paper_scissors':
        break
print(f'猜拳完成，当前状态: {st.get("game_state", {}).get("state")}')

# 观察最多 30 秒：AI 应自动完成其回合（回合最终应交回人类或游戏结束）
turns = []
for _ in range(60):
    st = {}
    sio.emit('test_get_game_state', {'room_id': state['room']}, callback=lambda r: st.update(r))
    deadline = time.time() + 3
    while not st and time.time() < deadline:
        time.sleep(0.05)
    gs = st.get('game_state', {})
    turns.append((gs.get('current_attacker'), gs.get('state'), gs.get('attacks_remaining')))
    if gs.get('state') == 'game_over':
        print('对局结束（AI 获胜或人类失败），AI 流程已运转')
        break
    if gs.get('current_attacker') == state['pid'] and gs.get('state') == 'attacking':
        # 回合交回人类，说明 AI 已完成一整回合
        print(f'PASS AI 完成自动回合并交还回合给人类（观察序列尾部: {turns[-3:]}）')
        break
    time.sleep(0.5)
else:
    print(f'FAIL AI 未在预期时间内完成回合: {turns[-5:]}')
    sys.exit(1)

sio.disconnect()
print('AI 房间全流程验证完成')
