# -*- coding: utf-8 -*-
"""连锁状态机 + 无效化引擎回归测试。

规则（与小弈确认）：
1. 失灵！只康连锁栈里紧邻它下方那一项（不再读全场 history）。
2. 响应窗口：打出后先给对方；对方放弃后窗口回到自己（支持自连锁）；
   连续两次放弃才结算。
3. 失灵！康不动看破！（看破优先级更高）；失灵！也康不动加百列之光。
4. 场地魔法被无效化 = 贴了再拆。
"""
import pytest

import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

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
    # 不让真实后台计时器跑起来
    monkeypatch.setattr(server.socketio, 'start_background_task',
                        lambda target, *a, **k: None)
    return captured


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def make_room():
    room = GameRoom('chain-test-room')
    room.players[P1] = Player(name='p1', ships=[], attacks=[], remaining_ships=0, sid='sid-p1')
    room.players[P2] = Player(name='p2', ships=[], attacks=[], remaining_ships=0, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 1
    room_manager.rooms[room.id] = room
    return room


def ship(*cells):
    return PlayerShip(positions=[Position(x, y) for x, y in cells], hits=[])


def card(name):
    return MagicCard(name)


def give_hand(player, names):
    player.magic_hand = [card(n) for n in names]


def play(room, player_id, name, targets=None):
    """走真实入口打出魔法卡。"""
    return server.handle_use_magic_card({
        'room_id': room.id, 'player_id': player_id,
        'card': {'name': name, 'speed': card(name).speed,
                 'type': card(name).type, 'description': ''},
        'targets': targets or {},
    })


def respond(room, player_id, name=None):
    """响应连锁：name=None 表示放弃。"""
    payload = {'room_id': room.id, 'player_id': player_id, 'chain': name is not None}
    if name is not None:
        payload['card'] = {'name': name, 'speed': card(name).speed,
                           'type': card(name).type, 'description': ''}
    return server.chain_response(payload)


# ---------------------------------------------------------------------------
# 结算顺序：栈顶先出（后发先至）
# ---------------------------------------------------------------------------
def test_chain_resolves_lifo_and_negated_skips(room):
    """失灵！在栈顶先结算，康掉下方刚打出的轰炸，轰炸不再炸船。"""
    room.players[P2].ships = [ship((0, 0)), ship((1, 0))]
    room.players[P2].remaining_ships = 2
    room.chain = [
        server.ChainItem(P1, card('轰炸'), {'target_line': {'type': 'row', 'index': 0}}, 0),
        server.ChainItem(P2, card('失灵！'), {}, 1),
    ]
    results = server.resolve_chain(room)

    # 失灵先出栈并标记下方项；轰炸被跳过
    assert results[0].card.name == '失灵！'
    assert getattr(results[0], 'negate_target', False) is True
    assert results[1].card.name == '轰炸'
    assert getattr(results[1], 'negated_skip', False) is True
    # 轰炸未生效：两艘船都还在
    assert room.players[P2].remaining_ships == 2
    # 被无效化的卡不进历史
    assert all(h['card'].name != '轰炸' for h in room.magic_history)


def test_chain_without_negation_applies_effect(room):
    """连锁中没有无效化卡时，效果正常生效。"""
    room.players[P2].ships = [ship((0, 0)), ship((1, 0))]
    room.players[P2].remaining_ships = 2
    room.chain = [
        server.ChainItem(P1, card('轰炸'), {'target_line': {'type': 'row', 'index': 0}}, 0),
    ]
    server.resolve_chain(room)
    assert room.players[P2].remaining_ships == 0


# ---------------------------------------------------------------------------
# 失灵！的目标 = 紧邻下方那一项
# ---------------------------------------------------------------------------
def test_shiling_negates_adjacent_not_stale_history(room):
    """失灵只康栈中紧邻下方那张，不会误伤更早的历史牌。"""
    room.magic_history = [{'card': card('溅射'), 'caster': P2, 'timestamp': 0}]
    room.chain = [
        server.ChainItem(P2, card('增援'), {}, 0),
        server.ChainItem(P1, card('失灵！'), {}, 1),
    ]
    results = server.resolve_chain(room)
    # 历史里的旧牌仍在（没有被 pop）
    assert any(h['card'].name == '溅射' for h in room.magic_history)
    # 增援被康，没进历史
    assert all(h['card'].name != '增援' for h in room.magic_history)
    assert getattr(results[1], 'negated_skip', False) is True


def test_shiling_cannot_negate_kanpo(room):
    """看破优先级高于失灵：失灵康不动看破，看破照常封锁。"""
    room.chain = [
        server.ChainItem(P2, card('看破！'), {}, 0),
        server.ChainItem(P1, card('失灵！'), {}, 1),
    ]
    results = server.resolve_chain(room)
    assert results[0].card.name == '失灵！'
    assert results[0].success is False
    # 看破正常生效
    assert room.players[P1].magic_blocked is True


def test_shiling_cannot_negate_gabriel(room):
    """失灵康不动加百列之光。"""
    room.chain = [
        server.ChainItem(P2, card('加百列之光'), {}, 0),
        server.ChainItem(P1, card('失灵！'), {}, 1),
    ]
    results = server.resolve_chain(room)
    assert results[0].card.name == '失灵！'
    assert results[0].success is False


# ---------------------------------------------------------------------------
# 加百列之光
# ---------------------------------------------------------------------------
def test_negated_field_card_goes_to_discard(room):
    """被无效化的场地魔法卡不会凭空消失：贴了再拆，进弃牌堆。"""
    room.chain = [
        server.ChainItem(P2, card('禁忌果实'), {}, 0),
        server.ChainItem(P1, card('失灵！'), {}, 1),
    ]
    server.resolve_chain(room)
    assert room.field_magic is None
    assert any(c.name == '禁忌果实' for c in room.magic_discard)


def test_gabriel_negates_adjacent_and_field(room):
    """加百列康栈中下方那一项，并拆掉当前生效的场地魔法。"""
    room.field_magic = card('禁忌果实')
    room.chain = [
        server.ChainItem(P2, card('轰炸'), {'target_line': {'type': 'row', 'index': 0}}, 0),
        server.ChainItem(P1, card('加百列之光'), {}, 1),
    ]
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1
    server.resolve_chain(room)
    assert room.field_magic is None          # 场地被拆
    assert room.players[P2].remaining_ships == 1  # 轰炸被康，船还在


# ---------------------------------------------------------------------------
# 响应窗口：自连锁 / 连续两次放弃
# ---------------------------------------------------------------------------
def test_play_opens_window_for_opponent(room):
    give_hand(room.players[P1], ['增援'])
    give_hand(room.players[P2], ['失灵！'])
    res = play(room, P1, '增援')
    assert res['status'] == 'success'
    assert room.chain_waiting is True
    assert room.chain_window == P2


def test_self_chain_after_opponent_passes(room):
    """对方放弃后，窗口回到自己，可追加自己的第二张速阶3。"""
    give_hand(room.players[P1], ['增援', '疗愈'])
    give_hand(room.players[P2], ['失灵！'])

    play(room, P1, '增援')
    assert room.chain_window == P2

    respond(room, P2, None)              # 对方放弃
    assert room.chain_waiting is True
    assert room.chain_window == P1       # 窗口回到自己

    respond(room, P1, '疗愈')            # 自连锁
    assert len(room.chain) == 2
    assert room.chain_window == P2


def test_two_consecutive_passes_resolve(room):
    give_hand(room.players[P1], ['增援', '疗愈'])
    give_hand(room.players[P2], ['失灵！'])

    play(room, P1, '增援')
    respond(room, P2, None)              # 第一次放弃
    assert room.chain_waiting is True    # 窗口回到 P1（手上还有速阶3）
    respond(room, P1, None)              # 第二次放弃 → 结算
    assert room.chain == []
    assert room.chain_waiting is False


def test_cannot_play_while_window_open(room):
    """响应窗口未关闭时不能另开新牌。"""
    give_hand(room.players[P1], ['增援', '疗愈'])
    give_hand(room.players[P2], ['失灵！'])
    play(room, P1, '增援')
    res = play(room, P1, '疗愈')
    assert res['status'] == 'error'


def test_chain_response_removes_card_from_hand(room):
    """连锁响应打出的速阶3必须从手牌移除并进弃牌堆。"""
    give_hand(room.players[P1], ['增援'])
    give_hand(room.players[P2], ['失灵！'])
    play(room, P1, '增援')
    respond(room, P2, '失灵！')
    assert all(c.name != '失灵！' for c in room.players[P2].magic_hand)
    assert any(c.name == '失灵！' for c in room.magic_discard)


# ---------------------------------------------------------------------------
# 超时兜底
# ---------------------------------------------------------------------------
def test_timeout_pass_advances_window(monkeypatch, room):
    """窗口超时视为放弃：顺延给对手（对手可响应时）。"""
    monkeypatch.setattr(server.time, 'sleep', lambda s: None)
    ran = []
    monkeypatch.setattr(server.socketio, 'start_background_task',
                        lambda target, *a, **k: ran.append(target))

    give_hand(room.players[P1], ['失灵！'])
    give_hand(room.players[P2], ['增援'])
    room.chain = [server.ChainItem(P2, card('增援'), {}, 0)]
    room.chain_window = P1
    room.chain_waiting = True
    room.chain_timer += 1

    server._schedule_chain_timeout(room.id, room.chain_timer)
    ran[0]()  # 手动触发超时回调

    # P1 放弃 → 窗口顺延给 P2（P2 有速阶3可响应）
    assert room.chain_passes == 1
    assert room.chain_window == P2
