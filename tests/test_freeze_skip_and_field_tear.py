# -*- coding: utf-8 -*-
"""Freezing 跳过回合 + 无效化类卡牌主动拆场地 的回归测试（2026-09-14）。

【需求 1 · Freezing！/神之宣告 的跳过】
  作者裁定：跳过的不是"小回合轮转"（P1 跳过 P2 后自己连续行动），
  而是【直接进入下一个大回合】—— 重新猜拳 + 重新发牌。
  旧实现把 skip 判定放在 `next_index == 0` 的"新大回合"判断【之后】，
  于是"跳过对方后索引绕回起点"这件事根本不会被看到。

【需求 2 · 无效化类卡牌要能主动拆已贴出的场地魔法】
  作者裁定：失灵！与加百列之光 ——
    · 有连锁栈  → 正常康连锁项（不额外拆场地）
    · 无连锁栈  → 主动拆掉当前生效的场地魔法
  归属不限：自己贴的和对方贴的都能拆。
  这让"场地早贴上了、过了一会想反悔"有解 —— 旧实现在无连锁时只会回退
  magic_history，场上那张场地反而拆不掉。
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
    room.current_phase = 'preparation'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 5
    room.magic_deck = [MagicCard(n) for n in ['冻结', '轰炸', '增援', '疗愈']]
    room_manager.rooms[room.id] = room
    return room


def card(name):
    return MagicCard(name)


# ===========================================================================
# 需求 1：Freezing！ 跳过后直接进新大回合
# ===========================================================================
def arm_skip(room, target=P2):
    room.current_attacker = P1
    room.current_phase = 'end'
    room.attacks_remaining = 0
    room.skip_opponent_turn = target


def test_skip_enters_new_round(room):
    """★ 跳过对方后应直接进入新大回合（round +1），而不是轮回到自己。"""
    arm_skip(room)
    before = room.round

    server.end_turn({'room_id': room.id, 'player_id': P1})

    assert room.round == before + 1, f'应进入新大回合，实际 round={room.round}'
    assert room.state == 'rock_paper_scissors', '应重新猜拳'


def test_skip_emits_rps_state(room, events):
    """要广播 rock_paper_scissors，前端才会切到猜拳界面。"""
    arm_skip(room)
    server.end_turn({'room_id': room.id, 'player_id': P1})

    states = [d.get('state') for e, d, to, r in events if e == 'game_state']
    assert 'rock_paper_scissors' in states, f'应广播猜拳状态，实际：{states}'


def test_skip_resets_phase(room):
    """★ 阶段必须重置：Freezing！ 是在结束阶段打出的，
    若把 current_phase 留在 'end'，新大回合一开始就处于结束阶段。"""
    arm_skip(room)
    server.end_turn({'room_id': room.id, 'player_id': P1})

    assert room.current_phase != 'end', f'阶段应重置，实际 {room.current_phase}'
    assert room.current_phase == 'preparation'


def test_skip_clears_flag(room):
    """标记用完要清掉，避免后续回合误跳。"""
    arm_skip(room)
    server.end_turn({'room_id': room.id, 'player_id': P1})
    assert room.skip_opponent_turn is None


def test_new_round_redraws(room):
    """新大回合会重新发牌（先手 1 张、后手 2 张）—— 由猜拳流程负责。"""
    arm_skip(room)
    server.end_turn({'room_id': room.id, 'player_id': P1})

    # 猜拳后手牌应增加（先手 1 / 后手 2）
    server.handle_rps_choice({'room_id': room.id, 'player_id': P1, 'choice': 'rock'})
    server.handle_rps_choice({'room_id': room.id, 'player_id': P2, 'choice': 'scissors'})

    total = len(room.players[P1].magic_hand) + len(room.players[P2].magic_hand)
    assert total == 3, f'新大回合应发 3 张牌（先手1+后手2），实际 {total}'


def test_normal_turn_rotation_unaffected(room):
    """反证：没有 skip 时，正常轮转不受影响（仍进 P2 的准备阶段）。"""
    room.current_attacker = P1
    room.current_phase = 'end'
    room.attacks_remaining = 0
    before = room.round

    server.end_turn({'room_id': room.id, 'player_id': P1})

    assert room.round == before, '不该进新大回合'
    assert room.current_attacker == P2
    assert room.current_phase == 'preparation'


def test_last_player_end_turn_still_new_round(room):
    """反证：最后一个行动者交回合，照常进新大回合。"""
    room.current_attacker = P2
    room.current_phase = 'end'
    room.attacks_remaining = 0
    before = room.round

    server.end_turn({'room_id': room.id, 'player_id': P2})

    assert room.round == before + 1
    assert room.state == 'rock_paper_scissors'


def test_skip_next_turn_also_new_round(room):
    """skip_next_turn 走同一口径（另一个跳过标记）。"""
    room.current_attacker = P1
    room.current_phase = 'end'
    room.attacks_remaining = 0
    room.skip_next_turn = P2
    before = room.round

    server.end_turn({'room_id': room.id, 'player_id': P1})

    assert room.round == before + 1, 'skip_next_turn 跳过后也该进新大回合'


# ===========================================================================
# 需求 2：无效化类卡牌主动拆场地
# ===========================================================================
def put_field(room, name, owner=P2):
    room.field_magic = card(name)
    room.field_magic_owner = owner
    if name == '恶魔契约':
        room.game_effects['demon_contract'] = True
    return room.field_magic


@pytest.mark.parametrize('tear_card', ['失灵！', '加百列之光'])
def test_tear_opponent_field(room, tear_card):
    """★ 无连锁时，失灵！/加百列之光 主动拆掉对方的场地。"""
    put_field(room, '恶魔契约', owner=P2)

    res = server.apply_magic_effect(room, P1, card(tear_card), {})

    assert res.success is True, f'{tear_card} 应成功，实际：{res.message}'
    assert room.field_magic is None, '场地应被拆除'
    assert 'demon_contract' not in room.game_effects, '房间级标记要一并清掉'
    assert '恶魔契约' in res.message, f'提示应点名拆了哪张，实际：{res.message}'


@pytest.mark.parametrize('tear_card', ['失灵！', '加百列之光'])
def test_tear_own_field(room, tear_card):
    """★ 作者裁定：自己贴的场地也能拆。"""
    put_field(room, '恶魔契约', owner=P1)

    res = server.apply_magic_effect(room, P1, card(tear_card), {})

    assert res.success is True, res.message
    assert room.field_magic is None, '自己贴的场地也该被拆'


def test_tear_broadcasts_field_update(room, events):
    """拆场地要广播，双方界面一起刷新。"""
    put_field(room, '恶魔契约')
    server.apply_magic_effect(room, P1, card('失灵！'), {})

    updates = [d for e, d, to, r in events if e == 'field_magic_updated']
    assert updates, '必须广播 field_magic_updated'
    assert updates[-1]['card'] is None


def test_tear_restores_attacks_for_papal(room):
    """拆掉教皇旨意后攻击次数要恢复（否则玩家有船却打不出去）。"""
    put_field(room, '教皇旨意', owner=P2)
    room.attacks_remaining = 0

    server.apply_magic_effect(room, P1, card('失灵！'), {})

    assert room.field_magic is None
    assert room.attacks_remaining > 0, f'攻击次数应恢复，实际 {room.attacks_remaining}'


# ---------------------------------------------------------------------------
# 对照：有连锁栈时仍以康连锁为主
# ---------------------------------------------------------------------------
def test_chain_takes_priority_over_tearing(room):
    """★ 有连锁栈时康连锁项，【不】拆场地（二选一口径）。"""
    put_field(room, '恶魔契约', owner=P2)
    room.chain = [ChainItem(P2, card('轰炸'), {}, 0)]

    res = server.apply_magic_effect(room, P1, card('加百列之光'), {})

    assert getattr(res, 'negate_target', False) is True, '应标记无效化连锁项'
    assert room.field_magic is not None, '有连锁时不该顺带拆场地'


def test_lingwu_chain_still_negates(room):
    """反证：失灵！在连锁里照旧康牌。"""
    room.chain = [ChainItem(P2, card('轰炸'), {}, 0)]
    res = server.apply_magic_effect(room, P1, card('失灵！'), {})
    assert getattr(res, 'negate_target', False) is True


# ---------------------------------------------------------------------------
# 对照：无连锁、无场地
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('tear_card', ['失灵！', '加百列之光'])
def test_no_target_reports_failure(room, tear_card):
    """无连锁、无场地 → 明确失败，不白扔一张牌。"""
    assert room.field_magic is None
    assert not room.chain

    res = server.apply_magic_effect(room, P1, card(tear_card), {})

    assert res.success is False
    assert '没有可无效化' in res.message


def test_lingwu_falls_back_to_history_without_field(room):
    """反证：无连锁、无场地时，失灵！仍回退到历史记录（原有能力不丢）。"""
    room.magic_history = [{'card': card('轰炸'), 'caster': P2, 'round': room.round}]

    res = server.apply_magic_effect(room, P1, card('失灵！'), {})

    assert res.success is True, res.message
    assert room.magic_history == [], '历史条目应被消费'
