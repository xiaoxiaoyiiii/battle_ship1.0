# -*- coding: utf-8 -*-
"""神威！归还后「船不可见」的回归测试（2026-09-20）。

作者实测症状：我方棋盘通过神威！除外了一回合，返回后**船变得不可见**。

根因：`_restore_due_shenwei()` 把船 `append` 回棋盘后，**只发了
`shenwei_hole_restored`（前端拿它清格子样式），漏发 `player_ships_updated`**
—— 前端手上没有船的数据，于是格子干净了、船也没画出来。

对比证据：同一个文件里解冻路径（end_turn 里）在改完船之后**明确调了**
`_emit_player_ships`。归还路径漏了这一步。

本文件断言的就是**用户看到的那件事**：归还后必须给本人下发船数据。
"""
import itertools

import pytest

import server
from server import GameRoom, Player, PlayerShip, Position

_seq = itertools.count(1)


def _mk_room():
    room = GameRoom('shenwei-test')
    room.round = 1
    room.players = {
        'p1': Player('甲', [], [], 0, user_id='u1', sid='sid-1'),
        'p2': Player('乙', [], [], 0, user_id='u2', sid='sid-2'),
    }
    return room


def _capture(monkeypatch):
    """收集 emit 调用。"""
    sent = []

    def fake_emit(event, data, to=None, room=None):
        sent.append({'name': event, 'data': data, 'to': to, 'room': room})

    monkeypatch.setattr(server, 'emit', fake_emit)
    return sent


def _add_excluded(room, pid, ships, return_turn):
    entries = room.game_effects.setdefault('excluded_ships', [])
    entries.append({'player': pid, 'ships': list(ships), 'return_turn': return_turn})


# ===========================================================================
# ★ 核心：归还后必须下发船数据（用户症状）
# ===========================================================================
def test_returned_ships_are_sent_to_owner(monkeypatch):
    """★ 神威归还后，必须给船主下发 `player_ships_updated`。

    没有这一条，前端只清掉了格子样式、**没有任何船的数据可画** → 船不可见。
    """
    room = _mk_room()
    player = room.players['p1']
    # 一艘被除外的船（不在棋盘上）
    excluded = PlayerShip([Position(2, 2)], [])
    _add_excluded(room, 'p1', [excluded], return_turn=2)

    sent = _capture(monkeypatch)
    server._restore_due_shenwei(room, current_round=2)

    # 船确实回到了棋盘上
    assert excluded in player.ships, '船应当被归还'
    assert player.remaining_ships == 1

    # ★ 并且**必须**把船数据发给本人
    ship_events = [e for e in sent if e['name'] == 'player_ships_updated']
    assert ship_events, (
        '归还后必须发 player_ships_updated —— 否则前端拿不到船，船不可见（作者实测症状）'
    )
    assert ship_events[0]['to'] == 'sid-1', '要发给船主本人'
    positions = ship_events[0]['data']['ships'][0]['positions']
    assert {'x': 2, 'y': 2} in positions


def test_return_also_syncs_ship_counts(monkeypatch):
    """归还改变了船数 → 双方船数视图也要同步（否则「你的船数」不更新）。"""
    room = _mk_room()
    _add_excluded(room, 'p1', [PlayerShip([Position(1, 1)], [])], return_turn=2)
    sent = _capture(monkeypatch)
    server._restore_due_shenwei(room, current_round=2)
    assert [e for e in sent if e['name'] == 'ships_updated'], '船数视图必须同步'


def test_hole_restored_still_emitted(monkeypatch):
    """反向守卫：原有的 `shenwei_hole_restored` 不许被这次的改动弄丢。"""
    room = _mk_room()
    server._add_shenwei_hole(room, 'p1', {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}, return_turn=2)
    sent = _capture(monkeypatch)
    server._restore_due_shenwei(room, current_round=2)
    assert [e for e in sent if e['name'] == 'shenwei_hole_restored'], \
        '洞恢复事件不许丢（前端靠它清格子样式）'


# ===========================================================================
# 不许过度发事件（无事也发会让客户端白重画）
# ===========================================================================
def test_no_ship_event_when_nothing_returned(monkeypatch):
    """没有船归还（还没到期）→ 不该发船数据事件。"""
    room = _mk_room()
    _add_excluded(room, 'p1', [PlayerShip([Position(0, 0)], [])], return_turn=5)
    sent = _capture(monkeypatch)
    server._restore_due_shenwei(room, current_round=2)
    assert not [e for e in sent if e['name'] == 'player_ships_updated'], \
        '未到期不该发船数据'


def test_no_ship_event_when_ship_already_on_board(monkeypatch):
    """船已经在棋盘上（重摆后又被 append 过）→ 不重复发、也不重复加。"""
    room = _mk_room()
    player = room.players['p1']
    ship = PlayerShip([Position(3, 3)], [])
    player.ships = [ship]
    player.remaining_ships = 1
    _add_excluded(room, 'p1', [ship], return_turn=2)
    sent = _capture(monkeypatch)
    server._restore_due_shenwei(room, current_round=2)
    assert player.ships.count(ship) == 1, '不许重复 append'
    assert not [e for e in sent if e['name'] == 'player_ships_updated'], \
        '船本来就在棋盘上，没变化就不该发'


# ===========================================================================
# 既有行为：重摆过的幽灵船不许回来
# ===========================================================================
def test_detached_ship_not_returned(monkeypatch):
    """棋盘被重摆过（船标了 `_detached`）→ 不归还（否则 6 艘变 8 艘）。"""
    room = _mk_room()
    player = room.players['p1']
    ghost = PlayerShip([Position(0, 0)], [])
    ghost._detached = True
    _add_excluded(room, 'p1', [ghost], return_turn=2)
    sent = _capture(monkeypatch)
    server._restore_due_shenwei(room, current_round=2)
    assert ghost not in player.ships, '幽灵船不许回来'
    assert not [e for e in sent if e['name'] == 'player_ships_updated']


def test_only_owner_gets_ship_event(monkeypatch):
    """★ 只发给船主，别广播给对手（对手不该看到对方船位）。"""
    room = _mk_room()
    _add_excluded(room, 'p1', [PlayerShip([Position(4, 4)], [])], return_turn=2)
    sent = _capture(monkeypatch)
    server._restore_due_shenwei(room, current_round=2)
    for e in sent:
        if e['name'] == 'player_ships_updated':
            assert e['to'] == 'sid-1', f"船数据只能发给船主，实际 to={e['to']}"
