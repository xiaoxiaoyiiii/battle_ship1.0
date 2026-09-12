# -*- coding: utf-8 -*-
"""绝处逢生 / 盗亦有道 缺陷修复的回归测试（2026-09-14）。

两个 bug 都是玩家实测发现的：

【Bug 1 · 绝处逢生】
  A. 攻击次数没重算：走的是 `_sync_attacks_after_ship_change` 的【增量】逻辑
     （+1 次），于是发动前那 5 次额度被完整保留 —— 场上只剩 1 艘船却有 6 次攻击。
     卡面语义下应该变成「1 + 保留的额外加成」。
  B. 牺牲的船被凭空移除：只 `caster.ships = []` + 塞进沉船堆，没走击沉流程，
     双方棋盘上这些船直接消失，也不触发任何击沉副作用，玩家不认可。

【Bug 2 · 盗亦有道】
  `magic_history` 只在【结算成功后】写入，而连锁是 LIFO（后发先至）结算——
  盗亦有道先出栈时，它要偷的那张对手的牌还没轮到结算、自然还没进历史，
  于是恒报「对方没有使用过魔法卡」。
  这与失灵！当初「康不到目标」是同一个病灶，修法一致：读【连锁栈】。
"""
import pytest

import server
from server import ChainItem, GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def events(monkeypatch):
    """拦截所有 socket emit，避免需要请求上下文。"""
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    # 别让真实后台定时器跑起来
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


def apply(room, caster, name, target=None):
    return server.apply_magic_effect(room, caster, card(name), target or {})


def place_last_stand(room, caster, x, y):
    """发动绝处逢生并完成唯一一艘船的放置。"""
    res = apply(room, caster, '绝处逢生')
    assert res.success is True, res.message
    return server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': caster, 'position': {'x': x, 'y': y}})


# ---------------------------------------------------------------------------
# Bug 1-A：绝处逢生后攻击次数必须重算
# ---------------------------------------------------------------------------
def test_last_stand_resets_attacks_to_one(room):
    """发动前有 5 次攻击 → 放完唯一一艘船后必须变成 1 次，而不是保留旧的 5(+1) 次。

    这是玩家实测的那条：'攻击次数应该是变成1才对，但是发现还是原本的攻击次数'。
    """
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3
    room.attacks_remaining = 5

    res = place_last_stand(room, P1, 1, 1)
    assert res['status'] == 'success'

    assert room.players[P1].remaining_ships == 1
    assert room.attacks_remaining == 1, (
        f'绝处逢生后场上只剩 1 艘船，攻击次数应为 1，实际 {room.attacks_remaining}')


def test_last_stand_keeps_subsidy_bonus(room):
    """跨回合累积的百亿补贴加成属于持卡者本人，重算时保留叠加。"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3
    room.players[P1].effect_flags.subsidy_bonus = 2
    room.attacks_remaining = 5

    place_last_stand(room, P1, 1, 1)
    assert room.attacks_remaining == 3, '基础 1 次 + 百亿补贴 2 次'


def test_last_stand_emits_attacks_updated(room, events):
    """重算后必须广播，否则前端还显示旧次数。"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3
    room.attacks_remaining = 5

    place_last_stand(room, P1, 1, 1)
    updates = [d for e, d, to, r in events if e == 'attacks_updated']
    assert updates, '必须广播 attacks_updated'
    assert updates[-1]['attacks_remaining'] == 1


def test_last_stand_under_eden_uses_six_minus_ships(room):
    """伊甸园下次数 = 6 - 船数 = 6 - 1 = 5，不能强行改成 1。"""
    room.field_magic = card('伊甸园')
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3
    room.attacks_remaining = 3

    place_last_stand(room, P1, 1, 1)
    assert room.attacks_remaining == 5


def test_last_stand_under_papal_decree_keeps_zero(room):
    """教皇旨意下攻击次数恒 0（改为弃卡攻击），绝处逢生不该把它抬起来。"""
    room.field_magic = card('教皇旨意')
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3
    room.attacks_remaining = 0

    place_last_stand(room, P1, 1, 1)
    assert room.attacks_remaining == 0


def test_last_stand_attacks_not_applied_to_opponent(room):
    """只有当前攻击者才重算，不影响对手回合。"""
    room.current_attacker = P2
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3
    room.attacks_remaining = 5

    place_last_stand(room, P1, 1, 1)
    assert room.attacks_remaining == 5, '不是自己的回合，不该动全局次数'


