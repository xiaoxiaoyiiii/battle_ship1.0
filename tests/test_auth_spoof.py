# -*- coding: utf-8 -*-
"""事件鉴权（防伪造 player_id）单元测试。

覆盖 server._identity_check 纯校验逻辑与 server._identity_ok 包装层：
- 登录用户（server_pid）身份一致性
- 游客（无登录）必须与入座时登记的 sid 一致
- 无 Flask 请求上下文（单元测试直调）时仅保留成员校验、不崩溃
"""
import pytest
import server
from server import GameRoom, Player

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def capture_emit(monkeypatch):
    events = []
    monkeypatch.setattr(server, 'emit',
                        lambda event, data, to=None, room=None: events.append((event, data, to, room)))
    return events


def make_room():
    room = GameRoom('r1')
    room.players[P1] = Player(name='p1', ships=[], attacks=[], remaining_ships=0, sid='sid1')
    room.players[P2] = Player(name='p2', ships=[], attacks=[], remaining_ships=0, sid='sid2')
    return room


# ---------- _identity_check（纯逻辑） ----------

def test_logged_user_matches_passes():
    room = make_room()
    assert server._identity_check(room, P1, server_pid=P1, sid='sid1') is True


def test_logged_user_acting_as_other_rejected():
    """登录用户是 p2，从自己的连接自称 p1 操作 -> 拒绝（伪造他人身份）。"""
    room = make_room()
    # sid='sid9' 是攻击者自己的连接，既不是 p1 的入座 sid，也非 p2 的会话 id
    assert server._identity_check(room, P1, server_pid=P2, sid='sid9') is False


def test_match_room_sid_key_convention_ok():
    """匹配房 key=入队时的 socket sid（即使已登录）：声称 player_id=本连接 sid 应通过。"""
    room = GameRoom('rm')
    room.players['sidA'] = Player(name='a', ships=[], attacks=[], remaining_ships=0, sid='sidA')
    room.players['sidB'] = Player(name='b', ships=[], attacks=[], remaining_ships=0, sid='sidB')
    # 登录用户（server_pid=uidA）在匹配房：声称 key=sidA、且是本连接 -> 通过
    assert server._identity_check(room, 'sidA', server_pid='uidA', sid='sidA') is True
    # 用他人连接伪造 sidA -> 拒绝
    assert server._identity_check(room, 'sidA', server_pid='uidA', sid='sidB') is False


def test_match_room_guest_ok():
    """游客在匹配房（server_pid 为空）：声称 key=本连接 sid -> 通过；他人连接 -> 拒绝。"""
    room = GameRoom('rm2')
    room.players['sidX'] = Player(name='x', ships=[], attacks=[], remaining_ships=0, sid='sidX')
    room.players['sidY'] = Player(name='y', ships=[], attacks=[], remaining_ships=0, sid='sidY')
    assert server._identity_check(room, 'sidX', server_pid=None, sid='sidX') is True
    assert server._identity_check(room, 'sidX', server_pid=None, sid='sidY') is False


def test_guest_sid_match_passes():
    room = make_room()
    assert server._identity_check(room, P1, server_pid=None, sid='sid1') is True


def test_guest_sid_mismatch_rejected():
    """游客用别人的连接 sid 自称 p1 -> 拒绝。"""
    room = make_room()
    assert server._identity_check(room, P1, server_pid=None, sid='sid2') is False


def test_unknown_player_rejected():
    room = make_room()
    assert server._identity_check(room, 'ghost', server_pid=None, sid='sid1') is False
    assert server._identity_check(room, 'ghost', server_pid=P1, sid='sid1') is False


def test_none_room_rejected():
    assert server._identity_check(None, P1, server_pid=P1, sid='sid1') is False


# ---------- _identity_ok（含请求上下文适配） ----------

def test_no_context_valid_member_ok():
    """无 Flask 上下文直调（如现有单元测试路径）不崩溃且成员校验通过。"""
    room = make_room()
    assert server._identity_ok(room, P1) is True


def test_no_context_unknown_player_rejected():
    room = make_room()
    assert server._identity_ok(room, 'ghost') is False


def test_wrapper_logged_user_spoof_rejected(monkeypatch):
    """模拟请求上下文：登录用户是 p2，自称 p1 -> 拒绝。"""
    import types
    room = make_room()
    monkeypatch.setattr(server, 'session', types.SimpleNamespace(get=lambda k: P2))
    monkeypatch.setattr(server, 'request', types.SimpleNamespace(sid='sid9'))  # 攻击者自己的连接
    assert server._identity_ok(room, P1) is False
    assert server._identity_ok(room, P2) is True


def test_wrapper_guest_sid_mismatch_rejected(monkeypatch):
    """模拟请求上下文：游客连接 sid=sid2 自称 p1 -> 拒绝。"""
    import types
    room = make_room()
    monkeypatch.setattr(server, 'session', types.SimpleNamespace(get=lambda k: None))
    monkeypatch.setattr(server, 'request', types.SimpleNamespace(sid='sid2'))
    assert server._identity_ok(room, P1) is False
    assert server._identity_ok(room, P2) is True
