# -*- coding: utf-8 -*-
"""2026-09-17 缺陷批的回归测试（作者逐条实测反馈）。

【1 · 冻结（#2 #7）】
  「冻结通过之后被冻结方的攻击次数计算出现问题」
  「冻结的战舰数目居然会把已经死亡的战舰加进去」
  同一个根因：`frozen_ship_count` / 冻结分支都按 `player.ships` **全量**统计，
  而本项目的击沉【不把船移出 ships】。攻击次数 = remaining_ships - 冻结数，
  沉掉的那艘被重复扣了一次；播报的数字也把死船算了进去。

【2 · 败者食尘（#3）】
  「准备阶段的攻击次数确实归 0，但进入战斗阶段之后又根据船数更新成了 6 次」
  卡面：「败者食尘生效的大回合内双方的攻击次数都为 0」——
  0 必须在整个大回合内压得住任何"按船数重算"。

【3 · 越战越勇（#4）】
  「成功使用之后应该立即给使用方增加一次攻击次数，而不是之后的攻击才开始生效」
  另外卡面写明「仅可在击沉对方的一艘战舰后立即使用才会有效」，
  条件不满足时要在**扣牌之前**拦掉（与饮血同口径）。

【4 · 条件不满足却吞牌（#5）】
  「一部分卡牌因为不满足使用条件而被打出时，效果没生效却把牌吞掉了，
    应该给使用方弹出广播说明，并且不消耗这张牌」
  根因：`handle_use_magic_card` 先扣牌进弃牌堆再压连锁，而条件是在
  `apply_magic_effect` 里才判的 —— 失败分支直接 return，从不退还。

【5 · 死者苏生的放置格（#6）】
  「原本沉船的那个格子恢复成未知格子，且那个位置在复活选船界面也是可选的」
  轰炸 / 硫磺火焰 / 牺牲会把船移出 `player.ships`（只留在 sunken_ships），
  而占位检查只扫 `ships` → 这些格子被当成空格。

【6 · 回光返照（#8）】
  「没有正确清空使用者的棋盘，被打过/沉船的格子仍然显示在上面」
  清错了数组：`caster.attacks` 是"我打在对方棋盘上的记录"，
  要清的是 `opponent.attacks`（对方打在我方棋盘上的记录）。
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
    room.players[P1] = Player(name='p1', ships=[], attacks=[], remaining_ships=6, sid='sid-p1')
    room.players[P2] = Player(name='p2', ships=[], attacks=[], remaining_ships=6, sid='sid-p2')
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


def board(room, pid, cells, remaining=None):
    """给某玩家摆上若干单格船。"""
    p = room.players[pid]
    p.ships = [ship(c) for c in cells]
    p.remaining_ships = len(cells) if remaining is None else remaining
    return p


def kill(room, pid, ship_obj):
    """把一艘船打沉（含本项目"船仍留在 ships 里"的真实口径）。"""
    p = room.players[pid]
    ship_obj.hits = list(ship_obj.positions)
    server._mark_ship_sunken(p, ship_obj)
    p.remaining_ships -= 1


def use(room, caster, name, targets=None):
    """走真实的出牌入口（不是直接调 apply_magic_effect）。"""
    return server.handle_use_magic_card({
        'room_id': room.id, 'player_id': caster,
        'card': {'name': name}, 'targets': targets or {},
    })


def messages_to(events, sid):
    return [d.get('text', '') for e, d, to, r in events
            if e == 'message' and to == sid]


# ---------------------------------------------------------------------------
# 1. 冻结：只算活船
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# 2. 败者食尘：本大回合双方的攻击次数恒为 0
# ---------------------------------------------------------------------------
def _place_six(room, pid, row):
    cells = [(i, row) for i in range(6)]
    return server.handle_place_ships({
        'room_id': room.id, 'player_id': pid,
        'ships': [{'positions': [{'x': x, 'y': y}], 'hits': []} for x, y in cells],
    })


def _baizhe_with_replacement(room):
    """打出败者食尘并让双方重新摆放（模拟真实流程）。"""
    for pid, row in ((P1, 0), (P2, 5)):
        board(room, pid, [(i, row) for i in range(6)])
    server.apply_magic_effect(room, P1, card('败者食尘'), {})
    for pid, row in ((P1, 0), (P2, 5)):
        assert _place_six(room, pid, row).get('status') == 'success'
    assert room.state == 'attacking'












# ---------------------------------------------------------------------------
# 3. 越战越勇：发动即 +1
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# 4. 条件不满足 → 不吞牌 + 明确播报
# ---------------------------------------------------------------------------
def test_conditional_failure_returns_card_to_hand(room, events):
    """★ 玩家实测：不满足条件的牌被打出后直接消失。"""
    for name in ['死者苏生', '疗愈', '绝处逢生', '神之宣告', '平等条约', '失灵！', '加百列之光', '余音绕梁', '桃园结义']:
        p1 = board(room, P1, [(0, 0), (1, 0), (2, 0)])
        if name in ('绝处逢生', '神之宣告'):
            p1.remaining_ships = 1          # 触发"需要至少 N 艘战舰"
        p1.magic_hand = [card(name)]
        if name == '桃园结义':
            p1.effect_flags.no_draw = True  # 无中生有生效中
        room.magic_deck = [card('冻结')]

        res = use(room, P1, name)
        assert res.get('status') == 'success', f'{name} 应能进入连锁（失败发生在结算时）：{res}'
        server.resolve_chain(room)

        hand = [c.name for c in p1.magic_hand]
        assert name in hand, f'{name} 条件不满足时必须退回手牌，实际手牌：{hand}'
        assert not any(c.name == name for c in room.magic_discard), f'{name} 不该留在弃牌堆'
        msgs = messages_to(events, 'sid-p1')
        assert any('退回手牌' in t for t in msgs), f'{name} 应有"退回手牌"提示，实际：{msgs}'


def test_successful_card_is_still_consumed(room):
    """反证：正常发动的牌照旧被消耗（别把退路做成"永不消耗"）。"""
    board(room, P2, [(0, 0), (1, 1)])
    room.players[P1].magic_hand = [card('冻结')]

    res = use(room, P1, '冻结', {'target_area': {'x1': 0, 'y1': 0, 'x2': 1, 'y2': 1}})
    assert res.get('status') == 'success', res
    server.resolve_chain(room)

    assert not any(c.name == '冻结' for c in room.players[P1].magic_hand)
    assert any(c.name == '冻结' for c in room.magic_discard)


def test_negated_card_is_not_refunded(room):
    """反证：被【康】掉的牌是被正常消耗的，绝不能退还。"""
    board(room, P2, [(0, 0), (1, 1)])
    room.players[P1].magic_hand = [card('冻结')]
    room.players[P2].magic_hand = [card('失灵！')]

    use(room, P1, '冻结', {'target_area': {'x1': 0, 'y1': 0, 'x2': 1, 'y2': 1}})
    resp = server.chain_response({'room_id': room.id, 'player_id': P2,
                                 'chain': True, 'card': {'name': '失灵！'}, 'targets': []})
    assert resp.get('status') == 'success', resp

    assert not any(c.name == '冻结' for c in room.players[P1].magic_hand), \
        '被无效化的牌不该退回手牌'
    assert any(c.name == '冻结' for c in room.magic_discard)


# ---------------------------------------------------------------------------
# 5. 死者苏生：已沉船的原格不可放置
# ---------------------------------------------------------------------------
def _ship_removed_by_magic(room, pid, cell):
    """模拟 轰炸/硫磺火焰 的击沉：船被移出 ships，只留在 sunken_ships 里。"""
    p = room.players[pid]
    victim = next(s for s in p.ships if (s.positions[0].x, s.positions[0].y) == cell)
    p.ships.remove(victim)
    victim.hits = list(victim.positions)
    server._mark_ship_sunken(p, victim)
    p.remaining_ships -= 1
    return victim








# ---------------------------------------------------------------------------
# 5b. 绝处逢生：白名单与黑名单不许互相矛盾（2026-09-17 实测回归）
# ---------------------------------------------------------------------------
def _placement_payload(events, sid):
    got = [d for e, d, to, r in events if e == 'placement_request' and to == sid]
    assert got, '应下发 placement_request'
    return got[-1]


def test_last_stand_placement_always_has_clickable_cells(room, events):
    """★ 作者实测回归：绝处逢生生效后「没有可用位置供玩家选择了」。

    病灶：绝处逢生把【全部】战舰牺牲掉（`ships.remove()` + 记进 `sunken_ships`），
    而 `_placement_blocked_cells` 在 2026-09-17 之后按「ships ∪ sunken_ships」
    算己方占位（那是给死者苏生/增援加的"刚沉掉那格不能摆"口径）→ 6 个候选格
    全被判成"已占用"。前端是 `blocked.has(key)` 优先于白名单，于是全灰、点不动。

    这里守的不变量：**allowed 与 blocked 绝不能有交集**（否则白名单形同虚设）。
    """
    p1 = board(room, P1, [(0, 0), (1, 0), (2, 0), (3, 0)])
    p1.magic_hand = [card('绝处逢生')]

    use(room, P1, '绝处逢生')
    server.resolve_chain(room)

    payload = _placement_payload(events, 'sid-p1')
    allowed = {(a[0] if isinstance(a, (list, tuple)) else a['x'],
                a[1] if isinstance(a, (list, tuple)) else a['y'])
               for a in (payload.get('allowed') or [])}
    blocked = {(b['x'], b['y']) for b in payload.get('blocked') or []}

    assert payload['kind'] == 'last_stand'
    assert len(allowed) == 4, f'四个原格都该是候选：{allowed}'
    assert not (allowed & blocked), (
        '候选格不得同时出现在 blocked 里（否则前端 blocked 优先 → 一个都点不了）：'
        f'交集={allowed & blocked}')
    clickable = allowed - blocked
    assert len(clickable) == 4, f'必须有格子可点，实际 {clickable}'










# ---------------------------------------------------------------------------
# 6. 回光返照：清的是"对方打在我方棋盘上的记录"
# ---------------------------------------------------------------------------
def test_last_radiance_clears_opponent_attacks_on_my_board(room, events):
    """★ 玩家实测：被打过/沉船的格子仍显示在回光返照使用者的棋盘上。"""
    board(room, P1, [(i, 0) for i in range(6)])
    board(room, P2, [(i, 5) for i in range(6)])
    room.players[P2].attacks = [
        Position(x=0, y=0, hit=True, ship_sunk=True),
        Position(x=1, y=0, hit=False, ship_sunk=False),
    ]
    room.players[P1].attacks = [Position(x=0, y=5, hit=True, ship_sunk=False)]
    room.player_id = P1

    res = server.apply_magic_effect(room, P1, card('回光返照'), {})

    assert res.success is True, res.message
    assert room.players[P2].attacks == [], '对方打在我方棋盘上的记录必须清空'
    assert len(room.players[P1].attacks) == 1, (
        '我打在对方棋盘上的记录不能被清 —— 清掉会让已探明的格子又能重打')
    assert room.players[P1].ships == []
    assert room.players[P1].remaining_ships == 0
