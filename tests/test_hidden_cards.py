# -*- coding: utf-8 -*-
"""「暂时隐藏的卡牌」回归测试（2026-09-16）。

作者需求：「把钢筋铁骨这张卡牌暂时隐藏，就是让人不能摸到这张牌」。

做法：`server.HIDDEN_CARD_NAMES` 里的卡名**不进共享牌堆**（见 `init_player_magic`）。
本文件锁三件事：

  1. 名单本身是有效的 —— 卡名真实存在，防手滑拼错导致"隐藏"**静默失效**
  2. 牌堆里确实没有它 —— 而且是「把整副牌抽干也抽不到」，直接验语义本身，
     而不是只验一个长度（长度对了但卡还在牌堆里的写法是可能的）
  3. 它是**隐藏**不是**删除** —— 卡池、卡面数据、结算分支都还在，复原只需删一个卡名

设计稿：`docs/superpowers/specs/2026-09-16-hide-gangjintiegu-design.md`
"""
import pytest

import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def events(monkeypatch):
    """隔离 emit：draw_card 会广播 hand_updated。"""
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


def make_room():
    room = GameRoom('hidden-cards-room')
    room.players[P1] = Player(
        name='p1', ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(6)],
        attacks=[], remaining_ships=6, sid='sid-p1')
    room.players[P2] = Player(
        name='p2', ships=[PlayerShip(positions=[Position(i, 5)], hits=[]) for i in range(6)],
        attacks=[], remaining_ships=6, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 1
    room_manager.rooms[room.id] = room
    return room


def pool_names():
    return [c.name for c in server.magic_cards]


def expected_deck_size():
    """牌堆应有的张数 = 卡池里没被隐藏的那些（失灵！有 3 份，所以按条数算而不是按卡名去重）。"""
    return sum(1 for c in server.magic_cards if c.name not in server.HIDDEN_CARD_NAMES)


# ---------------------------------------------------------------------------
# 1. 名单有效性：拼错卡名会让"隐藏"静默失效，必须挡住
# ---------------------------------------------------------------------------
def test_hidden_names_actually_exist_in_pool():
    unknown = [n for n in server.HIDDEN_CARD_NAMES if n not in pool_names()]
    assert not unknown, f'隐藏名单里有卡池中不存在的卡名（拼错了？）：{unknown}'


# ---------------------------------------------------------------------------
# 2. 牌堆里确实没有它
# ---------------------------------------------------------------------------
def test_new_room_deck_excludes_hidden_cards(room):
    room.init_player_magic(P1, server.magic_cards)

    deck = [c.name for c in room.magic_deck]
    leaked = sorted(set(deck) & server.HIDDEN_CARD_NAMES)
    assert not leaked, f'隐藏卡仍然进了牌堆：{leaked}'
    assert len(deck) == expected_deck_size(), (
        f'牌堆应 {expected_deck_size()} 张（卡池 {len(server.magic_cards)} 减去隐藏 '
        f'{len(server.HIDDEN_CARD_NAMES)} 个卡名），实际 {len(deck)} 张')


def test_draining_whole_deck_never_yields_hidden_card(room):
    """★ 直接验「摸不到」：双方轮流把整副牌抽干，看看到底出现过哪些卡名。

    注意重复卡会被丢进弃牌堆（draw_card 返回 None），所以手牌和弃牌堆都要看 ——
    只看手牌会漏掉"抽上来又被丢掉"的那部分。
    """
    room.init_player_magic(P1, server.magic_cards)
    total = len(room.magic_deck)
    assert total > 0, '牌堆不该是空的'

    turn = 0
    while room.magic_deck:
        pid = P1 if turn % 2 == 0 else P2
        turn += 1
        room.draw_card(pid)
        assert turn <= total, f'抽了 {turn} 次还没抽干 {total} 张的牌堆，循环没有收敛'

    emerged = [c.name for c in room.players[P1].magic_hand]
    emerged += [c.name for c in room.players[P2].magic_hand]
    emerged += [c.name for c in room.magic_discard]

    assert len(emerged) == total, (
        f'牌堆 {total} 张，但手牌+弃牌堆只追到 {len(emerged)} 张 —— 抽干过程本身有问题')
    leaked = sorted({n for n in emerged if n in server.HIDDEN_CARD_NAMES})
    assert not leaked, f'把整副牌抽干之后仍然摸到了隐藏卡：{leaked}'


# ---------------------------------------------------------------------------
# 3. 是「隐藏」不是「删除」：复原只需删一个卡名
# ---------------------------------------------------------------------------
def test_hidden_card_is_hidden_not_deleted(room):
    for name in server.HIDDEN_CARD_NAMES:
        assert name in pool_names(), (
            f'{name} 不该从卡池里消失 —— 那会破坏前后端一致性与针对性用例，'
            f'也会让"暂时隐藏"变成"永久删除"')

    card = next(c for c in server.magic_cards if c.name == '钢筋铁骨')
    assert card.speed == 3 and card.type == '普通', '卡面数据不该被动过'
    assert card.description, '卡面描述不该被清空'

    # 结算分支也原样保留：直接发动仍然正常（牺牲一艘，其余无敌）
    room.players[P1].ships = [
        PlayerShip(positions=[Position(0, 0)], hits=[]),
        PlayerShip(positions=[Position(1, 1)], hits=[]),
        PlayerShip(positions=[Position(2, 2)], hits=[]),
    ]
    room.players[P1].remaining_ships = 3
    res = server.apply_magic_effect(room, P1, MagicCard('钢筋铁骨'), {})
    assert res.success is True
    assert room.players[P1].remaining_ships == 2
    assert all(s.invincible for s in room.players[P1].ships)
