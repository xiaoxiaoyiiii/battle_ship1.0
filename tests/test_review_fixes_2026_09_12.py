# -*- coding: utf-8 -*-
"""2026-09-12 代码审查修复批的回归测试（P0 / P1）。"""
import time

import pytest

import server
from server import (ChainItem, GameRoom, MagicCard, Player, PlayerShip,
                    Position, room_manager)

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def events(monkeypatch):
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    return captured


def ship(*cells):
    return PlayerShip(positions=[Position(x, y) for x, y in cells], hits=[])


def card(name):
    return MagicCard(name)


def make_room(ships1=6, ships2=6):
    r = GameRoom('review-room')
    r.players[P1] = Player(name='p1', ships=[ship((i, 0)) for i in range(ships1)],
                           attacks=[], remaining_ships=ships1, sid='sid-p1', user_id='u1')
    r.players[P2] = Player(name='p2', ships=[ship((i, 0)) for i in range(ships2)],
                           attacks=[], remaining_ships=ships2, sid='sid-p2', user_id='u2')
    r.state = 'attacking'
    r.current_attacker = P1
    r.current_phase = 'battle'
    r.attack_order = [P1, P2]
    r.attacks_remaining = ships1
    r.round = 1
    room_manager.rooms[r.id] = r
    return r


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)
    room_manager.match_queue = []


def atk(room, pid, x, y):
    return server.handle_attack({'room_id': room.id, 'player_id': pid, 'x': x, 'y': y})


# 1. 调试事件门禁必须作用在真实 socket 注册路径上
def test_debug_events_blocked_on_real_socket_path(room):
    assert server.ENABLE_TEST_EVENTS is False
    client = server.socketio.test_client(server.app)
    try:
        ack = client.emit('test_win_game', {'room_id': room.id, 'player_id': P1},
                          callback=True)
        assert ack == {'status': 'error', 'message': '调试事件未启用'}
        assert room.state == 'attacking'
        assert not room.winner

        ack2 = client.emit('test_add_all_magic_cards',
                           {'room_id': room.id, 'player_id': P1}, callback=True)
        assert ack2['status'] == 'error'
        assert room.players[P1].magic_hand == []

        ack3 = client.emit('test_get_game_state', {'room_id': room.id}, callback=True)
        assert ack3['status'] == 'error'
    finally:
        client.disconnect()




# 2. 攻击次数 / 终局校验


def test_last_attack_cannot_be_reused_by_click_spam(room):
    room.attacks_remaining = 1
    assert atk(room, P1, 0, 0)['status'] == 'success'
    assert atk(room, P1, 1, 0)['status'] == 'error'
    assert room.attacks_remaining == 0


def test_attack_after_game_over_rejected_without_double_record(room, monkeypatch):
    calls = []
    monkeypatch.setattr(server.db, 'record_match', lambda *a, **k: calls.append(a))
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1
    room.attacks_remaining = 6

    first = atk(room, P1, 0, 0)
    assert first.get('game_over') is True
    assert room.state == 'game_over'
    assert len(calls) == 1

    for x in (1, 2, 3):
        assert atk(room, P1, x, 0)['status'] == 'error'
    assert len(calls) == 1, '对局结束后不允许重复记账'


# 3. 重连令牌判空
def test_rejoin_room_requires_real_token(room):
    client = server.socketio.test_client(server.app)
    try:
        assert client.emit('rejoin_room', {'room_id': room.id, 'player_id': P1,
                                           'token': None}, callback=True)['status'] == 'error'
        assert client.emit('rejoin_room', {'room_id': room.id, 'player_id': P1},
                           callback=True)['status'] == 'error'
        assert room.players[P1].sid == 'sid-p1'

        room.reconnect_tokens[P1] = 'good-token'
        assert client.emit('rejoin_room', {'room_id': room.id, 'player_id': P1,
                                           'token': 'wrong'}, callback=True)['status'] == 'error'
        assert client.emit('rejoin_room', {'room_id': room.id, 'player_id': P1,
                                           'token': 'good-token'}, callback=True)['status'] == 'success'
    finally:
        client.disconnect()


# 4. /user_stats 字段白名单


# 5. 魔法目标注入
def test_select_magic_target_drops_injected_server_state(room):
    res = server.handle_magic_target({
        'room_id': room.id, 'player_id': P1, 'temp_data_id': 'noop',
        'target_data': {
            'pending_placement': {'caster': P1, 'kind': 'reinforce',
                                  'remaining': 99, 'total': 99, 'placed': 0},
            'caster_choice': 0,
        },
    })
    assert res['status'] == 'success'
    assert 'pending_placement' not in room.magic_temp_data
    assert room.magic_temp_data.get('caster_choice') == 0


