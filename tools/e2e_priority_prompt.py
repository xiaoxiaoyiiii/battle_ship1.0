# -*- coding: utf-8 -*-
"""优先权询问（方案 D）真 socket 双客户端 E2E。

全部走真实事件协议（无单测桩），覆盖：

  1. A 进战斗阶段 → 手里有速阶3 的 B 收到 priority_request，且 A 的阶段【没被推进】
  2. B 点「取消」→ A 的阶段真正推进到 battle
  3. B 在窗口内打出速阶3 → 卡被消耗、生效，A 的阶段随后推进
  4. 对方不响应 → 10 秒倒计时到点自动放行（不会永久卡死）
  5. 「拒绝所有阶段转换时点」开关：勾上后不再询问，关掉后恢复
  6. 手上没有速阶3 也要问（作者裁定：要有选择权，哪怕只有取消按钮）
  7. 进结束阶段同样询问（且要先把攻击次数用完）
  8. 人机房不询问
  9. 反证：连锁窗口挂起时不弹优先权询问（连锁优先，避免双重弹窗）

用法：先带 ENABLE_TEST_EVENTS=1 启动服务，再 `python tools/e2e_priority_prompt.py`。
"""
import os
import sys
import time

import socketio

URL = os.environ.get('E2E_URL', 'http://127.0.0.1:5000')
WAIT = float(os.environ.get('E2E_WAIT', '16'))
PRIORITY_SECONDS = 10

problems = []


def check(ok, label, detail=None):
    print(('PASS  ' if ok else 'FAIL  ') + label +
          ('' if detail is None else '  ->  ' + repr(detail)))
    if not ok:
        problems.append(label)


class Agent:
    def __init__(self, name):
        self.name = name
        self.pid = None
        self.room = None
        self.sio = socketio.Client(reconnection=False)
        self.events = []          # 全部事件名（诊断用）
        self.priority_reqs = []
        self.chain_reqs = []
        self.errors = []

        @self.sio.on('*')
        def _catch_all(event, data=None):
            self.events.append(event)
            if event == 'priority_request':
                self.priority_reqs.append(data or {})
            elif event == 'chain_request':
                self.chain_reqs.append(data or {})
            elif event == 'error':
                self.errors.append(data)

    def connect(self):
        if not self.sio.connected:
            self.sio.connect(URL, transports=['polling'])

    @property
    def sid(self):
        return self.sio.sid

    def emit(self, event, data, timeout=6.0):
        box = {}

        def cb(resp):
            box['resp'] = resp

        self.sio.emit(event, data, callback=cb)
        deadline = time.time() + timeout
        while 'resp' not in box and time.time() < deadline:
            time.sleep(0.02)
        return box.get('resp')

    def wait_priority(self, timeout=WAIT):
        """等一条【新的】priority_request；超时返回 None。

        ⚠️ 事件可能在调用本函数之前就已经到达（服务端 emit 是同步投递的），
        所以不能只等"数量增加"——调用点一律先 clear()，这里以数量为准。
        """
        deadline = time.time() + timeout
        while not self.priority_reqs and time.time() < deadline:
            time.sleep(0.05)
        return self.priority_reqs[-1] if self.priority_reqs else None

    def clear(self):
        self.priority_reqs.clear()
        self.chain_reqs.clear()
        self.errors.clear()
        self.events.clear()


def call(cli, ev, data):
    return cli.emit(ev, data)


def state(agent):
    return agent.emit('test_get_game_state', {'room_id': agent.room})['game_state']


def setup_game(a, b, defender_speed3=()):
    """建房-加入-摆船-猜拳，返回 (attacker, defender, defender_pid)。

    注意：自定义房/匹配房里 players 的 key 就是 sid，`current_attacker`
    拿到的是 pid。attacker/defender 由服务端裁定，不能假设是 a 还是 b。
    """
    a.connect()
    b.connect()
    a.room = call(a, 'create_room', {'player_name': 'PR-A'})['room_id']
    b.room = a.room
    b.pid = call(b, 'join_room', {'room_id': a.room, 'player_name': 'PR-B'})['player_id']
    a.pid = next(k for k in state(a)['players'] if k != b.pid)

    ships = [{'positions': [{'x': i, 'y': i}], 'hits': []} for i in range(6)]
    call(a, 'place_ships', {'room_id': a.room, 'player_id': a.pid, 'ships': ships})
    ships2 = [{'positions': [{'x': i, 'y': 5 - i}], 'hits': []} for i in range(6)]
    call(b, 'place_ships', {'room_id': b.room, 'player_id': b.pid, 'ships': ships2})
    call(a, 'rps_choice', {'room_id': a.room, 'player_id': a.pid, 'choice': 'rock'})
    call(b, 'rps_choice', {'room_id': b.room, 'player_id': b.pid, 'choice': 'paper'})
    time.sleep(0.4)

    atk_pid = state(a)['current_attacker']
    atk, dfn = (a, b) if atk_pid == a.pid else (b, a)

    # 清空双方效果/手牌，再按需给对方发速阶3
    for who in (a, b):
        call(who, 'test_clear_all_effects', {'room_id': who.room})
    for name in defender_speed3:
        call(dfn, 'test_add_specific_magic_card',
             {'room_id': dfn.room, 'player_id': dfn.pid, 'card_name': name})
    time.sleep(0.3)
    a.clear()
    b.clear()
    return atk, dfn


