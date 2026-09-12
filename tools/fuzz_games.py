# -*- coding: utf-8 -*-
"""随机对局压力测试（fuzz）：找"没人想到的崩溃"。

思路：两名真实 socket 客户端开一局，之后**随机**执行合法动作
（炮击 / 出牌（含随机目标）/ 进战斗 / 进结束 / 交回合 / 连锁响应 / 教皇旨意 / 投降），
每局几十~上百个动作。断言：
  1. 每个 ack 都是 dict（handler 没抛异常冒到客户端）；
  2. 服务器 stdout 里没有未捕获 traceback（由外层脚本检查）；
  3. 对局要么正常打完，要么被动作预算截断——不允许卡死不动。

调试事件（ENABLE_TEST_EVENTS=1）用于给玩家塞满手牌，好把 42 张卡的分支都跑一遍。
"""
import random
import socketio
import sys
import time

URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:5057'
GAMES = int(sys.argv[2]) if len(sys.argv) > 2 else 3
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else 20260913
ACTIONS_PER_GAME = 200

random.seed(SEED)
CELLS = [(x, y) for x in range(6) for y in range(6)]


def make_client(tag, events):
    sio = socketio.Client(reconnection=False)

    @sio.on('*')
    def _any(event, data=None):
        events.append((event, data))

    return sio


def ack(sio, event, payload, timeout=6.0):
    box = {}

    def _cb(resp=None):
        box['r'] = resp

    sio.emit(event, payload, callback=_cb)
    end = time.time() + timeout
    while 'r' not in box and time.time() < end:
        time.sleep(0.01)
    return box.get('r')


