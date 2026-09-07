# -*- coding: utf-8 -*-
"""伊甸园攻击次数结算时机 + 神机妙算宣言流程（2026-09-07 新增）"""
import pytest
import server
from server import GameRoom, Player, MagicCard, PlayerShip

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def capture_emit(monkeypatch):
    events = []
    monkeypatch.setattr(server, 'emit',
                        lambda event, data, to=None, room=None: events.append((event, data, to, room)))
    return events


def card(name):
    return MagicCard(name)


def make_room():
    room = GameRoom('r1')
    for pid, sid in ((P1, 'sid1'), (P2, 'sid2')):
        room.players[pid] = Player(name=pid, ships=[], attacks=[], remaining_ships=0, sid=sid, user_id=pid)
        room.players[pid].magic_hand = []
    return room


# ---------- 伊甸园：攻击次数在准备阶段即按 6-n 结算 ----------

def test_eden_recalc_on_rps_winner():
    """猜先胜出进入准备阶段时，若伊甸园已在场 → 攻击次数 = 6 - 自身船数。"""
    room = make_room()
    room.field_magic = card('伊甸园')
    room.state = 'rock_paper_scissors'
    room.players[P1].ships = [PlayerShip(positions=[], hits=[])] * 4
    room.players[P1].remaining_ships = 4
    room.state = 'attacking'
    room.current_phase = 'preparation'
    room.current_attacker = P1
    server._recalc_attacker_attacks(room)
    assert room.attacks_remaining == 6 - 4


def test_eden_no_attacks_when_full_ships():
    """6 艘船在伊甸园下应在准备阶段就得到 0 次攻击（而非打一发后才变 0）。"""
    room = make_room()
    room.field_magic = card('伊甸园')
    room.state = 'attacking'
    room.current_phase = 'preparation'
    room.current_attacker = P1
    room.players[P1].ships = [PlayerShip(positions=[], hits=[])] * 6
    room.players[P1].remaining_ships = 6
    room.attacks_remaining = 6  # 模拟旧逻辑先给了 6 次
    server._recalc_attacker_attacks(room)
    assert room.attacks_remaining == 0


def test_eden_refresh_when_played_in_prep():
    """准备阶段贴出伊甸园 → 当前攻击者攻击次数立即刷新为 6-n 并广播。"""
    room = make_room()
    room.state = 'attacking'
    room.current_phase = 'preparation'
    room.current_attacker = P1
    room.players[P1].ships = [PlayerShip(positions=[], hits=[])] * 3
    room.players[P1].remaining_ships = 3
    room.attacks_remaining = 3
    server.apply_magic_effect(room, P1, card('伊甸园'), {})
    assert room.attacks_remaining == 6 - 3


def test_non_eden_uses_ship_count():
    """无伊甸园时按剩余船数结算（不受影响）。"""
    room = make_room()
    room.state = 'attacking'
    room.current_phase = 'preparation'
    room.current_attacker = P1
    room.players[P1].ships = [PlayerShip(positions=[], hits=[])] * 4
    room.players[P1].remaining_ships = 4
    server._recalc_attacker_attacks(room)
    assert room.attacks_remaining == 4


# ---------- 神机妙算：宣言流程 ----------

def test_shenji_requests_declare_when_no_prediction():
    """打出神机妙算但未宣言 → 返回 temp_data_id=shenji_declare 请求宣言。"""
    room = make_room()
    res = server.apply_magic_effect(room, P1, card('神机妙算'), {})
    assert res.temp_data_id == 'shenji_declare'
    assert room.magic_temp_data.get('pending_shenji', {}).get('caster') == P1


def test_shenji_confirm_applies_prediction():
    """confirm_shenji_declare 写入预测值并落效。"""
    room = make_room()
    server.room_manager.rooms[room.id] = room  # 注册到 room_manager（handler 按 id 取房）
    server.apply_magic_effect(room, P1, card('神机妙算'), {})
    room.players[P1].remaining_ships = 5
    res = server.handle_confirm_shenji_declare({
        'room_id': room.id, 'player_id': P1, 'prediction': 2
    })
    assert res['status'] == 'success'
    assert room.players[P1].effect_flags.prediction == 2
    assert room.magic_temp_data.get('pending_shenji') is None
    assert f'prediction_initial_{P1}' in room.game_effects
    server.room_manager.delete_room(room.id)


def test_shenji_apply_with_existing_prediction():
    """已宣言后再次结算 → 直接落效（老路径兼容）。"""
    room = make_room()
    room.magic_temp_data['prediction'] = 3
    res = server.apply_magic_effect(room, P1, card('神机妙算'), {})
    assert res.success is not False
    assert room.players[P1].effect_flags.prediction == 3
