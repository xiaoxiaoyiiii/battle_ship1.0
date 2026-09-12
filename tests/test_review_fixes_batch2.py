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
    """魔法卡造成的击沉被无效化时，百亿补贴发的 +3 也要一并撤销。

    改版后炮击造成的击沉不再可被无效化（卡面只针对魔法卡），
    所以这里用魔法来源的快照来覆盖「回滚连带撤销补贴」这条逻辑。
    """
    server.apply_magic_effect(room, P2, card('百亿补贴'), {})
    victim = ship((0, 0))
    room.players[P2].ships = [victim]
    room.players[P2].remaining_ships = 1
    room.round = 1

    # 走统一副作用入口，来源标为魔法（溅射/轰炸/硫磺火焰走的就是这条）
    server._on_ship_destroyed(room, P2, victim, source='magic')
    room.players[P2].remaining_ships = 0
    assert room.players[P2].effect_flags.subsidy_bonus == 3
    assert room.game_effects['last_ship_change'].get('subsidy_granted') is True

    res = server.apply_magic_effect(room, P2, card('平等条约'), {})
    assert res.success is True
    assert room.players[P2].remaining_ships == 1, '船数应被回滚'
    assert room.players[P2].effect_flags.subsidy_bonus == 0, '补贴也应一并撤销'


def test_treaty_cannot_rollback_attack_kill_any_more(room):
    """炮击造成的击沉：改版后平等条约无效化不了（补贴也不该被撤销）。"""
    server.apply_magic_effect(room, P2, card('百亿补贴'), {})
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1
    room.round = 1

    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 0})
    assert room.players[P2].remaining_ships == 0
    assert room.players[P2].effect_flags.subsidy_bonus == 3

    res = server.apply_magic_effect(room, P2, card('平等条约'), {})
    assert res.success is False
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

# ---------------------------------------------------------------------------
# 第二批补充：卡牌语义修正（余音绕梁/疗愈/神之宣告/克苏鲁之眼/绝处逢生/失灵！）
# ---------------------------------------------------------------------------
def make_book_room():
    return None


def test_yuyin_requires_preparation_phase(room):
    """卡面：余音绕梁只能在自己的准备阶段使用"""
    room.current_phase = 'battle'
    res = server.apply_magic_effect(room, P1, card('余音绕梁'), {})
    assert res.success is False
    assert not getattr(room.players[P1].effect_flags, 'forced_kill', 0)


def test_liaoyu_revives_in_place(room):
    """疗愈：原地复活（不再是"选一个未打过的新格子"）"""
    sunk = ship((2, 2))
    sunk.hits = list(sunk.positions)
    room.players[P1].ships = [sunk]
    room.players[P1].sunken_ships = [sunk]
    room.players[P1].remaining_ships = 0
    room.players[P1].attacks = [Position(2, 2)]
    room.players[P2].attacks = [Position(2, 2)]

    res = server.apply_magic_effect(room, P1, card('疗愈'), {})
    assert res.success is True
    assert room.players[P1].remaining_ships == 1
    assert sunk.hits == [], '复活必须清空命中'
    assert sunk.positions[0].x == 2 and sunk.positions[0].y == 2, '原地复活'
    assert all(not (a.x == 2 and a.y == 2) for a in room.players[P1].attacks)
    assert 'pending_placement' not in room.magic_temp_data


def test_cancel_magic_selection_returns_cards_to_deck(room):
    """取消桃园结义选择：已抽出的牌放回牌堆，不凭空消失"""
    drawn = [card('轰炸'), card('疗愈')]
    room.magic_deck = [card('冻结')]
    room.magic_temp_data = {'type': 'taoyuan_choice', 'caster': P1, 'cards': drawn}

    res = server.handle_cancel_magic_selection({'room_id': room.id, 'player_id': P1})
    assert res['status'] == 'success'
    assert room.magic_temp_data == {}
    names = sorted(c.name for c in room.magic_deck)
    assert names == sorted(['冻结', '轰炸', '疗愈'])


def test_cancel_magic_selection_rejects_other_player(room):
    room.magic_temp_data = {'type': 'taoyuan_choice', 'caster': P2, 'cards': []}
    res = server.handle_cancel_magic_selection({'room_id': room.id, 'player_id': P1})
    assert res['status'] == 'error'


def test_cancel_magic_selection_refuses_placement(room):
    room.magic_temp_data = {'pending_placement': {'caster': P1, 'kind': 'reinforce',
                                                  'remaining': 1, 'total': 1, 'placed': 0}}
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
    room.magic_temp_data = {'pending_sacrifice': {'player': P1, 'reason': 'divine_decree'}}

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