# ---------------------------------------------------------------------------
# Bug 1-B：牺牲的船必须走完整击沉流程
# ---------------------------------------------------------------------------
def test_last_stand_sunk_ships_leave_ships_list(room):
    """牺牲的船从 ships 移到沉船堆，且命中打满（与真实击沉口径一致）。"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3

    apply(room, P1, '绝处逢生')

    assert room.players[P1].ships == []
    assert len(room.players[P1].sunken_ships) == 3
    for sh in room.players[P1].sunken_ships:
        assert len(sh.hits) == len(sh.positions), '牺牲的船应记为已沉（命中打满）'


def test_last_stand_sacrifice_broadcasts_to_both_sides(room, events):
    """双方棋盘都要收到"这些船没了"的广播，而不是无声消失。"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3

    apply(room, P1, '绝处逢生')

    sacrificed = [d for e, d, to, r in events if e == 'ship_sacrificed']
    assert len(sacrificed) == 3, '三艘船都该广播'
    cells = sorted(tuple(sorted((p['x'], p['y']))) for d in sacrificed for p in d['positions'])
    assert cells == [(0, 0), (1, 1), (2, 2)]
    assert all(d['reason'] == 'last_stand' for d in sacrificed)
    assert [e for e, d, to, r in events if e == 'ships_updated']


def test_last_stand_triggers_sink_side_effects_once(room, events):
    """击沉通用副作用只结算一次：无瑕圣心中断恰好一次（不能逐艘触发 N 次）。"""
    room.game_effects['holy_heart'] = {'caster': P2, 'no_damage': True}
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3

    apply(room, P1, '绝处逢生')

    interrupted = [d for e, d, to, r in events if e == 'holy_heart_interrupted']
    assert len(interrupted) == 1, '三艘船同时牺牲，无瑕圣心只能中断一次'
    assert 'holy_heart' not in room.game_effects


