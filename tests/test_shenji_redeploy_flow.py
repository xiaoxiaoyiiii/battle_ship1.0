# -*- coding: utf-8 -*-
"""神机妙算预言成功后「重新部署」交互的回归测试（2026-09-14）。

玩家实测：宣言预言成功之后，没有出现让自己摆放已经死亡的船的界面。

卡面：「只可在对方的准备阶段以及自己的所有阶段使用。宣言一个数目x，
       如果对方的结束阶段结束之后自己的船数减少了x，那么那些原本会减少的船
       不会减少并【在原位置或者对方没有打过的位置重新部署】。」

根因：
  "重新部署"是玩家的主动选择，但旧实现直接调 _revive_sunken_ships()
  —— 那是"原地复活"，没有任何交互，玩家既看不到界面也做不了选择。

修法：
  新增放置流程 kind='shenji_redeploy'，逐艘让玩家点选位置：
    · 可选范围 = 各自的原位置（豁免"已被对方打过"）∪ 对方未打过的空格
    · 沉船仍留在 player.ships 里（本项目击沉不移除），占位检查必须跳过沉船，
      否则连原位都会被判成"已被己方战舰占用"
    · 重连快照也要带上合法格名单，否则面板恢复后原位置点不动
"""
import pytest

import server
from server import ChainItem, GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'


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
    room = GameRoom('test-room')
    room.players[P1] = Player(name='p1',
                              ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(6)],
                              attacks=[], remaining_ships=6, sid='sid-p1')
    room.players[P2] = Player(name='p2',
                              ships=[PlayerShip(positions=[Position(i, 5)], hits=[]) for i in range(6)],
                              attacks=[], remaining_ships=6, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 5
    room_manager.rooms[room.id] = room
    return room


def card(name):
    return MagicCard(name)


def declare(room, pid, x):
    """走真实的宣言入口。"""
    return server.handle_confirm_shenji_declare(
        {'room_id': room.id, 'player_id': pid, 'prediction': x})


def run_prediction(room, x=1):
    """宣言 x → 对方打沉 1 艘 → 大回合结束触发判定。返回 pending_placement。"""
    room.players[P1].effect_flags.prediction = x
    room.game_effects['prediction_initial_p1'] = {
        'ships': 6, 'sunken': len(room.players[P1].sunken_ships),
    }
    room.current_attacker = P2
    server.handle_attack({'room_id': room.id, 'player_id': P2, 'x': 0, 'y': 0})
    room.current_phase = 'end'
    room.attacks_remaining = 0
    server.end_turn({'room_id': room.id, 'player_id': P2})
    return room.magic_temp_data.get('pending_placement')


# ---------------------------------------------------------------------------
# 核心：预言成功必须开启重新部署流程
# ---------------------------------------------------------------------------
def test_prediction_success_opens_redeploy_flow(room, events):
    """★ 玩家场景：预言成功 → 必须出现放置流程（而不是静默原地复活）。"""
    pending = run_prediction(room, x=1)

    assert pending, '预言成功后必须开启放置流程，否则玩家没有任何界面'
    assert pending['kind'] == 'shenji_redeploy'
    assert pending['caster'] == P1
    assert pending['remaining'] == 1


def test_prediction_success_emits_placement_request(room, events):
    """要推送 placement_request，前端才会弹面板。"""
    run_prediction(room, x=1)
    reqs = [d for e, d, to, r in events if e == 'placement_request']
    assert reqs, '必须推送 placement_request'
    payload = reqs[-1]
    assert payload['kind'] == 'shenji_redeploy'
    assert payload.get('message'), '要有明确提示文案'


def test_redeploy_sends_no_whitelist(room, events):
    """★ 不能再下发 allowed 白名单（2026-09-16 修）。

    `allowed` 在前端是**白名单**语义（game.js: `blocked 命中 或 不在 allowed 里`
    → 直接禁点且不绑 click），那是绝处逢生「只准放在原本有船的格子」用的。
    神机妙算一度也下发它，于是**除了原位置全部点不动** —— 玩家实测报的
    「只能摆在原位置/被打过的格子，放不到对方没打过的空格」就是这么来的。

    改法：原位置改为「从 blocked 里剔除」（见下一条用例），不再下发白名单。
    """
    run_prediction(room, x=1)
    reqs = [d for e, d, to, r in events if e == 'placement_request']
    assert not (reqs[-1].get('allowed')), (
        f'神机妙算不该下发 allowed 白名单，实际：{reqs[-1].get("allowed")}')


def test_redeploy_original_cell_not_blocked(room, events):
    """原位置即便被对方打过，也不能出现在 blocked 里。"""
    run_prediction(room, x=1)
    reqs = [d for e, d, to, r in events if e == 'placement_request']
    blocked = {(b['x'], b['y']) for b in reqs[-1].get('blocked') or []}
    assert (0, 0) not in blocked, '原位置应豁免"已被对方打过"'


def test_can_redeploy_to_original_cell(room):
    """★ 玩家把船放回原位（该格已被对方打过）必须成功。

    注意沉船仍留在 player.ships 里（本项目击沉不移除），
    占位检查必须跳过沉船，否则原位会被误判成"已被己方战舰占用"。
    """
    run_prediction(room, x=1)
    assert room.players[P1].remaining_ships == 5

    res = server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 0, 'y': 0}})

    assert res.get('status') == 'success', f'应能放回原位，实际：{res}'
    assert room.players[P1].remaining_ships == 6, '船数应恢复'
    assert not room.magic_temp_data.get('pending_placement'), '流程应结束'


