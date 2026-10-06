# -*- coding: utf-8 -*-
"""八方来财「船数主动变化」全方向覆盖的回归测试（2026-09-14）。

玩家实测：用死者苏生复活自己的船（船数 5→6），八方来财没有摸牌。

根因：
  卡面是「接下来如果场上的战舰数目【主动发生了变化】，每发生一次变化，
  自己摸一张牌。己方击败对方的船不算主动发生变化。」
  「变化」是双向的，但实现只在【减少】方向挂了这个效果 ——
  船被击沉的五个分支各写了一份（还互相重复），
  【增加】方向（死者苏生 / 增援 / 疗愈 / 神机妙算 / 神威归还）一处都没有。

修法：
  抽出 _notify_treasure_hunter(room, player_id, times) 作为唯一入口，
  增减两个方向的船数变更点都调它；既有的五处重复实现也统一收敛过去。
  这样以后再加"改变船数"的新卡，只要走这个函数就不会漏。
"""
import pytest

import server
from server import ChainItem, GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'

DECK = ['冻结', '轰炸', '增援', '疗愈', '看破！', '饮血', '五险一金']


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


def setup(room, hand=()):
    """P1 持八方来财 + 牌堆充足；手牌只放给定卡，便于断言摸到几张。"""
    room.players[P1].effect_flags.treasure_hunter = True
    room.magic_deck = [card(n) for n in DECK]
    room.players[P1].magic_hand = [card(n) for n in hand]


def make_sunk(room, n=1):
    """把 P1 的前 n 艘船做成沉船（供复活类使用）。"""
    sunk = []
    for sh in list(room.players[P1].ships)[:n]:
        sh.hits = list(sh.positions)
        sunk.append(sh)
        room.players[P1].ships.remove(sh)
        room.players[P1].remaining_ships -= 1
    room.players[P1].sunken_ships = sunk
    return sunk


def place_at(room, pid, x, y):
    return server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': pid, 'position': {'x': x, 'y': y}})


# ---------------------------------------------------------------------------
# 核心：船数【增加】时摸牌
# ---------------------------------------------------------------------------
def test_treasure_hunter_on_revive(room):
    """★ 玩家场景：死者苏生复活自己的船 → 应摸一张。"""
    setup(room, ['死者苏生'])
    make_sunk(room, 1)
    assert room.players[P1].remaining_ships == 5

    server.apply_magic_effect(room, P1, card('死者苏生'), {})
    place_at(room, P1, 3, 3)

    assert room.players[P1].remaining_ships == 6, '复活应成功'
    hand = [c.name for c in room.players[P1].magic_hand]
    assert '冻结' in hand, f'船数增加应触发八方来财，实际手牌：{hand}'


def test_treasure_hunter_on_reinforce(room):
    """增援：召唤一艘船也是主动增加。

    注意：增援受 6 艘上限约束，所以要先让棋盘上有空位。
    """
    setup(room, ['增援'])
    make_sunk(room, 1)          # 先沉一艘，腾出位置
    assert room.players[P1].remaining_ships == 5

    server.apply_magic_effect(room, P1, card('增援'), {})
    place_at(room, P1, 3, 3)

    assert room.players[P1].remaining_ships == 6, '增援应成功'
    hand = [c.name for c in room.players[P1].magic_hand]
    # 手牌基数 = ['增援']（直接调 apply 不会扣牌）+ 摸到的 1 张
    assert '冻结' in hand, f'增援应触发八方来财，实际手牌：{hand}'








# ---------------------------------------------------------------------------
# 反证：减少方向（既有实现）不能被改坏
# ---------------------------------------------------------------------------
def test_treasure_hunter_still_works_on_sink(room):
    """反证：船被对方击沉仍要摸牌。"""
    setup(room)
    room.current_attacker = P2
    before = len(room.players[P1].magic_hand)

    server.handle_attack({'room_id': room.id, 'player_id': P2, 'x': 0, 'y': 0})

    assert room.players[P1].remaining_ships < 6, '这一炮应该击沉了船'
    assert len(room.players[P1].magic_hand) > before, '减少方向仍要摸牌'




