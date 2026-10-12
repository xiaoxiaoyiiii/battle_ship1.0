"""验证真实消费路径、信息隔离和注入随机源的可复现性。"""
from random import Random
from types import SimpleNamespace as Obj

import ai_brain
import replay
import server
import spectate
from application.observations import attack_observation, settlement_snapshot


def test_attack_snapshot_never_reads_enemy_and_survives_source_mutation():
    class HiddenPlayer:
        def __getattribute__(self, name):
            raise AssertionError("读取了敌方私有信息")
    player = Obj(attacks=[{'x': 0, 'y': 0}], revealed_positions=[{'x': 2, 'y': 3}])
    room = Obj(players={'me': player, 'enemy': HiddenPlayer()})
    snapshot = attack_observation(room, 'me')
    player.revealed_positions.clear()
    assert ai_brain.choose_attack_from_observation(snapshot, Random(9)) == (2, 3)
    assert snapshot.attacked == frozenset({(0, 0)})


def test_injected_random_source_is_independent_of_global_random():
    import random
    room = Obj(players={'me': Obj(attacks=[], revealed_positions=[])})
    observation = attack_observation(room, 'me')
    left, right = Random(12), Random(12)
    first = [ai_brain.choose_attack_from_observation(observation, left) for _ in range(20)]
    random.seed(999)
    for _ in range(100):
        random.random()
    second = [ai_brain.choose_attack_from_observation(observation, right) for _ in range(20)]
    assert first == second


def test_server_attack_path_accepts_local_rng(monkeypatch):
    monkeypatch.setattr(server, '_attackable_cells', lambda *args: [(0, 1), (2, 3)])
    monkeypatch.setattr(server, '_is_master', lambda *args: False)
    assert server._ai_choose_attack(Obj(), 'me', Random(5)) == Random(5).choice([(0, 1), (2, 3)])


def test_spectate_seats_do_not_read_player_details():
    room = Obj(players={'secret-sid': object(), 'other-sid': object()})
    assert spectate.seat_order(room) == ['secret-sid', 'other-sid']
    assert spectate.seat_label(room, 'secret-sid') == 'p1'
    assert spectate.seat_label('room-id', 'secret-sid') == 'unknown'


def test_settlement_snapshot_detaches_and_preserves_legacy_facts(monkeypatch):
    ship = Obj(hits=[(1, 2)])
    room = Obj(players={'w': Obj(ships=[ship]), 'l': Obj(ships=[Obj(hits=[])])},
               round=3, end_reason='surrender')
    snapshot = settlement_snapshot(room, 'w', 'l', 12)
    monkeypatch.setattr(server, '_match_duration_sec', lambda _: 12)
    expected = {'rounds': 3, 'attacker_total_hits': 1, 'defender_total_hits': 0,
                'loser_total_hits': 0, 'attackers': ['a'], 'max_hits': 1,
                'foe_ships': 1, 'total_ships': 2, 'duration_sec': 12, 'ended_by': 'surrender'}
    assert server._anticheat_facts(room, 'w', 'l') == expected
    ship.hits.clear()
    assert snapshot.facts() == expected


def test_replay_clock_port_looks_up_current_server_function(monkeypatch):
    monkeypatch.setattr(server, '_match_started_at', lambda _: 123)
    assert replay._STARTED_AT(Obj()) == 123
    monkeypatch.setattr(server, '_match_started_at', lambda _: 456)
    assert replay._STARTED_AT(Obj()) == 456