def test_injected_pending_placement_cannot_grant_extra_ships(room):
    server.handle_magic_target({
        'room_id': room.id, 'player_id': P1, 'temp_data_id': 'noop',
        'target_data': {'pending_placement': {'caster': P1, 'kind': 'reinforce',
                                              'remaining': 30, 'total': 30, 'placed': 0}},
    })
    res = server.handle_confirm_reinforcement({
        'room_id': room.id, 'player_id': P1, 'position': {'x': 5, 'y': 5}})
    assert res['status'] == 'error'
    assert room.players[P1].remaining_ships == 6


# 6. 复活 / 增援




# 7. 船数广播视角
def test_ships_updated_is_sent_per_viewer(room, events):
    room.players[P1].remaining_ships = 5
    room.players[P2].remaining_ships = 2
    server._emit_ships_updated(room)

    payloads = {e[2]: e[1] for e in events if e[0] == 'ships_updated'}
    assert payloads['sid-p1'] == {'player_remaining_ships': 5,
                                  'opponent_remaining_ships': 2}
    assert payloads['sid-p2'] == {'player_remaining_ships': 2,
                                  'opponent_remaining_ships': 5}


# 8. 连锁不得绕过封锁


def test_chain_response_ignores_forged_card_type(room):
    room.chain = [ChainItem(P1, card('失灵！'), [], time.time())]
    room.chain_waiting = True
    room.chain_window = P2
    room.players[P2].magic_hand = []

    res = server.chain_response({
        'room_id': room.id, 'player_id': P2, 'chain': True,
        'card': {'name': '看破！', 'speed': 3, 'type': '场地', 'description': 'x'},
        'targets': [],
    })
    assert res['status'] == 'error'
    assert room.players[P2].magic_hand == []


# 9. 教皇旨意弃卡攻击
def test_papal_attack_requires_your_turn(room):
    room.field_magic = card('教皇旨意')
    room.current_attacker = P2
    room.players[P1].magic_hand = [card('失灵！')]

    res = server.handle_papal_attack({'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 0})
    assert res['status'] == 'error'
    assert room.players[P2].remaining_ships == 6




# 10. 回合切换重置伤害统计


# 11. 猜拳平局（原先 IndexError）




# 12. 场地魔法归属与效果清理






def test_remove_field_magic_only_own(room):
    room.field_magic = card('伊甸园')
    room.field_magic_owner = P2
    res = server.handle_remove_field_magic({'room_id': room.id, 'player_id': P1})
    assert res['status'] == 'error'
    assert room.field_magic is not None

    room.field_magic_owner = P1
    res = server.handle_remove_field_magic({'room_id': room.id, 'player_id': P1})
    assert res['status'] == 'success'
    assert room.field_magic is None


# 13. 回光返照只持续发动当回合


# 14. 桃园结义不得绕过无中生有
def test_taoyuan_respects_no_draw(room):
    room.players[P1].effect_flags.no_draw = True
    room.magic_deck = [card('轰炸'), card('疗愈')]
    res = server.apply_magic_effect(room, P1, card('桃园结义'), {})
    assert res.success is False
    assert len(room.magic_deck) == 2
    assert room.players[P1].magic_hand == []


# 15. discard_card 不再抛 ValueError


# 16. 明智埋葬 / 仁王之盾 走真实链路


def test_shield_choice_via_confirm_magic_target(room):
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2)), ship((3, 3))]
    room.players[P1].remaining_ships = 4
    room.magic_temp_data = {'type': 'shield_choice', 'caster': P1}

    res = server.confirm_magic_target({
        'room_id': room.id, 'player_id': P1, 'temp_data_id': 'shield_choice',
        'target_data': {'ship_indices': [0, 1, 2, 3]}})
    assert res['status'] == 'success'
    assert sum(1 for s in room.players[P1].ships if s.shield) == 3


def test_shield_choice_rejects_empty_selection(room):
    room.players[P1].ships = [ship((0, 0))]
    room.players[P1].remaining_ships = 1
    room.magic_temp_data = {'type': 'shield_choice', 'caster': P1}
    res = server.confirm_magic_target({
        'room_id': room.id, 'player_id': P1, 'temp_data_id': 'shield_choice',
        'target_data': {'ship_indices': []}})
    assert res['status'] == 'error'
    assert room.players[P1].ships[0].shield is False