def test_can_redeploy_to_free_cell(room):
    """也可以放到对方没打过的空格（卡面的第二个选项）。"""
    run_prediction(room, x=1)
    res = server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 3, 'y': 3}})
    assert res.get('status') == 'success', f'应能放到空格，实际：{res}'
    assert room.players[P1].remaining_ships == 6


def test_redeploy_moves_ship_and_clears_hits(room):
    """重新部署后船要在新位置、命中清空（否则复活后打不沉）。"""
    run_prediction(room, x=1)
    server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 3, 'y': 3}})

    placed = [sh for sh in room.players[P1].ships
              if any(p.x == 3 and p.y == 3 for p in sh.positions)]
    assert placed, '船应出现在新位置'
    assert placed[0].hits == [], '命中必须清空'
    assert server._is_ship_alive(room.players[P1], placed[0]), '应被视为存活'


def test_redeploy_rejects_occupied_cell(room):
    """放到"己方活船"占用的格子仍要拒绝。"""
    run_prediction(room, x=1)
    # (1,0) 上有 P1 的活船
    res = server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 1, 'y': 0}})
    assert res.get('status') == 'error', f'活船占位不该放行，实际：{res}'


def test_redeploy_rejects_opponent_attacked_cell(room):
    """对方打过、且不是原位置的格子仍要拒绝（卡面只豁免"原位"）。"""
    run_prediction(room, x=1)
    # 让 P2 再打一个空位
    room.players[P2].attacks.append(Position(x=4, y=4))
    res = server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 4, 'y': 4}})
    assert res.get('status') == 'error', f'非原位的被攻击格不该放行，实际：{res}'


# ---------------------------------------------------------------------------
# 多艘：逐艘依次点选
# ---------------------------------------------------------------------------
def test_multi_ship_redeploy_is_sequential(room, events):
    """宣言 x=2、被打沉 2 艘 → 逐个点选，两次确认。"""
    room.players[P1].effect_flags.prediction = 2
    room.game_effects['prediction_initial_p1'] = {'ships': 6, 'sunken': 0}
    room.current_attacker = P2
    server.handle_attack({'room_id': room.id, 'player_id': P2, 'x': 0, 'y': 0})
    server.handle_attack({'room_id': room.id, 'player_id': P2, 'x': 1, 'y': 0})
    room.current_phase = 'end'
    room.attacks_remaining = 0
    server.end_turn({'room_id': room.id, 'player_id': P2})

    pending = room.magic_temp_data.get('pending_placement')
    assert pending and pending['kind'] == 'shenji_redeploy'
    assert pending['remaining'] == 2, f'应待放置 2 艘，实际 {pending}'

    r1 = server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 0, 'y': 0}})
    assert r1.get('status') == 'success', r1
    assert room.magic_temp_data['pending_placement']['remaining'] == 1, '应还剩 1 艘'

    r2 = server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 3, 'y': 3}})
    assert r2.get('status') == 'success', r2
    assert not room.magic_temp_data.get('pending_placement'), '两艘放完流程应结束'
    assert room.players[P1].remaining_ships == 6


# ---------------------------------------------------------------------------
# 反证：预言失败时不该开启流程
# ---------------------------------------------------------------------------
def test_prediction_failure_opens_nothing(room):
    """宣言 x=3 但只被打沉 1 艘 → 预言失败，不该开流程。"""
    pending = run_prediction(room, x=3)
    assert not pending, '预言未命中不该开放置流程'
    assert room.players[P1].effect_flags.prediction == 0, '标记应被消费'


def test_other_placement_kinds_unaffected(room):
    """反证：增援的放置流程不受影响（原位仍不可放）。"""
    room.players[P1].magic_hand = [card('增援')]
    room.players[P1].remaining_ships = 5
    room.players[P1].ships = room.players[P1].ships[:5]
    server.apply_magic_effect(room, P1, card('增援'), {})

    pending = room.magic_temp_data.get('pending_placement')
    assert pending and pending['kind'] == 'reinforce'

    # 增援没有 allow_cells 豁免，被打过的格子仍拒绝
    room.players[P2].attacks.append(Position(x=4, y=4))
    res = server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 4, 'y': 4}})
    assert res.get('status') == 'error', '增援不该放行被攻击过的格子'


def test_placement_error_ignore_sunken_flag(room):
    """_placement_error 的 ignore_sunken：沉船不占位，活船照常占位。"""
    owner = room.players[P1]
    dead = owner.ships[0]
    dead.hits = list(dead.positions)      # 让它变成沉船

    # 不跳过沉船 → (0,0) 被占用
    assert server._placement_error(room, P1, 0, 0, ignore_sunken=False) is not None
    # 跳过沉船 → (0,0) 可放（还需对方没打过；这里 P2 没打过 0,0）
    assert server._placement_error(room, P1, 0, 0, ignore_sunken=True) is None
    # 活船仍占位
    assert server._placement_error(room, P1, 1, 0, ignore_sunken=True) is not None
