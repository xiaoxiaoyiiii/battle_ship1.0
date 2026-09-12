# -*- coding: utf-8 -*-
"""「选一艘自己的船」类卡牌不能选中已沉没的船。

背景：本项目的「击沉」只减 `player.remaining_ships`，**不会把船从 `player.ships` 里
移走**（沉船留在列表里供复活类效果回收）。所以任何让玩家挑一艘自己的船的地方，
都必须先过滤掉沉船，否则会出现：

  · 克苏鲁之眼：对手拿一艘早就沉了的船来「暴露」，等于什么都没暴露
  · 恶魔契约 / 神之宣告：拿沉船抵账 = **零代价**发动
  · 仁王之盾：把护盾加在一艘沉船上，白白浪费

这些用例覆盖：统一判定 `_is_ship_alive`、候选列表、确认校验、AI 代选、
前端拿到的存活标记，以及四张卡各自的入口。
"""
import pytest

import server
from server import (GameRoom, MagicCard, Player, PlayerShip, Position,
                    room_manager)

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def events(monkeypatch):
    """拦截所有 socket emit，避免需要请求上下文。"""
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    return captured


def ship(*cells):
    return PlayerShip(positions=[Position(x, y) for x, y in cells], hits=[])


def card(name):
    return MagicCard(name)


def kill(player, idx):
    """模拟一次真实击沉：命中填满 + 进沉船堆 + 船数 -1。"""
    sh = player.ships[idx]
    sh.hits = list(sh.positions)
    player.sunken_ships.append(sh)
    player.remaining_ships -= 1
    return sh


@pytest.fixture
def room():
    r = GameRoom('alive-room')
    r.players[P1] = Player(name='p1', ships=[ship((i, 0)) for i in range(6)],
                           attacks=[], remaining_ships=6, sid='sid-p1', user_id='u1')
    r.players[P2] = Player(name='p2', ships=[ship((i, 5)) for i in range(6)],
                           attacks=[], remaining_ships=6, sid='sid-p2', user_id='u2')
    r.state = 'attacking'
    r.current_attacker = P1
    r.current_phase = 'battle'
    r.attack_order = [P1, P2]
    r.attacks_remaining = 6
    r.round = 1
    room_manager.rooms[r.id] = r
    yield r
    room_manager.rooms.pop(r.id, None)


def pick_events(events):
    return [d for (e, d, _t, _r) in events if e == 'sacrifice_request']


# ---------------------------------------------------------------------------
# 统一判定
# ---------------------------------------------------------------------------
def test_is_ship_alive_basics(room):
    p = room.players[P2]
    assert server._is_ship_alive(p, p.ships[0]) is True

    dead = kill(p, 0)
    assert server._is_ship_alive(p, dead) is False, '进了沉船堆就是死的'
    assert len(server._alive_ships(p)) == 5


def test_is_ship_alive_catches_full_hits_without_sunken_entry(room):
    """命中数满了但没进沉船堆（异常路径）也要判死，避免两边不同步时漏判。"""
    p = room.players[P2]
    p.ships[0].hits = list(p.ships[0].positions)   # 不 append 到 sunken_ships
    assert server._is_ship_alive(p, p.ships[0]) is False


def test_is_ship_alive_handles_none(room):
    assert server._is_ship_alive(room.players[P2], None) is False


# ---------------------------------------------------------------------------
# 候选列表 / 确认校验（克苏鲁之眼与恶魔契约共用的那条链路）
# ---------------------------------------------------------------------------
def test_ship_pick_offers_only_alive_ships(room, events):
    """候选列表不能把沉船发出去 —— 否则玩家会以为自己能选它。"""
    p = room.players[P2]
    dead = kill(p, 0)
    events.clear()

    server._request_ship_pick(room, P2, 'kraken_eye', '测试')

    req = pick_events(events)
    assert req, '应发出 sacrifice_request'
    offered = {(q['x'], q['y']) for sh in req[0]['ships'] for q in sh['positions']}
    assert (0, 0) not in offered, '已沉的船不该出现在候选里'
    assert (dead.positions[0].x, dead.positions[0].y) not in offered
    assert len(offered) == 5, f'应只剩 5 艘活船，实际 {offered}'


def test_confirm_sacrifice_rejects_dead_ship(room):
    """拿已沉船的格子去确认必须被拒（这是「零代价」漏洞的入口）。"""
    p = room.players[P2]
    kill(p, 0)
    room.magic_temp_data['pending_sacrifice'] = {'player': P2, 'reason': 'demon_contract'}

    res = server.handle_confirm_sacrifice({
        'room_id': room.id, 'player_id': P2, 'position': {'x': 0, 'y': 0}})
    assert res['status'] == 'error'
    assert '还活着' in res['message']
    assert p.remaining_ships == 5, '不该再扣一次船数'


def test_confirm_sacrifice_still_accepts_alive_ship(room):
    """别误伤 —— 活船照常可以选。"""
    p = room.players[P2]
    kill(p, 0)
    room.magic_temp_data['pending_sacrifice'] = {'player': P2, 'reason': 'demon_contract'}

    res = server.handle_confirm_sacrifice({
        'room_id': room.id, 'player_id': P2, 'position': {'x': 1, 'y': 5}})
    assert res['status'] == 'success'
    assert p.remaining_ships == 4


def test_ship_pick_skips_when_all_ships_dead(room, events):
    """一艘活船都没有时不弹窗、直接跳过（不再把一排沉船列给玩家）。"""
    p = room.players[P2]
    for i in range(len(p.ships)):
        kill(p, i)
    events.clear()

    assert server._request_ship_pick(room, P2, 'kraken_eye', '测试') is None
    assert not pick_events(events), '没有活船时不该发牺牲请求'


