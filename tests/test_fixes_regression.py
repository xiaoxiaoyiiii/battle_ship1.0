# -*- coding: utf-8 -*-
"""针对本轮安全/健壮性修复的回归测试。

覆盖：调试事件开关、游客匹配、surrender 鉴权、布船/攻击/魔法目标校验、
房间回收、盗亦有道防复制、db 列名白名单。
"""
import types

import pytest

import server
from server import (GameRoom, MagicCard, Player, PlayerShip, Position,
                    room_manager)

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def events(monkeypatch):
    """拦截所有 socket emit，避免需要请求上下文。"""
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    return captured


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)
    room_manager.match_queue = []


def make_room():
    r = GameRoom('fix-room')
    r.players[P1] = Player(name='p1', ships=[], attacks=[], remaining_ships=0, sid='sid-p1')
    r.players[P2] = Player(name='p2', ships=[], attacks=[], remaining_ships=0, sid='sid-p2')
    r.state = 'attacking'
    r.current_attacker = P1
    r.current_phase = 'battle'
    r.attack_order = [P1, P2]
    r.attacks_remaining = 6
    r.round = 1
    room_manager.rooms[r.id] = r
    return r


def ship(*cells):
    return PlayerShip(positions=[Position(x, y) for x, y in cells], hits=[])


def card(name):
    return MagicCard(name)


# ---------------------------------------------------------------------------
# 1. 调试事件默认关闭（防公网作弊）
# ---------------------------------------------------------------------------
def test_debug_events_disabled_by_default(room):
    assert server.ENABLE_TEST_EVENTS is False
    res = server.test_win_game({'room_id': room.id, 'player_id': P1})
    assert res['status'] == 'error'
    assert room.state != 'game_over'
    assert not room.winner


def test_debug_events_enabled_when_flag_on(monkeypatch, room):
    monkeypatch.setattr(server, 'ENABLE_TEST_EVENTS', True)
    res = server.test_win_game({'room_id': room.id, 'player_id': P1})
    assert res['status'] == 'success'
    assert room.state == 'game_over'
    assert room.winner == P1


# ---------------------------------------------------------------------------
# 2. 游客匹配：两个无登录用户都应能配对（原 None == None 恒真导致永远排不上）
# ---------------------------------------------------------------------------
def test_two_guests_can_match(monkeypatch):
    room_manager.match_queue = []
    created = {}

    def fake_join_room(room_id, sid):
        pass

    monkeypatch.setattr(server, 'join_room', fake_join_room)
    monkeypatch.setattr(server, 'session', types.SimpleNamespace(get=lambda k, d=None: None))

    for sid in ('guest-a', 'guest-b'):
        monkeypatch.setattr(server, 'request', types.SimpleNamespace(sid=sid))
        res = server.handle_find_match({'player_name': sid})
        assert res['status'] == 'success'

    # 两名游客应已配对并离开队列
    assert room_manager.get_match_queue_size() == 0
    matched_rooms = [
        r for r in room_manager.get_all_rooms().values()
        if set(r.players.keys()) == {'guest-a', 'guest-b'}
    ]
    assert len(matched_rooms) == 1
    assert matched_rooms[0].state == 'placing_ships'
    for rid in [r.id for r in matched_rooms]:
        room_manager.rooms.pop(rid, None)


def test_same_logged_user_not_matched_with_self(monkeypatch):
    """同一登录账号重复入队（两个标签页）不应被配对。"""
    room_manager.match_queue = []
    monkeypatch.setattr(server, 'session', types.SimpleNamespace(get=lambda k, d=None: 'uid-x'))
    monkeypatch.setattr(server, 'join_room', lambda room_id, sid: None)

    before = len(room_manager.get_all_rooms())
    for sid in ('tab-1', 'tab-2'):
        monkeypatch.setattr(server, 'request', types.SimpleNamespace(sid=sid))
        server.handle_find_match({'player_name': sid})

    assert len(room_manager.get_all_rooms()) == before
    assert room_manager.get_match_queue_size() == 2


# ---------------------------------------------------------------------------
# 3. surrender 必须通过身份校验
# ---------------------------------------------------------------------------
def test_surrender_rejects_other_connection(monkeypatch, room):
    """攻击者用自己的连接冒充 P1 投降 -> 拒绝。"""
    monkeypatch.setattr(server, 'session', types.SimpleNamespace(get=lambda k, d=None: P2))
    monkeypatch.setattr(server, 'request', types.SimpleNamespace(sid='sid-attacker'))
    res = server.handle_surrender({'room_id': room.id, 'player_id': P1})
    assert res['status'] == 'error'
    assert room.state != 'game_over'


def test_surrender_allows_self(monkeypatch, room):
    monkeypatch.setattr(server, 'session', types.SimpleNamespace(get=lambda k, d=None: None))
    monkeypatch.setattr(server, 'request', types.SimpleNamespace(sid='sid-p1'))
    res = server.handle_surrender({'room_id': room.id, 'player_id': P1})
    assert res['status'] == 'success'
    assert room.state == 'game_over'
    assert room.winner == P2


