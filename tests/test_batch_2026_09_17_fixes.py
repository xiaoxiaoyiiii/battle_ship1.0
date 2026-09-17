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
def test_frozen_ship_count_ignores_sunken_ships(room):
    p2 = board(room, P2, [(0, 0), (0, 1), (1, 0), (3, 3), (4, 4), (5, 5)])
    for s in p2.ships[:3]:
        s.frozen = room.round + 1

    assert server.frozen_ship_count(p2) == 3
    kill(room, P2, p2.ships[0])
    assert server.frozen_ship_count(p2) == 2, '已沉的船不得再计入冻结数'


def test_frozen_attacks_not_double_subtracted(room):
    """★ 玩家实测：冻结后被冻结方的攻击次数被多减了一次。"""
    p2 = board(room, P2, [(0, 0), (0, 1), (1, 0), (3, 3), (4, 4), (5, 5)])
    for s in p2.ships[:3]:
        s.frozen = room.round + 1

    room.current_attacker = P2
    server._recalc_attacker_attacks(room)
    assert room.attacks_remaining == 3, f'6 艘存活 - 3 艘冻结 = 3，实际 {room.attacks_remaining}'

    # 冻住的三艘里有一艘被打沉
    kill(room, P2, p2.ships[0])
    server._recalc_attacker_attacks(room)
    assert room.attacks_remaining == 3, (
        '5 艘存活 - 2 艘冻结 = 3；死船被重复扣了一次，'
        f'实际 {room.attacks_remaining}')


def test_freeze_message_excludes_sunken_ships(room, events):
    """★ 玩家实测：冻结播报的数字把已经死亡的战舰算了进去。"""
    p2 = board(room, P2, [(0, 0), (0, 1), (1, 0), (3, 3), (4, 4), (5, 5)])
    dead = p2.ships[1]
    kill(room, P2, dead)

    res = server.apply_magic_effect(room, P1, card('冻结'),
                                    {'target_area': {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}})

    assert res.success is True, res.message
    assert '冻结了2艘战舰' in res.message, res.message
    assert not getattr(dead, 'frozen', None), '死船不该被打上冻结标记'
    assert server.frozen_ship_count(p2) == 2


def test_revive_does_not_inherit_frozen(room):
    """复活不该把上一轮的冻结标记带回棋盘（否则凭空少一次攻击）。"""
    p1 = board(room, P1, [(0, 0), (1, 1), (2, 2)])
    dead = p1.ships[0]
    dead.frozen = room.round + 1
    kill(room, P1, dead)

    server._revive_sunken_ships(room, p1, 1)

    assert server.frozen_ship_count(p1) == 0, '复活后的船不应仍处于冻结状态'


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


def test_baizhe_zero_survives_enter_battle_phase(room):
    """★ 玩家实测：准备阶段确实归 0，一进战斗阶段又被按船数算回 6。"""
    _baizhe_with_replacement(room)
    room.current_attacker = P1
    room.current_phase = 'preparation'
    room.attacks_remaining = 0

    res = server.enter_battle_phase({'room_id': room.id, 'player_id': P1})

    assert res.get('status') == 'success', res
    assert room.current_phase == 'battle'
    assert room.attacks_remaining == 0, (
        f'败者食尘生效的大回合内不得按船数重算，实际 {room.attacks_remaining}')


def test_baizhe_zero_applies_to_both_players(room):
    """卡面：「生效的大回合内【双方】的攻击次数都为 0」。"""
    server.apply_magic_effect(room, P1, card('败者食尘'), {})
    board(room, P2, [(i, 5) for i in range(6)])

    room.current_attacker = P2
    server._recalc_attacker_attacks(room)
    assert room.attacks_remaining == 0, '对手在同一大回合内也应是 0'


def test_baizhe_zero_expires_next_big_round(room):
    """反证：下一个大回合恢复正常的按船数计算。"""
    server.apply_magic_effect(room, P1, card('败者食尘'), {})
    board(room, P1, [(i, 0) for i in range(6)])

    room.round += 1
    room.current_attacker = P1
    server._recalc_attacker_attacks(room)
    assert room.attacks_remaining == 6, f'新大回合应恢复正常，实际 {room.attacks_remaining}'


def test_baizhe_zero_not_refilled_by_wuxian(room):
    """五险一金不得把被规则压成 0 的次数回填成 3。"""
    _baizhe_with_replacement(room)
    room.players[P1].effect_flags.wuxian = True
    room.current_attacker = P1
    room.current_phase = 'preparation'
    room.attacks_remaining = 0

    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})

    assert room.attacks_remaining == 0, (
        f'五险一金不该盖掉败者食尘的 0，实际 {room.attacks_remaining}')


