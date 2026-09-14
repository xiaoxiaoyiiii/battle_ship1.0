# -*- coding: utf-8 -*-
"""出牌被拒时的提示文案：必须说真原因，不能一律甩锅给「阶段」。

作者实测反馈：
  「把那个轰炸魔法卡的报错改一下，准备阶段是可以用的，
    现在老是弹出准备阶段无法使用轰炸的警告，太烦了」

根因：`can_play_magic_card` 里「速阶1/2 只能在自己的回合使用」这条
（`room.current_attacker != player_id`）是玩家最常撞上的拒绝原因，
但 `handle_use_magic_card` 的文案分支里没有对应分支，于是掉进最后的
阶段兜底，弹出「当前阶段preparation无法使用速阶2的魔法卡」——
阶段本身完全合法（准备阶段本来就允许速阶2），玩家据此以为游戏坏了。

轰炸 = 速阶2。准备阶段 + 自己回合 本来就能用；只有
「不是自己回合」或「结束阶段」才该被拒，且原因要分开说清楚。
"""
import pytest

import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(server, 'emit', lambda *a, **k: None)
    monkeypatch.setattr(server.socketio, 'start_background_task', lambda t, *a, **k: t(*a, **k))
    monkeypatch.setattr(server, '_schedule_chain_timeout', lambda *a, **k: None)
    monkeypatch.setattr(server, '_schedule_priority_timeout', lambda *a, **k: None)
    monkeypatch.setattr(server, '_has_request_context', lambda: False)


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def make_room():
    room = GameRoom('t')
    for pid, sid, y in ((P1, 'sid-p1', 0), (P2, 'sid-p2', 5)):
        room.players[pid] = Player(
            name=pid,
            ships=[PlayerShip(positions=[Position(i, y)], hits=[]) for i in range(6)],
            attacks=[], remaining_ships=6, sid=sid)
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'preparation'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 5
    room.magic_deck = [MagicCard(n) for n in ['冻结', '疗愈', '饮血']]
    room_manager.rooms[room.id] = room
    return room


def give(room, pid, name):
    room.players[pid].magic_hand = [MagicCard(name)]


def play(room, pid, name, targets=None):
    return server.handle_use_magic_card({
        'room_id': room.id, 'player_id': pid,
        'card': {'name': name}, 'targets': targets if targets is not None else {},
    })


# ===========================================================================
# 轰炸（速阶2）
# ===========================================================================
def test_bomb_allowed_in_preparation_on_own_turn(room):
    """★ 准备阶段 + 自己回合：轰炸必须放行（作者反馈的核心）。"""
    room.current_attacker = P1
    room.current_phase = 'preparation'
    give(room, P1, '轰炸')

    res = play(room, P1, '轰炸', {'target_line': {'type': 'row', 'index': 0}})

    assert res['status'] == 'success', (
        '准备阶段本来就能用速阶2，不该被拒：' + str(res))


def test_bomb_allowed_in_battle_on_own_turn(room):
    """战斗阶段 + 自己回合：轰炸同样放行。"""
    room.current_attacker = P1
    room.current_phase = 'battle'
    give(room, P1, '轰炸')

    res = play(room, P1, '轰炸', {'target_line': {'type': 'row', 'index': 0}})
    assert res['status'] == 'success', str(res)


def test_not_your_turn_message_names_the_turn_not_the_phase(room):
    """★ 不是自己回合时，提示必须说「不是你的回合」，不能甩锅给阶段。

    这是作者看到那条烦人文案的真正来源：阶段是 preparation（合法），
    真实原因只是没轮到他。
    """
    room.current_attacker = P2          # 对方回合
    room.current_phase = 'preparation'  # 阶段本身完全合法
    give(room, P1, '轰炸')

    res = play(room, P1, '轰炸', {'target_line': {'type': 'row', 'index': 0}})

    assert res['status'] == 'error'
    msg = res['message']
    assert '不是你的回合' in msg or '自己的回合' in msg, (
        '应说清是回合问题，实际文案：' + msg)
    assert '当前阶段' not in msg, (
        '不能把原因归到阶段上（阶段本来是对的）：' + msg)
    assert '准备阶段' not in msg and 'preparation' not in msg, (
        '文案里不该出现阶段名：' + msg)


def test_genuine_phase_violation_still_names_the_phase(room):
    """真·阶段不允许时（结束阶段用速阶2），文案该照实说阶段。"""
    room.current_attacker = P1
    room.current_phase = 'end'
    give(room, P1, '轰炸')

    res = play(room, P1, '轰炸', {'target_line': {'type': 'row', 'index': 0}})

    assert res['status'] == 'error'
    assert 'end' in res['message'] or '结束阶段' in res['message'], res['message']


def test_speed3_card_still_usable_on_opponent_turn(room):
    """速阶3 任何时候都能用 —— 别被「不是你的回合」那条误伤。"""
    room.current_attacker = P2
    room.current_phase = 'battle'
    give(room, P1, '失灵！')

    res = play(room, P1, '失灵！')
    assert res['status'] == 'success', (
        '速阶3 不该受回合限制：' + str(res))


def test_speed1_card_on_opponent_turn_says_turn(room):
    """速阶1 在对方回合 → 同样报回合原因，不报阶段。"""
    room.current_attacker = P2
    room.current_phase = 'preparation'
    give(room, P1, '五险一金')

    res = play(room, P1, '五险一金')
    assert res['status'] == 'error'
    assert '当前阶段' not in res['message'], res['message']


def test_last_stand_still_wins_over_turn_message(room):
    """绝处逢生的文案优先级最高（它跟回合/阶段都没关系）。"""
    room.current_attacker = P2
    room.current_phase = 'preparation'
    room.players[P1].effect_flags.last_stand = True
    give(room, P1, '轰炸')

    res = play(room, P1, '轰炸', {'target_line': {'type': 'row', 'index': 0}})
    assert res['status'] == 'error'
    assert '绝处逢生' in res['message'], res['message']