def phase(agent):
    """阶段只能从服务器行为推断：本函数读的是 test_get_game_state 暴露的字段。"""
    return state(agent).get('current_phase')


def drain_attacks(atk, dfn):
    """把当前攻击者的攻击次数用光（进结束阶段的前置条件）。

    攻击次数默认 = 存活船数（6），随便打已有攻击过的格子会被后端拒绝，
    所以扫全盘、只打没打过的格子。
    """
    used = set()
    for _ in range(40):
        left = int(state(atk).get('attacks_remaining') or 0)
        if left <= 0:
            break
        for x in range(6):
            for y in range(6):
                if (x, y) in used:
                    continue
                used.add((x, y))
                r = atk.emit('attack',
                             {'room_id': atk.room, 'player_id': atk.pid, 'x': x, 'y': y})
                if r and r.get('status') == 'success':
                    break
            else:
                continue
            break
        else:
            break
    return state(atk).get('attacks_remaining')


def teardown(*agents):
    for ag in agents:
        try:
            ag.sio.disconnect()
        except Exception:
            pass


# ============================================================ 场景 1~2
print('--- 场景 1：对方有速阶3 → 进战斗阶段前弹询问，且阶段不推进 ---')
a, b = Agent('A'), Agent('B')
try:
    atk, dfn = setup_game(a, b, defender_speed3=['失灵！'])
    resp = call(atk, 'enter_battle_phase', {'room_id': atk.room, 'player_id': atk.pid})
    check(bool(resp and resp.get('awaiting_priority')), '进战斗阶段被挂起', resp)
    req = dfn.wait_priority(timeout=5)
    check(req is not None, '对方收到了 priority_request', dfn.events[-6:])
    if req:
        check(req.get('action') == 'enter_battle', 'action=enter_battle', req.get('action'))
        check(req.get('actor') == atk.pid, 'actor 是发起者', req.get('actor'))
        names = [c.get('name') for c in (req.get('speed3_cards') or [])]
        check('失灵！' in names, '列出了对方的速阶3', names)
        check(int(req.get('countdown') or 0) > 0, '带倒计时', req.get('countdown'))
    check(phase(atk) == 'preparation',
          '询问期间阶段【没有】被推进 —— 这就是为了修抢时点', phase(atk))

    print('--- 场景 2：对方点取消 → 阶段真正推进 ---')
    r = dfn.emit('priority_response',
                 {'room_id': dfn.room, 'player_id': dfn.pid, 'respond': False})
    check(r and r.get('status') == 'success', '取消被接受', r)
    time.sleep(0.8)
    check(phase(atk) == 'battle', '取消后阶段推进到 battle', phase(atk))
finally:
    teardown(a, b)

# ============================================================ 场景 3
print('--- 场景 3：窗口内打出速阶3 → 卡被消耗且阶段照常推进 ---')
a, b = Agent('A'), Agent('B')
try:
    atk, dfn = setup_game(a, b, defender_speed3=['加百列之光'])
    call(atk, 'enter_battle_phase', {'room_id': atk.room, 'player_id': atk.pid})
    check(dfn.wait_priority(timeout=5) is not None, '询问已发出')
    r = dfn.emit('priority_response', {
        'room_id': dfn.room, 'player_id': dfn.pid, 'respond': True,
        'card': {'name': '加百列之光'}, 'targets': [],
    })
    check(r and r.get('status') == 'success', '窗口内出速阶3 被接受', r)
    time.sleep(1.0)
    hand = state(dfn)['players'][dfn.pid].get('magic_hand') or []
    names = [c if isinstance(c, str) else c.get('name') for c in hand]
    check('加百列之光' not in names, '打出的卡离开了手牌', names)
    check(phase(atk) == 'battle', '打完后发起者的阶段照常推进', phase(atk))
finally:
    teardown(a, b)

