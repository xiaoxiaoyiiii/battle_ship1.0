# -*- coding: utf-8 -*-
"""教皇旨意「攻击次数归零」修复的回归测试（2026-09-14）。

玩家实测：教皇旨意通过后双方的攻击次数没有清零，
导致轮到自己时不能结束攻击阶段，对局卡死。

根因：
  教皇旨意是速阶1，而 can_play_magic_card 允许速阶1在【战斗阶段】使用。
  但攻击次数只在 enter_battle_phase 的「准备阶段→战斗阶段」转换里被压成 0
  （server.py 的 field_magic_name(room) == '教皇旨意' 分支）。
  从战斗阶段中途打出这张场地卡时，那个时机早已过去（或根本不会再来），
  attacks_remaining 一直停在旧值（实测 6），于是
  handle_enter_end_phase 的「还有剩余攻击次数」门禁永远拒绝 → 卡死。

修法：
  · 卡牌生效分支里【立即】把 attacks_remaining 压成 0 并广播
    （不再依赖"进入战斗阶段"那一刻）；
  · 成对处理另一面：教皇旨意被顶替/拆除时恢复攻击次数
    （否则玩家会"有船却一次也打不出去"）。
"""
import pytest

import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

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
    room.current_phase = 'preparation'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 1
    room_manager.rooms[room.id] = room
    return room


def card(name):
    return MagicCard(name)


def use(room, caster, name):
    return server.handle_use_magic_card({
        'room_id': room.id, 'player_id': caster,
        'card': {'name': name}, 'targets': {},
    })


# ---------------------------------------------------------------------------
# 核心：打出即归零
# ---------------------------------------------------------------------------
def test_papal_zeroes_attacks_immediately(room):
    """卡面「通过后双方攻击次数变为0」—— 打出当场就得归零。"""
    room.players[P1].magic_hand = [card('教皇旨意')]
    room.attacks_remaining = 6

    res = use(room, P1, '教皇旨意')
    assert res.get('status') == 'success', res
    assert room.attacks_remaining == 0, (
        f'打出后必须立即归零，实际 {room.attacks_remaining}')


def test_papal_from_battle_phase_does_not_deadlock(room, events):
    """★ 玩家实测的卡死路径：战斗阶段中途打出教皇旨意。

    修复前 attacks_remaining 停在 6 → 进结束阶段被拒 → 对局卡死。
    """
    room.players[P1].magic_hand = [card('教皇旨意')]
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert room.current_phase == 'battle'
    assert room.attacks_remaining == 6

    res = use(room, P1, '教皇旨意')
    assert res.get('status') == 'success', res
    assert room.attacks_remaining == 0, '战斗阶段打出也必须立即归零'

    end = server.handle_enter_end_phase({'room_id': room.id, 'player_id': P1})
    assert end.get('status') == 'success', (
        f'归零后应能进入结束阶段，实际被拒：{end}')
    assert room.current_phase == 'end'


def test_papal_from_preparation_then_battle(room):
    """准备阶段打出（唯一"正常"时机）也照样归零并可走完全程。"""
    room.players[P1].magic_hand = [card('教皇旨意')]
    assert use(room, P1, '教皇旨意')['status'] == 'success'
    assert room.attacks_remaining == 0

    assert server.enter_battle_phase({'room_id': room.id, 'player_id': P1})['status'] == 'success'
    assert room.attacks_remaining == 0

    assert server.handle_enter_end_phase({'room_id': room.id, 'player_id': P1})['status'] == 'success'


def test_papal_opponent_turn_also_zero(room):
    """卡面说的是「双方」：换到对方回合、进战斗阶段时同样是 0。"""
    room.players[P1].magic_hand = [card('教皇旨意')]
    use(room, P1, '教皇旨意')

    room.current_attacker = P2
    room.current_phase = 'preparation'
    room.attacks_remaining = 6

    server.enter_battle_phase({'room_id': room.id, 'player_id': P2})
    assert room.attacks_remaining == 0, '对方回合同为 0'
    end = server.handle_enter_end_phase({'room_id': room.id, 'player_id': P2})
    assert end.get('status') == 'success', '对方也不该卡死'


def test_papal_emits_attacks_updated(room, events):
    """归零后必须广播，否则前端仍显示旧次数。"""
    room.players[P1].magic_hand = [card('教皇旨意')]
    use(room, P1, '教皇旨意')

    updates = [d for e, d, to, r in events if e == 'attacks_updated']
    assert updates, '必须广播 attacks_updated'
    assert updates[-1]['attacks_remaining'] == 0