def test_ai_ship_pick_only_chooses_alive(room):
    """AI 代选也不能选到沉船。"""
    room.is_ai_room = True
    p = room.players[P2]
    dead = kill(p, 0)
    # 把 AI 的 id 绑到 P2 上
    room.players = {P1: room.players[P1], f'ai-{room.id}': p}
    p.name = 'AI'

    for _ in range(30):
        picked = server._request_ship_pick(room, f'ai-{room.id}', 'demon_contract', 'x')
        assert picked is not dead, 'AI 不该选到已沉的船'
        assert server._is_ship_alive(p, picked)


# ---------------------------------------------------------------------------
# 克苏鲁之眼
# ---------------------------------------------------------------------------
def test_kraken_eye_rejects_caster_picking_dead_ship(room):
    p = room.players[P1]
    kill(p, 0)
    res = server.apply_magic_effect(room, P1, card('克苏鲁之眼'),
                                    {'target_area': {'x1': 0, 'y1': 0, 'x2': 0, 'y2': 0}})
    assert res.success is False
    assert '还活着' in res.message


def test_kraken_eye_caster_picking_alive_ship_works(room):
    p = room.players[P1]
    kill(p, 0)
    res = server.apply_magic_effect(room, P1, card('克苏鲁之眼'),
                                    {'target_area': {'x1': 2, 'y1': 0, 'x2': 2, 'y2': 0}})
    assert res.success is True, res.message
    revealed = [(q.x, q.y) for q in room.players[P2].revealed_positions]
    assert (2, 0) in revealed


# ---------------------------------------------------------------------------
# 神之宣告
# ---------------------------------------------------------------------------
def test_divine_decree_ignores_dead_ship_cells(room):
    """点选的两艘里混了沉船 → 沉船不算数，只从活船里补。"""
    p = room.players[P1]
    dead = kill(p, 0)          # (0,0) 已沉
    kill(p, 1)                 # (1,0) 已沉

    res = server.apply_magic_effect(room, P1, card('神之宣告'), {
        'effect_choice': 2,
        'selected_cells': [{'x': 0, 'y': 0}, {'x': 1, 'y': 0}],
    })
    assert res.success is True, res.message

    sacrificed = set()
    for sh in p.sunken_ships:
        for q in sh.positions:
            sacrificed.add((q.x, q.y))
    # 原本沉的两艘 + 随机补的两艘活船
    assert (0, 0) in sacrificed and (1, 0) in sacrificed
    assert p.remaining_ships == 2, f'6 艘 - 2 沉 - 2 牺牲 = 2，实际 {p.remaining_ships}'
    assert all(server._is_ship_alive(p, sh) is False
               for sh in p.ships if sh in p.sunken_ships)
    assert dead in p.sunken_ships


# ---------------------------------------------------------------------------
# 仁王之盾
# ---------------------------------------------------------------------------
def test_king_shield_skips_dead_ships(room):
    p = room.players[P1]
    kill(p, 0)
    res = server.confirm_magic_target({
        'room_id': room.id, 'player_id': P1, 'temp_data_id': 'shield_choice',
        'target_data': {'ship_indices': [0, 1, 2]}})
    assert res['status'] == 'success'
    assert '2' in res['message']
    assert p.ships[0].shield is False, '沉船不该拿到护盾'
    assert p.ships[1].shield is True and p.ships[2].shield is True


def test_king_shield_rejects_all_dead(room):
    p = room.players[P1]
    kill(p, 0)
    res = server.confirm_magic_target({
        'room_id': room.id, 'player_id': P1, 'temp_data_id': 'shield_choice',
        'target_data': {'ship_indices': [0]}})
    assert res['status'] == 'error'
    assert '已沉没' in res['message']


# ---------------------------------------------------------------------------
# 下发给前端的存活标记
# ---------------------------------------------------------------------------
def test_player_ships_payload_marks_alive(room, events):
    p = room.players[P1]
    kill(p, 0)
    events.clear()
    server._emit_player_ships(room, P1)

    payload = [d for (e, d, _t, _r) in events if e == 'player_ships_updated']
    assert payload, '应发出 player_ships_updated'
    flags = [sh['alive'] for sh in payload[0]['ships']]
    assert flags.count(False) == 1, f'应恰好 1 艘标记为已沉，实际 {flags}'
    assert flags[0] is False


def test_kill_pushes_player_ships_with_alive_flag(room, events):
    """击沉后必须把己方棋盘重推一次。

    否之前端手里那份还是「摆船时自己拼的」，既没有 alive 标记、也不知道船已经沉了，
    「选一艘自己的船」类的卡就会把沉船也画成可点（克苏鲁之眼就是这么漏的）。
    """
    p = room.players[P2]
    p.ships = [ship((0, 5))]
    p.remaining_ships = 1
    room.attack_order = [P1, P2]
    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attacks_remaining = 6
    events.clear()

    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 5})

    payload = [d for (e, d, t, _r) in events
               if e == 'player_ships_updated' and t == 'sid-p2']
    assert payload, '击沉后应把己方棋盘推给被击沉的一方'
    assert payload[-1]['ships'][0]['alive'] is False, '推下去的存活标记要如实'


def test_room_sync_marks_alive_and_filters_pick_candidates(room):
    p = room.players[P1]
    kill(p, 0)
    room.magic_temp_data['pending_sacrifice'] = {'player': P1, 'reason': 'demon_contract'}

    sync = server._build_room_sync(room, P1)
    assert [sh['alive'] for sh in sync['ships']].count(False) == 1

    offered = {(q['x'], q['y']) for sh in sync['pending_sacrifice_ships'] for q in sh['positions']}
    assert (0, 0) not in offered, '重连快照里的候选也不能含沉船'
    assert len(offered) == 5
