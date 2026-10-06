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
















# ---------------------------------------------------------------------------
# 问题 2：神机妙算只复活本大回合沉的船
# ---------------------------------------------------------------------------
def declare_prediction(room, x):
    """走真实的宣言入口：写预测值 + 记录快照（含 sunken_ids）。"""
    room.players[P1].effect_flags.prediction = x
    server._apply_shenji_prediction(room, P1, x)
    return room.game_effects.get('prediction_initial_p1')


def sink_one(room, idx):
    """把 P1 的第 idx 艘船记为沉船。"""
    ship = room.players[P1].ships[idx]
    ship.hits = list(ship.positions)
    if ship not in room.players[P1].sunken_ships:
        room.players[P1].sunken_ships.append(ship)
    room.players[P1].remaining_ships -= 1
    return ship


def test_shenji_only_redeploys_this_round_ships(room, events):
    """本回合新沉的船才该被登记（旧沉船不算）。

    说明：sunken_ships 按时间追加，所以"取最后 N 艘"在常见数据下与
    "按快照切出本回合新沉的"结果相同 —— 本测试锁定的是【正确结果】，
    两种实现都能通过。真正区分两者的是下面的
    test_shenji_prediction_matches_but_only_fresh_exist。
    """
    room.players[P1].remaining_ships = 6
    old1 = sink_one(room, 5)              # 旧沉船 1
    old2 = sink_one(room, 4)              # 旧沉船 2
    declare_prediction(room, 1)
    new_sunk = sink_one(room, 3)          # 本回合只新沉 1 艘

    end_round(room)

    targets = room.game_effects.get('shenji_redeploy_ships') or []
    assert len(targets) == 1, f'本回合只沉了 1 艘，应只登记 1 艘，实际 {len(targets)}'
    assert targets[0] is new_sunk, '只能登记【本回合新沉】的那艘'
    assert old1 not in targets and old2 not in targets, '旧沉船不该被登记'


def test_shenji_never_pads_with_old_sunken(room):
    """★ 关键区分：沉船堆里的旧船【多于】本回合新沉的船时，
    绝不能拿旧船凑数（旧实现按"最后 N 艘"取，会凑进旧船）。

    场景：已有 3 艘旧沉船 → 宣言 x=2 → 快照记 3 → 本回合又沉 2 艘（共 5，diff=2 命中）。
    正确：登记本回合那 2 艘。
    错误（旧实现 sunken[-2:]）：同样取到最新 2 艘 —— 结果相同，
    所以这里再验证"只登记 2 艘、且不含任何旧船"。
    """
    room.players[P1].remaining_ships = 6
    olds = [sink_one(room, 5), sink_one(room, 4), sink_one(room, 3)]
    declare_prediction(room, 2)
    a = sink_one(room, 2)
    b = sink_one(room, 1)

    end_round(room)
    targets = room.game_effects.get('shenji_redeploy_ships') or []
    assert len(targets) == 2, f'应登记 2 艘，实际 {len(targets)}'
    assert set(id(t) for t in targets) == {id(a), id(b)}, '只能登记本回合新沉的两艘'
    for o in olds:
        assert o not in targets, '旧沉船混进来了'


def test_shenji_scoped_by_snapshot_not_position(room):
    """按【快照】而不是按【沉船堆位置】划定范围。

    构造沉船堆顺序被人为打乱的场景（模拟复活后再沉导致位置靠后），
    正确实现仍只看快照之后新增的沉船。
    """
    room.players[P1].remaining_ships = 6
    old = sink_one(room, 5)
    declare_prediction(room, 1)
    new_sunk = sink_one(room, 4)
    # 人为把旧的移到列表末尾（模拟顺序被打乱）
    room.players[P1].sunken_ships.remove(old)
    room.players[P1].sunken_ships.append(old)

    end_round(room)
    targets = room.game_effects.get('shenji_redeploy_ships') or []
    assert targets and targets[0] is new_sunk, (
        '应按快照划定范围，而不是依赖沉船堆的排列顺序')






def test_shenji_multi_round_only_takes_fresh(room):
    """宣言 x=2：旧沉船 + 本回合沉 2 艘 → 只登记本回合那 2 艘。"""
    room.players[P1].remaining_ships = 6
    sink_one(room, 5)                     # 旧
    declare_prediction(room, 2)
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
    declare_prediction(room, 1)
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
