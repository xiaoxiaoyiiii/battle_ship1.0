# -*- coding: utf-8 -*-
"""极限增援平局 + 神机妙算沉船归属 的回归测试（2026-09-14）。

【问题 1 · 极限增援】
  玩家实测：结算时双方船数相同，却出现了"获胜"判定。
  根因：船数相同时用 random.choice 随机选一个获胜者 —— 胜负交给运气，
  而且玩家/AI 双方看到的结果不透明。
  作者裁定：船数相同时【不结算，继续对局】。

【问题 2 · 神机妙算】
  卡面「那些原本会减少的船不会减少并……重新部署」。
  作者确认：只算【神机妙算触发的这一个大回合】里沉的船；
  上一回合就沉掉的船不属于"原本会减少的船"，不该被复活。
  旧实现取 sunken_ships 的最后 N 艘，会把更早回合的旧沉船也算进来。
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


def make_room(p1_ships=4, p2_ships=4):
    room = GameRoom('test-room')
    room.players[P1] = Player(name='p1',
                              ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(6)],
                              attacks=[], remaining_ships=p1_ships, sid='sid-p1')
    room.players[P2] = Player(name='p2',
                              ships=[PlayerShip(positions=[Position(i, 5)], hits=[]) for i in range(6)],
                              attacks=[], remaining_ships=p2_ships, sid='sid-p2')
    room.state = 'attacking'
    # 必须由"最后一个行动者"交回合才会进入新大回合（next_index == 0）
    room.current_attacker = P2
    room.current_phase = 'end'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 0
    room.round = 10
    room_manager.rooms[room.id] = room
    return room


def card(name):
    return MagicCard(name)


def arm_reinforcement(room, remaining_turns=1):
    room.game_effects['reinforcement_check'] = {
        'caster': P1, 'remaining_turns': remaining_turns,
        'activated_round': room.round - 2,
    }


def end_round(room):
    """由最后一个行动者交回合，触发大回合结束的判定。"""
    room.current_phase = 'end'
    room.attacks_remaining = 0
    room.current_attacker = P2
    return server.end_turn({'room_id': room.id, 'player_id': P2})


# ---------------------------------------------------------------------------
# 问题 1：极限增援平局不结算
# ---------------------------------------------------------------------------
def test_reinforcement_tie_does_not_finish_game(room, events):
    """★ 船数相同时不得判负/判胜，继续对局。"""
    arm_reinforcement(room)
    assert room.players[P1].remaining_ships == room.players[P2].remaining_ships

    res = end_round(room)

    assert room.state != 'game_over', f'平局不该结束对局，实际 state={room.state}'
    assert not room.winner, f'平局不该产生胜者，实际 winner={room.winner!r}'
    assert res.get('game_over') is not True


def test_reinforcement_tie_emits_explanation(room, events):
    """平局时要给出明确提示，别让玩家一脸茫然。"""
    arm_reinforcement(room)
    end_round(room)

    texts = [d.get('text', '') for e, d, to, r in events if e == 'message']
    assert any('船数相同' in t or '无人获胜' in t for t in texts), (
        f'应有平局提示，实际：{texts}')


def test_reinforcement_tie_clears_effect(room):
    """平局后作废这张卡，避免每回合反复判定。"""
    arm_reinforcement(room)
    end_round(room)
    assert 'reinforcement_check' not in room.game_effects, '平局后效果应结束'


def test_reinforcement_tie_is_not_random(room):
    """反复触发多次都应保持"不结算"（旧实现是 random.choice，会随机出胜者）。"""
    for _ in range(8):
        r = make_room(4, 4)
        arm_reinforcement(r)
        end_round(r)
        assert r.state != 'game_over', '平局在任何一次随机下都不该结束对局'
        assert not r.winner
        room_manager.rooms.pop(r.id, None)


def test_reinforcement_fewer_ships_still_wins(room):
    """反证：一方船少时照常判其获胜。"""
    room.players[P1].remaining_ships = 3
    room.players[P2].remaining_ships = 5
    arm_reinforcement(room)
    end_round(room)
    assert room.state == 'game_over'
    assert room.winner == P1, f'船少的 P1 应获胜，实际 {room.winner}'


def test_reinforcement_other_side_wins(room):
    """反证：反过来也一样。"""
    room.players[P1].remaining_ships = 5
    room.players[P2].remaining_ships = 3
    arm_reinforcement(room)
    end_round(room)
    assert room.winner == P2, f'船少的 P2 应获胜，实际 {room.winner}'


def test_reinforcement_no_double_winner_broadcast(room, events):
    """一次结算只能广播一个胜者（防"双方都被宣布胜利"）。"""
    room.players[P1].remaining_ships = 3
    room.players[P2].remaining_ships = 5
    arm_reinforcement(room)
    end_round(room)

    winners = {d['winner'] for e, d, to, r in events
               if e in ('game_over', 'game_state')
               and isinstance(d, dict) and d.get('winner')}
    assert len(winners) <= 1, f'不该出现多个胜者，实际：{winners}'


def test_reinforcement_after_game_over_is_idempotent(room):
    """对局结束后再次交回合不会翻转胜负。"""
    room.players[P1].remaining_ships = 3
    room.players[P2].remaining_ships = 5
    arm_reinforcement(room)
    end_round(room)
    first = room.winner

    res = end_round(room)
    assert room.winner == first, '胜负不该被二次改写'
    assert res.get('status') == 'error', '对局已结束，应拒绝'


# ---------------------------------------------------------------------------
# 问题 2：神机妙算只复活本大回合沉的船
# ---------------------------------------------------------------------------
def sink_one(room, idx):
    """把 P1 的第 idx 艘船记为沉船。"""
    ship = room.players[P1].ships[idx]
    ship.hits = list(ship.positions)
    if ship not in room.players[P1].sunken_ships:
        room.players[P1].sunken_ships.append(ship)
    room.players[P1].remaining_ships -= 1
    return ship


def test_shenji_only_redeploys_this_round_ships(room, events):
    """★ 上一回合就沉的船不该被复活，只算本大回合新沉的。"""
    room.players[P1].remaining_ships = 6
    old_sunk = sink_one(room, 5)          # 旧沉船
    room.players[P1].effect_flags.prediction = 1
    # 宣言时快照：已经沉了 1 艘（那艘是旧的）
    room.game_effects['prediction_initial_p1'] = {'ships': 5, 'sunken': 1}
    new_sunk = sink_one(room, 4)          # 本回合新沉

    end_round(room)

    targets = room.game_effects.get('shenji_redeploy_ships') or []
    assert targets, '应登记待部署的船'
    assert targets[0] is new_sunk, '只能登记【本回合新沉】的那艘'
    assert old_sunk not in targets, '旧沉船不该被登记'


def test_shenji_redeploy_keeps_old_sunken(room):
    """部署完成后，旧沉船仍应留在沉船堆里（没被误复活）。"""
    room.players[P1].remaining_ships = 6
    old_sunk = sink_one(room, 5)
    room.players[P1].effect_flags.prediction = 1
    room.game_effects['prediction_initial_p1'] = {'ships': 5, 'sunken': 1}
    sink_one(room, 4)

    end_round(room)
    res = server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 3, 'y': 3}})
    assert res.get('status') == 'success', res

    assert old_sunk in room.players[P1].sunken_ships, '旧沉船应留着'
    assert room.players[P1].remaining_ships == 5, '只恢复 1 艘'


def test_shenji_no_old_sunken_still_works(room):
    """反证：没有旧沉船时行为不变。"""
    room.players[P1].remaining_ships = 6
    room.players[P1].effect_flags.prediction = 1
    room.game_effects['prediction_initial_p1'] = {'ships': 6, 'sunken': 0}
    sunk = sink_one(room, 5)

    end_round(room)
    targets = room.game_effects.get('shenji_redeploy_ships') or []
    assert targets and targets[0] is sunk


def test_shenji_multi_round_only_takes_fresh(room):
    """宣言 x=2：旧沉船 + 本回合沉 2 艘 → 只登记本回合那 2 艘。"""
    room.players[P1].remaining_ships = 6
    sink_one(room, 5)                     # 旧
    room.players[P1].effect_flags.prediction = 2
    room.game_effects['prediction_initial_p1'] = {'ships': 5, 'sunken': 1}
    a = sink_one(room, 4)
    b = sink_one(room, 3)

    end_round(room)
    targets = room.game_effects.get('shenji_redeploy_ships') or []
    assert len(targets) == 2, f'应登记 2 艘，实际 {len(targets)}'
    assert set(id(t) for t in targets) == {id(a), id(b)}


def test_shenji_old_sunken_never_placed(room):
    """即使玩家反复点选，旧沉船也不会被放回棋盘。"""
    room.players[P1].remaining_ships = 6
    old_sunk = sink_one(room, 5)
    room.players[P1].effect_flags.prediction = 1
    room.game_effects['prediction_initial_p1'] = {'ships': 5, 'sunken': 1}
    sink_one(room, 4)

    end_round(room)
    # 只放一艘，之后流程即结束（(1,1) 是空位：(0,0)~(5,0) 才是活船/沉船所在）
    res1 = server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 1, 'y': 1}})
    assert res1.get('status') == 'success', res1
    assert not room.magic_temp_data.get('pending_placement')

    # 再点一次不该有反应（流程已结束）
    res = server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 2, 'y': 2}})
    assert res.get('status') == 'error'
    assert old_sunk in room.players[P1].sunken_ships, '旧沉船必须还在'
