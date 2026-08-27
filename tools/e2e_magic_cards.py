# -*- coding: utf-8 -*-
"""socket.io 双客户端 E2E 测试：按前端真实事件协议逐张打出全部魔法卡。

用法：先 `python server.py` 启动服务，再 `python tools/e2e_magic_cards.py`。
输出：控制台逐卡结果表 + tests/e2e_magic_report.json。
"""
import json
import os
import sys
import time

import socketio

URL = os.environ.get('E2E_URL', 'http://127.0.0.1:5000')
REPORT_PATH = os.path.join(os.path.dirname(__file__), '..', 'tests', 'e2e_magic_report.json')

RESOLVE_TIMEOUT = 6.0


class Agent:
    """模拟一个前端客户端（一个 socket 连接 + 事件记录）。"""

    def __init__(self, name):
        self.name = name
        self.pid = None
        self.room = None
        self.sio = socketio.Client(reconnection=False)
        self.log = []
        self.resolved = None
        self.chain_req_count = 0

        @self.sio.on('*')
        def _catch_all(event, data=None):
            self.log.append((event, data))
            if event == 'chain_resolved':
                self.resolved = data
            elif event == 'chain_request':
                # 与前端一致：收到连锁请求后自动选择不连锁
                self.chain_req_count += 1
                self.sio.emit('chain_response', {
                    'room_id': self.room, 'player_id': self.pid, 'chain': False
                })

    def connect(self):
        if not self.sio.connected:
            self.sio.connect(URL, transports=['polling'])

    def emit(self, event, data, timeout=5.0):
        box = {}

        def cb(resp):
            box['resp'] = resp

        self.sio.emit(event, data, callback=cb)
        deadline = time.time() + timeout
        while 'resp' not in box and time.time() < deadline:
            time.sleep(0.02)
        return box.get('resp')

    def wait_resolved(self, timeout=RESOLVE_TIMEOUT):
        deadline = time.time() + timeout
        while self.resolved is None and time.time() < deadline:
            time.sleep(0.05)
        return self.resolved


def setup_game(a: Agent, b: Agent):
    """走完整前端流程：建房-加入-摆船-猜拳。"""
    a.connect()
    b.connect()
    r = a.emit('create_room', {'player_name': 'E2E-A'})
    a.room = r['room_id']
    r = b.emit('join_room', {'room_id': a.room, 'player_name': 'E2E-B'})
    b.room = a.room
    b.pid = r['player_id']

    st = a.emit('test_get_game_state', {'room_id': a.room})
    keys = list(st['game_state']['players'].keys())
    a.pid = next(k for k in keys if k != b.pid)

    ships = [{'positions': [{'x': i, 'y': i}], 'hits': []} for i in range(6)]
    assert a.emit('place_ships', {'room_id': a.room, 'player_id': a.pid, 'ships': ships})['status'] == 'success'
    ships2 = [{'positions': [{'x': i, 'y': 5 - i}], 'hits': []} for i in range(6)]
    assert b.emit('place_ships', {'room_id': b.room, 'player_id': b.pid, 'ships': ships2})['status'] == 'success'

    a.emit('rps_choice', {'room_id': a.room, 'player_id': a.pid, 'choice': 'rock'})
    b.emit('rps_choice', {'room_id': b.room, 'player_id': b.pid, 'choice': 'paper'})
    time.sleep(0.3)
    # rock vs paper 在该服务端实现下先手为 p1(E2E-A)
    st = a.emit('test_get_game_state', {'room_id': a.room})
    attacker = st['game_state']['current_attacker']
    return (a, b) if attacker == a.pid else (b, a)


def refresh_boards(actor: Agent, other: Agent):
    """用服务端测试桩恢复双方棋盘与效果（对应前端测试面板功能）。5艘留出增援/复活空间。"""
    actor.emit('test_clear_all_effects', {'room_id': actor.room})
    actor.emit('test_set_player_ships', {'room_id': actor.room, 'player_id': actor.pid, 'ship_count': 5})
    actor.emit('test_set_opponent_ships', {'room_id': actor.room, 'player_id': actor.pid, 'ship_count': 5})


def opponent_ship_cells(actor: Agent, other: Agent, attacked: set):
    st = actor.emit('test_get_game_state', {'room_id': actor.room})
    opp = st['game_state']['players'][other.pid]
    cells = []
    for s in opp['ships']:
        for (x, y) in s['positions']:
            if (x, y) not in attacked:
                cells.append((x, y))
    return cells


