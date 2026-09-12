# -*- coding: utf-8 -*-
"""多级连锁「无效化」修复的回归测试（2026-09-14）。

玩家实测报的问题：
  同一个连锁里「对方出牌 → 我用失灵 → 我又用加百列」，
  加百列没有无效化失灵，导致失灵照常无效化了对方的第一张牌。

根因：加百列之光（以及失灵！）判断无效化目标时要求
  `room.chain[-1].player_id != caster_id`（即"只能康对方的牌"）。
  自连锁时栈顶正下方是【自己】刚打的失灵，该条件为假 →
  不设 negate_target → 失灵照常结算 → 康掉了第一张牌。

作者裁定：同一连锁里后手应能推翻前手，一律无效化「正下方那一项」，不看归属。
本文件同时锁定「被谁康掉」的提示语义（negated_by），
区分"被别人康了"与"自己发动失败"这两种完全不同的失败。
"""
import pytest

import server
from server import ChainItem, GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def events(monkeypatch):
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    monkeypatch.setattr(server.socketio, 'start_background_task',
                        lambda target, *a, **k: None)
    monkeypatch.setattr(server, '_schedule_chain_timeout', lambda *a, **k: None)
    return captured


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def make_room():
    room = GameRoom('test-room')
    room.players[P1] = Player(name='p1', ships=[ship_obj()], attacks=[], remaining_ships=3, sid='sid-p1')
    room.players[P2] = Player(name='p2', ships=[ship_obj((5, 5))], attacks=[], remaining_ships=3, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 3
    room.round = 1
    room_manager.rooms[room.id] = room
    return room


def ship_obj(*cells):
    return PlayerShip(positions=[Position(x, y) for x, y in (cells or ((0, 0),))], hits=[])


def card(name):
    return MagicCard(name)


def build_chain(room, spec):
    """spec: [(player, cardname), ...] 从栈底到栈顶。"""
    room.chain = [ChainItem(pl, card(cn), {}, i) for i, (pl, cn) in enumerate(spec)]
    return room.chain


def by_name(results, name):
    return next(r for r in results if r.card.name == name)


# ---------------------------------------------------------------------------
# 核心：自连锁时，后手能推翻前手
# ---------------------------------------------------------------------------
def test_self_chain_gabriel_negates_own_lingwu(room):
    """★ 玩家场景：对方出牌 → 我失灵 → 我又加百列。

    加百列必须无效化我前面打的失灵，使失灵不再康掉对方那张牌。
    """
    build_chain(room, [(P1, '无中生有'), (P2, '失灵！'), (P2, '加百列之光')])
    results = server.resolve_chain(room)

    gab = by_name(results, '加百列之光')
    ling = by_name(results, '失灵！')
    first = by_name(results, '无中生有')

    assert gab.success is True, '加百列应正常结算'
    assert getattr(ling, 'negated_skip', False) is True, (
        '失灵必须被加百列无效化（这正是修复点）')
    assert first.success is True, '对方第一张牌不再被失灵无效化，应正常生效'
    assert not getattr(first, 'negated_skip', False)


def test_self_chain_records_negated_by(room):
    """被康的项要记下「被谁康的」，供前端给出明确因果。"""
    build_chain(room, [(P1, '无中生有'), (P2, '失灵！'), (P2, '加百列之光')])
    results = server.resolve_chain(room)

    ling = by_name(results, '失灵！')
    assert getattr(ling, 'negated_by', None) == '加百列之光'
    assert '加百列之光' in ling.message, f'提示应点名是谁康的：{ling.message}'


def test_negated_message_distinguishes_from_own_failure(room):
    """「被康」与「自己发动失败」的提示必须能区分开。"""
    build_chain(room, [(P1, '无中生有'), (P2, '失灵！'), (P2, '加百列之光')])
    results = server.resolve_chain(room)
    ling = by_name(results, '失灵！')
    assert getattr(ling, 'negated_skip', False) is True

    # 对照：失灵康不动加百列，是「发动失败」而不是「被康」
    room2 = make_room()
    build_chain(room2, [(P1, '加百列之光'), (P2, '失灵！')])
    results2 = server.resolve_chain(room2)
    ling2 = by_name(results2, '失灵！')
    assert ling2.success is False
    assert not getattr(ling2, 'negated_skip', False), (
        '免疫导致的失败不该被标成"被无效化"')
    room_manager.rooms.pop(room2.id, None)


# ---------------------------------------------------------------------------
# 反证：正常顺序（康对方的牌）不受影响
# ---------------------------------------------------------------------------
def test_gabriel_still_negates_opponent_card(room):
    """反证：加百列康【对方】的牌，行为不变。"""
    build_chain(room, [(P1, '无中生有'), (P2, '加百列之光')])
    results = server.resolve_chain(room)

    assert by_name(results, '加百列之光').success is True
    assert getattr(by_name(results, '无中生有'), 'negated_skip', False) is True


def test_lingwu_still_negates_opponent_card(room):
    """反证：失灵康对方的牌，行为不变。"""
    build_chain(room, [(P1, '无中生有'), (P2, '失灵！')])
    results = server.resolve_chain(room)

    ling = by_name(results, '失灵！')
    assert ling.success is True
    assert getattr(by_name(results, '无中生有'), 'negated_skip', False) is True
    assert getattr(by_name(results, '无中生有'), 'negated_by', None) == '失灵！'


def test_lingwu_still_immune_to_gabriel(room):
    """反证：加百列免疫失灵，这条卡面规则不能因为本次改动而失效。"""
    build_chain(room, [(P1, '加百列之光'), (P2, '失灵！')])
    results = server.resolve_chain(room)

    ling = by_name(results, '失灵！')
    assert ling.success is False
    assert '免疫' in ling.message


def test_lingwu_still_immune_to_kanpo(room):
    """反证：看破！优先于失灵！。"""
    build_chain(room, [(P1, '看破！'), (P2, '失灵！')])
    results = server.resolve_chain(room)

    ling = by_name(results, '失灵！')
    assert ling.success is False
    assert '看破' in ling.message


# ---------------------------------------------------------------------------
# 自连锁：失灵康自己前面打的牌
# ---------------------------------------------------------------------------
def test_self_chain_lingwu_negates_own_lingwu(room):
    """失灵自连锁：后一个失灵康掉前一个失灵。"""
    build_chain(room, [(P1, '无中生有'), (P2, '失灵！'), (P2, '失灵！')])
    results = server.resolve_chain(room)

    # 出栈顺序：[P2 失灵(顶), P2 失灵(中), P1 无中生有]
    lings = [r for r in results if r.card.name == '失灵！']
    assert lings[0].success is True, '栈顶的失灵应正常发动'
    assert getattr(lings[1], 'negated_skip', False) is True, '下面那个失灵应被康掉'
    # 第一个失灵被康 → 对方第一张牌不再被康
    assert by_name(results, '无中生有').success is True


# ---------------------------------------------------------------------------
# 端到端：走真实事件链路（出牌 → 连锁响应 → 结算）
# ---------------------------------------------------------------------------
def test_end_to_end_self_chain(room):
    """完整链路：P1 出牌 → P2 失灵 → P2 加百列 → 结算。"""
    room.players[P1].magic_hand = [card('无中生有'), card('看破！')]
    room.players[P2].magic_hand = [card('失灵！'), card('加百列之光')]
    room.magic_deck = [card('冻结'), card('轰炸'), card('增援')]

    assert server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '无中生有'}, 'targets': {},
    })['status'] == 'success'

    assert server.chain_response({
        'room_id': room.id, 'player_id': P2, 'chain': True,
        'card': {'name': '失灵！'}, 'targets': [],
    })['status'] == 'success'

    assert server.chain_response({
        'room_id': room.id, 'player_id': P2, 'chain': True,
        'card': {'name': '加百列之光'}, 'targets': [],
    })['status'] == 'success'

    # 窗口最终会回到 P1；结算由放弃/超时触发，这里直接结算
    if room.chain:
        server.resolve_chain(room)

    hand = [c.name for c in room.players[P1].magic_hand]
    assert '无中生有' not in hand, '无中生有已打出'
    # 无中生有效果是"摸两张"，若被失灵康掉就不会摸到牌
    assert '冻结' in hand and '轰炸' in hand, (
        f'无中生有应正常生效（摸2张），实际手牌：{hand}')
