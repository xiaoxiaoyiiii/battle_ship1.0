# -*- coding: utf-8 -*-
"""协议级 e2e：2026-09-17 缺陷批（真实服务端 + 真实 socket，两个客户端）。

与 pytest 的区别：它真的建两个 socket 连接、真的摆船猜拳、真的出牌，
因此能验证「服务端广播给前端的 payload」这一层（pytest 里的 emit 是假的）。

覆盖（都是玩家实测反馈的那几条）：
  V1 死者苏生（没有沉船）→ 效果不生效，但牌必须退回手牌 + 有明确播报
  V2 越战越勇（刚击沉一艘）→ 发动当场攻击次数 +1，并广播 attacks_updated
  V3 冻结 → 播报的"冻结了N艘战舰"必须等于区域内【存活】战舰数
  V4 回光返照 → 清的是"对方打在我方棋盘上的记录"，不是"我打在对方棋盘上的"

用法（需要 `ENABLE_TEST_EVENTS=1`，工具依赖 test_* 桩来摆放与查状态）：
    PORT=5000 CORS_ORIGINS=http://127.0.0.1:5000 ENABLE_TEST_EVENTS=1 \
        BATTLESHIP_DB_PATH=.tmp/e2e.db python server.py
    python tools/e2e_batch_2026_09_17.py
"""
import sys
import time

import socketio

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

URL = 'http://127.0.0.1:5000'
RESULTS = []


def check(ok, label, detail=''):
    print(('PASS  ' if ok else 'FAIL  ') + label + (('  ->  ' + str(detail)) if detail != '' else ''))
    RESULTS.append((bool(ok), label))


class Agent:
    def __init__(self, name):
        self.name = name
        self.pid = None
        self.room = None
        self.hand = []
        self.states = {}
        self.log = []
        self.sio = socketio.Client(reconnection=False)

        @self.sio.on('*')
        def _all(event, data=None):
            self.log.append((event, data))
            if event == 'hand_updated':
                self.hand = [c.get('name') for c in (data or {}).get('hand', [])]
            elif event == 'chain_request':
                self.sio.emit('chain_response', {
                    'room_id': self.room, 'player_id': self.pid, 'chain': False})
            elif event == 'priority_request':
                # 与真实玩家点「取消」一致：不响应这个时点，让阶段转换照常进行
                self.sio.emit('priority_response', {
                    'room_id': self.room, 'player_id': self.pid, 'respond': False})

    def connect(self):
        if not self.sio.connected:
            self.sio.connect(URL, transports=['polling'])

    def emit(self, event, data, timeout=6.0):
        box = {}

        def cb(resp):
            box['resp'] = resp

        self.sio.emit(event, data, callback=cb)
        deadline = time.time() + timeout
        while 'resp' not in box and time.time() < deadline:
            time.sleep(0.02)
        return box.get('resp')

    def state(self):
        r = self.emit('test_get_game_state', {'room_id': self.room})
        return (r or {}).get('game_state') or {}

    def texts(self, event='message'):
        return [(d or {}).get('text', '') for e, d in self.log if e == event]


def setup(a, b):
    a.connect(); b.connect()
    a.room = a.emit('create_room', {'player_name': 'V-A'})['room_id']
    r = b.emit('join_room', {'room_id': a.room, 'player_name': 'V-B'})
    b.room = a.room
    b.pid = r['player_id']
    st = a.emit('test_get_game_state', {'room_id': a.room})['game_state']
    a.pid = next(p for p in st['players'] if p != b.pid)

    ships = [{'positions': [{'x': i, 'y': 0}], 'hits': []} for i in range(6)]
    a.emit('place_ships', {'room_id': a.room, 'player_id': a.pid, 'ships': ships})
    ships2 = [{'positions': [{'x': i, 'y': 5}], 'hits': []} for i in range(6)]
    b.emit('place_ships', {'room_id': b.room, 'player_id': b.pid, 'ships': ships2})
    a.emit('rps_choice', {'room_id': a.room, 'player_id': a.pid, 'choice': 'rock'})
    b.emit('rps_choice', {'room_id': b.room, 'player_id': b.pid, 'choice': 'paper'})
    time.sleep(0.4)
    st = a.state()
    actor, other = (a, b) if st['current_attacker'] == a.pid else (b, a)
    check(st['current_attacker'] == actor.pid, '前置：测试方是先手（当前攻击者）', st['current_attacker'])
    return actor, other


def play(agent, name, targets=None):
    agent.emit('test_add_specific_magic_card',
               {'room_id': agent.room, 'player_id': agent.pid, 'card_name': name})
    time.sleep(0.2)
    resp = agent.emit('use_magic_card', {
        'room_id': agent.room, 'player_id': agent.pid,
        'card': {'name': name}, 'targets': targets or {}})
    time.sleep(1.2)
    return resp


def sink_one(actor, other):
    """真实打沉对方一艘单格船（越战越勇的前置）。"""
    st = actor.state()
    opp = st['players'][other.pid]
    singles = [s['positions'][0] for s in opp['ships'] if len(s['positions']) == 1]
    if not singles:
        return None
    x, y = singles[0]
    if st['current_phase'] != 'battle':
        actor.emit('enter_battle_phase', {'room_id': actor.room, 'player_id': actor.pid})
        # 阶段转换要先问对方"要不要响应"，等它的自动放弃走完（后台任务重放）
        time.sleep(1.2)
    resp = actor.emit('attack', {'room_id': actor.room, 'player_id': actor.pid, 'x': x, 'y': y})
    time.sleep(0.4)
    return (resp or {}).get('status'), (x, y)