def test_baizhe_zero_not_refilled_by_ship_change(room):
    """船数变化（增援/复活）也不许把 0 加回来。"""
    server.apply_magic_effect(room, P1, card('败者食尘'), {})
    board(room, P1, [(i, 0) for i in range(6)])
    room.current_attacker = P1

    server._sync_attacks_after_ship_change(room, P1, 1)
    assert room.attacks_remaining == 0


# ---------------------------------------------------------------------------
# 3. 越战越勇：发动即 +1
# ---------------------------------------------------------------------------
def test_battle_spirit_grants_attack_immediately(room, events):
    """★ 玩家实测：发动后攻击次数没有任何变化，要等下一发击沉才生效。"""
    board(room, P1, [(0, 0), (1, 0)])
    room.attacks_remaining = 2
    board(room, P2, [(5, 5)])
    room.players[P1].magic_hand = [card('越战越勇')]
    room.last_attack = {'attacker': P1, 'x': 3, 'y': 3, 'hit': True,
                        'ship_sunk': True, 'round': room.round}

    res = use(room, P1, '越战越勇')
    assert res.get('status') == 'success', res
    server.resolve_chain(room)

    assert room.players[P1].effect_flags.battle_spirit is True
    assert room.attacks_remaining == 3, (
        f'发动当场就应 +1（2 → 3），实际 {room.attacks_remaining}')
    ups = [d for e, d, to, r in events if e == 'attacks_updated']
    assert any(d.get('attacks_remaining') == 3 for d in ups), '应广播新的攻击次数'


def test_battle_spirit_still_stacks_on_later_kills(room):
    """本大回合内再击沉一艘，仍然 +1（原有行为不能被改坏）。"""
    board(room, P1, [(0, 0), (1, 0)])
    board(room, P2, [(5, 5)])
    room.attacks_remaining = 2
    room.players[P1].magic_hand = [card('越战越勇')]
    room.last_attack = {'attacker': P1, 'x': 3, 'y': 3, 'hit': True,
                        'ship_sunk': True, 'round': room.round}
    use(room, P1, '越战越勇')
    server.resolve_chain(room)
    assert room.attacks_remaining == 3

    # 3 次里花掉 1 次并击沉一艘：3 - 1 + 1 = 3
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 5, 'y': 5})
    assert room.attacks_remaining == 3, (
        f'击沉后应再 +1，实际 {room.attacks_remaining}')


def test_battle_spirit_requires_fresh_kill(room):
    """卡面「仅可在击沉对方的一艘战舰后立即使用才会有效」——没有击沉就不该消耗。"""
    room.players[P1].magic_hand = [card('越战越勇')]
    room.last_attack = {'attacker': P1, 'x': 0, 'y': 0, 'hit': True,
                        'ship_sunk': False, 'round': room.round}

    res = use(room, P1, '越战越勇')

    assert res.get('status') == 'error', res
    assert '越战越勇' in res['message']
    assert [c.name for c in room.players[P1].magic_hand] == ['越战越勇']
    assert not any(c.name == '越战越勇' for c in room.magic_discard)
    assert room.players[P1].effect_flags.battle_spirit is False


# ---------------------------------------------------------------------------
# 4. 条件不满足 → 不吞牌 + 明确播报
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('name', ['死者苏生', '疗愈', '绝处逢生', '神之宣告',
                                  '平等条约', '失灵！', '加百列之光',
                                  '余音绕梁', '桃园结义'])
def test_conditional_failure_returns_card_to_hand(room, events, name):
    """★ 玩家实测：不满足条件的牌被打出后直接消失。"""
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


def test_old_sunken_cell_is_blocked_for_revive(room):
    """★ 玩家实测：复活面板把"刚沉掉的那一格"也列成可点。"""
    p1 = board(room, P1, [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 5)])
    _ship_removed_by_magic(room, P1, (5, 5))

    blocked = {(b['x'], b['y']) for b in server._placement_blocked_cells(room, P1)}
    assert (5, 5) in blocked, '已沉船的原格不得出现在可放置列表里'
    assert server._placement_error(room, P1, 5, 5) is not None
    # 反证：空格照旧可放
    assert server._placement_error(room, P1, 5, 0) is None


def test_revive_confirm_rejects_old_sunken_cell(room):
    """端到端：走真实出牌 + 放置确认，原格必须被拒。"""
    p1 = board(room, P1, [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 5)])
    _ship_removed_by_magic(room, P1, (5, 5))
    p1.magic_hand = [card('死者苏生')]

    use(room, P1, '死者苏生')
    server.resolve_chain(room)

    out = server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 5, 'y': 5}})
    assert out.get('status') == 'error', out

    # 空格可以放
    ok = server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 5, 'y': 0}})
    assert ok.get('status') == 'success', ok


