# -*- coding: utf-8 -*-
"""测试护栏：把「最危险但零覆盖」的路径锁住。

背景（2026-09-13 审计实测）：
  * 12 个 test_* 高危调试事件里，此前只有 1 个有回归覆盖；
  * 连锁引擎的超时/窗口推进/能否响应**没有任何测试**（grep 0 命中），
    而这部分逻辑一旦回归，表现为"对局卡死"或"效果凭空丢失"，极难排查。
本文件按「参数化 + 直接单测纯函数」的方式补齐，避免以后重复踩坑。
"""
import pathlib
import re
import time

import pytest

import server
from server import ChainItem, GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def events(monkeypatch):
    """拦截 emit，避免单测直调 handler 时缺请求上下文。"""
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    return captured


@pytest.fixture(autouse=True)
def no_background_timeout(monkeypatch):
    """连锁窗口会起后台超时任务，单测里替换成记账桩。

    real 字段保留原函数：测超时逻辑本身时要直接调它（否则调到的就是桩）。
    """
    scheduled = []
    real = server._schedule_chain_timeout
    monkeypatch.setattr(server, '_schedule_chain_timeout',
                        lambda room_id, token: scheduled.append((room_id, token)))
    return {'scheduled': scheduled, 'real': real}


def ship(*cells):
    return PlayerShip(positions=[Position(x, y) for x, y in cells], hits=[])


def card(name):
    return MagicCard(name)


def make_room():
    r = GameRoom('guard-room')
    r.players[P1] = Player(name='p1', ships=[ship((i, 0)) for i in range(6)],
                           attacks=[], remaining_ships=6, sid='sid-p1', user_id='u1')
    r.players[P2] = Player(name='p2', ships=[ship((i, 1)) for i in range(6)],
                           attacks=[], remaining_ships=6, sid='sid-p2', user_id='u2')
    r.state = 'attacking'
    r.current_attacker = P1
    r.current_phase = 'battle'
    r.attack_order = [P1, P2]
    r.attacks_remaining = 6
    r.round = 1
    room_manager.rooms[r.id] = r
    return r


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)
    room_manager.match_queue = []


# ---------------------------------------------------------------------------
# 1. 12 个调试事件在生产模式下必须全部被拒
# ---------------------------------------------------------------------------
def _declared_test_events():
    """直接从 server.py 源码里取事件名：以后新增 test_* handler 会自动纳入覆盖。"""
    src = pathlib.Path(server.__file__).read_text(encoding='utf-8')
    return sorted(set(re.findall(r"@socketio\.on\('(test_[^']+)'\)", src)))


def test_declared_test_events_are_twelve():
    names = _declared_test_events()
    assert len(names) == 12, names


@pytest.mark.parametrize('event', _declared_test_events())
def test_every_debug_event_rejected_by_default(room, event):
    """生产模式（未设 ENABLE_TEST_EVENTS）下，12 个事件一个都不能放行。"""
    assert server.ENABLE_TEST_EVENTS is False
    client = server.socketio.test_client(server.app)
    try:
        ack = client.emit(event, {'room_id': room.id, 'player_id': P1}, callback=True)
        assert ack == {'status': 'error', 'message': '调试事件未启用'}, (event, ack)
    finally:
        client.disconnect()


def test_debug_events_do_not_mutate_room(room):
    """被拒的调试事件不能顺手改状态（挑最危险的三个）。"""
    client = server.socketio.test_client(server.app)
    try:
        client.emit('test_win_game', {'room_id': room.id, 'player_id': P1}, callback=True)
        client.emit('test_add_all_magic_cards', {'room_id': room.id, 'player_id': P1}, callback=True)
        client.emit('test_set_opponent_ships',
                    {'room_id': room.id, 'player_id': P1, 'ship_count': 1}, callback=True)
    finally:
        client.disconnect()
    assert room.state == 'attacking' and room.winner == ''
    assert room.players[P1].magic_hand == []
    assert room.players[P2].remaining_ships == 6


# ---------------------------------------------------------------------------
# 2. 能否响应连锁
# ---------------------------------------------------------------------------
def test_can_respond_chain_requires_speed3(room):
    assert server._can_respond_chain(room, P1) is False       # 手牌为空
    room.players[P1].magic_hand = [card('冻结')]              # 速阶 2
    assert server._can_respond_chain(room, P1) is False
    room.players[P1].magic_hand = [card('失灵！')]            # 速阶 3
    assert server._can_respond_chain(room, P1) is True


def test_can_respond_chain_blocked_by_kanpo(room):
    """看破！生效中的玩家不参与连锁。"""
    room.players[P1].magic_hand = [card('失灵！')]
    room.players[P1].magic_blocked = True
    assert server._can_respond_chain(room, P1) is False
    room.players[P1].magic_blocked = False
    assert server._can_respond_chain(room, P1) is True


def test_ai_never_responds_chain(room):
    """AI 目前不参与连锁响应（已在 _can_respond_chain 里显式排除）。"""
    ai = 'ai-guard'
    room.players[ai] = Player(name='AI', ships=[ship((0, 5))], attacks=[],
                              remaining_ships=1, sid='sid-ai', user_id=None)
    room.players[ai].magic_hand = [card('失灵！')]
    assert server._can_respond_chain(room, ai) is False


