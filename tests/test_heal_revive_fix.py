# -*- coding: utf-8 -*-
"""疗愈「战舰并没有复活」的回归测试（2026-09-14）。

玩家实测：使用疗愈后，战舰并没有复活。

根因链条（关键在于本项目的两个设计特性叠加）：
  ① 「击沉」只减 remaining_ships，**不会把船移出 player.ships**；
  ② `_is_ship_alive` 的第一道判据是「船在 sunken_ships 里就视为已沉」，
     与 hits 无关。

  于是只要 sunken_ships 里出现**同一艘船的重复条目**，复活就会失效：
    · 复活时 pop() 只取走一条，其余重复条目还在；
    · 即使 hits 清空、remaining_ships 也 +1，_is_ship_alive 仍返回 False；
    · 前端按 alive 字段渲染 → 这艘船继续被画成沉船 → 玩家看到"没复活"。
  更糟的是重复条目还会造成幽灵计数（船数涨了、棋盘上没船）。

  重复条目的来源：8 处登记沉船的代码全部**无条件 append**，同一艘船在
  「沉 → 复活 → 再沉」的循环里会被反复登记。

修法：
  · 新增 _mark_ship_sunken(player, ship) 带去重，8 处登记点统一改走它；
  · 复活的两个入口（_revive_sunken_ships / 死者苏生的放置流程）在复活时
    把该船在沉船堆里的【所有】重复记录一起清掉，并跳过"其实还活着"的幽灵条目。
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


def alive_count(room, pid=P1):
    p = room.players[pid]
    return len([s for s in p.ships if server._is_ship_alive(p, s)])


# ---------------------------------------------------------------------------
# 核心：带重复条目时，疗愈必须真的把船复活（数字与棋盘一致）
# ---------------------------------------------------------------------------
def test_heal_works_with_duplicate_sunken_entries(room):
    """★ 玩家场景：沉船堆里有重复条目时，疗愈必须真的复活（alive 变 True）。"""
    p = room.players[P1]
    ship = p.ships[0]
    ship.hits = list(ship.positions)          # 打满命中 = 已沉
    p.sunken_ships.extend([ship, ship])       # 重复登记
    p.remaining_ships = 5
    room.magic_deck = [card('冻结')]

    assert server._is_ship_alive(p, ship) is False, '前置：该船应被判为已沉'

    res = server.apply_magic_effect(room, P1, card('疗愈'), {})
    assert res.success is True
    assert res.message  # '疗愈生效，1 艘战舰在原地复活'

    assert server._is_ship_alive(p, ship) is True, (
        '复活后该船必须被视为存活，否则前端继续画成沉船 = 玩家看到"没复活"')
    assert p.remaining_ships == 6
    assert alive_count(room) == 6, '棋盘实际存活数必须与 remaining_ships 一致'
    assert ship not in p.sunken_ships, '该船的所有沉船记录都应被清掉'


def test_heal_count_matches_board(room):
    """remaining_ships 必须等于棋盘实际存活数（防幽灵计数）。"""
    p = room.players[P1]
    for i in (5, 4):
        sh = p.ships[i]
        sh.hits = list(sh.positions)
        p.sunken_ships.extend([sh, sh])       # 都重复登记
    p.remaining_ships = 4
    room.magic_deck = [card('冻结')] * 4

    server.apply_magic_effect(room, P1, card('疗愈'), {})

    assert p.remaining_ships == alive_count(room), (
        f'数字与棋盘不一致：remaining={p.remaining_ships} alive={alive_count(room)}')
    assert p.remaining_ships == 6


def test_heal_sets_alive_flag_for_frontend(room, events):
    """_emit_player_ships 的 payload 里该船 alive 必须是 True。"""
    p = room.players[P1]
    ship = p.ships[0]
    ship.hits = list(ship.positions)
    p.sunken_ships.extend([ship, ship])
    p.remaining_ships = 5
    room.magic_deck = [card('冻结')]

    server.apply_magic_effect(room, P1, card('疗愈'), {})

    payloads = [d for e, d, to, r in events if e == 'player_ships_updated']
    assert payloads, '疗愈后必须推送己方棋盘'
    ships = payloads[-1]['ships']
    assert ships[0]['alive'] is True, (
        f'前端拿到的 alive 必须是 True，实际 {ships[0]}')


# ---------------------------------------------------------------------------
# 登记侧去重
# ---------------------------------------------------------------------------
def test_mark_ship_sunken_dedupes(room):
    """_mark_ship_sunken 对同一艘船只登记一次。"""
    p = room.players[P1]
    ship = p.ships[0]
    assert server._mark_ship_sunken(p, ship) is True
    assert server._mark_ship_sunken(p, ship) is False, '第二次不该重复登记'
    assert p.sunken_ships.count(ship) == 1


def test_sunk_effects_does_not_duplicate(room):
    """走真实击沉路径两次，沉船堆里也只有一条记录。"""
    ship = room.players[P1].ships[0]
    server._apply_ship_sunk_effects(room, room.id, P2, P1, ship, 0, 0)
    server._apply_ship_sunk_effects(room, room.id, P2, P1, ship, 0, 0)
    assert room.players[P1].sunken_ships.count(ship) == 1, '不该出现重复条目'


def test_no_duplicate_after_sink_revive_sink(room):
    """完整循环：沉 → 复活 → 再沉，沉船堆始终只有一条。"""
    p = room.players[P1]
    ship = p.ships[0]
    room.magic_deck = [card('冻结')]

    server._apply_ship_sunk_effects(room, room.id, P2, P1, ship, 0, 0)
    assert p.sunken_ships.count(ship) == 1

    server.apply_magic_effect(room, P1, card('疗愈'), {})
    assert server._is_ship_alive(p, ship) is True

    server._apply_ship_sunk_effects(room, room.id, P2, P1, ship, 0, 0)
    assert p.sunken_ships.count(ship) == 1, '再沉也不该重复'
    assert server._is_ship_alive(p, ship) is False


# ---------------------------------------------------------------------------
# 死者苏生路径同样要有防护
# ---------------------------------------------------------------------------
def test_susheng_clears_all_duplicates(room):
    """死者苏生（放置流程）也要清掉所有重复记录。"""
    p = room.players[P1]
    ship = p.ships[5]
    ship.hits = list(ship.positions)
    p.sunken_ships.extend([ship, ship])
    p.remaining_ships = 5
    p.magic_hand = [card('死者苏生')]

    server.apply_magic_effect(room, P1, card('死者苏生'), {})
    res = server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 3, 'y': 3}})
    assert res.get('status') == 'success', res

    assert server._is_ship_alive(p, ship) is True, '复活后必须被视为存活'
    assert ship not in p.sunken_ships
    assert p.remaining_ships == alive_count(room)


def test_ghost_entry_does_not_inflate_count(room):
    """沉船堆里"其实还活着"的幽灵条目：不该让它虚增船数。"""
    p = room.players[P1]
    healthy = p.ships[0]                       # 完好无损的船
    p.sunken_ships.append(healthy)             # 被人为塞进沉船堆（幽灵条目）
    room.magic_deck = [card('冻结')]
    before = p.remaining_ships

    server._revive_sunken_ships(room, p, 1)

    assert p.remaining_ships == before, (
        f'不该为幽灵条目加船数，{before} -> {p.remaining_ships}')
    assert server._is_ship_alive(p, healthy) is True
    assert healthy not in p.sunken_ships, '幽灵条目应被清掉'


# ---------------------------------------------------------------------------
# 反证：正常情况不受影响
# ---------------------------------------------------------------------------
def test_normal_heal_still_works(room):
    """反证：没有重复条目时，疗愈照常复活至多 2 艘。"""
    p = room.players[P1]
    for i in (5, 4):
        sh = p.ships[i]
        sh.hits = list(sh.positions)
        server._mark_ship_sunken(p, sh)
    p.remaining_ships = 4
    room.magic_deck = [card('冻结')] * 4

    res = server.apply_magic_effect(room, P1, card('疗愈'), {})
    assert res.success is True
    assert p.remaining_ships == 6
    assert alive_count(room) == 6
    assert p.sunken_ships == []


def test_heal_rejects_when_full(room):
    """反证：船满时仍拒绝疗愈。"""
    p = room.players[P1]
    res = server.apply_magic_effect(room, P1, card('疗愈'), {})
    assert res.success is False
    assert '上限' in res.message


def test_heal_rejects_without_sunken(room):
    """反证：没有沉船时仍拒绝疗愈。"""
    p = room.players[P1]
    p.remaining_ships = 5
    res = server.apply_magic_effect(room, P1, card('疗愈'), {})
    assert res.success is False
    assert '没有可复活' in res.message
