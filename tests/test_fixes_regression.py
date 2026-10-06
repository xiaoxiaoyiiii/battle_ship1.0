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




# ---------------------------------------------------------------------------
# 2. 游客匹配：两个无登录用户都应能配对（原 None == None 恒真导致永远排不上）
# ---------------------------------------------------------------------------




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




def test_place_ships_rejects_overlap(room):
    cells = [(0, 0)] * 6
    res = server.handle_place_ships({
        'room_id': room.id, 'player_id': P1, 'ships': _ship_payload(cells),
    })
    assert res['status'] == 'error'




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




# ---------------------------------------------------------------------------
# 8. 盗亦有道：不得复制卡牌 / 不得重复盗取
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# 9. db.update_user 列名白名单
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 10. 统一攻击路径（Phase 3.1）
# ---------------------------------------------------------------------------


def test_yuyin_forced_kill_via_real_attack_path(room):
    """余音绕梁：真实攻击路径下强制击杀无视护盾，按攻击阶段计数。"""
    room.current_phase = 'preparation'
    server.apply_magic_effect(room, P1, card('余音绕梁'), {})
    assert room.players[P1].effect_flags.forced_kill == 2
    room.current_phase = 'battle'

    # 对方是护盾船：普通攻击挡不下，强制击杀必须击沉
    room.players[P2].ships = [ship((0, 0)), ship((1, 1))]
    room.players[P2].ships[0].shield = True
    room.players[P2].remaining_ships = 2
    room.attacks_remaining = 6

    res = server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 0})
    assert res['status'] == 'success'
    assert room.players[P2].remaining_ships == 1  # 护盾未能挡住强制击杀
    assert room.players[P1].effect_flags.forced_kill == 2, '击杀不消耗阶段数'


def test_forced_kill_consumed_per_attack_phase(room):
    """余音绕梁按攻击阶段消耗：可在一整个攻击阶段内多次强制击杀。"""
    room.current_phase = 'preparation'
    server.apply_magic_effect(room, P1, card('余音绕梁'), {})
    room.current_phase = 'battle'
    # 第三艘不打的船：打光会被判终局，handle_enter_end_phase 会被门禁拒绝
    room.players[P2].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P2].remaining_ships = 3
    room.attacks_remaining = 6

    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 0})
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 1, 'y': 1})
    assert room.players[P1].effect_flags.forced_kill == 2, '同一攻击阶段内可多次强制击杀'

    # 进入结束阶段才消耗一次
    room.attacks_remaining = 0
    server.handle_enter_end_phase({'room_id': room.id, 'player_id': P1})
    assert room.players[P1].effect_flags.forced_kill == 1












# ---------------------------------------------------------------------------
# 11. 魔法卡数据健壮性：未知卡名不得让 handler 崩溃（原 IndexError）
# ---------------------------------------------------------------------------




def test_use_magic_card_invalid_card_name_returns_error(room, monkeypatch):
    """use_magic_card 收到未知卡名时返回错误响应，不抛异常。"""
    monkeypatch.setattr(server, 'session', types.SimpleNamespace(get=lambda k, d=None: None))
    monkeypatch.setattr(server, 'request', types.SimpleNamespace(sid='sid-p1'))
    res = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '完全不存在的卡牌'},
    })
    assert res['status'] == 'error'
    assert '无效' in res['message']


def test_use_magic_card_non_dict_card_returns_error(room, monkeypatch):
    """card 字段不是 dict 时（如字符串）也应返回错误，不崩溃。"""
    monkeypatch.setattr(server, 'session', types.SimpleNamespace(get=lambda k, d=None: None))
    monkeypatch.setattr(server, 'request', types.SimpleNamespace(sid='sid-p1'))
    res = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': 'not-a-dict',
    })
    assert res['status'] == 'error'


def test_chain_response_invalid_card_name_returns_error(room, monkeypatch):
    """chain_response 收到未知卡名时返回错误响应，不抛异常。"""
    room.chain_waiting = True
    room.chain_window = P1
    monkeypatch.setattr(server, 'session', types.SimpleNamespace(get=lambda k, d=None: None))
    monkeypatch.setattr(server, 'request', types.SimpleNamespace(sid='sid-p1'))
    res = server.chain_response({
        'room_id': room.id, 'player_id': P1,
        'chain': True, 'card': {'name': '完全不存在的卡牌'},
    })
    assert res['status'] == 'error'
    assert '无效' in res['message']
