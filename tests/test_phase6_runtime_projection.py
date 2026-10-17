from types import SimpleNamespace

import server
from application.ai_runtime import seeded_runtime
from application.replay_observation import capture_replay_observation, clear_replay_observation
from application.spectate_projection import project_snapshot


def test_room_ai_runtime_is_independent_and_clock_is_injected(monkeypatch):
    pauses = []
    room = SimpleNamespace(ai_runtime=seeded_runtime(17, sleep=pauses.append))
    monkeypatch.setattr(server.room_manager, 'get_room', lambda room_id: room)
    first = [room.ai_runtime.rng.randrange(1000) for _ in range(5)]
    server._ai_pause('one-room', 0.3)
    assert pauses == [0.3]
    another = seeded_runtime(17)
    assert first == [another.rng.randrange(1000) for _ in range(5)]


def test_public_projection_transposes_board_and_copies_effects():
    sides = {
        'p1': {'attacks': [{'x': 1, 'y': 2, 'hit': False}]},
        'p2': {'attacks': [{'x': 3, 'y': 4, 'hit': True}]},
    }
    effects = {'last_stand_cells': [(2, 2)], 'shenwei_holes': [{'x': 5, 'y': 5}]}
    payload = project_snapshot(
        room_public={'room_id': 'r'}, sides=sides, seat_labels={},
        game_logs=[], chain={}, effects=effects, spectators=[], spectator_limit=8,
    )
    assert payload['board_attacks']['p1'] == sides['p2']['attacks']
    assert payload['board_attacks']['p2'] == sides['p1']['attacks']
    assert payload['last_stand_cells'] == [{'x': 2, 'y': 2}]
    sides['p2']['attacks'][0]['x'] = 0
    assert payload['board_attacks']['p1'][0]['x'] == 3


def test_replay_observation_detaches_live_player_but_shares_recording_state():
    room = server.GameRoom('replay-observation')
    ship = server.PlayerShip([server.Position(1, 2)], [])
    room.players['p1'] = server.Player('一号', [ship], [], 1, sid='p1')
    observed = capture_replay_observation(room)
    assert observed is not room
    assert observed.players['p1'] is not room.players['p1']
    assert observed.replay is room.replay
    ship.positions[0].x = 5
    assert observed.players['p1'].ships[0].positions[0].x == 1
    clear_replay_observation(room)
    room.state = 'game_over'
    assert capture_replay_observation(room) is None
    assert room.replay is None
