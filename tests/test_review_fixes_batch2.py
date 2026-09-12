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
def test_subsidy_bonus_goes_to_holder_not_attacker(room):
    server.apply_magic_effect(room, P2, card('百亿补贴'), {})
    room.players[P2].ships = [ship((0, 0)), ship((1, 0))]
    room.players[P2].remaining_ships = 2
    before = room.attacks_remaining          # P1 的攻击池

    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 0})

    assert room.attacks_remaining == before - 1, '对手的攻击池不应拿到补贴'
    assert room.players[P2].effect_flags.subsidy_bonus == 3
    assert room.players[P1].effect_flags.subsidy_bonus == 0


def test_full_fire_respects_frozen_ships(room):
    """火力全开翻倍时，冻结船不提供攻击次数。"""
    room.current_phase = 'preparation'
    room.current_attacker = P1
    room.players[P1].remaining_ships = 6
    room.players[P1].ships[0].frozen = room.round + 1
    room.players[P1].effect_flags.double_attacks = True

    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert room.attacks_remaining == (6 - 1) * 2


def test_all_ships_frozen_means_no_attack(room):
    for s in room.players[P1].ships:
        s.frozen = room.round + 1
    server._recalc_attacker_attacks(room)
    assert room.attacks_remaining == 0
    assert server.handle_attack({'room_id': room.id, 'player_id': P1,
                                 'x': 0, 'y': 5})['status'] == 'error'


def test_subsidy_bonus_applies_on_holders_turn(room):
    room.players[P2].effect_flags.subsidy = True
    room.players[P2].effect_flags.subsidy_bonus = 6
    room.current_attacker = P2
    room.players[P2].remaining_ships = 4
    server._recalc_attacker_attacks(room)
    assert room.attacks_remaining == 4 + 6


# ---------------------------------------------------------------------------
# 平等条约：快照过期 + 回滚补贴
# ---------------------------------------------------------------------------
def test_treaty_snapshot_expires_after_round(room):
    room.game_effects['last_ship_change'] = {
        'player': P2, 'count': 1, 'ship': room.players[P2].ships[0],
        'hits_added': [Position(0, 5)], 'round': 1,
    }
    room.round = 2
    res = server.apply_magic_effect(room, P2, card('平等条约'), {})
    assert res.success is False
    assert 'last_ship_change' not in room.game_effects


def test_treaty_rollback_also_removes_subsidy_bonus(room):
    server.apply_magic_effect(room, P2, card('百亿补贴'), {})
    room.players[P2].ships = [ship((0, 0)), ship((1, 0))]
    room.players[P2].remaining_ships = 2
    room.round = 1

    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 0})
    assert room.players[P2].remaining_ships == 1
    assert room.players[P2].effect_flags.subsidy_bonus == 3

    res = server.apply_magic_effect(room, P2, card('平等条约'), {})
    assert res.success is True
    assert room.players[P2].remaining_ships == 2, '船数应被回滚'
    assert room.players[P2].effect_flags.subsidy_bonus == 0, '补贴也应一并撤销'


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
def test_negated_field_card_keeps_active_field(room):
    active = card('恶魔契约')
    room.field_magic = active
    room.field_magic_owner = P2
    room.game_effects['demon_contract'] = True

    negated = card('伊甸园')
    room.chain = [ChainItem(P1, negated, [], time.time())]
    room.chain[0].negated = True

    server.resolve_chain(room)

    assert room.field_magic is active, '被无效化的场地卡不应拆掉场上已有的场地'
    assert room.game_effects.get('demon_contract') is True
    assert negated in room.magic_discard


# ---------------------------------------------------------------------------
# 终局路径必须写战绩
# ---------------------------------------------------------------------------
def test_reinforcement_countdown_skips_activation_round(room):
    """卡面：不算生效的那个大回合 —— 进入下个大回合时不应递减。"""
    room.attack_order = [P2, P1]
    room.current_attacker = P1
    room.current_phase = 'end'
    room.attacks_remaining = 0

    server.apply_magic_effect(room, P1, card('极限增援'), {})
    assert room.game_effects['reinforcement_check']['remaining_turns'] == 2

    server.end_turn({'room_id': room.id, 'player_id': P1})
    assert room.game_effects['reinforcement_check']['remaining_turns'] == 2, \
        '生效的这个大回合不计入'
    assert room.state != 'game_over'


def test_yinxue_requires_prior_hit(room):
    res = server.apply_magic_effect(room, P1, card('饮血'), {})
    assert res.success is False
    room.last_attack = {'attacker': P1, 'x': 0, 'y': 0, 'hit': True}
    assert server.apply_magic_effect(room, P1, card('饮血'), {}).success is True


def test_reinforcement_endgame_records_match(room, monkeypatch, events):
    calls = []
    monkeypatch.setattr(server.db, 'record_match', lambda *a, **k: calls.append(a))

    room.attack_order = [P2, P1]          # P1 是本大回合最后行动者
    room.current_attacker = P1
    room.current_phase = 'end'
    room.attacks_remaining = 0
    room.players[P1].remaining_ships = 4
    room.players[P2].remaining_ships = 2  # 船少者（P2）获胜
    room.game_effects['reinforcement_check'] = {
        'remaining_turns': 1, 'activated_round': room.round - 2}

    res = server.end_turn({'room_id': room.id, 'player_id': P1})
    assert res.get('game_over') is True
    assert room.state == 'game_over'
    assert room.winner == P2
    assert len(calls) == 1, '极限增援终局也应写战绩'
    assert any(e[0] == 'game_state' for e in events)