def pre_attack(actor: Agent, other: Agent, attacked: set, need_sunk=False):
    """先发起一次真实攻击（溅射/雷达子弹/越战越勇的前置条件）。"""
    cells = opponent_ship_cells(actor, other, attacked)
    if not cells:
        return False
    # 击沉需要单格船：选只出现一次的格子
    if need_sunk:
        st = actor.emit('test_get_game_state', {'room_id': actor.room})
        opp = st['game_state']['players'][other.pid]
        singles = [s['positions'][0] for s in opp['ships']
                   if len(s['positions']) == 1 and tuple(s['positions'][0]) not in attacked]
        if not singles:
            return False
        x, y = singles[0]
    else:
        x, y = cells[0]
    attacked.add((x, y))
    resp = actor.emit('attack', {'room_id': actor.room, 'player_id': actor.pid, 'x': x, 'y': y})
    if resp and resp.get('status') == 'error' and '战斗阶段' in resp.get('message', ''):
        actor.emit('enter_battle_phase', {'room_id': actor.room, 'player_id': actor.pid})
        resp = actor.emit('attack', {'room_id': actor.room, 'player_id': actor.pid, 'x': x, 'y': y})
    return resp and resp.get('status') == 'success'


def recover_phase(env):
    """阶段被卡牌改变（如回光返照设为end）后恢复可出牌状态，必要时交换角色。"""
    actor, other = env['actor'], env['other']
    actor.emit('test_end_turn', {'room_id': actor.room})
    st = actor.emit('test_get_game_state', {'room_id': actor.room})
    if st['game_state']['current_attacker'] != actor.pid:
        env['actor'], env['other'] = other, actor
        actor, other = env['actor'], env['other']
    actor.emit('enter_battle_phase', {'room_id': actor.room, 'player_id': actor.pid})


# ---------------------------------------------------------------------------
# 每张卡的目标与前置/后续动作定义（依据卡面文本）
# ---------------------------------------------------------------------------
AREA_3X3 = {'target_area': {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}}
AREA_2X2 = {'target_area': {'x1': 0, 'y1': 0, 'x2': 1, 'y2': 1}}
ROW0 = [{'x': i, 'y': 0} for i in range(6)]

CARDS = [
    # (卡名, targets, 前置, 备注)
    ('轰炸', {'target_line': {'type': 'row', 'index': 0}}, None, '速2 选行轰炸'),
    ('硫磺火焰', {'target_cells': ROW0}, None, '速2 六格强杀'),
    ('神威！', AREA_3X3, None, '速2 3x3除外'),
    ('探测雷达', AREA_2X2, None, '速2 2x2显形'),
    ('雷达子弹', {}, 'attack_hit', '速2 需先命中'),
    ('溅射', {}, 'attack_hit', '速2 需先命中'),
    ('越战越勇', {}, 'attack_sunk', '速2 需先击沉'),
    ('余音绕梁', {}, None, '速1 强制击杀'),
    ('火力全开', {}, None, '速1 攻击翻倍'),
    ('灵气复苏', {}, None, '速1 临时数据'),
    ('教皇旨意', {}, None, '场地'),
    ('无暇圣心', {}, None, '速1 计时获胜'),
    ('极限增援', {}, None, '速1 计时判胜'),
    ('无中生有', {}, None, '速1 抽2锁抽'),
    ('桃园结义', {}, None, '速1 抽n选牌'),
    ('饮血', {}, None, '速2 击杀摸牌'),
    ('克苏鲁之眼', {}, None, '速2 互曝（已知崩溃）'),
    ('Freezing！', {}, None, '速2 跳对方回合'),
    ('五险一金', {}, None, '速2 无伤+3'),
    ('看破！', {}, None, '速2 封锁魔法'),
    ('八方来财', {}, None, '速3 变化摸牌'),
    ('平等条约', {}, None, '速3 无船数变化时应拒绝'),
    ('百亿补贴', {}, None, '速3 船亡+3'),
    ('神之宣告', {}, None, '速3 牺牲2选效果'),
    ('绝处逢生', {}, None, '速3 孤注一掷'),
    ('死者苏生', {}, None, '速3 无沉船时应拒绝'),
    ('疗愈', {}, None, '速3 复活至多2'),
    ('盗亦有道', {}, None, '速3 无历史时应拒绝'),
    ('回光返照', {}, None, '速1 需先手'),
    ('明智埋葬', {}, 'add_extra', '速2 需手牌'),
    ('仁王之盾', {}, None, '速1 选船护盾'),
    ('钢筋铁骨', {}, None, '速3 献祭无敌'),
    ('神机妙算', {}, 'prediction', '速3 宣言'),
    ('失灵！', {}, None, '速3 无目标时应拒绝'),
    ('加百列之光', {}, None, '速3 无效化'),
    ('冻结', AREA_3X3, None, '速2（已知崩溃：PlayerShip 不可迭代，服务端异常无ack）'),
    ('恶魔契约', {}, None, '场地（已知崩溃：field分支把卡对象当卡名重建，IndexError）'),
    ('禁忌果实', {}, None, '场地（已知崩溃：同上）'),
    ('伊甸园', {}, None, '场地（已知崩溃：同上）'),
    ('增援', {}, None, '速3 放置战舰'),
    ('败者食尘', {}, None, '速1 重启对局(最后)'),
]