def test_attack_record_of_old_sunken_cell_is_kept(room):
    """放在别处时，对方打在原沉船格上的历史不得被顺手清掉。"""
    p1 = board(room, P1, [(0, 0), (1, 0), (5, 5)])
    room.players[P2].attacks = [Position(x=5, y=5, hit=True, ship_sunk=True)]
    _ship_removed_by_magic(room, P1, (5, 5))
    p1.magic_hand = [card('死者苏生')]

    use(room, P1, '死者苏生')
    server.resolve_chain(room)
    server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 3, 'y': 3}})

    assert any(a.x == 5 and a.y == 5 for a in room.players[P2].attacks), \
        '原沉船格的攻击历史不该消失（否则那一格对对方"变回未知"）'


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


def test_last_stand_still_confirmable_after_blocked_fix(room):
    """端到端：修好 blocked 之后，原格仍能被服务端接受并放下那一艘船。"""
    p1 = board(room, P1, [(0, 0), (1, 0), (2, 0)])
    p1.magic_hand = [card('绝处逢生')]

    use(room, P1, '绝处逢生')
    server.resolve_chain(room)
    assert p1.remaining_ships == 0, '绝处逢生应牺牲全部战舰'

    out = server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 1, 'y': 0}})
    assert out.get('status') == 'success', out
    assert p1.remaining_ships == 1


def test_cell_xy_accepts_both_shapes():
    """候选格的两种形态（[x,y] 与 {'x':..}）都要能解包。"""
    assert server._cell_xy([2, 3]) == (2, 3)
    assert server._cell_xy((2, 3)) == (2, 3)
    assert server._cell_xy({'x': 2, 'y': 3}) == (2, 3)
    assert server._cell_xy('nope') is None
    assert server._cell_xy(None) is None


def test_revive_still_blocks_sunken_cells(room, events):
    """反证：死者苏生/增援那条口径不能被这次修复改回去（原格仍必须灰掉）。"""
    p1 = board(room, P1, [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 5)])
    _ship_removed_by_magic(room, P1, (5, 5))
    p1.magic_hand = [card('死者苏生')]

    use(room, P1, '死者苏生')
    server.resolve_chain(room)

    payload = _placement_payload(events, 'sid-p1')
    blocked = {(b['x'], b['y']) for b in payload.get('blocked') or []}
    assert (5, 5) in blocked, '死者苏生仍不许摆到刚沉掉的那一格'
    assert 'allowed' not in payload, 'allowed 是绝处逢生的白名单语义，别乱下发'


def test_shenji_redeploy_still_allows_original_cell(room, events):
    """反证：神机妙算的"重新部署"仍可放回原位置（ignore_sunken 语义不变）。"""
    p1 = board(room, P1, [(0, 0), (1, 0), (2, 0)])
    room.players[P2].attacks = [Position(x=0, y=0, hit=True, ship_sunk=True)]
    victim = p1.ships[0]
    kill(room, P1, victim)

    # 服务端校验：原位置（已被对方打过）在 allow_cells 豁免下必须放行
    assert server._placement_error(room, P1, 0, 0, allow_cells={(0, 0)},
                                   ignore_sunken=True) is None

    # 下发给前端的 blocked 也要把原位置剔除（与 _emit_placement_request 同口径）
    room.game_effects['shenji_redeploy_cells'] = [[0, 0]]
    room.magic_temp_data['pending_placement'] = {
        'caster': P1, 'kind': 'shenji_redeploy',
        'remaining': 1, 'total': 1, 'placed': 0,
    }
    server._emit_placement_request(room, P1)
    payload = [d for e, d, to, r in events if e == 'placement_request'][-1]
    blocked = {(b['x'], b['y']) for b in payload['blocked']}
    assert (0, 0) not in blocked, f'神机妙算的原位置必须仍可点，实际 blocked={blocked}'
    assert 'allowed' not in payload, 'allowed 是白名单语义，神机妙算不能下发'


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


def test_last_radiance_keeps_other_board_marks(room):
    """反证：对方棋盘上的显形/攻击记录与本卡无关，不该被清。"""
    board(room, P1, [(0, 0)])
    board(room, P2, [(5, 5)])
    room.players[P2].attacks = [Position(x=0, y=0, hit=True, ship_sunk=False)]
    room.players[P2].revealed_positions = [Position(x=0, y=0)]

    server.apply_magic_effect(room, P1, card('回光返照'), {})

    assert room.players[P2].attacks == []
    assert room.players[P2].revealed_positions == [], \
        '对方视角里我方的棋盘（显形记录）也要清空（卡面要求）'
    assert room.players[P1].attacks == []
