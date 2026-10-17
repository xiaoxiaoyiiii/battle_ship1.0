"""验证真实消费路径、信息隔离和注入随机源的可复现性。"""
from random import Random
from types import SimpleNamespace as Obj

import ai_brain
import replay
import server
import spectate
from application.observations import (
    attack_observation, card_observation, choice_observation, placement_observation,
    settlement_snapshot, ship_pick_observation, target_observation,
)


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


def test_card_snapshot_does_not_read_enemy_hand_or_ships():
    class PublicEnemy:
        remaining_ships = 4
        revealed_positions = [{'x': 1, 'y': 2}]

        @property
        def ships(self):
            raise AssertionError('读取了对手船位')

        @property
        def magic_hand(self):
            raise AssertionError('读取了对手手牌')

    own = Obj(magic_hand=[Obj(name='轰炸'), Obj(name='克苏鲁之眼')],
              remaining_ships=2, attacks=[{'x': 0, 'y': 0}],
              revealed_positions=[])
    room = Obj(players={'me': own, 'enemy': PublicEnemy()}, last_attack={'hit': True})
    snapshot = card_observation(room, 'me')
    expected = ai_brain.choose_card(room, 'me', [0, 1])
    own.magic_hand.clear()
    assert ai_brain.choose_card_from_observation(snapshot, [0, 1]) == expected
    assert snapshot.hand_names == ('轰炸', '克苏鲁之眼')


def test_placement_and_ship_pick_use_only_public_enemy_attacks():
    class PublicEnemy:
        attacks = [{'x': 3, 'y': 3}]

        @property
        def ships(self):
            raise AssertionError('读取了对手船位')

    room = Obj(players={'me': Obj(), 'enemy': PublicEnemy()})
    cells = [(0, 0), (3, 3)]
    placement = placement_observation(room, 'me', cells)
    assert ai_brain.choose_placement_index(placement) == 1
    assert ai_brain.resolve_placement(room, 'me', 'reinforce', cells) == (3, 3)

    ships = [Obj(positions=[Obj(x=0, y=0)]), Obj(positions=[Obj(x=3, y=3)])]
    choice = ship_pick_observation(room, 'me', ships)
    assert ai_brain.choose_ship_index(choice, 'demon_contract') == 1
    assert ai_brain.resolve_ship_pick(room, 'me', 'demon_contract', ships) is ships[1]
    PublicEnemy.attacks.clear()
    assert ai_brain.choose_placement_index(placement) == 1
    assert ai_brain.choose_ship_index(choice, 'demon_contract') == 1


def test_target_snapshot_is_independent_of_enemy_private_board():
    class HiddenEnemy:
        @property
        def ships(self):
            raise AssertionError('读取了对手船位')

        @property
        def magic_hand(self):
            raise AssertionError('读取了对手手牌')

    own = Obj(attacks=[{'x': 0, 'y': 0}],
              revealed_positions=[{'x': 2, 'y': 2}],
              ships=[Obj(positions=[Obj(x=5, y=5)])])
    room = Obj(players={'me': own, 'enemy': HiddenEnemy()})
    snapshot = target_observation(room, 'me')
    for name in ('冻结', '轰炸', '硫磺火焰'):
        expected = ai_brain.resolve_target(room, 'me', Obj(name=name))
        assert ai_brain.resolve_target_from_observation(snapshot, name) == expected
    own.revealed_positions.clear()
    own.ships.clear()
    assert snapshot.revealed == frozenset({(2, 2)})
    assert snapshot.own_ship_cells == frozenset({(5, 5)})


def test_numeric_choice_uses_public_counts_only():
    class PublicEnemy:
        remaining_ships = 5

        @property
        def ships(self):
            raise AssertionError('读取了对手船位')

    room = Obj(players={'me': Obj(remaining_ships=3), 'enemy': PublicEnemy()},
               attacks_remaining=2)
    snapshot = choice_observation(room, 'me')
    assert ai_brain.resolve_choice(room, 'me', 'lingqi_choice', list(range(7))) == 4
    assert ai_brain.resolve_choice_from_observation(snapshot, 'shenji_predict', list(range(7))) == 2