# ---------------------------------------------------------------------------
# 反证：未持卡时不该有任何摸牌
# ---------------------------------------------------------------------------
def test_no_draw_without_treasure_hunter(room):
    room.magic_deck = [card(n) for n in DECK]
    room.players[P1].magic_hand = []
    assert room.players[P1].effect_flags.treasure_hunter is False

    server.apply_magic_effect(room, P1, card('增援'), {})
    place_at(room, P1, 3, 3)

    assert room.players[P1].magic_hand == [], '未持卡不该摸牌'




def test_notify_helper_draws_for_holder(room):
    """辅助函数本身：持卡则摸 times 张。"""
    setup(room)
    assert server._notify_treasure_hunter(room, 3) == 3
    assert len(room.players[P1].magic_hand) == 3




def test_notify_helper_hits_every_holder(room):
    """★ 判定对象是【全场的船数变化】，摸牌的是【持卡者】—— 两者解耦。

    双方都持八方来财时，一次船数变化两人各摸一张。
    """
    setup(room)
    room.players[P2].effect_flags.treasure_hunter = True
    assert server._notify_treasure_hunter(room, 1) == 2, '两位持卡者各摸一张'
    assert len(room.players[P1].magic_hand) == 1
    assert len(room.players[P2].magic_hand) == 1




# ---------------------------------------------------------------------------
# 作者澄清的语义：判定对象是【全场】的船数主动变化，摸牌的是持卡者
# ---------------------------------------------------------------------------
def test_opponent_revive_also_triggers_holder(room):
    """★ 对方用死者苏生复活【对方自己】的船 → 持卡者也要摸牌。

    卡面「场上的战舰数目主动发生了变化」说的是全场；
    "己方击败对方的船不算"只排除【攻击造成的减少】。
    """
    setup(room)                      # 只有 P1 持卡
    # 让 P2 有沉船可复活
    sunk = room.players[P2].ships[0]
    sunk.hits = list(sunk.positions)
    room.players[P2].sunken_ships = [sunk]
    room.players[P2].remaining_ships = 5

    server._revive_sunken_ships(room, room.players[P2], 1)

    hand = [c.name for c in room.players[P1].magic_hand]
    assert len(hand) == 1, f'对方复活自己的船，持卡者应摸一张，实际：{hand}'




def test_holder_attack_sinking_opponent_does_not_draw(room):
    """★ 卡面排除项：持卡者【自己】开炮击沉对方的船 → 不摸牌。"""
    setup(room)
    room.current_attacker = P1
    server._apply_ship_sunk_effects(
        room, room.id, P1, P2, room.players[P2].ships[5])

    assert room.players[P1].magic_hand == [], (
        f'"己方击败对方的船不算"，实际摸了：{[c.name for c in room.players[P1].magic_hand]}')


def test_opponent_attack_sinking_holder_does_draw(room):
    """★ 对方开炮击沉【持卡者自己】的船 → 持卡者要摸牌。"""
    setup(room)
    room.current_attacker = P2
    server._apply_ship_sunk_effects(
        room, room.id, P2, P1, room.players[P1].ships[5])

    assert len(room.players[P1].magic_hand) == 1, (
        '是对方击败了我方，属于主动变化')


def test_magic_sinking_holder_by_self_still_draws(room):
    """持卡者用【魔法卡】击沉对方的船 → 仍要摸牌。

    卡面排除的是"击败"（攻击），魔法卡造成的变化照算。
    """
    setup(room)
    server._apply_ship_loss_linkage(room, P1, P2, count=1)
    assert len(room.players[P1].magic_hand) == 1, (
        '魔法卡不是"击败"，不该被排除')
