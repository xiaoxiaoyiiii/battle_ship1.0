# -*- coding: utf-8 -*-
"""回合计时（思考超时兜底）回归。

2026-09-13 审计：此前**只有连锁窗口**有 10 秒超时，炮击/准备阶段可以无限长考，
对手只能干等。现在加了 90 秒看门狗（`TURN_TIMEOUT_SECONDS`，0 = 关闭），
超时只做一次保底动作、不判负：准备阶段→进战斗；战斗→随机开火一发；结束→交出回合。

本文件锁住四件事：① 三种阶段各自的保底动作；② 该催的才催（AI 房 / 连锁窗口 /
等待点选 / 有人掉线 / 刚操作过 都不催）；③ 只惩罚完全不动的人；④ 可关闭。
"""
import time

import pytest

import server
from server import (ChainItem, GameRoom, MagicCard, Player, PlayerShip,
                    Position, room_manager)

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def events(monkeypatch):
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    return captured


@pytest.fixture(autouse=True)
def timeout_seconds(monkeypatch):
    monkeypatch.setattr(server, 'TURN_TIMEOUT_SECONDS', 90)
    return 90


def ship(*cells):
    return PlayerShip(positions=[Position(x, y) for x, y in cells], hits=[])


def make_room(phase='battle', ai=False):
    r = GameRoom('timer-room')
    r.players[P1] = Player(name='p1', ships=[ship((i, 0)) for i in range(6)],
                           attacks=[], remaining_ships=6, sid='sid-p1', user_id='u1')
    r.players[P2] = Player(name='p2', ships=[ship((i, 1)) for i in range(6)],
                           attacks=[], remaining_ships=6, sid='sid-p2', user_id='u2')
    r.is_ai_room = ai
    r.state = 'attacking'
    r.current_attacker = P1
    r.current_phase = phase
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


def _arm(room, since):
    """模拟"这位玩家已经卡住 since 秒"（先让看门狗认一次人头）。"""
    room._timer_attacker = P1
    room.turn_started_at = since


# ---------------------------------------------------------------------------
# 1. 三种阶段的保底动作
# ---------------------------------------------------------------------------
def test_timeout_attacks_once_in_battle(room):
    _arm(room, time.time() - 91)
    acted = server._auto_act_on_timeouts()
    assert acted == [room.id]
    assert room.attacks_remaining == 5, '战斗阶段超时应自动开火恰好一发'
    assert len(room.players[P1].attacks) == 1
    assert room.current_attacker == P1, '保底动作不交回合'


def test_timeout_enters_battle_phase_from_preparation(room):
    room.current_phase = 'preparation'
    _arm(room, time.time() - 91)

    server._auto_act_on_timeouts()

    assert room.current_phase == 'battle', '准备阶段超时应自动进入战斗阶段'


def test_timeout_ends_turn_in_end_phase(room):
    room.current_phase = 'end'
    _arm(room, time.time() - 91)

    server._auto_act_on_timeouts()

    assert room.current_attacker == P2, '结束阶段超时应自动交出回合'


def test_timeout_notifies_both_sides(room, events):
    _arm(room, time.time() - 91)
    server._auto_act_on_timeouts()
    texts = [e[1] for e in events if isinstance(e[1], dict)]
    joined = ' '.join(str(d.get('text') or d.get('message') or '') for d in texts)
    assert '思考超时' in joined, '必须明确告诉双方发生了什么'


# ---------------------------------------------------------------------------
# 2. 该催的才催
# ---------------------------------------------------------------------------
def test_no_action_before_deadline(room):
    _arm(room, time.time() - 10)
    assert server._auto_act_on_timeouts() == []
    assert room.attacks_remaining == 6


def test_first_sighting_only_arms_the_clock(room):
    room.turn_started_at = None
    room._timer_attacker = None
    assert server._auto_act_on_timeouts() == [], '第一次看到该玩家只记时间，不动作'
    assert room.turn_started_at is not None


def test_turn_change_restarts_the_clock(room):
    _arm(room, time.time() - 999)          # 上一个人早已超时
    room.current_attacker = P2               # 但回合已经换人了
    assert server._auto_act_on_timeouts() == [], '换人后应重新计时'
    assert room._timer_attacker == P2


def test_ai_rooms_are_skipped():
    r = make_room(ai=True)
    try:
        _arm(r, time.time() - 999)
        assert server._auto_act_on_timeouts() == [], 'AI 房不该被看门狗干预'
        assert r.attacks_remaining == 6
    finally:
        room_manager.rooms.pop(r.id, None)


def test_open_chain_window_is_skipped(room):
    room.chain = [ChainItem(P1, MagicCard('无中生有'), [], time.time())]
    room.chain_waiting = True
    _arm(room, time.time() - 999)
    assert server._auto_act_on_timeouts() == [], '连锁有自己的 10 秒窗口，不该被抢跑'


def test_pending_choices_are_skipped(room):
    for key in ('pending_placement', 'pending_sacrifice', 'pending_shenji'):
        room.magic_temp_data = {key: {'caster': P1}}
        _arm(room, time.time() - 999)
        assert server._auto_act_on_timeouts() == [], f'{key} 等待点选时不该催'
    room.magic_temp_data = {}


def test_disconnected_opponent_is_skipped(room):
    room.disconnected = {P2: time.time()}
    _arm(room, time.time() - 999)
    assert server._auto_act_on_timeouts() == [], '有人掉线宽限中不该催'


def test_rooms_not_in_attacking_state_are_skipped(room):
    room.state = 'placing_ships'
    _arm(room, time.time() - 999)
    assert server._auto_act_on_timeouts() == []


def test_timeout_can_be_disabled(monkeypatch, room):
    monkeypatch.setattr(server, 'TURN_TIMEOUT_SECONDS', 0)
    _arm(room, time.time() - 999)
    assert server._auto_act_on_timeouts() == [], 'TURN_TIMEOUT_SECONDS=0 时应完全关闭'


# ---------------------------------------------------------------------------
# 3. 一直在操作的玩家不该被催（门禁装饰器顺带重置计时）
# ---------------------------------------------------------------------------
def test_successful_action_refreshes_the_clock(room):
    room.turn_started_at = time.time() - 89      # 已经想了 89 秒
    res = server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 1})
    assert res['status'] == 'success'
    assert time.time() - room.turn_started_at < 2, '成功操作后必须重新计时'


def test_failed_action_does_not_refresh_the_clock(room):
    room.turn_started_at = time.time() - 89
    res = server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 9, 'y': 9})
    assert res['status'] == 'error'
    assert time.time() - room.turn_started_at > 80, '无效操作不该骗过看门狗'
