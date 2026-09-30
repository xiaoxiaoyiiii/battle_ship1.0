"""The deterministic replay fixture must remain behind the debug event gate."""

from types import SimpleNamespace

import server


def test_ai_rps_choice_debug_gate_and_stage(monkeypatch):
    room = SimpleNamespace(is_ai_room=True, state='rock_paper_scissors')
    monkeypatch.setattr(server.room_manager, 'get_room', lambda _room_id: room)
    monkeypatch.setattr(server, '_debug_actor_allowed', lambda: True)

    monkeypatch.setattr(server, 'ENABLE_TEST_EVENTS', False)
    rejected = server.test_set_ai_rps_choice({'room_id': 'fixture', 'choice': 'scissors'})
    assert rejected['status'] == 'error'
    assert not hasattr(room, 'test_ai_rps_choice')

    monkeypatch.setattr(server, 'ENABLE_TEST_EVENTS', True)
    assert server.test_set_ai_rps_choice({'room_id': 'fixture', 'choice': 'bad'})['status'] == 'error'
    assert not hasattr(room, 'test_ai_rps_choice')
    assert server.test_set_ai_rps_choice({'room_id': 'fixture', 'choice': 'scissors'})['status'] == 'success'
    assert room.test_ai_rps_choice == 'scissors'

    room.state = 'attacking'
    assert server.test_set_ai_rps_choice({'room_id': 'fixture', 'choice': 'rock'})['status'] == 'error'
    assert room.test_ai_rps_choice == 'scissors'
