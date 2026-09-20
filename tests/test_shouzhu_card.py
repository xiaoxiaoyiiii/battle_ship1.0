# -*- coding: utf-8 -*-
"""守株待兔（普通魔法卡）的回归测试。

按 CLAUDE.md 第 7 节「改卡要同步 4 处」要求覆盖：
  · magic_card.json / magic_cards.js 一致性
  · apply_magic_effect 的守株待兔分支
  · 选船 → set trap 标记
  · trap 标记的船被击沉 → 对方牺牲 min(2, alive)
  · 对方船数 1 → 也要牺牲那 1 艘
  · 对方船数 0 → 跳过
  · 新大回合 trap 过期
  · 看破 / 禁忌果实反制
  · AI 自动选船
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
    room = GameRoom('test-trap-room')
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


def apply_shouzhu(room, caster):
    """直接调用 apply_magic_effect（不模拟扣牌流程，本卡无须那种副作用）。"""
    return server.apply_magic_effect(room, caster, card('守株待兔'), {})


def confirm_sacrifice(room, player, x, y):
    return server.handle_confirm_sacrifice({
        'room_id': room.id,
        'player_id': player,
        'position': {'x': x, 'y': y},
    })


def kill_ship_via_apply_sunk(room, attacker_id, defender_id, ship):
    """模拟「击沉」走 _apply_ship_sunk_effects 的副作用链路。"""
    # 选个 ship 上任意一格当命中点
    x, y = ship.positions[0].x, ship.positions[0].y
    server._apply_ship_sunk_effects(room, room.id, attacker_id, defender_id, ship, x, y)


# ---------------------------------------------------------------------------
# 卡牌定义一致性
# ---------------------------------------------------------------------------
def test_card_definition_consistent():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, 'static', 'magic_card.json'), encoding='utf-8') as f:
        json_cards = json.load(f)
    shouzhu_json = [c for c in json_cards if c['name'] == '守株待兔']
    assert len(shouzhu_json) == 1
    wj = shouzhu_json[0]
    assert wj['speed'] == 1
    assert wj['type'] == '普通'

    with open(os.path.join(here, 'static', 'magic_cards.js'), encoding='utf-8') as f:
        js_src = f.read()
    assert f'name: "守株待兔"' in js_src
    assert f'speed: {wj["speed"]}' in js_src
    assert f'type: "{wj["type"]}"' in js_src
    assert wj['description'] in js_src


def test_shouzhu_card_enters_deck():
    names = [c.name for c in server.magic_cards]
    assert '守株待兔' in names


def test_deck_size_grew():
    """新加一张普通卡，牌池规模从 45 → 46。"""
    deck = server.magic_cards
    assert len(deck) == 46, f'卡池应 46 条，实际 {len(deck)}'


# ---------------------------------------------------------------------------
# 发动：没活船不能打
# ---------------------------------------------------------------------------
def test_blocked_when_no_ships(room):
    """施法者 0 活船 → 失败，不进入选船待办。"""
    room.players[P1].remaining_ships = 0
    # ships 还在但 remaining_ships=0 表示全沉了
    res = apply_shouzhu(room, P1)
    assert res.success is False
    assert '没有战舰' in res.message
    # 没有待办
    picks = getattr(room, 'pending_ship_picks', None) or []
    assert all(p.get('reason') != 'trap_setup' for p in picks)


# ---------------------------------------------------------------------------
# 选船待办登记（人类路径）
# ---------------------------------------------------------------------------
def test_human_path_registers_trap_setup_pick(room):
    """人类施法者打出 → 入队一条 trap_setup 待办，等玩家点船。"""
    # 确保是非 AI 房间
    room.is_ai_room = False
    res = apply_shouzhu(room, P1)
    assert res.success is True
    picks = getattr(room, 'pending_ship_picks', None) or []
    trap_picks = [p for p in picks if p.get('reason') == 'trap_setup' and p.get('player') == P1]
    assert len(trap_picks) == 1


# ---------------------------------------------------------------------------
# AI 自动选船并打标记
# ---------------------------------------------------------------------------
def test_ai_auto_picks_and_sets_trap(room, monkeypatch, events):
    """AI 房间：_request_ship_pick 直接返回一艘活船，应立刻打标记并广播。"""
    room.is_ai_room = True
    # P2 是 AI；让 P1 仍然是人，但 P1 是施法者；让 P1 也算 AI 触发自动选
    # 实际机制：_request_ship_pick 检查 chooser_id == _ai_player_id
    monkeypatch.setattr(server, '_ai_player_id', lambda r: P1)
    res = apply_shouzhu(room, P1)
    assert res.success is True
    # 应该有一艘船被打上 trap
    traps = [s for s in room.players[P1].ships if getattr(s, 'trap', False)]
    assert len(traps) == 1
    # 广播 trap_set
    sets = find_emit(events, 'trap_set')
    assert len(sets) >= 1


# ---------------------------------------------------------------------------
# 人类确认：handle_confirm_sacrifice 的 trap_setup 分支
# ---------------------------------------------------------------------------
def test_human_confirm_sets_trap(room):
    """人类玩家点选一艘船 → trap=True，待办被消费，广播 trap_set。"""
    room.is_ai_room = False
    apply_shouzhu(room, P1)
    # 玩家点 (0, 0) 那艘船
    resp = confirm_sacrifice(room, P1, 0, 0)
    assert resp['status'] == 'success'
    # (0,0) 对应第一艘船，应有 trap 标记
    target = next((s for s in room.players[P1].ships
                   if any(p.x == 0 and p.y == 0 for p in s.positions)), None)
    assert target is not None
    assert target.trap is True
    # 其它船没被打标记
    others = [s for s in room.players[P1].ships if s is not target]
    assert all(not getattr(s, 'trap', False) for s in others)
    # 待办已被消费
    picks = getattr(room, 'pending_ship_picks', None) or []
    assert all(p.get('reason') != 'trap_setup' for p in picks)


def test_human_confirm_invalid_cell(room):
    """点一个没有船的格子 → 报错，待办仍在。"""
    room.is_ai_room = False
    apply_shouzhu(room, P1)
    # (3, 3) 不在 P1 的船位上（P1 船都在 y=0 行）
    resp = confirm_sacrifice(room, P1, 3, 3)
    assert resp['status'] == 'error'
    picks = getattr(room, 'pending_ship_picks', None) or []
    assert any(p.get('reason') == 'trap_setup' for p in picks)


def test_human_confirm_wrong_player(room):
    """非施法者不能确认。"""
    room.is_ai_room = False
    apply_shouzhu(room, P1)
    resp = confirm_sacrifice(room, P2, 0, 5)  # P2 来点
    assert resp['status'] == 'error'


# ---------------------------------------------------------------------------
# 触发：陷阱船被击沉 → 对方牺牲 min(2, alive)
# ---------------------------------------------------------------------------
def test_trap_triggered_opponent_sacrifices_two(room, monkeypatch):
    """陷阱船被击沉（普通攻击路径）→ 对方牺牲 2 艘（AI 自动）。"""
    room.is_ai_room = True
    # P2 是 AI，被要求牺牲时自动选
    monkeypatch.setattr(server, '_ai_player_id', lambda r: P2)
    # P1 把第一艘船打上陷阱
    target = room.players[P1].ships[0]
    target.trap = True
    # P2 有 6 艘活船
    assert len(server._alive_ships(room.players[P2])) == 6

    # 走 _apply_ship_sunk_effects（普通攻击击沉路径）
    kill_ship_via_apply_sunk(room, P2, P1, target)

    # P2 应该牺牲了 2 艘（AI 自动选）
    assert room.players[P2].remaining_ships == 4
    # 触发后 trap 标记被清掉（即便 ship 还在 ships 列表里 —— 普通攻击路径会保留沉船对象）
    # 注意：_apply_ship_sunk_effects 不会从 ships 移除，只是标记 sunken
    # 但 trap 标记已被 _on_ship_destroyed 清掉
    assert target.trap is False


def test_trap_triggered_opponent_one_ship(room, monkeypatch):
    """对方只有 1 艘活船时，也要牺牲那 1 艘（不豁免）。"""
    room.is_ai_room = True
    monkeypatch.setattr(server, '_ai_player_id', lambda r: P2)
    # P2 只留 1 艘活船
    only = room.players[P2].ships[0]
    for s in room.players[P2].ships[1:]:
        server._mark_ship_sunken(room.players[P2], s)
    room.players[P2].remaining_ships = 1

    # P1 第一艘船打上陷阱
    target = room.players[P1].ships[0]
    target.trap = True

    kill_ship_via_apply_sunk(room, P2, P1, target)

    # P2 那 1 艘被牺牲
    assert room.players[P2].remaining_ships == 0


def test_trap_triggered_opponent_zero_ships(room, monkeypatch):
    """对方没有活船 → 不入队牺牲（need=0）。"""
    room.is_ai_room = True
    monkeypatch.setattr(server, '_ai_player_id', lambda r: P2)
    # P2 全部标记沉没
    for s in room.players[P2].ships:
        server._mark_ship_sunken(room.players[P2], s)
    room.players[P2].remaining_ships = 0

    target = room.players[P1].ships[0]
    target.trap = True
    kill_ship_via_apply_sunk(room, P2, P1, target)

    # 不应该入队 trap_sacrifice 待办
    picks = getattr(room, 'pending_ship_picks', None) or []
    assert all(p.get('reason') != 'trap_sacrifice' for p in picks)


def test_trap_triggered_human_queues_two_picks(room):
    """人类对手：陷阱触发后入队 2 条 trap_sacrifice 待办等玩家点。"""
    room.is_ai_room = False
    target = room.players[P1].ships[0]
    target.trap = True
    kill_ship_via_apply_sunk(room, P2, P1, target)

    picks = [p for p in (getattr(room, 'pending_ship_picks', None) or [])
             if p.get('player') == P2 and p.get('reason') == 'trap_sacrifice']
    assert len(picks) == 2


def test_trap_triggered_via_magic_path(room, monkeypatch):
    """区域魔法（硫磺火焰/轰炸）击沉陷阱船 → 同样触发。"""
    room.is_ai_room = True
    monkeypatch.setattr(server, '_ai_player_id', lambda r: P2)
    target = room.players[P1].ships[0]
    target.trap = True

    # 直接调用 _on_ship_destroyed（区域魔法共用入口，source='magic'）
    server._on_ship_destroyed(room, P1, target, source='magic')

    assert room.players[P2].remaining_ships == 4  # 牺牲 2 艘


# ---------------------------------------------------------------------------
# 触发后 trap 标记被清，不会重复触发
# ---------------------------------------------------------------------------
def test_trap_cleared_after_trigger(room, monkeypatch):
    """同一艘船的陷阱只能触发一次（_on_ship_destroyed 触发后立刻清标记）。"""
    room.is_ai_room = True
    monkeypatch.setattr(server, '_ai_player_id', lambda r: P2)
    target = room.players[P1].ships[0]
    target.trap = True

    kill_ship_via_apply_sunk(room, P2, P1, target)
    assert target.trap is False
    # 第二次再调 _on_ship_destroyed（理论上不会发生，但验证不会再次触发）
    before = room.players[P2].remaining_ships
    server._on_ship_destroyed(room, P1, target, source='magic')
    assert room.players[P2].remaining_ships == before  # 没再牺牲


# ---------------------------------------------------------------------------
# 跨回合过期
# ---------------------------------------------------------------------------
def test_trap_expires_next_round(room):
    """新大回合开始时，trap 标记被清掉。"""
    target = room.players[P1].ships[0]
    target.trap = True

    # 模拟 end_turn 进入新大回合（绕过整套阶段流转：直接调用清理段会太重，这里
    # 直接验证清理逻辑本身）
    # 简化：直接调用 end_turn 走到 next_index==0 分支
    # 先把房间状态摆到能让 end_turn 进入新大回合
    room.current_phase = 'end'
    room.current_attacker = P2  # 攻击顺序最后一个，结束 → 进新大回合
    room.attack_order = [P1, P2]
    room.chain = []
    room.chain_waiting = False
    server.end_turn({'room_id': room.id, 'player_id': P2})

    assert target.trap is False
    assert room.round == 2  # 进入新大回合


# ---------------------------------------------------------------------------
# 速阶 1 在自己回合的准备阶段可用
# ---------------------------------------------------------------------------
def test_playable_in_preparation_phase(room):
    room.current_phase = 'preparation'
    room.current_attacker = P1
    assert server.can_play_magic_card(room, P1, card('守株待兔')) is True


def test_not_playable_in_opponent_turn(room):
    room.current_phase = 'preparation'
    room.current_attacker = P2
    assert server.can_play_magic_card(room, P1, card('守株待兔')) is False


# ---------------------------------------------------------------------------
# 看破 / 禁忌果实反制
# ---------------------------------------------------------------------------
def test_kanpo_blocks_shouzhu(room):
    """看破！生效时，被封锁的玩家不能用守株待兔。"""
    room.players[P1].magic_blocked = True
    give_hand(room.players[P1], ['守株待兔'])
    room.current_phase = 'preparation'
    room.current_attacker = P1

    r = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '守株待兔', 'speed': 1, 'type': '普通', 'description': ''},
        'targets': {},
    })
    assert r['status'] == 'error'
    assert '看破' in r['message']


def test_forbidden_fruit_blocks_shouzhu(room):
    """禁忌果实生效时，非场地非失灵类卡不能发动。"""
    room.field_magic = card('禁忌果实')
    give_hand(room.players[P1], ['守株待兔'])
    room.current_phase = 'preparation'
    room.current_attacker = P1
    assert server.can_play_magic_card(room, P1, card('守株待兔')) is False


# ---------------------------------------------------------------------------
# _SHIP_PICK_CARDS / SHIP_PICK_PRIORITY 登记
# ---------------------------------------------------------------------------
def test_ship_pick_registry():
    assert server._SHIP_PICK_CARDS.get('守株待兔') == 'trap_setup'
    assert server.SHIP_PICK_PRIORITY.get('trap_setup') == 75
    assert server.SHIP_PICK_PRIORITY.get('trap_sacrifice', 0) == 0  # 牺牲用 dice 同款去重豁免