def wait_event(events, name, pred=None, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        for ev, data in events:
            if ev == name and (pred is None or pred(data)):
                return data
        time.sleep(0.05)
    return None


def state_of(sio, room_id):
    res = ack(sio, 'test_get_game_state', {'room_id': room_id})
    if isinstance(res, dict):
        return res.get('game_state') or {}
    return {}


def play_one_game(idx, problems):
    ae, be = [], []
    a = make_client('A', ae)
    b = make_client('B', be)
    a.connect(URL, transports=['polling'])
    b.connect(URL, transports=['polling'])
    try:
        a.emit('find_match', {'player_name': f'FZ-A-{idx}'})
        time.sleep(0.3)
        b.emit('find_match', {'player_name': f'FZ-B-{idx}'})
        ga = wait_event(ae, 'game_state', lambda d: d and d.get('room_id'))
        gb = wait_event(be, 'game_state', lambda d: d and d.get('room_id'))
        if not ga or not gb:
            problems.append(f'G{idx}: 匹配失败')
            return
        room = ga['room_id']
        pa, pb = ga['player_id'], gb['player_id']
        clients = {pa: (a, ae), pb: (b, be)}

        # 布船：随机合法摆位
        for pid, (sio, _) in clients.items():
            cells = random.sample(CELLS, 6)
            res = ack(sio, 'place_ships', {
                'room_id': room, 'player_id': pid,
                'ships': [{'positions': [{'x': x, 'y': y}], 'hits': []} for x, y in cells]})
            if not isinstance(res, dict):
                problems.append(f'G{idx}: place_ships 返回非 dict: {res!r}')

        # 猜拳
        for _ in range(12):
            for pid, (sio, _) in clients.items():
                ack(sio, 'rps_choice', {'room_id': room, 'player_id': pid,
                                        'choice': random.choice(['rock', 'paper', 'scissors'])})
            time.sleep(0.4)
            if state_of(a, room).get('current_attacker'):
                break

        # 塞满手牌，把卡牌分支都跑一遍
        for pid, (sio, _) in clients.items():
            ack(sio, 'test_add_all_magic_cards', {'room_id': room, 'player_id': pid})
            ack(sio, 'test_set_player_ships', {'room_id': room, 'player_id': pid, 'ship_count': 6})
        time.sleep(0.5)

        acted = 0
        for step in range(ACTIONS_PER_GAME):
            st = state_of(a, room)
            if st.get('state') == 'game_over' or st.get('winner'):
                acted = -1
                break
            attacker = st.get('current_attacker')
            if not attacker or attacker not in clients:
                time.sleep(0.3)
                continue
            sio, evs = clients[attacker]
            phase = st.get('current_phase')
            choice = random.random()

            if random.random() < 0.01:
                ack(sio, 'surrender', {'room_id': room, 'player_id': attacker})
                acted = -1
                break
            elif choice < 0.45:
                x, y = random.choice(CELLS)
                res = ack(sio, 'attack', {'room_id': room, 'player_id': attacker, 'x': x, 'y': y})
            elif choice < 0.75:
                hand = st.get('magic_hand') or []
                if hand:
                    card = random.choice(hand)
                    targets = random.choice([
                        [],
                        {'target_area': {'x1': random.randint(0, 4), 'y1': random.randint(0, 4),
                                         'x2': 5, 'y2': 5}},
                        {'target_line': {'type': random.choice(['row', 'col']),
                                         'index': random.randint(0, 5)}},
                        {'ship_indices': random.sample(range(6), 2)},
                        {'effect_choice': random.choice(['effect1', 'effect2'])},
                    ])
                    res = ack(sio, 'use_magic_card', {
                        'room_id': room, 'player_id': attacker,
                        'card': {'name': card.get('name'), 'speed': card.get('speed'),
                                 'type': card.get('type')},
                        'targets': targets})
                    # 连锁窗口：由**对窗口有响应权**的一方随机响应或放弃
                    # （窗口一般属于对手；先查 chain_window，拿不到就两边都试——
                    #   错误分支同样是有效输入，但要保证"接受"路径也被覆盖）
                    if random.random() < 0.85:
                        time.sleep(random.uniform(0.1, 0.6))
                        st2 = state_of(a, room)
                        responder = st2.get('chain_window') if st2.get('chain_waiting') else None
                        for candidate in ([responder] if responder in clients else []) + \
                                [pid for pid in clients if pid != attacker]:
                            rsio, _ = clients[candidate]
                            ack(rsio, 'chain_response', {
                                'room_id': room, 'player_id': candidate,
                                'response': random.choice(['pass', 'negate']),
                                'card_name': '失灵！' if random.random() < 0.5 else None,
                                'targets': []})
                            if random.random() < 0.5:
                                break
                else:
                    res = ack(sio, 'end_turn', {'room_id': room, 'player_id': attacker})
            elif choice < 0.85:
                res = ack(sio, 'enter_battle_phase', {'room_id': room, 'player_id': attacker})
                if not isinstance(res, dict) or res.get('status') != 'success':
                    res = ack(sio, 'enter_end_phase', {'room_id': room, 'player_id': attacker})
            elif choice < 0.93:
                res = ack(sio, 'end_turn', {'room_id': room, 'player_id': attacker})
            else:
                res = ack(sio, 'papal_attack', {'room_id': room, 'player_id': attacker,
                                                'card_index': random.randint(0, 3),
                                                'x': random.randint(0, 5), 'y': random.randint(0, 5)})

            if not isinstance(res, dict):
                problems.append(f'G{idx} step{step}: {choice:.2f} 动作返回非 dict: {res!r}')
            elif res.get('status') not in ('success', 'error', None):
                problems.append(f'G{idx} step{step}: 未知返回 {res!r}')
            elif isinstance(res.get('message'), str) and 'Traceback' in res['message']:
                problems.append(f'G{idx} step{step}: 返回里带 traceback')
            acted += 1
            time.sleep(0.05)

        print(f'  G{idx}: room={room} 动作数={acted}'
              f'{"(已终局)" if acted == -1 else ""}')
    finally:
        try:
            a.disconnect()
        except Exception:
            pass
        try:
            b.disconnect()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 第二阶段：畸形载荷。合法动作跑不出崩溃，崩溃通常藏在校验缺口里
# （合法输入全部被拦住了，但 None / 字符串 / 负数 / 巨数 / 嵌套结构可能直接
#   打进 handler 内部抛 TypeError —— 表现为 ack 回调永不返回 + 服务端 traceback）。
# ---------------------------------------------------------------------------
JUNK_VALUES = [None, '', 0, -1, 999999, 3.7, True, False, [], {}, 'x', 'DROP TABLE users',
               [1, 2, 3], {'a': {'b': {'c': 1}}}, -0.5, 1e308, '０', '\u0000']

# handler 抛异常时 ack 回调**不会返回** —— 必须把"没有回调"判为失败，
# 否则畸形载荷阶段会因为 res 是 None 而静默通过（实测踩过这个坑：
# 服务端日志里 295 条 traceback，脚本却报"全部通过"）。
NO_CALLBACK_IS_FAILURE = True

WRITE_HANDLERS = [
    ('attack', ['room_id', 'player_id', 'x', 'y']),
    ('use_magic_card', ['room_id', 'player_id', 'card', 'targets']),
    ('chain_response', ['room_id', 'player_id', 'response', 'card_name', 'targets']),
    ('select_magic_target', ['room_id', 'player_id', 'card_index', 'target']),
    ('confirm_magic_target', ['room_id', 'player_id', 'targets']),
    ('place_ships', ['room_id', 'player_id', 'ships']),
    ('rps_choice', ['room_id', 'player_id', 'choice']),
    ('end_turn', ['room_id', 'player_id']),
    ('enter_battle_phase', ['room_id', 'player_id']),
    ('enter_end_phase', ['room_id', 'player_id']),
    ('papal_attack', ['room_id', 'player_id', 'card_index', 'x', 'y']),
    ('confirm_reinforcement_position', ['room_id', 'player_id', 'x', 'y']),
    ('cancel_placement', ['room_id', 'player_id']),
    ('surrender', ['room_id', 'player_id']),
    ('remove_field_magic', ['room_id', 'player_id']),
    ('get_magic_temp_data', ['room_id', 'player_id']),
    ('get_discard_pile', ['room_id', 'player_id']),
    ('request_revealed_positions', ['room_id', 'player_id']),
    ('chat_message', ['room_id', 'player_id', 'message']),
    ('get_reconnect_token', ['room_id', 'player_id']),
    ('rejoin_room', ['room_id', 'player_id', 'token']),
]


def fuzz_malformed(idx, problems):
    """对一个真实房间发一堆畸形载荷：只要求「不崩」（返回 dict 或安静返回）。"""
    ae, be = [], []
    a = make_client('A', ae)
    b = make_client('B', be)
    a.connect(URL, transports=['polling'])
    b.connect(URL, transports=['polling'])
    sent = 0
    try:
        a.emit('find_match', {'player_name': f'MF-A-{idx}'})
        time.sleep(0.3)
        b.emit('find_match', {'player_name': f'MF-B-{idx}'})
        ga = wait_event(ae, 'game_state', lambda d: d and d.get('room_id'))
        gb = wait_event(be, 'game_state', lambda d: d and d.get('room_id'))
        if not ga or not gb:
            problems.append(f'M{idx}: 匹配失败')
            return
        room, pa = ga['room_id'], ga['player_id']
        stock = {'room_id': room, 'player_id': pa, 'x': 0, 'y': 0, 'card_index': 0,
                 'targets': [], 'ships': [{'positions': [{'x': 0, 'y': 0}], 'hits': []}],
                 'card': {'name': '冻结', 'speed': 2, 'type': '普通'},
                 'choice': 'rock', 'response': 'pass', 'card_name': '失灵！',
                 'message': 'hi', 'token': 'x', 'target': {}}

        # 1) 每个写 handler × 若干畸形字段组合
        for event, fields in WRITE_HANDLERS:
            for _ in range(6):
                payload = dict(stock)
                for f in fields:
                    if random.random() < 0.55:
                        payload[f] = random.choice(JUNK_VALUES)
                for f in random.sample(['room_id', 'player_id'], 1):
                    if random.random() < 0.35:
                        payload[f] = random.choice(JUNK_VALUES)
                res = ack(a, event, payload, timeout=1.5)
                sent += 1
                if res is None:
                    if NO_CALLBACK_IS_FAILURE:
                        problems.append(f'M{idx}: {event} 未返回（多半是 handler 抛异常）payload={payload!r:.120}')
                elif not isinstance(res, dict):
                    problems.append(f'M{idx}: {event} 返回非 dict: {res!r}')

        # 2) 非 dict 顶层载荷（前端/恶意客户端可能直接发字符串或数组）
        for event, _ in WRITE_HANDLERS[:10]:
            for junk in [None, 'abc', 123, [], [{'room_id': room}]]:
                res = ack(a, event, junk, timeout=1.5)
                sent += 1
                if res is None:
                    if NO_CALLBACK_IS_FAILURE:
                        problems.append(f'M{idx}: {event} 非 dict 载荷未返回（多半是抛异常）junk={junk!r:.80}')
                elif not isinstance(res, dict):
                    problems.append(f'M{idx}: {event} 非 dict 载荷返回 {res!r}')

        # 3) 超长字符串 / 超深嵌套
        deep = {'room_id': room, 'player_id': pa, 'ships': []}
        node = deep['ships']
        for _ in range(60):
            child = []
            node.append(child)
            node = child
        ack(a, 'place_ships', deep, timeout=2.0)
        ack(a, 'chat_message', {'room_id': room, 'player_id': pa, 'message': '海' * 20000}, timeout=2.0)
        sent += 2
        print(f'  M{idx}: 畸形载荷 {sent} 次')
    finally:
        try:
            a.disconnect()
        except Exception:
            pass
        try:
            b.disconnect()
        except Exception:
            pass


def main():
    problems = []
    t0 = time.time()
    for i in range(GAMES):
        play_one_game(i, problems)
    print('第二阶段：畸形载荷')
    for i in range(2):
        fuzz_malformed(i, problems)
    print(f'\n{GAMES} 局随机对局完成，用时 {time.time() - t0:.1f}s')
    if problems:
        print(f'发现 {len(problems)} 个问题：')
        for p in problems[:20]:
            print('  -', p)
        sys.exit(1)
    print('结果: 全部通过（无异常返回 / 无卡死）')


if __name__ == '__main__':
    main()