def test_last_stand_records_ship_change_snapshot(room):
    """写入平等条约台账，source 标记为 sacrifice（自牺牲，不算被击沉）。"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3

    apply(room, P1, '绝处逢生')

    snap = room.game_effects.get('last_ship_change')
    assert snap is not None, '必须写 last_ship_change 快照'
    assert snap['player'] == P1
    assert snap['source'] == 'sacrifice'


def test_last_stand_does_not_double_count_sunken_ships(room):
    """已经沉掉的船不重复入堆（否则复活类卡牌会把沉船再恢复一次）。"""
    alive_a, alive_b = ship((0, 0)), ship((1, 1))
    dead = ship((2, 2))
    dead.hits = list(dead.positions)          # 已沉
    room.players[P1].ships = [alive_a, alive_b, dead]
    room.players[P1].sunken_ships = [dead]
    room.players[P1].remaining_ships = 3      # 活船 2 艘，但卡的条件看的是剩余船数（>=3 才可发动）

    apply(room, P1, '绝处逢生')

    assert len(room.players[P1].sunken_ships) == 3, f'沉船堆应保持 3 艘，实际 {len(room.players[P1].sunken_ships)}'
    assert room.players[P1].sunken_ships.count(dead) == 1


def test_last_stand_original_cells_only_from_alive_ships(room):
    """可选格子只来自活船：让玩家在一艘早已沉掉的船的格子上放新船毫无意义。"""
    alive = ship((0, 0))
    dead = ship((5, 5))
    dead.hits = list(dead.positions)
    room.players[P1].ships = [alive, dead, ship((1, 1))]
    room.players[P1].sunken_ships = [dead]
    room.players[P1].remaining_ships = 3

    apply(room, P1, '绝处逢生')

    cells = room.game_effects.get('last_stand_cells')
    assert (5, 5) not in cells, '已沉船的位置不该出现在可选格里'
    assert (0, 0) in cells and (1, 1) in cells


# ---------------------------------------------------------------------------
# Bug 2：盗亦有道在连锁中必须偷到紧邻下方那一张
# ---------------------------------------------------------------------------
def test_daoyouyoudao_steals_card_from_chain(room):
    """连锁中：对手先出牌（尚未结算、不在 history 里），盗亦有道压栈后应能偷到。

    这正是「对方未使用魔法卡」那个报错的复现路径。
    """
    opponent_card = card('轰炸')
    # 对手的牌已压栈但【还没结算】→ magic_history 里没有任何记录
    room.chain = [ChainItem(P2, opponent_card, [], 0)]
    room.magic_history = []
    room.players[P2].magic_hand = [card('盗亦有道')]

    res = apply(room, P1, '盗亦有道')

    assert res.success is True, f'应成功偷取，实际报错：{res.message}'
    assert '轰炸' in res.message
    stolen = [c for c in room.players[P1].magic_hand if c.name == '轰炸']
    assert len(stolen) == 1
    assert stolen[0] is opponent_card, '必须是转移同一张牌实例，不能复制'


def test_daoyouyoudao_chain_dedupes_repeat_steal(room):
    """连锁中偷过一次后，同一张牌不能再被偷（防卡牌增殖）。"""
    opponent_card = card('轰炸')
    room.chain = [ChainItem(P2, opponent_card, [], 0)]
    room.magic_history = []

    res1 = apply(room, P1, '盗亦有道')
    assert res1.success is True

    # 同一项还在栈上，再偷一次必须失败
    res2 = apply(room, P1, '盗亦有道')
    assert res2.success is False


def test_daoyouyoudao_chain_writes_single_history_entry(room):
    """连锁偷牌后，对手那张牌在历史里只能有一条记录。

    回归：曾用"占位条目"实现去重，结果同一张牌在 history 里出现两条
    （占位那条带 stolen、结算那条不带）——回退分支扫到不带标记的那条，
    会让同一张牌被无限次盗取，等于凭空造牌。
    """
    room.current_attacker = P2
    room.players[P2].magic_hand = [card('八方来财')]
    room.players[P1].magic_hand = [card('盗亦有道')]
    room.magic_deck = []

    server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P2,
        'card': {'name': '八方来财'}, 'targets': {},
    })
    opponent_card = room.chain[-1].card
    server.chain_response({
        'room_id': room.id, 'player_id': P1, 'chain': True,
        'card': {'name': '盗亦有道'}, 'targets': [],
    })
    server.resolve_chain(room)

    entries = [e for e in room.magic_history if e['card'] is opponent_card]
    assert len(entries) == 1, f'同一张牌不该有两条历史记录，实际 {len(entries)} 条'


def test_daoyouyoudao_chain_marks_history_stolen(room):
    """连锁中偷走的牌，结算写历史时必须带上 stolen 标记。

    走完整真实链路（出牌 → 连锁响应 → 结算），确保被偷的那张牌确实结算成功、
    写进历史时带上 stolen —— 否则回退分支会允许它被再偷一次。
    """
    room.current_attacker = P2
    room.players[P2].magic_hand = [card('八方来财')]
    room.players[P1].magic_hand = [card('盗亦有道')]
    room.magic_deck = []

    server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P2,
        'card': {'name': '八方来财'}, 'targets': {},
    })
    opponent_card = room.chain[-1].card

    server.chain_response({
        'room_id': room.id, 'player_id': P1, 'chain': True,
        'card': {'name': '盗亦有道'}, 'targets': [],
    })
    server.resolve_chain(room)

    entries = [e for e in room.magic_history if e['card'] is opponent_card]
    assert entries, '被偷的牌结算成功应写入历史'
    assert len(entries) == 1, f'同一张牌不该有两条历史记录，实际 {len(entries)} 条'
    assert entries[0].get('stolen') is True, (
        '被偷走的牌在历史里必须标记 stolen，否则会被重复盗取')


def test_daoyouyoudao_chain_removes_from_discard(room):
    """连锁路径也要从弃牌堆移除原卡，保证是转移而非复制。"""
    opponent_card = card('轰炸')
    room.chain = [ChainItem(P2, opponent_card, [], 0)]
    room.magic_discard = [opponent_card]

    apply(room, P1, '盗亦有道')
    assert opponent_card not in room.magic_discard


def test_daoyouyoudao_chain_ignores_own_card_below(room):
    """栈顶正下方若是自己的牌，不能偷自己的。"""
    room.chain = [ChainItem(P1, card('轰炸'), [], 0)]
    res = apply(room, P1, '盗亦有道')
    assert res.success is False
    assert '对方没有使用过魔法卡' in res.message


def test_daoyouyoudao_chain_falls_back_to_history(room):
    """栈顶是自己或栈空时，回退到全局历史里对方最近的那张。"""
    used = card('冻结')
    room.magic_history = [{'card': used, 'caster': P2, 'timestamp': 1, 'round': 1}]
    room.magic_discard = [used]
    room.chain = []                      # 非连锁场景

    res = apply(room, P1, '盗亦有道')
    assert res.success is True
    assert '冻结' in res.message
    assert used not in room.magic_discard


def test_daoyouyoudao_skips_negated_entries_in_history(room):
    """历史里被无效化的项不算"对方打出的牌"，回退时应跳过。"""
    negated = card('轰炸')
    real = card('冻结')
    room.magic_history = [
        {'card': negated, 'caster': P2, 'timestamp': 1, 'round': 1, 'negated_skip': True},
        {'card': real, 'caster': P2, 'timestamp': 2, 'round': 1},
    ]
    room.magic_discard = [negated, real]

    res = apply(room, P1, '盗亦有道')
    assert res.success is True
    assert '冻结' in res.message, '应偷到真正生效的那张，而不是被无效化的那张'


def test_daoyouyoudao_full_chain_resolution(room):
    """端到端：走 resolve_chain 真实链路，盗亦有道必须能偷到对手那张牌。

    链路：P2 出「轰炸」→ P1 连锁「盗亦有道」→ 无人再响应 → 结算（LIFO）。
    """
    room.players[P2].magic_hand = [card('轰炸')]
    room.players[P1].magic_hand = [card('盗亦有道')]
    room.magic_deck = []
    room.chain = []
    room.chain_waiting = False
    room.current_attacker = P2          # 轮到 P2 行动，由它先出牌

    # P2 打出轰炸：进入连锁
    resp0 = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P2,
        'card': {'name': '轰炸', 'speed': 3, 'type': '普通'},
        'targets': {'target_line': {'type': 'row', 'index': 0}},
    })
    assert resp0.get('status') == 'success', resp0
    assert room.chain, '轰炸应压入连锁栈'

    # P1 连锁盗亦有道
    resp = server.chain_response({
        'room_id': room.id, 'player_id': P1, 'chain': True,
        'card': {'name': '盗亦有道', 'speed': 3},
        'targets': [],
    })
    assert resp.get('status') != 'error', resp

    # 无人再响应 → 结算
    server.resolve_chain(room)

    names = [c.name for c in room.players[P1].magic_hand]
    assert '盗亦有道' not in names, '盗亦有道应已用掉'
    assert '轰炸' in names, f'盗亦有道必须偷到对手的轰炸，实际手牌：{names}'


# ---------------------------------------------------------------------------
# 绝处逢生生效期间的出牌封锁：提示必须说明真实原因
#
# 旧行为：绝处逢生生效时出牌被拒，理由却被报成「当前阶段battle无法使用
# 速阶1的魔法卡」—— 阶段明明是对的，玩家据此以为游戏坏了。
# ---------------------------------------------------------------------------
def test_last_stand_blocks_active_play_with_correct_reason(room):
    """主动出牌被拒时，理由必须是「绝处逢生生效」，而不是甩锅给阶段。"""
    room.players[P1].effect_flags.last_stand = True
    room.players[P1].magic_hand = [card('增援')]

    res = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '增援'}, 'targets': {},
    })

    assert res.get('status') == 'error'
    assert '绝处逢生' in res['message'], f'提示应点名绝处逢生，实际：{res["message"]}'
    assert '当前阶段' not in res['message'], (
        f'不该甩锅给阶段（误导），实际：{res["message"]}')


def test_last_stand_blocks_speed3_play_too(room):
    """速阶 3 卡同样被封锁 —— 它平时不受阶段限制，最容易漏判。"""
    room.players[P1].effect_flags.last_stand = True
    room.players[P1].magic_hand = [card('八方来财')]

    res = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '八方来财'}, 'targets': {},
    })

    assert res.get('status') == 'error'
    assert '绝处逢生' in res['message'], f'实际：{res["message"]}'


def test_last_stand_player_cannot_respond_chain(room):
    """绝处逢生生效中的玩家不参与连锁响应，窗口根本不该为他打开。"""
    room.players[P1].effect_flags.last_stand = True
    room.players[P1].magic_hand = [card('失灵！')]

    assert server._can_respond_chain(room, P1) is False


def test_last_stand_player_rejected_if_forges_chain_response(room):
    """即使绕过前端直接发 chain_response，服务端也必须拒绝（按放弃处理）。"""
    room.players[P1].effect_flags.last_stand = True
    room.players[P1].magic_hand = [card('失灵！')]
    room.chain = [ChainItem(P2, card('轰炸'), [], 0)]
    room.chain_waiting = True
    room.chain_window = P1
    room.chain_timer = 1

    res = server.chain_response({
        'room_id': room.id, 'player_id': P1, 'chain': True,
        'card': {'name': '失灵！', 'speed': 3}, 'targets': [],
    })

    assert res.get('status') == 'error', res
    assert not any(c.name == '失灵！' for c in room.chain), '不得把牌压进连锁栈'
    assert room.players[P1].magic_hand, '牌不该从手牌里消失'


def test_chain_opens_normally_without_last_stand(room):
    """反证：没有绝处逢生时，连锁响应窗口照常打开（别把功能的正常路径改坏）。"""
    room.players[P1].magic_hand = [card('失灵！')]
    assert server._can_respond_chain(room, P1) is True


def test_other_block_reason_still_reported(room):
    """反证：禁忌果实等其他封锁理由不受影响，仍报自己的原因。"""
    room.field_magic = card('禁忌果实')
    room.players[P1].magic_hand = [card('增援')]

    res = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '增援'}, 'targets': {},
    })

    assert res.get('status') == 'error'
    assert '禁忌果实' in res['message'], f'实际：{res["message"]}'
