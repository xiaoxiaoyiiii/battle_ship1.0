# -*- coding: utf-8 -*-
"""溅射 / 轰炸 / 硫磺火焰 返回 affected_positions 的回归测试（修复旧夹具）。"""
import pytest

import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def capture_emit(monkeypatch):
    events = []
    monkeypatch.setattr(server, 'emit',
                        lambda event, data, to=None, room=None: events.append((event, data, to, room)))
    return events


def make_room():
    room = GameRoom('r1')
    room.players[P1] = Player(name='p1', ships=[], attacks=[], remaining_ships=0, sid='sid1')
    room.players[P2] = Player(name='p2', ships=[], attacks=[], remaining_ships=0, sid='sid2')
    return room


def test_splash_returns_affected_positions():
    room = make_room()
    room.players[P2].ships = [PlayerShip(positions=[Position(3, 2)], hits=[])]
    room.players[P2].remaining_ships = 1
    room.last_attack = {'attacker': P1, 'x': 3, 'y': 3, 'hit': True}

    res = server.apply_magic_effect(room, P1, MagicCard('溅射'), {})
    assert res.success is True
    assert isinstance(res['affected_positions'], list)
    assert any(pos.x == 3 and pos.y == 2 for pos in res['affected_positions'])


def test_bomb_returns_affected_positions():
    room = make_room()
    room.players[P2].ships = [PlayerShip(positions=[Position(0, 2), Position(1, 2)], hits=[])]
    room.players[P2].remaining_ships = 1

    res = server.apply_magic_effect(
        room, P1, MagicCard('轰炸'),
        {'target_line': {'type': 'row', 'index': 2}})
    assert res.success is True


def test_sulfur_returns_affected_positions():
    room = make_room()
    room.players[P2].ships = [PlayerShip(positions=[Position(2, 0), Position(3, 0)], hits=[])]
    room.players[P2].remaining_ships = 1

    cells = [{'x': i, 'y': 0} for i in range(6)]
    res = server.apply_magic_effect(
        room, P1, MagicCard('硫磺火焰'), {'target_cells': cells})
    assert res.success is True
    assert any(pos.x == 2 and pos.y == 0 for pos in res['affected_positions'])