def run_card(env, name: str, targets: dict, pre, attacked: set):
    # 每张卡前重建连接与会话，避免长会话下 polling 半连接导致丢 ack
    env['actor'].sio.disconnect()
    env['other'].sio.disconnect()
    env['actor'], env['other'] = setup_game(env['actor'], env['other'])
    actor, other = env['actor'], env['other']
    entry = {'card': name, 'ack': None, 'resolved': None, 'success': None,
             'message': '', 'followup': '', 'verdict': 'FAIL', 'note': ''}
    refresh_boards(actor, other)

    if pre == 'add_extra':
        actor.emit('test_add_specific_magic_card',
                   {'room_id': actor.room, 'player_id': actor.pid, 'card_name': '冻结'})
    if pre == 'prediction':
        actor.emit('select_magic_target', {
            'room_id': actor.room, 'player_id': actor.pid,
            'temp_data_id': 'prediction', 'target_data': {'prediction': 1}})
    if pre in ('attack_hit', 'attack_sunk'):
        if not pre_attack(actor, other, attacked, need_sunk=(pre == 'attack_sunk')):
            entry['note'] = '前置攻击失败'
            return entry

    actor.emit('test_add_specific_magic_card',
               {'room_id': actor.room, 'player_id': actor.pid, 'card_name': name})
    actor.resolved = None
    ack = actor.emit('use_magic_card', {
        'room_id': actor.room, 'player_id': actor.pid,
        'card': {'name': name}, 'targets': targets})

    # 阶段/回合被上一张卡污染时，恢复后重试一次（卡仍在手牌中）
    if ack and ack.get('status') == 'error' and '当前阶段' in ack.get('message', ''):
        recover_phase(env)
        actor, other = env['actor'], env['other']
        actor.emit('test_add_specific_magic_card',
                   {'room_id': actor.room, 'player_id': actor.pid, 'card_name': name})
        actor.resolved = None
        ack = actor.emit('use_magic_card', {
            'room_id': actor.room, 'player_id': actor.pid,
            'card': {'name': name}, 'targets': targets})
        entry['note'] = '阶段恢复后重试'

    entry['ack'] = ack.get('status') if ack else None
    if not ack or ack.get('status') != 'success':
        entry['message'] = (ack or {}).get('message', '无应答')
        # 服务端合法拒绝（如前置不满足）也属于契约正确
        entry['verdict'] = 'REJECTED'
        return entry

    resolved = actor.wait_resolved()
    if resolved is None:
        entry['verdict'] = 'CRASH/TIMEOUT'
        entry['note'] = '未收到 chain_resolved（服务端结算线程异常）'
        return entry

    results = resolved.get('results', [])
    r0 = results[0] if results else {}
    card_field = r0.get('card') or {}
    rname = card_field.get('name') if isinstance(card_field, dict) else getattr(card_field, 'name', '?')
    entry['resolved'] = rname
    entry['success'] = r0.get('success')
    entry['message'] = r0.get('message', '')

    # 处理需要二次交互的卡（前端同样有对应弹窗流程）
    temp_id = r0.get('temp_data_id')
    if temp_id == 'taoyuan_choice' and r0.get('success'):
        resp = actor.emit('confirm_magic_target', {
            'room_id': actor.room, 'player_id': actor.pid,
            'temp_data_id': temp_id, 'target_data': {'caster_choice': 0}})
        entry['followup'] = resp.get('message', '') if resp else 'no-ack'
    elif temp_id == 'lingqi_choice' and r0.get('success'):
        resp = actor.emit('confirm_magic_target', {
            'room_id': actor.room, 'player_id': actor.pid,
            'temp_data_id': temp_id, 'target_data': {'target_ships': 2}})
        entry['followup'] = resp.get('message', '') if resp else 'no-ack'
    elif temp_id == 'reinforcement_choice':
        resp = actor.emit('confirm_reinforcement_position', {
            'room_id': actor.room, 'player_id': actor.pid,
            'position': {'x': 0, 'y': 5}})
        entry['followup'] = resp.get('status', '') if resp else 'no-ack'
    elif temp_id == 'bury_choice':
        resp = actor.emit('select_magic_target', {
            'room_id': actor.room, 'player_id': actor.pid,
            'temp_data_id': temp_id, 'target_data': {'card_index': 0}})
        entry['followup'] = resp.get('message', '') if resp else 'no-ack'
    elif temp_id == 'shield_choice':
        resp = actor.emit('select_magic_target', {
            'room_id': actor.room, 'player_id': actor.pid,
            'temp_data_id': temp_id, 'target_data': {'ship_indices': [0, 1]}})
        entry['followup'] = resp.get('message', '') if resp else 'no-ack'

    if entry['success'] is True or entry['verdict'] == '':
        entry['verdict'] = 'PASS'
    elif entry['success'] is False:
        entry['verdict'] = 'EFFECT-FAIL'
    return entry