# ============================================================ 场景 4
print('--- 场景 4：对方不响应 → 倒计时到点自动放行 ---')
a, b = Agent('A'), Agent('B')
try:
    atk, dfn = setup_game(a, b, defender_speed3=['失灵！'])
    t0 = time.time()
    call(atk, 'enter_battle_phase', {'room_id': atk.room, 'player_id': atk.pid})
    check(dfn.wait_priority(timeout=5) is not None, '询问已发出')
    deadline = time.time() + PRIORITY_SECONDS + 6
    while time.time() < deadline and phase(atk) != 'battle':
        time.sleep(0.3)
    dt = time.time() - t0
    check(phase(atk) == 'battle', '不响应时超时自动放行，不会永久卡死', round(dt, 1))
    check(dt >= PRIORITY_SECONDS - 2, '确实等满了窗口才放行（不是立刻）', round(dt, 1))
    check(dt <= PRIORITY_SECONDS + 5, '放行没有超出窗口太多', round(dt, 1))
finally:
    teardown(a, b)

# ============================================================ 场景 5
print('--- 场景 5：「拒绝所有阶段转换时点」开关 ---')
a, b = Agent('A'), Agent('B')
try:
    atk, dfn = setup_game(a, b, defender_speed3=['失灵！'])
    r = dfn.emit('set_decline_priority',
                 {'room_id': dfn.room, 'player_id': dfn.pid, 'decline': True})
    check(r and r.get('decline') is True, '开关可以单独打开', r)
    dfn.clear()
    resp = call(atk, 'enter_battle_phase', {'room_id': atk.room, 'player_id': atk.pid})
    check(dfn.wait_priority(timeout=3) is None, '开关打开后不再询问')
    check(not (resp and resp.get('awaiting_priority')), '阶段直接推进（返回值无 awaiting）', resp)
    time.sleep(0.6)
    check(phase(atk) == 'battle', '阶段确实到了 battle', phase(atk))

    dfn.clear()
    r = dfn.emit('set_decline_priority',
                 {'room_id': dfn.room, 'player_id': dfn.pid, 'decline': False})
    check(r and r.get('decline') is False, '开关可以关掉', r)
    drain_attacks(atk, dfn)
    call(atk, 'enter_end_phase', {'room_id': atk.room, 'player_id': atk.pid})
    check(dfn.wait_priority(timeout=5) is not None, '关掉开关后恢复询问')
    dfn.emit('priority_response', {'room_id': dfn.room, 'player_id': dfn.pid, 'respond': False})
    time.sleep(0.6)
    check(phase(atk) == 'end', '取消后进到 end', phase(atk))
finally:
    teardown(a, b)

# ============================================================ 场景 6
print('--- 场景 6：手上没有速阶3 也要问（只有取消按钮）---')
a, b = Agent('A'), Agent('B')
try:
    atk, dfn = setup_game(a, b, defender_speed3=())
    resp = call(atk, 'enter_battle_phase', {'room_id': atk.room, 'player_id': atk.pid})
    check(bool(resp and resp.get('awaiting_priority')), '没有速阶3 时仍然询问', resp)
    req = dfn.wait_priority(timeout=5)
    check(req is not None, '对方仍然收到 priority_request')
    if req:
        check((req.get('speed3_cards') or []) == [],
              'speed3_cards 为空列表（前端据此显示"没有速阶3"）', req.get('speed3_cards'))
    dfn.emit('priority_response', {'room_id': dfn.room, 'player_id': dfn.pid, 'respond': False})
    time.sleep(0.7)
    check(phase(atk) == 'battle', '取消后阶段推进', phase(atk))
finally:
    teardown(a, b)

# ============================================================ 场景 7
print('--- 场景 7：进结束阶段同样询问 ---')
a, b = Agent('A'), Agent('B')
try:
    atk, dfn = setup_game(a, b, defender_speed3=['失灵！'])
    call(atk, 'enter_battle_phase', {'room_id': atk.room, 'player_id': atk.pid})
    dfn.wait_priority(timeout=5)
    dfn.emit('priority_response', {'room_id': dfn.room, 'player_id': dfn.pid, 'respond': False})
    time.sleep(0.7)
    left = drain_attacks(atk, dfn)
    check(left in (0, None), '攻击次数已用完', left)
    dfn.clear()
    resp = call(atk, 'enter_end_phase', {'room_id': atk.room, 'player_id': atk.pid})
    check(bool(resp and resp.get('awaiting_priority')), '进结束阶段被挂起', resp)
    req = dfn.wait_priority(timeout=5)
    check(req is not None and req.get('action') == 'enter_end',
          'action=enter_end', req and req.get('action'))
    dfn.emit('priority_response', {'room_id': dfn.room, 'player_id': dfn.pid, 'respond': False})
    time.sleep(0.7)
    check(phase(atk) == 'end', '取消后进到 end', phase(atk))
