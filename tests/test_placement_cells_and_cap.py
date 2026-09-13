# -*- coding: utf-8 -*-
"""神机妙算空格被误禁 + 放置后格子状态 + 船数上限 的回归测试（2026-09-14）。

玩家实测报的三个问题：
  1. 神机妙算重新部署时"只能摆放原本沉船的地方"；
  2. 摆完后"这个格子出现很大的问题"；
  3. 增援弹出"船数已达上限"但牌被吞掉，而作者确认【不存在船数上限】。

根因：
  ① `_placement_blocked_cells`（决定前端哪些格子画成灰色）与 `_placement_error`
     （真正的校验）是两套独立实现，且已漂移：前者把【所有】己方船（含沉船）
     都算作占用，后者在 ignore_sunken=True 时会跳过沉船。于是神机妙算时
     旧沉船的位置也被画成灰色，玩家以为只能点原位。
  ② 放置流程的四个分支都没有把新位置从【双方的攻击历史】里移除
     （只有 _revive_sunken_ships 做了）。后果：那格仍被前端画成"已命中"，
     且 handle_attack 会以"你已经攻击过这个位置"拒绝对方再打 —— 幽灵船。
  ③ 增援/死者苏生/疗愈 三处都有 `remaining_ships >= 6` 的拒绝，
     而牌在 handle_use_magic_card 里已经离手 → 白吞一张卡。

作者裁定：船数只受棋盘格数（36 格）限制，没有 6 艘上限。
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
    room.round = 10
    room_manager.rooms[room.id] = room
    return room


def card(name):
    return MagicCard(name)


# ---------------------------------------------------------------------------
# 问题 1：blocked 与校验口径必须一致
# ---------------------------------------------------------------------------
def test_blocked_cells_skip_sunken(room):
    """ignore_sunken=True 时，沉船位置不该被算作占用。"""
    p = room.players[P1]
    dead = p.ships[0]
    dead.hits = list(dead.positions)
    server._mark_ship_sunken(p, dead)

    default_blocked = {(b['x'], b['y']) for b in server._placement_blocked_cells(room, P1)}
    assert (0, 0) in default_blocked, '默认口径把沉船算作占用'

    relaxed = {(b['x'], b['y'])
               for b in server._placement_blocked_cells(room, P1, ignore_sunken=True)}
    assert (0, 0) not in relaxed, 'ignore_sunken 应跳过沉船，否则前端把它画成灰色'


def test_blocked_and_error_agree(room):
    """★ blocked 与 _placement_error 必须对每个格子给出同样的结论。

    这两个函数是两套独立实现，曾经漂移过 —— 神机妙算时空格被误画成灰色，
    玩家以为"只能摆在原本沉船的地方"。
    """
    p = room.players[P1]
    dead = p.ships[0]
    dead.hits = list(dead.positions)
    server._mark_ship_sunken(p, dead)
    # 让对方打过一些格子
    for x, y in [(2, 2), (3, 3)]:
        room.players[P2].attacks.append(Position(x=x, y=y))

    blocked = {(b['x'], b['y'])
               for b in server._placement_blocked_cells(room, P1, ignore_sunken=True)}

    for x in range(6):
        for y in range(6):
            err = server._placement_error(room, P1, x, y, ignore_sunken=True)
            if (x, y) in blocked:
                assert err is not None, f'({x},{y}) 被画成灰色，但校验说可放 —— 口径不一致'
            else:
                assert err is None, f'({x},{y}) 可点，但校验拒绝：{err} —— 口径不一致'


def test_shenji_free_cells_not_blocked(room, events):
    """★ 神机妙算下发的 blocked 里，不该有"对方未打过、也没被活船占用"的空格。"""
    p = room.players[P1]
    # 两艘旧沉船 + 两艘本回合新沉
    for i in (5, 4):
        sh = p.ships[i]
        sh.hits = list(sh.positions)
        server._mark_ship_sunken(p, sh)
    p.remaining_ships = 4
    server._apply_shenji_prediction(room, P1, 2)
    room.game_effects['prediction_initial_p1']['sunken_ids'] = []
    for i in (3, 2):
        sh = p.ships[i]
        sh.hits = list(sh.positions)
        server._mark_ship_sunken(p, sh)
    p.remaining_ships = 2

    events.clear()
    server._begin_shenji_redeploy(room, P1, 2, already_sunken_ids=[])

    reqs = [d for e, d, to, r in events if e == 'placement_request']
    assert reqs
    payload = reqs[-1]
    blocked = {(b['x'], b['y']) for b in payload.get('blocked') or []}
    opp_attacked = {(a.x, a.y) for a in room.players[P2].attacks}
    alive_cells = {(pos.x, pos.y) for sh in p.ships
                   if server._is_ship_alive(p, sh) for pos in sh.positions}

    free = [(x, y) for x in range(6) for y in range(6)
            if (x, y) not in opp_attacked and (x, y) not in alive_cells]
    wrongly_blocked = [c for c in free if c in blocked]
    assert not wrongly_blocked, (
        f'这些空格被误禁，玩家会以为只能摆原位：{wrongly_blocked}')


# ---------------------------------------------------------------------------
# 问题 2：放置后格子状态
# ---------------------------------------------------------------------------
def test_reinforce_clears_attack_history(room):
    """增援放到某格后，该格要从双方攻击历史里移除。"""
    room.players[P1].remaining_ships = 5
    room.players[P1].ships = room.players[P1].ships[:5]
    room.players[P2].attacks.append(Position(x=3, y=3))   # 对方打过
    room.players[P1].attacks.append(Position(x=3, y=3))   # 自己也打过

    room.players[P1].magic_hand = [card('增援')]
    server.apply_magic_effect(room, P1, card('增援'), {})
    # 增援不允许放被对方打过的格 → 换一个干净的格子；这里直接验证清理函数
    server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 1, 'y': 1}})

    assert not any(a.x == 1 and a.y == 1 for a in room.players[P2].attacks)
    assert not any(a.x == 1 and a.y == 1 for a in room.players[P1].attacks)


def test_clear_attacks_helper(room):
    """_clear_attacks_on_cells 清双方的历史。"""
    room.players[P1].attacks.append(Position(x=2, y=2))
    room.players[P2].attacks.append(Position(x=2, y=2))
    room.players[P2].attacks.append(Position(x=4, y=4))

    server._clear_attacks_on_cells(room, [Position(x=2, y=2)])

    assert not any(a.x == 2 and a.y == 2 for a in room.players[P1].attacks)
    assert not any(a.x == 2 and a.y == 2 for a in room.players[P2].attacks)
    assert any(a.x == 4 and a.y == 4 for a in room.players[P2].attacks), '别的格不该被误清'


def test_shenji_original_cell_becomes_attackable(room):
    """★ 神机妙算把船放回"对方打过的原位"后，对方必须能再打这个格。

    否则这艘船永远打不沉（handle_attack 会以"你已经攻击过这个位置"拒绝）——
    就是玩家说的"这个格子出现很大的问题"。
    """
    p = room.players[P1]
    ship = p.ships[0]
    room.players[P2].attacks.append(Position(x=0, y=0))    # 对方打过原位
    ship.hits = list(ship.positions)
    server._mark_ship_sunken(p, ship)
    p.remaining_ships = 5

    server._apply_shenji_prediction(room, P1, 1)
    room.game_effects['prediction_initial_p1']['sunken_ids'] = []
    server._begin_shenji_redeploy(room, P1, 1, already_sunken_ids=[])

    out = server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 0, 'y': 0}})
    assert out.get('status') == 'success', out

    assert not any(a.x == 0 and a.y == 0 for a in room.players[P2].attacks), (
        '原位应从对方攻击历史里移除，否则前端仍画成已命中')
    # 对方可以再打这个格
    room.current_attacker = P2
    room.attacks_remaining = 6
    atk = server.handle_attack({'room_id': room.id, 'player_id': P2, 'x': 0, 'y': 0})
    assert atk.get('status') == 'success', f'对方应能攻击该格，实际：{atk}'


def test_revive_clears_attack_history(room):
    """死者苏生放到新格后同样要清历史。"""
    p = room.players[P1]
    ship = p.ships[5]
    ship.hits = list(ship.positions)
    server._mark_ship_sunken(p, ship)
    p.remaining_ships = 5
    p.magic_hand = [card('死者苏生')]

    server.apply_magic_effect(room, P1, card('死者苏生'), {})
    server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 2, 'y': 2}})

    assert not any(a.x == 2 and a.y == 2 for a in room.players[P2].attacks)


# ---------------------------------------------------------------------------
# 问题 3：没有船数上限
# ---------------------------------------------------------------------------
def test_reinforce_at_six_ships_allowed(room, events):
    """★ 有 6 艘船时增援不该被拒（作者：不存在船数上限）。"""
    room.players[P1].remaining_ships = 6
    room.players[P1].magic_hand = [card('增援')]

    res = server.apply_magic_effect(room, P1, card('增援'), {})
    assert res.success is True, f'不该有船数上限，实际：{res.message}'
    assert room.magic_temp_data.get('pending_placement', {}).get('kind') == 'reinforce'


def test_reinforce_can_exceed_six(room):
    """真的能摆到 7 艘。"""
    room.players[P2].remaining_ships = 3
    room.players[P1].remaining_ships = 6
    room.players[P1].magic_hand = [card('增援')]
    server.apply_magic_effect(room, P1, card('增援'), {})

    out = server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 3, 'y': 3}})
    assert out.get('status') == 'success', out
    assert room.players[P1].remaining_ships == 7
    alive = len([s for s in room.players[P1].ships
                 if server._is_ship_alive(room.players[P1], s)])
    assert alive == 7, f'棋盘实际存活数也应是 7，实际 {alive}'


def test_no_cap_message_anywhere(room):
    """三张卡都不该再出现"战舰数量已达上限"。"""
    cases = [
        ('增援', 6, {}),
        ('死者苏生', 6, {}),
        ('疗愈', 6, {}),
    ]
    for name, ships, _ in cases:
        room.players[P1].remaining_ships = ships
        room.players[P1].magic_hand = [card(name)]
        res = server.apply_magic_effect(room, P1, card(name), {})
        assert '上限' not in (res.message or ''), (
            f'{name} 仍报船数上限：{res.message}')
        room.magic_temp_data.pop('pending_placement', None)


def test_full_board_reinforce_enters_flow(room, events):
    """★ 端到端：走真实出牌入口，6 艘船时增援必须进入放置流程（牌不被吞）。"""
    room.magic_deck = [card('冻结')]
    room.players[P1].magic_hand = [card('增援')]

    res = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '增援'}, 'targets': {},
    })
    assert res.get('status') == 'success', res
    assert room.magic_temp_data.get('pending_placement', {}).get('kind') == 'reinforce', (
        '应进入放置流程；若被拒，牌已在出牌时消耗，玩家会被白吞一张卡')


def test_invalid_placement_keeps_pending(room):
    """位置非法被拒时，流程不该被清空（牌还能继续用）。"""
    room.players[P1].remaining_ships = 5
    room.players[P1].ships = room.players[P1].ships[:5]
    room.players[P2].attacks.append(Position(x=1, y=1))
    room.players[P1].magic_hand = [card('增援')]
    server.apply_magic_effect(room, P1, card('增援'), {})

    out = server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 1, 'y': 1}})
    assert out.get('status') == 'error'
    assert room.magic_temp_data.get('pending_placement'), '失败后应还能继续选位置'

    # 换个合法格子仍能成功
    ok = server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 4, 'y': 4}})
    assert ok.get('status') == 'success', ok
    assert room.players[P1].remaining_ships == 6
