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
def test_both_sides_receive_opponent_effects(room, captured):
    """★ 对方挂了效果，我这边也要收到（作者核心需求）。"""
    server._emit_active_effects(room)

    assert len(captured) == 2, '应该给双方各推一份'
    by_sid = {c['to']: c['data'] for c in captured}
    assert set(by_sid) == {'sid-p1', 'sid-p2'}
    # 结构固定
    for payload in by_sid.values():
        assert 'self' in payload and 'opponent' in payload, payload


def test_opponent_effect_is_visible_to_me(room, captured):
    """★ 对方打出的五险一金，必须出现在我收到的 opponent 列表里。"""
    room.players[P2].effect_flags.wuxian = True   # 对方挂了五险一金

    server._emit_active_effects(room)

    mine = next(c['data'] for c in captured if c['to'] == 'sid-p1')
    theirs = next(c['data'] for c in captured if c['to'] == 'sid-p2')

    assert [e['name'] for e in mine['opponent']] == ['五险一金'], mine
    assert [e['name'] for e in mine['self']] == [], mine
    # 反过来：对方自己的列表里它在 self，且他的 opponent 是空的
    assert [e['name'] for e in theirs['self']] == ['五险一金'], theirs
    assert [e['name'] for e in theirs['opponent']] == [], theirs


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
def test_effect_carries_card_description(room, captured):
    """★ 每条效果都要带卡面原文，前端才能展开阐释框。"""
    room.players[P1].effect_flags.wuxian = True
    server._emit_active_effects(room)

    mine = next(c['data'] for c in captured if c['to'] == 'sid-p1')
    entry = mine['self'][0]
    assert entry['name'] == '五险一金'
    assert entry['description'], '必须带说明文字'
    assert '攻击次数' in entry['description'], entry['description']


def test_description_matches_card_data(room):
    """说明必须就是卡牌数据里的原文，不能各写一份。"""
    from server import magic_cards
    by_name = {c.name: c.description for c in magic_cards}
    for attr, label, _expiry, _suffix in server._EFFECT_BADGES:
        if label not in by_name:
            continue
        badges = server._effect_badges(_fake_player_with(attr))
        assert badges[0]['description'] == by_name[label], label


def _fake_player_with(attr):
    p = Player(name='x', ships=[], attacks=[], remaining_ships=0, sid='s')
    setattr(p.effect_flags, attr, True)
    return p


def test_all_badge_labels_exist_as_cards():
    """角标里的每个名字都必须是真实卡名（否则说明文字取不到）。

    ⚠️ 元组第 4 位是【显示后缀】，不参与这条契约：绝处逢生有两条角标
    （锁卡 / 击杀即胜），生命周期不同必须分开显示，但两者的角标名都必须是
    真实卡名「绝处逢生」，否则浮层取不到卡面原文。
    """
    from server import magic_cards
    names = {c.name for c in magic_cards}
    missing = [label for _attr, label, _e, _s in server._EFFECT_BADGES if label not in names]
    assert not missing, f'这些角标名不是卡名，说明文字会取空：{missing}'


def test_expiry_reflects_real_lifecycle(room, captured):
    """★ 失效时机要和代码里的真实清理点一致。

    真实清理点（见 handle_end_turn）：
      · 小回合切换只保留 permanent_flags =
        ['holy_heart','reinforcement_check','no_draw','prediction','forced_kill']
      · 其余交出回合就清；大回合结束再统一清空
    """
    room.players[P1].effect_flags.no_draw = True        # 跨小回合保留
    room.players[P1].effect_flags.vampire = True        # 交出回合就清
    room.players[P1].effect_flags.wuxian = True         # 触发一次即失效

    server._emit_active_effects(room)
    mine = next(c['data'] for c in captured if c['to'] == 'sid-p1')
    by_name = {e['name']: e for e in mine['self']}

    assert '大回合' in by_name['无中生有']['expires'], by_name['无中生有']
    assert '本回合' in by_name['饮血']['expires'], by_name['饮血']
    assert '触发' in by_name['五险一金']['expires'], by_name['五险一金']


def test_normalize_helper_tolerates_old_shape():
    """前端兼容旧数据：纯字符串数组也要能渲染（升级瞬间不白屏）。"""
    # 这条是前端逻辑，这里只校验服务端不会再下发旧形状
    assert all(
        isinstance(e, dict) and 'name' in e and 'description' in e and 'expires' in e
        for e in server._effect_badges(_fake_player_with('subsidy'))
    )


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


def test_no_effects_yields_empty_lists(room, captured):
    """没有任何效果时下发空列表（前端据此隐藏整块）。"""
    server._emit_active_effects(room)
    for c in captured:
        assert c['data']['self'] == []
        assert c['data']['opponent'] == []


def test_effect_cleared_disappears_from_badge(room, captured):
    """效果被清掉后角标要跟着消失（旧实现这里已经会推，别回归）。"""
    room.players[P1].effect_flags.subsidy = True
    server._emit_active_effects(room)
    mine = next(c['data'] for c in captured if c['to'] == 'sid-p1')
    assert [e['name'] for e in mine['self']] == ['百亿补贴']

    captured.clear()
    room.players[P1].effect_flags.subsidy = False
    server._emit_active_effects(room)
    mine = next(c['data'] for c in captured if c['to'] == 'sid-p1')
    assert mine['self'] == []
