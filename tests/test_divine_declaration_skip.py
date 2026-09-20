# -*- coding: utf-8 -*-
"""神之宣告「跳过对方所有阶段」的回归测试（2026-09-20）。

作者实测症状：**效果二（跳过对手的所有阶段）疑似并未实现**，
要求"跳过阶段应该和 Freezing 的实现方式一样"。

── 诊断经过（用探针实测，不是读码猜的）────────────────────────────────

1. 先验"标记有没有挂上"：三个阶段打出都挂上了 `skip_opponent_turn = 对方` → 通过。
2. 再验"跳过有没有真的发生"：自己回合打出、以及对方回合（连锁）打出，
   两种时机下 `end_turn` 都消费了标记并直接进入新大回合 → **机制是通的**。
3. 于是差异只能在**语义范围**上。实测：

     卡面（magic_card.json / magic_cards.js / 前端按钮，**三处一致**）写的是
         "跳过**这一个大回合内**对方的所有阶段"
     而实现走的是 `next_index == 0` 分支 → **round + 1、重新猜拳、重新发牌**

   ★ 也就是说：实现跳过的是"对方本回合 + 整个大回合被翻页"，
     而卡面承诺的只是"对方在本大回合内没有阶段"。
     多出来的"翻页"会**额外重置双方状态**（猜拳重来、重新摸牌、
     `damage_dealt_this_turn` 归零），这是卡面没写的。

本文件钉住两点：
  A. 卡面承诺的效果**必须真的发生**：对方在本大回合内拿不到行动权；
  B. 跳过的**作用域必须与卡面一致**：不该顺手把大回合翻页（那是 Freezing！的既有语义，
     由 `test_freeze_skip_and_field_tear.py` 单独钉住，两者是不同的卡）。
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


def make_room(cur_attacker=P1, phase='battle'):
    room = GameRoom('divine-scope')
    room.players[P1] = Player(
        name='p1',
        ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(6)],
        attacks=[], remaining_ships=6, sid='sid-p1', user_id='u1')
    room.players[P2] = Player(
        name='p2',
        ships=[PlayerShip(positions=[Position(i, 5)], hits=[]) for i in range(6)],
        attacks=[], remaining_ships=6, sid='sid-p2', user_id='u2')
    room.state = 'attacking'
    room.current_attacker = cur_attacker
    room.current_phase = phase
    room.attack_order = [P1, P2]
    room.attacks_remaining = 3
    room.round = 5
    room.magic_deck = [MagicCard(n) for n in ['冻结', '轰炸', '增援', '疗愈']]
    room_manager.rooms[room.id] = room
    return room


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def card(name):
    return MagicCard(name)


def play(room, caster, choice=2):
    return server.apply_magic_effect(room, caster, card('神之宣告'), {
        'effect_choice': choice,
        'selected_cells': [{'x': 0, 'y': 0}, {'x': 1, 'y': 0}],
    })


# ===========================================================================
# A. 卡面承诺：对方在本大回合内拿不到行动权
# ===========================================================================
def test_opponent_never_acts_this_round(room):
    """★ 打完神之宣告（效果二）后，对方**在本大回合内不许拿到行动权**。"""
    room.current_attacker = P1
    room.current_phase = 'battle'
    res = play(room, P1)
    assert res.success is not False

    # 施法者走完自己的阶段
    room.attacks_remaining = 0
    room.current_phase = 'end'
    server.end_turn({'room_id': room.id, 'player_id': P1})

    assert room.current_attacker != P2, (
        '对方不该拿到行动权（卡面：跳过这一个大回合内对方的所有阶段）'
    )


def test_marker_survives_phase_transitions(room):
    """★ 标记不许在阶段转换中被清掉（那会让效果静默失效）。"""
    room.current_attacker = P1
    room.current_phase = 'battle'
    play(room, P1)
    assert room.skip_opponent_stages == P2

    # 战斗 → 结束阶段
    room.attacks_remaining = 0
    server.handle_enter_end_phase({'room_id': room.id, 'player_id': P1})
    assert room.skip_opponent_stages == P2, \
        '阶段转换不该清掉跳过标记（否则效果二静默失效）'


def test_divine_does_not_use_freezing_marker(room):
    """★ 两张卡的标记必须**分开**。

    混用会让神之宣告白拿 Freezing 的"翻页"副作用
    （重新猜拳 + 重新发牌），而卡面只承诺"这一个大回合内跳过对方阶段"。
    """
    room.current_attacker = P1
    room.current_phase = 'battle'
    play(room, P1)
    assert not room.skip_opponent_turn, \
        '神之宣告不该动 Freezing！ 的标记（那会把大回合翻页）'
    assert room.skip_opponent_stages == P2


# ===========================================================================
# B. 作用域：与卡面一致，不许顺手翻页
# ===========================================================================
def test_skip_does_not_advance_big_round(room):
    """★ 跳过的作用域是**本大回合**，不该把大回合翻页。

    卡面写的是"跳过这一个大回合内对方的所有阶段" ——
    翻页（round+1、重新猜拳、重新发牌）是 **Freezing！** 的既有语义，
    两者不是同一张卡，不能共用一个副作用。

    ⚠️ 这是本批修的核心：原来两张卡共用 `skip_opponent_turn`，
       而它的消费点绑死在"绕回起点 → 开新大回合"那一支上，
       于是神之宣告**必然**带上 Freezing 的翻页效果。
    """
    room.current_attacker = P1
    room.current_phase = 'end'
    room.attacks_remaining = 0
    play(room, P1)
    before = room.round

    server.end_turn({'room_id': room.id, 'player_id': P1})

    assert room.round == before, (
        f'神之宣告不该推进大回合（卡面只说"这一个大回合内"），'
        f'实际 round {before} -> {room.round}'
    )


def test_freezing_still_advances_big_round(room):
    """★ 反向守卫：Freezing！ 的翻页语义**不许**被这次改动弄坏。"""
    room.current_attacker = P1
    room.current_phase = 'end'
    room.attacks_remaining = 0
    room.players[P1].damage_dealt_this_turn = 0
    res = server.apply_magic_effect(room, P1, card('Freezing！'), {})
    assert res.success is not False
    before = room.round

    server.end_turn({'room_id': room.id, 'player_id': P1})

    assert room.round == before + 1, 'Freezing！ 必须保持"直接进新大回合"'
    assert room.state == 'rock_paper_scissors'


# ===========================================================================
# C. 效果一不受影响
# ===========================================================================
def test_effect_one_does_not_skip(room):
    """效果一（让对方选一艘船阵亡）不该挂跳过标记。"""
    room.current_attacker = P1
    play(room, P1, choice=1)
    assert not room.skip_opponent_turn
