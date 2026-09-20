# -*- coding: utf-8 -*-
"""卧薪尝胆（普通魔法卡）的回归测试。

按 CLAUDE.md 第 7 节「改卡要同步 4 处」要求覆盖：
  · magic_card.json / magic_cards.js 一致性
  · 发动条件「自己船数 < 对方船数」在扣牌前拦截
  · apply_magic_effect 卧薪尝胆分支：所有活船 shield=True
  · 护盾效果同仁王之盾：被攻击时挡下一炮、shield 转 False
  · 看破 / 禁忌果实反制
"""
import json
import os

import pytest

import server
from server import (GameRoom, MagicCard, Player, PlayerShip, Position,
                    room_manager)

P1, P2 = 'p1', 'p2'


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def events(monkeypatch):
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    monkeypatch.setattr(server.socketio, 'start_background_task',
                        lambda target, *a, **k: None)
    monkeypatch.setattr(server, '_schedule_chain_timeout', lambda *a, **k: None)
    return captured


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def make_room():
    room = GameRoom('test-woxin-room')
    room.players[P1] = Player(name='p1',
                              ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(6)],
                              attacks=[], remaining_ships=6, sid='sid-p1')
    room.players[P2] = Player(name='p2',
                              ships=[PlayerShip(positions=[Position(i, 5)], hits=[]) for i in range(6)],
                              attacks=[], remaining_ships=6, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'preparation'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 1
    room_manager.rooms[room.id] = room
    return room


def card(name):
    return MagicCard(name)


def give_hand(player, names):
    player.magic_hand = [card(n) for n in names]


def find_emit(events, event_name, to=None):
    out = []
    for ev, data, t, r in events:
        if ev == event_name and (to is None or t == to):
            out.append((ev, data, t, r))
    return out


def apply_woxin(room, caster):
    return server.apply_magic_effect(room, caster, card('卧薪尝胆'), {})


# ---------------------------------------------------------------------------
# 卡牌定义一致性
# ---------------------------------------------------------------------------
def test_card_definition_consistent():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, 'static', 'magic_card.json'), encoding='utf-8') as f:
        json_cards = json.load(f)
    woxin_json = [c for c in json_cards if c['name'] == '卧薪尝胆']
    assert len(woxin_json) == 1
    wj = woxin_json[0]
    assert wj['speed'] == 1
    assert wj['type'] == '普通'

    with open(os.path.join(here, 'static', 'magic_cards.js'), encoding='utf-8') as f:
        js_src = f.read()
    assert f'name: "卧薪尝胆"' in js_src
    assert f'speed: {wj["speed"]}' in js_src
    assert f'type: "{wj["type"]}"' in js_src
    assert wj['description'] in js_src


def test_woxin_card_enters_deck():
    names = [c.name for c in server.magic_cards]
    assert '卧薪尝胆' in names


def test_deck_size_grew():
    """新加一张普通卡，牌池规模 46 → 48。"""
    deck = server.magic_cards
    assert len(deck) == 48, f'卡池应 48 条，实际 {len(deck)}'


# ---------------------------------------------------------------------------
# 发动条件
# ---------------------------------------------------------------------------
def test_blocked_when_ships_not_less(room):
    """自己船数 == 对方 → 拒；手牌不丢。"""
    room.players[P1].remaining_ships = 6
    room.players[P2].remaining_ships = 6
    give_hand(room.players[P1], ['卧薪尝胆'])
    room.current_phase = 'preparation'
    room.current_attacker = P1

    resp = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '卧薪尝胆', 'speed': 1, 'type': '普通', 'description': ''},
        'targets': {},
    })
    assert resp['status'] == 'error'
    assert '卧薪尝胆' in resp['message']
    # 手牌不丢
    assert len(room.players[P1].magic_hand) == 1
    assert room.players[P1].magic_hand[0].name == '卧薪尝胆'


def test_blocked_when_ships_greater(room):
    """自己船数 > 对方 → 拒。"""
    room.players[P1].remaining_ships = 6
    room.players[P2].remaining_ships = 3
    give_hand(room.players[P1], ['卧薪尝胆'])
    room.current_phase = 'preparation'
    room.current_attacker = P1

    resp = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '卧薪尝胆', 'speed': 1, 'type': '普通', 'description': ''},
        'targets': {},
    })
    assert resp['status'] == 'error'


