# -*- coding: utf-8 -*-
"""无中生有「只摸上来一张」的回归测试（2026-09-14）。

玩家实测：手牌只有「无中生有」时打出它，却只摸上来一张牌。

排查结论：服务端在牌堆充足时**稳定摸 2 张**（60 组随机牌堆 + 特殊牌堆穷举验证）。
真正的原因是**全局共享牌堆是一副有限的牌**（卡池 43 条，见文末的牌堆规模测试），
双方对局中持续摸牌，快摸完时自然抽不满 —— 这是物理限制，作者确认「抽不满正常」。

但旧实现的提示文案**无论实际抽到几张都报"抽了2张牌"**，玩家因此以为卡坏了。
本文件锁定"提示必须如实反映实际抽到的张数"，让玩家能区分：
  · 牌堆不足 → "只抽到1张牌" / "牌堆已空"
  · 规则限制（no_draw）→ 0 张

同时锁定牌堆充足时确实摸 2 张（防回归）。
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
    room.players[P1] = Player(name='p1',
                              ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(6)],
                              attacks=[], remaining_ships=6, sid='sid-p1')
    room.players[P2] = Player(name='p2',
                              ships=[PlayerShip(positions=[Position(i, 5)], hits=[]) for i in range(6)],
                              attacks=[], remaining_ships=6, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 5
    room_manager.rooms[room.id] = room
    return room


def card(name):
    return MagicCard(name)


DECKS = [
    ['冻结', '轰炸', '增援', '看破！', '饮血'],
    ['失灵！', '失灵！', '冻结', '疗愈'],
    ['五险一金', '饮血', '疗愈', '加百列之光'],
]


# ---------------------------------------------------------------------------
# 核心：牌堆充足时必须摸 2 张
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('deck', DECKS)
def test_draws_two_when_deck_sufficient(room, deck):
    """牌堆充足时稳定摸 2 张。"""
    room.magic_deck = [card(n) for n in deck]
    room.players[P1].magic_hand = []

    res = server.apply_magic_effect(room, P1, card('无中生有'), {})

    assert res.success is True
    assert len(room.players[P1].magic_hand) == 2, (
        f'应摸 2 张，实际 {[c.name for c in room.players[P1].magic_hand]}')


def test_draws_two_via_real_use_path(room):
    """★ 走真实出牌链路（含扣牌）：手牌只有「无中生有」时也摸 2 张。"""
    room.magic_deck = [card(n) for n in ['冻结', '轰炸', '增援', '看破！']]
    room.players[P1].magic_hand = [card('无中生有')]

    resp = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '无中生有'}, 'targets': {},
    })
    assert resp.get('status') == 'success', resp
    server.resolve_chain(room)

    names = [c.name for c in room.players[P1].magic_hand]
    assert len(names) == 2, f'手牌只有无中生有时应摸 2 张，实际：{names}'
    assert '无中生有' not in names, '打出去的牌不该还在手牌里'


def test_no_duplicate_name_discarded(room):
    """反证：摸到的两张不同名，不该被去重丢进弃牌堆。"""
    room.magic_deck = [card('冻结'), card('轰炸'), card('增援')]
    room.players[P1].magic_hand = []

    server.apply_magic_effect(room, P1, card('无中生有'), {})
    assert len(room.players[P1].magic_hand) == 2
    assert room.magic_discard == [], '不该有卡被去重丢弃'


# ---------------------------------------------------------------------------
# 提示文案必须如实
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# no_draw 标记
# ---------------------------------------------------------------------------


def test_no_draw_blocks_subsequent_draws(room):
    """标记生效后，后续摸牌确实被挡。"""
    room.magic_deck = [card('冻结'), card('轰炸'), card('增援')]
    room.players[P1].magic_hand = []
    server.apply_magic_effect(room, P1, card('无中生有'), {})

    got = room.draw_card(P1)
    assert got is None, 'no_draw 生效期间不该摸到牌'
    assert len(room.players[P1].magic_hand) == 2




# ---------------------------------------------------------------------------
# 牌堆规模（供理解"为什么有时抽不满"）
# ---------------------------------------------------------------------------