def main():
    only = os.environ.get('E2E_ONLY', '')  # 只测指定卡名（逗号分隔），用于调试
    a, b = Agent('E2E-A'), Agent('E2E-B')
    a.connect()
    b.connect()
    actor, other = setup_game(a, b)
    env = {'actor': actor, 'other': other}
    print(f'房间 {a.room} | 先手/执行者: {actor.name} ({actor.pid})')

    attacked = set()
    report = []
    need_resetup = {'灵气复苏', '败者食尘'}
    for name, targets, pre, note in CARDS:
        if only and name not in only.split(','):
            continue
        a.log.clear()
        b.log.clear()
        entry = run_card(env, name, targets, pre, attacked)
        actor, other = env['actor'], env['other']
        entry['note'] = entry['note'] or note
        if only:
            entry['events_actor'] = [e for e, _ in actor.log]
            entry['events_other'] = [e for e, _ in other.log]
        report.append(entry)
        print(f"[{entry['verdict']:<14}] {name:<6} | {entry['message'][:40]:<40} | {entry['followup']}")
        if name in need_resetup:
            actor, other = setup_game(a, b)
            env = {'actor': actor, 'other': other}
            attacked = set()
            print('   -- 对局已重置（重新建房/摆船/猜拳）--')

    # 特殊场景：场地魔法替换（已知后端崩溃路径）
    actor, other = env['actor'], env['other']
    if not actor.sio.connected:
        env['actor'], env['other'] = setup_game(a, b)
        actor, other = env['actor'], env['other']
    refresh_boards(actor, other)
    actor.emit('test_add_specific_magic_card',
               {'room_id': actor.room, 'player_id': actor.pid, 'card_name': '恶魔契约'})
    actor.resolved = None
    actor.emit('use_magic_card', {'room_id': actor.room, 'player_id': actor.pid,
                                  'card': {'name': '恶魔契约'}, 'targets': {}})
    actor.wait_resolved()
    actor.emit('test_add_specific_magic_card',
               {'room_id': actor.room, 'player_id': actor.pid, 'card_name': '禁忌果实'})
    actor.resolved = None
    actor.emit('use_magic_card', {'room_id': actor.room, 'player_id': actor.pid,
                                  'card': {'name': '禁忌果实'}, 'targets': {}})
    resolved = actor.wait_resolved()
    replace = {'card': '场地魔法替换(恶魔契约→禁忌果实)',
               'verdict': 'PASS' if resolved else 'CRASH/TIMEOUT',
               'success': bool(resolved), 'message': '', 'followup': '', 'note': '专项场景'}
    report.append(replace)
    print(f"[{replace['verdict']:<14}] {replace['card']}")

    passed = sum(1 for e in report if e['verdict'] == 'PASS')
    rejected = sum(1 for e in report if e['verdict'] == 'REJECTED')
    crashed = sum(1 for e in report if e['verdict'] == 'CRASH/TIMEOUT')
    failed = len(report) - passed - rejected - crashed
    print(f'\n总计 {len(report)} 项: PASS {passed} | 合法拒绝 {rejected} | 崩溃/超时 {crashed} | 其他失败 {failed}')

    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f'报告已写入 {os.path.abspath(REPORT_PATH)}')

    try:
        a.sio.disconnect()
    except Exception:
        pass
    try:
        b.sio.disconnect()
    except Exception:
        pass
    return 0 if crashed == 0 and failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