def test_playable_when_ships_less(room):
    """自己船数 < 对方 → 通过。"""
    room.players[P1].remaining_ships = 3
    room.players[P2].remaining_ships = 6
    assert server._woxin_requirement_reason(room, P1, card('卧薪尝胆')) is None


def test_requirement_reason_function(room):
    """_woxin_requirement_reason 直接单元测试。"""
    # 非「卧薪尝胆」不拦
    assert server._woxin_requirement_reason(room, P1, card('无中生有')) is None
    # 6 vs 6 → 拦
    assert server._woxin_requirement_reason(room, P1, card('卧薪尝胆')) is not None
    # 5 vs 6 → 过
    room.players[P1].remaining_ships = 5
    assert server._woxin_requirement_reason(room, P1, card('卧薪尝胆')) is None
    # 6 vs 5 → 拦
    room.players[P1].remaining_ships = 6
    room.players[P2].remaining_ships = 5
    assert server._woxin_requirement_reason(room, P1, card('卧薪尝胆')) is not None


# ---------------------------------------------------------------------------
# 效果：所有活船加护盾
# ---------------------------------------------------------------------------
def test_all_alive_ships_get_shield(room, events):
    """发动后所有活船 shield=True。"""
    room.players[P1].remaining_ships = 3
    room.players[P2].remaining_ships = 6
    # P1 有 3 艘活船（其余 3 艘标记为沉没）
    for s in room.players[P1].ships[3:]:
        server._mark_ship_sunken(room.players[P1], s)

    res = apply_woxin(room, P1)
    assert res.success is True
    alive = server._alive_ships(room.players[P1])
    assert len(alive) == 3
    assert all(s.shield is True for s in alive)
    # 沉船不应该被打标记（虽然它本来 shield=False 也无所谓，但确认下）
    sunken = [s for s in room.players[P1].ships if not server._is_ship_alive(room.players[P1], s)]
    # 沉船的 shield 仍为 False（卧薪尝胆只动活船）
    assert all(not s.shield for s in sunken)


def test_no_alive_ships_fails(room):
    """没有活船 → 失败。"""
    room.players[P1].remaining_ships = 1
    room.players[P2].remaining_ships = 6
    # P1 全部标记沉没（但 remaining_ships 仍 < 对方，绕过条件检查）
    for s in room.players[P1].ships:
        server._mark_ship_sunken(room.players[P1], s)
    room.players[P1].remaining_ships = 0  # 0 < 6 通过条件
    res = apply_woxin(room, P1)
    assert res.success is False
    assert '没有战舰' in res.message


def test_shields_added_event(room, events):
    """发动后广播 shields_added 事件给双方。"""
    room.players[P1].remaining_ships = 3
    room.players[P2].remaining_ships = 6
    for s in room.players[P1].ships[3:]:
        server._mark_ship_sunken(room.players[P1], s)

    apply_woxin(room, P1)
    added = find_emit(events, 'shields_added')
    # 应该有一次房间级广播
    assert any(r == room.id for _, _, _, r in added)
    data = added[0][1]
    assert data['player'] == P1
    assert data['count'] == 3


# ---------------------------------------------------------------------------
# 护盾效果同仁王之盾：被攻击时挡下一炮、shield 转 False
# ---------------------------------------------------------------------------
def test_shield_blocks_one_attack(room, events):
    """加盾后第一炮被挡下，shield 转 False；第二炮正常命中。"""
    room.players[P1].remaining_ships = 3
    room.players[P2].remaining_ships = 6
    for s in room.players[P1].ships[3:]:
        server._mark_ship_sunken(room.players[P1], s)
    apply_woxin(room, P1)

    # 切到战斗阶段，让 P2 攻击 P1 第一艘船的格子 (0, 0)
    room.current_phase = 'battle'
    room.current_attacker = P2
    room.attacks_remaining = 6

    # 第一炮：(0, 0)
    server.handle_attack({
        'room_id': room.id, 'player_id': P2,
        'x': 0, 'y': 0,
    })
    # 应该被挡下：shield_absorbed 事件
    absorbed = find_emit(events, 'shield_absorbed')
    assert len(absorbed) >= 1
    # shield 被消耗
    target = room.players[P1].ships[0]
    assert target.shield is False
    # 船没沉（hits 应该还是空，shield 挡下不记录 hit）
    assert len(target.hits) == 0


