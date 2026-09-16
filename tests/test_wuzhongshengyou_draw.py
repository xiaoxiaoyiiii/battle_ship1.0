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
def test_message_reports_one_when_deck_has_one(room):
    """★ 牌堆只剩 1 张时，提示必须说"只抽到1张"，不能说"抽了2张"。"""
    room.magic_deck = [card('冻结')]
    room.players[P1].magic_hand = []

    res = server.apply_magic_effect(room, P1, card('无中生有'), {})

    assert len(room.players[P1].magic_hand) == 1
    assert '1张' in res.message, f'应如实说只抽到 1 张，实际：{res.message}'
    assert '2张' not in res.message, f'不该谎报抽了 2 张，实际：{res.message}'


def test_message_reports_empty_deck(room):
    """★ 牌堆为空时，提示必须说明是牌堆空了。"""
    room.magic_deck = []
    room.players[P1].magic_hand = []

    res = server.apply_magic_effect(room, P1, card('无中生有'), {})

    assert room.players[P1].magic_hand == []
    assert '牌堆已空' in res.message or '没有抽到' in res.message, (
        f'应说明牌堆空了，实际：{res.message}')
    assert '抽了2张' not in res.message


def test_message_two_when_full_draw(room):
    """牌堆充足时文案照旧（别把正常路径改坏）。"""
    room.magic_deck = [card('冻结'), card('轰炸')]
    room.players[P1].magic_hand = []

    res = server.apply_magic_effect(room, P1, card('无中生有'), {})
    assert '2张' in res.message


# ---------------------------------------------------------------------------
# no_draw 标记
# ---------------------------------------------------------------------------
def test_no_draw_flag_set_after_drawing(room):
    """标记必须在两次摸牌【之后】设置，否则会把自己挡掉。"""
    room.magic_deck = [card('冻结'), card('轰炸')]
    room.players[P1].magic_hand = []

    server.apply_magic_effect(room, P1, card('无中生有'), {})

    assert room.players[P1].effect_flags.no_draw is True
    assert room.players[P2].effect_flags.no_draw is True
    assert len(room.players[P1].magic_hand) == 2, '自己不该被自己的标记挡住'


def test_no_draw_blocks_subsequent_draws(room):
    """标记生效后，后续摸牌确实被挡。"""
    room.magic_deck = [card('冻结'), card('轰炸'), card('增援')]
    room.players[P1].magic_hand = []
    server.apply_magic_effect(room, P1, card('无中生有'), {})

    got = room.draw_card(P1)
    assert got is None, 'no_draw 生效期间不该摸到牌'
    assert len(room.players[P1].magic_hand) == 2


def test_residual_no_draw_blocks_all(room):
    """残留的 no_draw 会把两张都挡掉（提示应如实说 0 张）。"""
    room.magic_deck = [card('冻结'), card('轰炸')]
    room.players[P1].magic_hand = []
    room.players[P1].effect_flags.no_draw = True

    res = server.apply_magic_effect(room, P1, card('无中生有'), {})

    assert room.players[P1].magic_hand == []
    assert '抽了2张' not in res.message, '实际一张没抽到，不该说抽了 2 张'


# ---------------------------------------------------------------------------
# 牌堆规模（供理解"为什么有时抽不满"）
# ---------------------------------------------------------------------------
def test_deck_size_is_finite(room):
    """牌堆是一副有限的全局共享牌，双方共用 —— 抽不满是物理限制。

    卡池 43 条；**实际进牌堆的张数 = 卡池减去 `server.HIDDEN_CARD_NAMES`**
    （暂时隐藏的卡不进牌堆，见 tests/test_hidden_cards.py）。
    """
    deck = server.magic_cards
    assert len(deck) == 43, f'卡池应 43 条，实际 {len(deck)}'
    names = [c.name for c in deck]
    dups = {n for n in names if names.count(n) > 1}
    assert dups == {'失灵！'}, f'只有「失灵！」是多份，实际重复：{dups}'

    hidden = sum(1 for n in names if n in server.HIDDEN_CARD_NAMES)
    assert hidden == len(server.HIDDEN_CARD_NAMES), '隐藏名单里的每个卡名都应当真实存在于卡池'

    room.init_player_magic(P1, server.magic_cards)
    assert len(room.magic_deck) == len(deck) - hidden, (
        f'牌堆应 {len(deck) - hidden} 张（卡池 {len(deck)} 减去隐藏 {hidden}），'
        f'实际 {len(room.magic_deck)}')
