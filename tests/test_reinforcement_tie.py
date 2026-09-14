# -*- coding: utf-8 -*-
"""「极限增援结算时双方船数相同 → 回合卡死」回归测试（2026-09-14）。

作者反馈：
    极限增援卡牌出现问题。当双方船数相同时不会判定谁获胜，
    但是游戏会直接卡死，无法进行下一步操作，就是不能结束阶段了按钮直接消失了。

根因：`end_turn` 里 `if next_index == 0:` 那一段是【进入新大回合】的收尾
（`room.state = 'rock_paper_scissors'`、`current_phase = 'preparation'`、
广播 `game_state`），极限增援的结算就夹在中间。平局分支以前写的是

    room.game_effects.pop('reinforcement_check', None)
    emit('message', {…'无人获胜'…})
    return {'status': 'success'}        # ← 把后面的收尾全跳过

而这个 return 之前 `room.round` 已经 +1 了。结果是：回合不推进、阶段留在 'end'、
一条状态事件都不发 —— 客户端界面停在旧阶段，交回合按钮不可见/按不动，
玩家看到的就是"卡死、按钮消失"。实测：tools/reinforcement_tie_check.mjs。

正确行为（作者裁定）：平局不判胜负，但**照常进入新大回合、继续对局**。
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
                        lambda target, *a, **k: target(*a, **k))
    monkeypatch.setattr(server, '_schedule_chain_timeout', lambda *a, **k: None)
    monkeypatch.setattr(server, '_schedule_priority_timeout', lambda *a, **k: None)
    monkeypatch.setattr(server, '_has_request_context', lambda: True)
    monkeypatch.setattr(server, '_maybe_run_ai_turn', lambda *a, **k: None)
    return captured


def make_room(ships_p1=4, ships_p2=4, remaining_turns=0):
    """当前攻击者是 P2（attack_order 的最后一位）——
    这样 P2 结束回合时 next_index 会绕回 0，走到"进入新大回合"那一段，
    极限增援的结算就在里面。"""
    room = GameRoom('reinforcement-tie-room')
    room.players[P1] = Player(name='p1',
                              ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(ships_p1)],
                              attacks=[], remaining_ships=ships_p1, sid='sid-p1')
    room.players[P2] = Player(name='p2',
                              ships=[PlayerShip(positions=[Position(i, 5)], hits=[]) for i in range(ships_p2)],
                              attacks=[], remaining_ships=ships_p2, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P2
    room.current_phase = 'end'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 0
    room.round = 3
    room.game_effects['reinforcement_check'] = {
        'turn': room.round,
        'caster': P1,
        'remaining_turns': remaining_turns,
        'activated_round': room.round - 2,
    }
    room_manager.rooms[room.id] = room
    return room


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def kinds(events):
    return [e for e, _d, _t, _r in events]


# ── 平局：不判胜负，但必须继续对局 ──────────────────────────────

def test_tie_does_not_declare_a_winner(room, events):
    resp = server.end_turn({'room_id': room.id, 'player_id': P2})

    assert resp.get('game_over') is not True
    assert room.winner is None or room.winner == ''
    assert room.state != 'game_over'
    assert 'game_over' not in kinds(events), '平局不该广播 game_over'


def test_tie_advances_to_a_new_big_round(room, events):
    """★ 核心：平局之后必须照常进入新大回合，而不是停在 attacking+end。"""
    round_before = room.round

    resp = server.end_turn({'room_id': room.id, 'player_id': P2})

    assert resp.get('status') == 'success'
    assert room.round == round_before + 1, '回合数应该 +1（不是原地不动）'
    assert room.state == 'rock_paper_scissors', \
        '平局后要进入新大回合（重新猜拳），不能留在 attacking'
    assert room.current_phase == 'preparation', \
        '阶段必须重置为准备阶段，否则界面上没有可点的按钮'


def test_tie_broadcasts_the_new_round_so_clients_can_continue(room, events):
    """★ 客户端能继续操作的前提：收到状态广播。

    以前这里直接 return，一条 turn_change / phase_updated / game_state 都不发，
    客户端界面停在旧阶段 → 交回合按钮消失、下一步不了（作者反馈的"卡死"）。
    """
    server.end_turn({'room_id': room.id, 'player_id': P2})

    got = kinds(events)
    assert 'game_state' in got, '必须广播新状态，否则客户端不知道回合已经推进'
    states = [d.get('state') for e, d, _t, _r in events if e == 'game_state']
    assert 'rock_paper_scissors' in states, f'广播的状态应该是进入猜拳，实际 {states}'


def test_tie_still_tells_the_players_why_nothing_happened(room, events):
    """平局要有一句明确的播报，别让玩家以为卡了。"""
    server.end_turn({'room_id': room.id, 'player_id': P2})

    msgs = [d.get('text', '') for e, d, _t, _r in events if e == 'message']
    assert any('无人获胜' in m for m in msgs), msgs


def test_tie_effect_is_not_re_armed(room, events):
    """作废之后不能又被塞回 game_effects —— 否则每个大回合都再判一次。"""
    server.end_turn({'room_id': room.id, 'player_id': P2})

    assert 'reinforcement_check' not in room.game_effects


def test_tie_does_not_skip_a_round(room, events):
    """回合数只能 +1。旧实现在平局时 return、回合没推进，
    玩家再点一次才推进 —— 那一次会再 +1，等于这个效果白吃掉一个大回合。"""
    round_before = room.round
    server.end_turn({'room_id': room.id, 'player_id': P2})
    assert room.round == round_before + 1


# ── 非平局：仍然是"船少的一方获胜" ─────────────────────────────

def test_fewer_ships_wins_still_works(room, events):
    """船数不同时照旧结算：数量少的一方赢（P2 只有 3 艘 → P2 获胜）。"""
    room.players[P2].remaining_ships = 3

    resp = server.end_turn({'room_id': room.id, 'player_id': P2})

    assert resp.get('game_over') is True
    assert resp.get('winner') == P2
    assert room.state == 'game_over'
    assert any(e == 'game_over' for e in kinds(events)), '必须广播 game_over'


def test_more_ships_loses(room, events):
    """P2 船多 → P1 获胜。"""
    room.players[P2].remaining_ships = 5

    resp = server.end_turn({'room_id': room.id, 'player_id': P2})

    assert resp.get('game_over') is True
    assert resp.get('winner') == P1


def test_effect_still_active_before_timer_runs_out(room, events):
    """剩余回合还没到 0：只更新计数，不结算。"""
    room.game_effects['reinforcement_check']['remaining_turns'] = 2

    resp = server.end_turn({'room_id': room.id, 'player_id': P2})

    assert resp.get('status') == 'success'
    assert 'reinforcement_check' in room.game_effects, '计时没到不该作废'
    updates = [d for e, d, _t, _r in events if e == 'reinforcement_turn_updated']
    assert updates and updates[-1]['remaining_turns'] == 1, updates