def test_shield_one_per_ship(room, events):
    """每艘船的护盾独立，挡一炮后该船的护盾消失，其它船护盾仍在。"""
    room.players[P1].remaining_ships = 2
    room.players[P2].remaining_ships = 6
    for s in room.players[P1].ships[2:]:
        server._mark_ship_sunken(room.players[P1], s)
    apply_woxin(room, P1)

    room.current_phase = 'battle'
    room.current_attacker = P2
    room.attacks_remaining = 6

    # 打第一艘 (0, 0)
    server.handle_attack({
        'room_id': room.id, 'player_id': P2,
        'x': 0, 'y': 0,
    })
    assert room.players[P1].ships[0].shield is False
    assert room.players[P1].ships[1].shield is True  # 第二艘还有盾


def test_forced_kill_ignores_shield(room, events):
    """强制击杀无视护盾（沿用仁王之盾的口径）。"""
    room.players[P1].remaining_ships = 3
    room.players[P2].remaining_ships = 6
    for s in room.players[P1].ships[3:]:
        server._mark_ship_sunken(room.players[P1], s)
    apply_woxin(room, P1)

    room.current_phase = 'battle'
    room.current_attacker = P2
    room.attacks_remaining = 6
    # P2 拥有强制击杀
    room.players[P2].effect_flags.forced_kill = 1

    server.handle_attack({
        'room_id': room.id, 'player_id': P2,
        'x': 0, 'y': 0,
    })
    # 强制击杀：船直接沉，护盾没用上
    assert server._is_ship_alive(room.players[P1], room.players[P1].ships[0]) is False


# ---------------------------------------------------------------------------
# 速阶 1 在自己回合的准备阶段可用
# ---------------------------------------------------------------------------
def test_playable_in_preparation_phase(room):
    """准备阶段、自己回合 → can_play_magic_card 返回 True。"""
    room.current_phase = 'preparation'
    room.current_attacker = P1
    room.players[P1].remaining_ships = 3
    room.players[P2].remaining_ships = 6
    assert server.can_play_magic_card(room, P1, card('卧薪尝胆')) is True


def test_not_playable_in_opponent_turn(room):
    """不是自己回合 → can_play_magic_card 返回 False。"""
    room.current_phase = 'preparation'
    room.current_attacker = P2
    room.players[P1].remaining_ships = 3
    room.players[P2].remaining_ships = 6
    assert server.can_play_magic_card(room, P1, card('卧薪尝胆')) is False


# ---------------------------------------------------------------------------
# 看破 / 禁忌果实反制
# ---------------------------------------------------------------------------
def test_kanpo_blocks_woxin(room):
    """看破！生效时，被封锁的玩家不能用卧薪尝胆。"""
    room.players[P1].magic_blocked = True
    give_hand(room.players[P1], ['卧薪尝胆'])
    room.players[P1].remaining_ships = 3
    room.players[P2].remaining_ships = 6
    room.current_phase = 'preparation'
    room.current_attacker = P1

    r = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '卧薪尝胆', 'speed': 1, 'type': '普通', 'description': ''},
        'targets': {},
    })
    assert r['status'] == 'error'
    assert '看破' in r['message']


def test_forbidden_fruit_blocks_woxin(room):
    """禁忌果实生效时，非场地非失灵类卡不能发动。"""
    room.field_magic = card('禁忌果实')
    give_hand(room.players[P1], ['卧薪尝胆'])
    room.players[P1].remaining_ships = 3
    room.players[P2].remaining_ships = 6
    room.current_phase = 'preparation'
    room.current_attacker = P1
    assert server.can_play_magic_card(room, P1, card('卧薪尝胆')) is False
