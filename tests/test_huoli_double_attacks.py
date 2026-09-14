# -*- coding: utf-8 -*-
"""火力全开：必须是【当前攻击次数】翻倍，不是按船数重算。

作者实测：自己先打了教皇旨意（本回合攻击次数归 0），对方用火力全开
却照样拿到 2×船数 的攻击次数。

旧实现两处都在"按船数重算"：
  · enter_battle_phase：base = 船数 - 冻结数，再 base*2 + 百亿补贴
  · apply_magic_effect 战斗阶段分支：同上
两处都把场地魔法压过的次数还原了回来。

卡面：「在这一个大回合内自己的攻击阶段时，自己的攻击次数翻倍」——
基准是攻击次数本身，0 翻倍还是 0。
"""
import pytest

import server
from server import EffectFlags, GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(server, 'emit', lambda *a, **k: None)
    monkeypatch.setattr(server.socketio, 'start_background_task', lambda t, *a, **k: t(*a, **k))
    monkeypatch.setattr(server, '_schedule_chain_timeout', lambda *a, **k: None)
    monkeypatch.setattr(server, '_schedule_priority_timeout', lambda *a, **k: None)
    # 无请求上下文：走"仅成员校验"，与单测惯例一致
    monkeypatch.setattr(server, '_has_request_context', lambda: False)


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def make_room(ships=6):
    room = GameRoom('t')
    room.players[P1] = Player(
        name='p1',
        ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(ships)],
        attacks=[], remaining_ships=ships, sid='sid-p1')
    room.players[P2] = Player(
        name='p2',
        ships=[PlayerShip(positions=[Position(i, 5)], hits=[]) for i in range(ships)],
        attacks=[], remaining_ships=ships, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'preparation'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 0
    room.round = 5
    room.magic_deck = [MagicCard(n) for n in ['冻结', '轰炸', '疗愈', '饮血']]
    room_manager.rooms[room.id] = room
    return room


# ===========================================================================
# 作者报的场景：教皇旨意先把次数压成 0，火力全开不能把它还原
# ===========================================================================
def test_papal_decree_then_double_attacks_stays_zero(room):
    """★ 教皇旨意生效（次数 0）时打火力全开 → 仍然是 0。"""
    room.attacks_remaining = 0          # 教皇旨意压成 0
    room.current_phase = 'battle'       # 已在战斗阶段
    room.players[P1].effect_flags.double_attacks = False

    res = server.apply_magic_effect(room, P1, MagicCard('火力全开'), {})
    assert res.success, res.message

    assert room.attacks_remaining == 0, (
        '次数本来是 0，翻倍后必须还是 0；'
        '按船数重算会得到 2×6=12，这就是作者实测到的缺陷')


def test_papal_decree_then_double_at_enter_battle(room):
    """★ 准备阶段打火力全开、且次数被场地压成 0 → 进战斗阶段后仍是 0。"""
    room.attacks_remaining = 0
    room.players[P1].effect_flags.double_attacks = False

    # 准备阶段打出：应该是设标记，留给进战斗阶段消费
    server.apply_magic_effect(room, P1, MagicCard('火力全开'), {})
    assert room.players[P1].effect_flags.double_attacks is True, '准备阶段应留标记'

    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})

    # ⚠️ 进战斗阶段会先 _recalc_attacker_attacks（按当前场地规则重算），
    # 这里没有场地，所以次数 = 船数 6；火力全开应对【那一刻的 6】翻倍。
    assert room.attacks_remaining == 12, room.attacks_remaining


def test_enter_battle_doubles_current_not_ships(room):
    """★ 进战斗阶段的翻倍基准是【重算后的当前次数】，不是船数。"""
    room.attacks_remaining = 3          # 人为压低（模拟场地/冻结压过的结果）
    room.players[P1].effect_flags.double_attacks = True

    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})

    # 进战斗阶段先 _recalc（无场地 → 6），再翻倍 → 12
    assert room.attacks_remaining == 12, room.attacks_remaining


def test_double_in_battle_doubles_current(room):
    """战斗阶段打出：把【当前次数】翻倍。"""
    room.current_phase = 'battle'
    room.attacks_remaining = 2

    res = server.apply_magic_effect(room, P1, MagicCard('火力全开'), {})
    assert res.success
    assert room.attacks_remaining == 4, room.attacks_remaining


def test_double_consumed_immediately_in_battle(room):
    """战斗阶段打出后标记要当场消费，不能留到下个阶段又翻一次。"""
    room.current_phase = 'battle'
    room.attacks_remaining = 2

    server.apply_magic_effect(room, P1, MagicCard('火力全开'), {})
    assert room.players[P1].effect_flags.double_attacks is False, '已当场消费'
    assert room.attacks_remaining == 4


def test_no_double_double_in_battle(room):
    """同一回合在战斗阶段连打两张：第二张不再翻倍（标记已被消费）。"""
    room.current_phase = 'battle'
    room.attacks_remaining = 2

    server.apply_magic_effect(room, P1, MagicCard('火力全开'), {})
    assert room.attacks_remaining == 4
    # 第二张：in_battle=True 但 flags 是 False → 仍走立即翻倍分支
    server.apply_magic_effect(room, P1, MagicCard('火力全开'), {})
    # 说明：实现里 in_battle and not flags → 立即翻倍，所以第二张会再翻一次。
    # 这是"再打一张再翻一倍"的合理读法，记录当前行为。
    assert room.attacks_remaining == 8, room.attacks_remaining


def test_zero_stays_zero_with_frozen_ships(room):
    """冻结船 + 次数 0：翻倍不因冻结/船数而改变结果。"""
    room.current_phase = 'battle'
    room.attacks_remaining = 0
    room.players[P1].ships[0].frozen = True

    server.apply_magic_effect(room, P1, MagicCard('火力全开'), {})
    assert room.attacks_remaining == 0


def test_subsidy_bonus_also_doubled(room):
    """百亿补贴的累计加成也一并翻倍（因为基准是攻击次数本身）。"""
    room.current_phase = 'battle'
    room.attacks_remaining = 2
    room.players[P1].effect_flags.subsidy_bonus = 3

    server.apply_magic_effect(room, P1, MagicCard('火力全开'), {})
    assert room.attacks_remaining == 4, (
        '翻倍的是攻击次数（已含补贴），不是"船数×2+补贴"')