# ---------------------------------------------------------------------------
# 3. 响应窗口推进（含超时兜底）
# ---------------------------------------------------------------------------
def test_advance_chain_window_opens_for_responsive_player(room, events, no_background_timeout):
    room.chain = [ChainItem(P1, card('无中生有'), [], time.time())]
    room.players[P2].magic_hand = [card('失灵！')]

    server._advance_chain_window(room, P2)

    assert room.chain_waiting is True
    assert room.chain_window == P2
    reqs = [e for e in events if e[0] == 'chain_request']
    assert reqs, '必须给能响应的一方发 chain_request'
    assert reqs[0][1]['countdown'] == server.CHAIN_RESPONSE_SECONDS
    # 同时要挂上超时兜底，且带上代际令牌
    assert no_background_timeout['scheduled'] == [(room.id, room.chain_timer)]


def test_advance_chain_window_two_passes_resolve_chain(room, events):
    """双方都无法响应：连续两次自动放弃后结算，绝不死循环。"""
    room.chain = [ChainItem(P1, card('无中生有'), [], time.time())]
    room.players[P1].magic_hand = []
    room.players[P2].magic_hand = []

    server._advance_chain_window(room, P2)

    assert room.chain == [], '无人可响应时必须结算，不能把连锁栈挂着'
    assert room.chain_waiting is False
    assert not [e for e in events if e[0] == 'chain_request']


def test_chain_timeout_ignores_stale_token(room, monkeypatch, no_background_timeout):
    """过期令牌（旧定时器）不得推进窗口，避免与正常响应竞态双重结算。"""
    monkeypatch.setattr(server.time, 'sleep', lambda *_: None)
    monkeypatch.setattr(server.socketio, 'start_background_task', lambda fn, *a, **kw: fn(*a, **kw))

    room.chain = [ChainItem(P1, card('无中生有'), [], time.time())]
    room.chain_waiting = True
    room.chain_window = P2
    room.chain_timer = 7
    room.players[P2].magic_hand = [card('失灵！')]

    no_background_timeout['real'](room.id, 3)   # 过期令牌
    assert room.chain_waiting is True, '过期定时器不得改动窗口'
    assert room.chain_timer == 7


def test_chain_timeout_passes_then_resolves(room, monkeypatch, events, no_background_timeout):
    """当前令牌超时：记一次放弃并顺延；连续两次后结算。"""
    monkeypatch.setattr(server.time, 'sleep', lambda *_: None)
    monkeypatch.setattr(server.socketio, 'start_background_task', lambda fn, *a, **kw: fn(*a, **kw))

    room.chain = [ChainItem(P1, card('无中生有'), [], time.time())]
    room.chain_waiting = True
    room.chain_window = P2
    room.chain_timer = 1
    room.players[P1].magic_hand = [card('失灵！')]

    no_background_timeout['real'](room.id, 1)
    # P2 超时 → 窗口顺延给 P1（P1 有速阶3，能响应）
    assert room.chain_passes == 1
    assert room.chain_waiting is True and room.chain_window == P1

    # P1 也超时 → 第二次放弃 → 结算
    no_background_timeout['real'](room.id, room.chain_timer)
    assert room.chain == [] and room.chain_waiting is False


# ---------------------------------------------------------------------------
# 4. 连锁响应 handler 的输入校验
# ---------------------------------------------------------------------------
def test_chain_response_outside_window_rejected(room):
    room.chain = [ChainItem(P1, card('无中生有'), [], time.time())]
    room.chain_waiting = True
    room.chain_window = P2
    room.players[P1].magic_hand = [card('失灵！')]

    res = server.chain_response({'room_id': room.id, 'player_id': P1,
                                 'chain': True, 'card': {'name': '失灵！', 'speed': 3}})
    assert res['status'] == 'error', '不在响应窗口里的人不能插队出牌'


def test_chain_response_uses_server_side_card_instance(room):
    """客户端伪造 speed=3 不能把一张速阶2的牌塞进连锁。"""
    room.chain = [ChainItem(P1, card('无中生有'), [], time.time())]
    room.chain_waiting = True
    room.chain_window = P2
    room.chain_timer = 1
    room.players[P2].magic_hand = [card('冻结')]      # 速阶 2

    res = server.chain_response({'room_id': room.id, 'player_id': P2, 'chain': True,
                                 'card': {'name': '冻结', 'speed': 3}})
    assert res['status'] == 'error'
    assert len(room.chain) == 1, '拒绝时必须不改变连锁栈'


def test_chain_response_with_legal_card_stacks(room):
    room.chain = [ChainItem(P1, card('无中生有'), [], time.time())]
    room.chain_waiting = True
    room.chain_window = P2
    room.chain_timer = 1
    room.players[P2].magic_hand = [card('失灵！')]
    # 施法者也留着速阶3（看破！是速阶2，不算）：否则 P2 响应后窗口绕回 P1、
    # P1 无法响应即自动结算，连锁栈会被清空
    room.players[P1].magic_hand = [card('失灵！')]

    res = server.chain_response({'room_id': room.id, 'player_id': P2, 'chain': True,
                                 'card': {'name': '失灵！', 'speed': 3}})
    assert res['status'] == 'success'
    assert len(room.chain) == 2
    assert room.chain_passes == 0