# ---------------------------------------------------------------------------
# 4. 布船服务端校验
# ---------------------------------------------------------------------------
def _ship_payload(cells):
    return [{'positions': [{'x': x, 'y': y}], 'hits': []} for x, y in cells]


def test_place_ships_rejects_wrong_count(room):
    res = server.handle_place_ships({
        'room_id': room.id, 'player_id': P1,
        'ships': _ship_payload([(0, 0), (1, 1)]),  # 应为 6 艘
    })
    assert res['status'] == 'error'


def test_place_ships_rejects_out_of_range(room):
    cells = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (9, 9)]
    res = server.handle_place_ships({
        'room_id': room.id, 'player_id': P1, 'ships': _ship_payload(cells),
    })
    assert res['status'] == 'error'


def test_place_ships_rejects_overlap(room):
    cells = [(0, 0)] * 6
    res = server.handle_place_ships({
        'room_id': room.id, 'player_id': P1, 'ships': _ship_payload(cells),
    })
    assert res['status'] == 'error'


def test_place_ships_accepts_valid(room):
    cells = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (5, 5)]
    res = server.handle_place_ships({
        'room_id': room.id, 'player_id': P1, 'ships': _ship_payload(cells),
    })
    assert res['status'] == 'success'
    assert len(room.players[P1].ships) == 6


# ---------------------------------------------------------------------------
# 5. 攻击坐标校验
# ---------------------------------------------------------------------------
def test_attack_rejects_out_of_range(room):
    room.players[P1].remaining_ships = 3
    res = server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 9, 'y': 0})
    assert res['status'] == 'error'
    # 越界攻击不应消耗攻击次数，也不应记为已攻击
    assert room.attacks_remaining == 6
    assert room.players[P1].attacks == []


def test_attack_rejects_non_integer(room):
    room.players[P1].remaining_ships = 3
    res = server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 'a', 'y': 0})
    assert res['status'] == 'error'
    assert room.attacks_remaining == 6


# ---------------------------------------------------------------------------
# 6. 魔法卡目标校验
# ---------------------------------------------------------------------------
def test_magic_target_out_of_range_rejected(room):
    room.players[P1].magic_hand = [card('神威！')]
    res = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1, 'card': {'name': '神威！'},
        'targets': {'target_area': {'x1': 0, 'y1': 0, 'x2': 9, 'y2': 9}},
    })
    assert res['status'] == 'error'


def test_sanitize_targets_normalizes(room):
    targets, err = server._sanitize_magic_targets(
        {'target_line': {'type': 'row', 'index': '3'}}
    )
    assert err is None
    assert targets['target_line']['index'] == 3


# ---------------------------------------------------------------------------
# 7. 已结束房间回收（内存泄漏修复）
# ---------------------------------------------------------------------------
def test_reaper_removes_ended_rooms(room):
    room.state = 'game_over'
    # 首次观察只计时，不删除
    assert server._reap_ended_rooms(now=1000.0) == []
    assert room.id in room_manager.get_all_rooms()
    # 超过宽限期后删除
    reaped = server._reap_ended_rooms(now=1000.0 + server._ROOM_GRACE_SECONDS + 1)
    assert room.id in reaped
    assert room.id not in room_manager.get_all_rooms()


def test_reaper_keeps_active_rooms(room):
    room.state = 'attacking'
    room._game_over_since = 1.0
    assert server._reap_ended_rooms(now=999999.0) == []
    assert room.id in room_manager.get_all_rooms()


# ---------------------------------------------------------------------------
# 8. 盗亦有道：不得复制卡牌 / 不得重复盗取
# ---------------------------------------------------------------------------
def test_daoyouyoudao_moves_card_from_discard(room):
    used = card('轰炸')
    room.magic_history = [{'card': used, 'caster': P2}]
    room.magic_discard = [used]
    res = server.apply_magic_effect(room, P1, card('盗亦有道'), {})
    assert res.success is True
    stolen = [c for c in room.players[P1].magic_hand if c.name == '轰炸']
    assert len(stolen) == 1
    # 卡牌应从弃牌堆转移，而不是被复制
    assert used not in room.magic_discard


def test_daoyouyoudao_cannot_steal_same_entry_twice(room):
    used = card('轰炸')
    room.magic_history = [{'card': used, 'caster': P2}]
    room.magic_discard = [used]
    server.apply_magic_effect(room, P1, card('盗亦有道'), {})
    res2 = server.apply_magic_effect(room, P1, card('盗亦有道'), {})
    assert res2.success is False


# ---------------------------------------------------------------------------
# 9. db.update_user 列名白名单
# ---------------------------------------------------------------------------
def test_update_user_rejects_unknown_column():
    import db as db_module
    assert db_module.db.update_user('nonexistent-uid', not_a_column='x') is False
