# -*- coding: utf-8 -*-
"""审查修复批（第二批）：百亿补贴归属 / 平等条约过期 / 溅射崩溃 /
无效化场地卡副作用 / 终局记战绩 的真实链路回归测试。"""
import time

import pytest

import server
from server import (ChainItem, GameRoom, MagicCard, Player, PlayerShip,
                    Position, room_manager)

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def events(monkeypatch):
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    return captured


def ship(*cells):
    return PlayerShip(positions=[Position(x, y) for x, y in cells], hits=[])


def card(name):
    return MagicCard(name)


def make_room(ships1=6, ships2=6):
    r = GameRoom('review-room-2')
    r.players[P1] = Player(name='p1', ships=[ship((i, 0)) for i in range(ships1)],
                           attacks=[], remaining_ships=ships1, sid='sid-p1', user_id='u1')
    r.players[P2] = Player(name='p2', ships=[ship((i, 5)) for i in range(ships2)],
                           attacks=[], remaining_ships=ships2, sid='sid-p2', user_id='u2')
    r.state = 'attacking'
    r.current_attacker = P1
    r.current_phase = 'battle'
    r.attack_order = [P1, P2]
    r.attacks_remaining = ships1
    r.round = 1
    room_manager.rooms[r.id] = r
    return r


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)
    room_manager.match_queue = []


# ---------------------------------------------------------------------------
# 百亿补贴：+3 必须归持卡者自己
# ---------------------------------------------------------------------------


def test_full_fire_respects_frozen_ships(room):
    """火力全开翻倍时，冻结船不提供攻击次数。"""
    room.current_phase = 'preparation'
    room.current_attacker = P1
    room.players[P1].remaining_ships = 6
    room.players[P1].ships[0].frozen = room.round + 1
    room.players[P1].effect_flags.double_attacks = True

    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert room.attacks_remaining == (6 - 1) * 2






# ---------------------------------------------------------------------------
# 平等条约：炮击击沉康不动（快照机制已删，见 tests/test_pingdeng_tiaoyue_chain.py）
# ---------------------------------------------------------------------------
def test_treaty_cannot_negate_attack_kill_and_keeps_subsidy(room):
    """炮击造成的击沉：平等条约无效化不了（补贴也不该被撤销）。

    ★ 2026-09-24 改版：原来的"船数变化快照"整条删除 —— 平等条约改成**连锁无效化**
      （目标 = 栈中正下方那一项）。本用例保留它真正要守的两件事：
      ① 炮击击沉不可被康、船不会回来；② 百亿补贴已经发出去的 +3 不会被撤销。
      旧版那条"回滚连带撤销补贴"的用例随快照一起删除 —— 现在**根本没有回滚**。
    """
    server.apply_magic_effect(room, P2, card('百亿补贴'), {})
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1
    room.round = 1

    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 0})
    assert room.players[P2].remaining_ships == 0
    assert room.players[P2].effect_flags.subsidy_bonus == 3

    res = server.apply_magic_effect(room, P2, card('平等条约'), {})
    assert res.success is False
    assert res.message, '失败必须有文案'
    assert room.players[P2].remaining_ships == 0, '炮击击沉不该被回滚'
    assert room.players[P2].effect_flags.subsidy_bonus == 3, '补贴也不该被撤销'


# ---------------------------------------------------------------------------
# 溅射 + 回光返照：必须返回 ChainResult（曾返回 dict 导致连锁崩溃）
# ---------------------------------------------------------------------------
def test_splash_last_chance_returns_chain_result(room):
    room.players[P2].ships = [ship((3, 2)), ship((5, 5))]
    room.players[P2].remaining_ships = 2
    room.game_effects['last_chance'] = {'caster': P2, 'active': True, 'round': 1}
    room.last_attack = {'attacker': P1, 'x': 3, 'y': 3, 'hit': True}

    res = server.apply_magic_effect(room, P1, card('溅射'), {})
    assert hasattr(res, 'success'), '必须返回 ChainResult，否则 resolve_chain 会 AttributeError'
    assert res.caster == P1
    assert res['game_over'] is True
    assert room.state == 'game_over'
    assert room.winner == P1


# ---------------------------------------------------------------------------
# 被无效化的场地卡不得拆掉场上已有场地
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 终局路径必须写战绩
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# 第二批补充：卡牌语义修正（余音绕梁/疗愈/神之宣告/克苏鲁之眼/绝处逢生/失灵！）
# ---------------------------------------------------------------------------
def make_book_room():
    return None








def test_cancel_magic_selection_rejects_other_player(room):
    room.magic_temp_data = {'type': 'taoyuan_choice', 'caster': P2, 'cards': []}
    res = server.handle_cancel_magic_selection({'room_id': room.id, 'player_id': P1})
    assert res['status'] == 'error'




def test_attack_rejects_fractional_coordinates(room):
    """1.9 这类小数不应被 int() 静默截断成 1"""
    res = server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 1.9, 'y': 0})
    assert res['status'] == 'error'
    assert room.players[P1].attacks == []
    assert room.attacks_remaining == 6


def test_attack_on_empty_enemy_board_does_not_instant_win(room):
    """对手还没有船（未布船/放置流程中途）时，一击不应判胜"""
    room.players[P2].ships = []
    room.players[P2].remaining_ships = 0
    res = server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 0})
    assert res.get('game_over') is not True
    assert room.state != 'game_over'


def test_room_sync_carries_state_flags_and_pending_picks(room):
    """重连快照要带上状态标记与"待自己点选"的信息"""
    room.players[P1].magic_blocked = True
    room.players[P1].effect_flags.no_draw = True
    # ⚠️ 2026-09-20：待选改走**优先队列**（旧实现是 `magic_temp_data` 单槽，
    #    会被第二个请求覆盖、也会被 `magic_temp_data = {}` 抹掉）。
    server._request_ship_pick(room, P1, 'divine_decree', 'm')

    snap = server._build_room_sync(room, P1)
    assert snap['magic_blocked'] is True
    assert snap['effect_flags'].get('no_draw') is True
    assert snap['pending_sacrifice']['reason'] == 'divine_decree'
    assert len(snap['pending_sacrifice_ships']) == len(room.players[P1].ships)

    # 对手视角不应看到"待我方点选"
    snap2 = server._build_room_sync(room, P2)
    assert snap2['pending_sacrifice'] is None


def test_shiling_cannot_negate_previous_round_magic(room):
    """卡面：被影响的魔法卡必须为"当前时段刚使用的"""
    room.round = 2
    room.magic_history = [{'card': card('轰炸'), 'caster': P2, 'round': 1}]
    res = server.apply_magic_effect(room, P1, card('失灵！'), {})
    assert res.success is False
    assert len(room.magic_history) == 1, '过期条目不应被吃掉'