finally:
    teardown(a, b)

# ============================================================ 场景 8
print('--- 场景 8：人机房不询问 ---')
ai = Agent('AI')
try:
    ai.connect()
    r = call(ai, 'create_ai_room', {'player_name': 'PR-AI', 'difficulty': 'easy'})
    check(bool(r and r.get('room_id')), '建人机房成功', r)
    ai.room = r['room_id']
    # 与前端 aiMatch() 一致：create_ai_room 只预置 AI 座位，真人还要 join_room 才入座
    jr = call(ai, 'join_room', {'room_id': ai.room, 'player_name': 'PR-AI'})
    check(jr and jr.get('status') == 'success', '真人 join_room 成功', jr)
    ai.pid = jr['player_id']
    st = state(ai)
    check(ai.pid in st['players'], '真人座位已就位', list(st['players']))
    ships = [{'positions': [{'x': i, 'y': i}], 'hits': []} for i in range(6)]
    r = call(ai, 'place_ships', {'room_id': ai.room, 'player_id': ai.pid, 'ships': ships})
    check(r and r.get('status') == 'success', '摆船成功', r)
    # AI 会自动出拳；真人也要出，才知道谁先手。
    # ⚠️ 可能平局（服务端会清空重来），所以循环重出直到分出先手。
    for _ in range(10):
        call(ai, 'rps_choice', {'room_id': ai.room, 'player_id': ai.pid, 'choice': 'rock'})
        time.sleep(0.9)
        if state(ai).get('current_attacker'):
            break
    st = state(ai)
    atk_pid = st.get('current_attacker')
    check(bool(atk_pid), '猜拳已分出先手（否则无法进战斗阶段）', atk_pid)
    # 人机房的关键断言：无论谁先手，推进阶段都不该弹优先权询问。
    # 若 AI 先手，就等它自己推进（AI 会 enter_battle_phase），再验真人这边没弹窗。
    ai.clear()
    if atk_pid == ai.pid:
        resp = call(ai, 'enter_battle_phase', {'room_id': ai.room, 'player_id': ai.pid})
        check(not (resp and resp.get('awaiting_priority')),
              '人机房不弹优先权询问（AI 不会响应）', resp)
        time.sleep(0.6)
        check(phase(ai) == 'battle', '阶段直接推进', (phase(ai), resp))
    else:
        # AI 先手：等它推进阶段
        deadline = time.time() + 8
        while time.time() < deadline and phase(ai) != 'battle':
            time.sleep(0.3)
        check(phase(ai) == 'battle', 'AI 自行推进到 battle（未被优先权询问卡住）', phase(ai))
    check(ai.wait_priority(timeout=2) is None, '真人全程没收到 priority_request')
except Exception as exc:
    check(False, '人机房场景执行失败', repr(exc))
finally:
    teardown(ai)

# ============================================================ 场景 9
print('--- 场景 9（反证）：连锁窗口挂起时不弹优先权询问 ---')
a, b = Agent('A'), Agent('B')
try:
    atk, dfn = setup_game(a, b, defender_speed3=['失灵！'])
    # 攻击者打出一张会开连锁窗口的速阶3卡（失灵！是速阶3，对方可以康）
    call(atk, 'test_add_specific_magic_card',
         {'room_id': atk.room, 'player_id': atk.pid, 'card_name': '失灵！'})
    time.sleep(0.3)
    call(atk, 'use_magic_card', {
        'room_id': atk.room, 'player_id': atk.pid,
        'card': {'name': '失灵！'}, 'targets': [],
    })
    time.sleep(0.8)
    # 确认连锁窗口真的开着（否则这个反证是空跑）
    st = state(atk)
    check(bool(st.get('chain') or st.get('chain_window')),
          '连锁窗口确实挂起了（前置条件成立）',
          {'chain': st.get('chain'), 'chain_window': st.get('chain_window')})
    dfn.clear()
    resp = call(atk, 'enter_battle_phase', {'room_id': atk.room, 'player_id': atk.pid})
    check(dfn.wait_priority(timeout=2.5) is None,
          '有连锁挂起时不弹优先权询问（连锁优先，避免双重弹窗）', resp)
finally:
    teardown(a, b)

print('')
if problems:
    print('✗ %d 项未通过：' % len(problems))
    for p in problems:
        print('   · ' + p)
    sys.exit(1)
print('✓ 全部通过')
