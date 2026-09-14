# -*- coding: utf-8 -*-
"""疗愈复活后，那一格必须能被对方重新攻击（作者反馈，2026-09-14）。

作者原话：「疗愈仍然存在问题 复活在原地之后对方可能无法攻击这个复活的格子
因为已经被红色叉叉占用了」

链路上的两层：
  ① 服务端：`_clear_attacks_on_cells` 已经把这一格从双方 attacks 里移除，
     `handle_attack` 的「你已经攻击过这个位置了」也就不会再拦。这层原本是对的。
  ② 前端：`gameState.myAttacks` / `opponentAttacks` 是【本地缓存】，
     而 `initGameBoards()` 只在 `!alreadyAttacked` 时才给对手棋盘的格子
     绑点击监听 —— 服务端清了但没通知前端，那个格子就一直画着 ✕ 且
     【没有点击监听】，玩家点它毫无反应。这才是真正卡住人的地方。

所以本文件既验服务端数据，也验「必须重发一份给前端」。
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
    monkeypatch.setattr(server.socketio, 'start_background_task', lambda t, *a, **k: None)
    monkeypatch.setattr(server, '_schedule_chain_timeout', lambda *a, **k: None)
    monkeypatch.setattr(server, '_schedule_priority_timeout', lambda *a, **k: None)
    monkeypatch.setattr(server, '_has_request_context', lambda: False)
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
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 5
    room.magic_deck = [MagicCard(n) for n in ['冻结', '疗愈']]
    room_manager.rooms[room.id] = room
    return room


def sink_p2_ship_at(room, x, y):
    """让 P1 打沉 P2 在 (x,y) 的那艘单格船（走真实结算）。"""
    ship = next(s for s in room.players[P2].ships if s.positions[0].x == x)
    if room.players[P2].remaining_ships <= 1:
        # 至少要留一艘，免得直接判终局
        room.players[P2].ships.append(PlayerShip(positions=[Position(4, 4)], hits=[]))
        room.players[P2].remaining_ships += 1
    ship.positions = [Position(x, y)]
    ship.hits = []
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': x, 'y': y})
    return ship


def badges_of(events, sid, key):
    return [d.get(key) for (e, d, t, _r) in events
            if e == 'board_attacks_updated' and t == sid]


# ===========================================================================
# 服务端：清数据 + 必须重发
# ===========================================================================
def test_revive_removes_cell_from_both_attack_lists(room):
    """复活后这一格必须从双方攻击历史里消失。"""
    sink_p2_ship_at(room, 2, 5)
    assert any(a.x == 2 and a.y == 5 for a in room.players[P1].attacks), '前提：P1 打过这格'

    room.players[P2].magic_hand = [MagicCard('疗愈')]
    server.handle_use_magic_card({'room_id': room.id, 'player_id': P2,
                                  'card': {'name': '疗愈'}, 'targets': {}})

    assert not any(a.x == 2 and a.y == 5 for a in room.players[P1].attacks), \
        '复活后 P1 的攻击历史里不该再有这一格'
    assert not any(a.x == 2 and a.y == 5 for a in room.players[P2].attacks)


def test_revived_cell_can_be_attacked_again(room):
    """★ 复活后对方能再打这一格（否则这艘船永远打不沉，对手无法获胜）。"""
    sink_p2_ship_at(room, 2, 5)
    room.players[P2].magic_hand = [MagicCard('疗愈')]
    server.handle_use_magic_card({'room_id': room.id, 'player_id': P2,
                                  'card': {'name': '疗愈'}, 'targets': {}})
    # 复活后那条船还在 (2,5)
    assert any(any(p.x == 2 and p.y == 5 for p in s.positions)
               for s in room.players[P2].ships), '前提：原地复活，位置不变'

    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attacks_remaining = 3
    res = server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 2, 'y': 5})
    assert res.get('status') == 'success', f'★ 应该能再打这一格，实际 {res}'


def test_revive_broadcasts_board_attacks(room, events):
    """★ 必须把清理结果重发给前端。

    否则前端本地缓存里那格还是"打过"，`initGameBoards` 就不会给它绑点击监听。
    """
    sink_p2_ship_at(room, 2, 5)
    events.clear()

    room.players[P2].magic_hand = [MagicCard('疗愈')]
    server.handle_use_magic_card({'room_id': room.id, 'player_id': P2,
                                  'card': {'name': '疗愈'}, 'targets': {}})

    p1_my = badges_of(events, 'sid-p1', 'my_attacks')
    assert p1_my, '★ P1 应该收到 board_attacks_updated'
    flat = p1_my[-1] or []
    assert not any(a['x'] == 2 and a['y'] == 5 for a in flat), \
        f'P1 的 my_attacks 里不该再有 (2,5)：{flat}'


def test_revive_broadcasts_to_defender_too(room, events):
    """复活的这一方也要收到：他自己棋盘上那格的 ✕ 得擦掉。"""
    sink_p2_ship_at(room, 2, 5)
    events.clear()

    room.players[P2].magic_hand = [MagicCard('疗愈')]
    server.handle_use_magic_card({'room_id': room.id, 'player_id': P2,
                                  'card': {'name': '疗愈'}, 'targets': {}})

    p2_opp = badges_of(events, 'sid-p2', 'opponent_attacks')
    assert p2_opp, '★ P2 应该收到 board_attacks_updated'
    flat = p2_opp[-1] or []
    assert not any(a['x'] == 2 and a['y'] == 5 for a in flat), \
        f'P2 的 opponent_attacks 里不该再有 (2,5)：{flat}'


def test_broadcast_includes_remaining_other_cells(room, events):
    """重发必须是【完整列表】而不是只删一条：没被清的格子要留着。"""
    sink_p2_ship_at(room, 2, 5)
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 0})
    events.clear()

    room.players[P2].magic_hand = [MagicCard('疗愈')]
    server.handle_use_magic_card({'room_id': room.id, 'player_id': P2,
                                  'card': {'name': '疗愈'}, 'targets': {}})

    flat = badges_of(events, 'sid-p1', 'my_attacks')[-1]
    assert any(a['x'] == 0 and a['y'] == 0 for a in flat), \
        f'没被清理的格子要保留在列表里：{flat}'
    assert not any(a['x'] == 2 and a['y'] == 5 for a in flat)


def test_broadcast_keeps_hit_flag(room, events):
    """重发要带上 hit 标记（前端靠它决定画 ✕ 还是 ●）。"""
    sink_p2_ship_at(room, 2, 5)
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 0})
    events.clear()

    room.players[P2].magic_hand = [MagicCard('疗愈')]
    server.handle_use_magic_card({'room_id': room.id, 'player_id': P2,
                                  'card': {'name': '疗愈'}, 'targets': {}})

    flat = badges_of(events, 'sid-p1', 'my_attacks')[-1]
    entry = next(a for a in flat if a['x'] == 0 and a['y'] == 0)
    assert 'hit' in entry and isinstance(entry['hit'], bool), entry


def test_no_broadcast_when_nothing_cleared(room, events):
    """没有任何格子被清时不发这份广播（避免无意义的重绘）。"""
    events.clear()
    server._clear_attacks_on_cells(room, [Position(0, 0)])
    assert not [1 for (e, _d, _t, _r) in events if e == 'board_attacks_updated']


def test_reinforcement_also_broadcasts(room, events):
    """增援 / 重新部署走的是同一个清理函数，也必须重发。

    （作者报的"摆完后格子状态不对"和这次是同一个病灶。）
    """
    room.players[P1].attacks = [Position(x=3, y=3, hit=False)]
    events.clear()
    server._clear_attacks_on_cells(room, [Position(3, 3)])
    assert badges_of(events, 'sid-p1', 'my_attacks'), \
        '增援路径同样要重发 board_attacks_updated'