def main():
    a, b = Agent('A'), Agent('B')
    try:
        actor, other = setup(a, b)

        # ---------------- V1 死者苏生：不满足条件 → 牌退回手牌 ----------------
        actor.log.clear()
        resp = play(actor, '死者苏生')
        hand = actor.hand
        check(resp and resp.get('status') == 'success', 'V1a 出牌请求被接受（失败发生在结算时）', resp)
        check('死者苏生' in hand, 'V1b 没有可复活的战舰时，牌退回手牌', hand)
        check(any('退回手牌' in t for t in actor.texts()), 'V1c 给出「已退回手牌」的明确播报',
              [t for t in actor.texts() if '死者苏生' in t])
        st = actor.state()
        srv_hand = st['players'][actor.pid]['magic_hand']
        check('死者苏生' in srv_hand, 'V1d 服务端手牌里也确实还有这张牌', srv_hand)

        # ---------------- V2 越战越勇：发动即 +1 ----------------
        sunk = sink_one(actor, other)
        check(sunk and sunk[0] == 'success', 'V2a 先真实击沉对方一艘战舰', sunk)
        before = actor.state()['attacks_remaining']
        resp = play(actor, '越战越勇')
        after = actor.state()['attacks_remaining']
        check(resp and resp.get('status') == 'success', 'V2b 越战越勇出牌成功', resp)
        check(after == before + 1, 'V2c 发动当场攻击次数 +1', {'before': before, 'after': after})
        ups = [d for e, d in actor.log if e == 'attacks_updated']
        check(any((d or {}).get('attacks_remaining') == before + 1 for d in ups),
              'V2d 广播了新的攻击次数', ups[-1] if ups else None)

        # ---------------- V3 冻结：播报只算活船 ----------------
        actor.emit('test_set_opponent_ships',
                   {'room_id': actor.room, 'player_id': actor.pid, 'ship_count': 6})
        time.sleep(0.3)
        st = actor.state()
        opp = st['players'][other.pid]
        # 取一个覆盖若干船的 3x3 区域：用第一艘船的位置当中心
        first = opp['ships'][0]['positions'][0]
        x1 = max(0, min(3, first[0] - 1))
        y1 = max(0, min(3, first[1] - 1))
        area = {'x1': x1, 'y1': y1, 'x2': x1 + 2, 'y2': y1 + 2}
        expected = 0
        for s in opp['ships']:
            dead = len(s['hits']) >= len(s['positions'])
            if dead:
                continue
            if any(area['x1'] <= p[0] <= area['x2'] and area['y1'] <= p[1] <= area['y2']
                   for p in s['positions']):
                expected += 1
        actor.log.clear()
        resp = play(actor, '冻结', {'target_area': area})
        check(resp and resp.get('status') == 'success', 'V3a 冻结发动成功', resp)
        # 效果文案在 chain_resolved 的 results 里（出牌 ack 只报"已加入连锁"）
        msg = ''
        for e, d in actor.log:
            if e != 'chain_resolved':
                continue
            for r in (d or {}).get('results', []):
                if (r.get('card') or {}).get('name') == '冻结':
                    msg = r.get('message', '')
        check(('冻结了%d艘战舰' % expected) in msg,
              'V3b 播报的船数 = 区域内【存活】战舰数', {'expected': expected, 'msg': msg})

        # ---------------- V4 回光返照：清对方打在我方棋盘的记录 ----------------
        # ⚠️ 「绝处逢生放置格」不在这里测：它需要"出牌 → 连锁结算 → 下发放置请求"，
        # 而本工具是【两个 python-socketio 客户端】，结算是在响应方那次请求里跑的，
        # 跨客户端 emit 会让响应方的 transport 掉线（实测旧代码 eb2b5b4 同样复现，
        # 属工具场景的产物、不是服务端缺陷）。那一条改由浏览器工具
        # `tools/last_stand_board_check.mjs` 第 4 节验证（真实页面 + 人机对手）。
        actor.log.clear()
        resp = play(actor, '回光返照')
        check(resp and resp.get('status') == 'success', 'V4a 回光返照发动成功', resp)
        boards = [d for e, d in actor.log if e == 'board_attacks_updated']
        check(bool(boards), 'V4b 重推了棋盘攻击记录（前端才画得干净）', len(boards))
        if boards:
            last = boards[-1]
            check(last.get('opponent_attacks') == [],
                  'V4c 对方打在我方棋盘的记录被清空', last.get('opponent_attacks'))
            check(len(last.get('my_attacks') or []) >= 1,
                  'V4d 我打在对方棋盘的记录【保留】（否则已探明的格子又能重打）',
                  len(last.get('my_attacks') or []))

        time.sleep(0.3)
        st = actor.state()
        check(st['players'][actor.pid]['remaining_ships'] == 0,
              'V4e 自己的棋盘确实被清空（等重新摆放）', st['players'][actor.pid]['remaining_ships'])
    finally:
        for x in (a, b):
            try:
                if x.sio.connected:
                    x.sio.disconnect()
            except Exception:
                pass

    bad = [label for ok, label in RESULTS if not ok]
    print('')
    print(('✗ %d 项未通过: %s' % (len(bad), ' | '.join(bad))) if bad else '✓ 全部通过')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
