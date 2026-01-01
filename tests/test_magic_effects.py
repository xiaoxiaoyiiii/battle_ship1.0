import types
import server


def make_room():
    room = server.GameRoom('r1')
    # setup players
    p1 = 'p1'
    p2 = 'p2'
    room.players[p1] = {'name': 'p1', 'ships': [], 'attacks': [], 'remaining_ships': 0}
    room.players[p2] = {'name': 'p2', 'ships': [], 'attacks': [], 'remaining_ships': 0}
    return room, p1, p2


def test_splash_returns_affected_positions(monkeypatch):
    room, p1, p2 = make_room()
    # opponent has a ship at (3,2)
    room.players[p2]['ships'] = [{'id': 's1', 'positions': [{'x': 3, 'y': 2}], 'hits': []}]
    room.players[p2]['remaining_ships'] = 1
    # last attack hit at (3,3)
    room.last_attack = {'attacker': p1, 'x': 3, 'y': 3, 'hit': True}

    card = {'name': '溅射'}

    # capture emits
    emitted = []
    def fake_emit(event, data, room=None, to=None):
        emitted.append((event, data, room, to))
    monkeypatch.setattr(server, 'emit', fake_emit)

    res = server.apply_magic_effect(room, p1, card, {})
    assert res['success'] is True
    assert 'affected_positions' in res
    assert isinstance(res['affected_positions'], list)
    # the four neighbors but only one valid hit in this setup
    assert any(pos['x'] == 3 and pos['y'] == 2 for pos in res['affected_positions'])


def test_bomb_returns_affected_positions(monkeypatch):
    room, p1, p2 = make_room()
    # opponent has ship occupying (0,2) and (1,2)
    room.players[p2]['ships'] = [{'id': 's2', 'positions': [{'x': 0, 'y': 2}, {'x': 1, 'y': 2}], 'hits': []}]
    room.players[p2]['remaining_ships'] = 1

    card = {'name': '轰炸'}
    target_line = {'type': 'row', 'index': 2}

    emitted = []
    def fake_emit(event, data, room=None, to=None):
        emitted.append((event, data, room, to))
    monkeypatch.setattr(server, 'emit', fake_emit)

    res = server.apply_magic_effect(room, p1, card, {'target_line': target_line})
    assert res['success'] is True
    assert 'affected_positions' in res
    assert any(pos['x'] == 0 and pos['y'] == 2 for pos in res['affected_positions'])


def test_sulfur_returns_affected_positions(monkeypatch):
    room, p1, p2 = make_room()
    room.players[p2]['ships'] = [{'id': 's3', 'positions': [{'x': 2, 'y': 0}, {'x': 3, 'y': 0}], 'hits': []}]
    room.players[p2]['remaining_ships'] = 1

    card = {'name': '硫磺火焰'}
    cells = [{'x': i, 'y': 0} for i in range(6)]

    emitted = []
    def fake_emit(event, data, room=None, to=None):
        emitted.append((event, data, room, to))
    monkeypatch.setattr(server, 'emit', fake_emit)

    res = server.apply_magic_effect(room, p1, card, {'target_cells': cells})
    assert res['success'] is True
    assert 'affected_positions' in res
    assert any(pos['x'] == 2 and pos['y'] == 0 for pos in res['affected_positions'])