# ---------------------------------------------------------------------------
# 成对处理：教皇旨意离场时恢复攻击次数
# ---------------------------------------------------------------------------
def test_field_replacement_restores_attacks(room):
    """教皇旨意被别的场地魔法顶替后，攻击次数应按存活船数恢复。"""
    room.players[P1].magic_hand = [card('教皇旨意'), card('伊甸园')]
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    use(room, P1, '教皇旨意')
    assert room.attacks_remaining == 0

    # 换上一张别的场地魔法顶替（伊甸园也是场地卡）
    server._place_field_magic(room, P1, card('伊甸园'))
    assert room.game_effects.get('papal_edict') is None, '标记应被清掉'
    # 伊甸园规则：次数 = 6 - 船数 = 6 - 6 = 0；这里只断言"不再被教皇旨意压着"
    server._recalc_attacker_attacks(room)
    assert server.field_magic_name(room) == '伊甸园'


def test_removing_papal_restores_attacks(room):
    """加百列之光拆掉教皇旨意后，玩家应恢复攻击能力（不再恒为 0）。"""
    room.players[P1].magic_hand = [card('教皇旨意')]
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    use(room, P1, '教皇旨意')
    assert room.attacks_remaining == 0

    # 模拟加百列拆场地：清效果 + 清 field_magic
    server._clear_field_magic_effects(room)
    room.field_magic = None
    room.field_magic_owner = None

    assert room.attacks_remaining > 0, (
        f'教皇旨意离场后应恢复攻击次数，实际 {room.attacks_remaining}')
    assert room.attacks_remaining == 6


def test_removing_papal_outside_battle_also_restores(room):
    """准备阶段拆掉教皇旨意同样要恢复攻击次数。

    2026-09-14 扩大范围：恢复逻辑原先只覆盖 battle 相位（守卫写了
    current_phase == 'battle'），于是"准备阶段打出教皇旨意 → 场地被拆除 →
    进战斗阶段"这条路整段被跳过 —— 进战斗阶段时两个特例分支都不命中，
    次数停在 0，玩家 4 艘船零输出（实测复现）。
    现在拆场地的纠正在所有相位都执行，且进战斗阶段本身也无条件重算。
    """
    room.players[P1].magic_hand = [card('教皇旨意')]
    use(room, P1, '教皇旨意')
    assert room.attacks_remaining == 0
    room.current_phase = 'preparation'

    server._clear_field_magic_effects(room)
    assert room.attacks_remaining == 6, (
        f'准备阶段拆场也要恢复（6 艘船），实际 {room.attacks_remaining}')


def test_prep_phase_remove_then_battle_no_deadlock(room):
    """★ 完整卡死路径：准备阶段打教皇旨意 → 拆场 → 进战斗阶段。"""
    room.players[P1].magic_hand = [card('教皇旨意')]
    use(room, P1, '教皇旨意')

    # 模拟加百列拆场地（先 clear 再清 field_magic，与真实代码顺序一致）
    server._clear_field_magic_effects(room)
    room.field_magic = None
    room.field_magic_owner = None

    assert server.enter_battle_phase({'room_id': room.id, 'player_id': P1})['status'] == 'success'
    assert room.attacks_remaining == 6, (
        f'进入战斗阶段必须按当前规则重算，实际 {room.attacks_remaining}')
    # 真的能开炮
    res = server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 5, 'y': 5})
    assert res.get('status') == 'success', f'应能正常攻击，实际 {res}'


# ---------------------------------------------------------------------------
# 反证：教皇旨意的其他行为不受影响
# ---------------------------------------------------------------------------
def test_papal_attack_still_works(room):
    """弃卡攻击不消耗常规次数，仍可用。"""
    room.players[P1].magic_hand = [card('教皇旨意'), card('轰炸')]
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    use(room, P1, '教皇旨意')

    res = server.handle_papal_attack({
        'room_id': room.id, 'player_id': P1, 'discard_card_index': 0,
        'x': 5, 'y': 5,
    })
    assert res.get('status') == 'success', res
    assert room.attacks_remaining == 0, '弃卡攻击不消耗常规次数，仍为 0'


def test_other_field_magic_untouched(room):
    """反证：别的场地魔法不受影响（伊甸园仍按其规则算次数）。"""
    room.field_magic = card('伊甸园')
    room.players[P1].remaining_ships = 4
    server._recalc_attacker_attacks(room)
    assert room.attacks_remaining == 2, f'6-4=2，实际 {room.attacks_remaining}'
