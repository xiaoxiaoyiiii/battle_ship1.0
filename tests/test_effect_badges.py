# -*- coding: utf-8 -*-
"""「生效中效果」角标：双方可见 + 带卡面说明 + 带失效时机。

作者需求：
  「有持续效果的卡牌通过之后会出现一个小框提示玩家现在这个效果正在生效
    （比如五险一金）……希望鼠标移上去或者手机端点击之后可以出现具体效果阐释框
    ……让双方都可见正在生效的效果，比如说对方使用了五险一金，
    就在屏幕镜像右边的地方出现一个五险一金的小框」

改动前的问题：
  · `_emit_active_effects` 只发本人（注释写着"角标是给自己看的状态，不广播给对方"）
    → 玩家完全看不到对手挂着什么；
  · 角标只带一个名字，唯一的"说明"是前端 title 属性（只有名字，没有效果文字）；
  · 重连快照里根本没带这份数据 → 重连后角标全空，要等下一次广播才恢复。
"""
import pytest

import server
from server import GameRoom, Player, PlayerShip, Position, MagicCard, room_manager

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def captured(monkeypatch):
    """记录所有 active_effects 推送，返回 [(to_sid, payload), ...]。"""
    sent = []

    def fake_emit(event, data=None, to=None, room=None):
        if event == 'active_effects':
            sent.append({'to': to, 'room': room, 'data': data})
        return None

    monkeypatch.setattr(server, 'emit', fake_emit)
    monkeypatch.setattr(server.socketio, 'start_background_task', lambda t, *a, **k: t(*a, **k))
    monkeypatch.setattr(server, '_schedule_chain_timeout', lambda *a, **k: None)
    monkeypatch.setattr(server, '_schedule_priority_timeout', lambda *a, **k: None)
    monkeypatch.setattr(server, '_has_request_context', lambda: False)
    return sent


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def make_room():
    room = GameRoom('t')
    room.players[P1] = Player(name='p1',
                              ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(6)],
                              attacks=[], remaining_ships=6, sid='sid-p1')
    room.players[P2] = Player(name='p2',
                              ships=[PlayerShip(positions=[Position(i, 5)], hits=[]) for i in range(6)],
                              attacks=[], remaining_ships=6, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'preparation'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 5
    room.magic_deck = [MagicCard(n) for n in ['冻结', '疗愈']]
    room_manager.rooms[room.id] = room
    return room


# ===========================================================================
# 双方可见
# ===========================================================================




def test_both_sides_effects_do_not_mix(room, captured):
    """双方各挂不同效果时不能串台。"""
    room.players[P1].effect_flags.subsidy = True          # 我：百亿补贴
    room.players[P2].effect_flags.treasure_hunter = True  # 对方：八方来财

    server._emit_active_effects(room)

    mine = next(c['data'] for c in captured if c['to'] == 'sid-p1')
    assert [e['name'] for e in mine['self']] == ['百亿补贴']
    assert [e['name'] for e in mine['opponent']] == ['八方来财']


# ===========================================================================
# 说明文字与失效时机
# ===========================================================================




def _fake_player_with(attr):
    p = Player(name='x', ships=[], attacks=[], remaining_ships=0, sid='s')
    setattr(p.effect_flags, attr, True)
    return p








# ===========================================================================
# 重连快照
# ===========================================================================
def test_reconnect_snapshot_carries_effect_badges(room):
    """★ 重连快照必须带上双方效果，否则重连后角标全空。"""
    room.players[P1].effect_flags.subsidy = True
    room.players[P2].effect_flags.no_draw = True

    snap = server._build_room_sync(room, P1)

    assert 'effect_badges' in snap, '快照里必须有这份数据'
    assert [e['name'] for e in snap['effect_badges']['self']] == ['百亿补贴']
    assert [e['name'] for e in snap['effect_badges']['opponent']] == ['无中生有']


def test_reconnect_snapshot_is_recipient_scoped(room):
    """快照也必须按收件人视角，P1 和 P2 拿到的 self/opponent 相反。"""
    room.players[P1].effect_flags.subsidy = True
    room.players[P2].effect_flags.wuxian = True

    s1 = server._build_room_sync(room, P1)['effect_badges']
    s2 = server._build_room_sync(room, P2)['effect_badges']

    assert [e['name'] for e in s1['self']] == ['百亿补贴']
    assert [e['name'] for e in s1['opponent']] == ['五险一金']
    assert [e['name'] for e in s2['self']] == ['五险一金']
    assert [e['name'] for e in s2['opponent']] == ['百亿补贴']
