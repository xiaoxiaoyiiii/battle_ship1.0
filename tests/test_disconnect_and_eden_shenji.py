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


# ---------- 桃园结义 / 取消匹配 / 教皇旨意（2026-09-07 第二批） ----------





def test_papal_recalc_zero_at_prep():
    """教皇旨意：准备阶段攻击次数应直接为 0（与伊甸园同款结算时机）。"""
    room = make_room()
    room.field_magic = card('教皇旨意')
    room.state = 'attacking'
    room.current_phase = 'preparation'
    room.current_attacker = P1
    room.players[P1].ships = [PlayerShip(positions=[], hits=[])] * 5
    room.players[P1].remaining_ships = 5
    room.attacks_remaining = 5
    server._recalc_attacker_attacks(room)
    assert room.attacks_remaining == 0




# ---------- 人机对战：AI 布船规则与玩家一致（2026-09-08） ----------

def test_ai_placement_same_rules_as_human():
    """AI 布船：6 艘单格船、坐标不重叠且在 0-5 内（与玩家规则一致）。"""
    room = GameRoom('airoom')
    room.is_ai_room = True
    room.players['ai-x'] = Player(name='AI', ships=[], attacks=[], remaining_ships=0, user_id=None, sid='ai-x')
    server._ai_place_ships(room, 'ai-x')
    p = room.players['ai-x']
    assert len(p.ships) == 6 and p.remaining_ships == 6
    assert all(len(s.positions) == 1 for s in p.ships), 'AI 应为单格船'
    coords = [(s.positions[0].x, s.positions[0].y) for s in p.ships]
    assert len(set(coords)) == 6, '坐标不能重叠'
    assert all(0 <= x < 6 and 0 <= y < 6 for x, y in coords), '坐标需在棋盘内'


def test_ai_placement_respects_max_ships():
    """灵气复苏等改变 max_ships 后，AI 布船数量跟随该上限。"""
    room = GameRoom('airoom2')
    room.is_ai_room = True
    room.players['ai-y'] = Player(name='AI', ships=[], attacks=[], remaining_ships=0, user_id=None, sid='ai-y')
    room.players['ai-y'].max_ships = 3
    server._ai_place_ships(room, 'ai-y')
    assert len(room.players['ai-y'].ships) == 3
