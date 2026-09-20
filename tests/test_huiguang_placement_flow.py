# -*- coding: utf-8 -*-
"""回光返照「布完船之后的收尾」回归测试（2026-09-20 第二批）。

作者实测（在我第一版修复之后）：**打出回光返照后，施法者重新布好船，
不会重新进入猜拳阶段，而是继续这个回合，并且本回合攻击次数变成 0**
（但可被教皇旨意弃牌等"加攻击次数"的手段绕过）。

── 诊断过程（用探针实测）────────────────────────────────────────────

服务端主流程其实是**对的**：`handle_place_ships` 里 `all_placed` 成立后会走到
`room.state = 'rock_paper_scissors'`（探针确认 state 确实变成了 rps）。

真正的问题在**「谁被算作需要重新布船」这个判据**上：

    all_placed = all(len(p.ships) > 0 for p in room.players.values())

回光返照只清施法者一个人的船（对手 6 艘一直在），所以布完自己的船之后
`all_placed` **恒为真** —— 这没错。但这条判据是**为"双方一起重摆"设计的**
（灵气复苏 / 败者食尘），它无法表达"这一局只有一个人需要重摆"。

更要命的是 `polar_reversal_applied` / `zero_attacks_round`（败者食尘的
"本大回合攻击次数为 0"）与 `last_chance`（回光返照自己的标记）**共用
`game_effects` 与 room 上的同名状态**，而我的第一版修复调用的
`_clear_multiturn_effects` 只清计数类、不碰这两个，于是两者会互相串味。

本文件钉住用户报告的两件事：
  A. 布完船之后**必须重新猜拳**（不许继续当前回合）；
  B. 重新猜拳进入新回合后，攻击次数**按船数正常结算**，不许被残留的
     "攻击次数为 0"规则压住（那是败者食尘的机制，不是回光返照的）。
"""
import pytest

import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

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


def make_room():
    room = GameRoom('hghz-flow')
    room.players[P1] = Player(
        name='p1',
        ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(6)],
        attacks=[], remaining_ships=6, sid='sid-p1', user_id='u1')
    room.players[P2] = Player(
        name='p2',
        ships=[PlayerShip(positions=[Position(i, 5)], hits=[]) for i in range(6)],
        attacks=[], remaining_ships=6, sid='sid-p2', user_id='u2')
    room.state = 'attacking'
    room.current_attacker = P1          # 回光返照要求自己先手
    room.current_phase = 'preparation'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 5
    room.magic_deck = [MagicCard(n) for n in ['冻结', '轰炸', '增援', '疗愈']]
    room_manager.rooms[room.id] = room
    return room


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def play_huiguang(room):
    return server.apply_magic_effect(room, P1, MagicCard('回光返照'), {})


def place_six(room, pid=P1, y=3):
    return server.handle_place_ships({
        'room_id': room.id, 'player_id': pid,
        'ships': [{'positions': [{'x': i, 'y': y}], 'hits': []} for i in range(6)],
    })


# ===========================================================================
# A. ★ 布完船必须重新猜拳
# ===========================================================================
def test_placement_resumes_own_turn_in_preparation(room):
    """★ 布完船 → **还是自己的回合、还在准备阶段**。

    作者裁定的完整流程：
      「用完之后应该自己还是处于准备阶段，然后进入战斗阶段但是攻击次数为 0，
        然后可以进入结束阶段，然后再结束结束阶段进入对方的回合」
    """
    before_round = room.round
    play_huiguang(room)
    place_six(room)

    assert room.state == 'attacking', \
        f'布完船应回到 attacking，实际 state={room.state}'
    assert room.round == before_round, \
        f'不该翻大回合，round {before_round} -> {room.round}'
    assert room.current_attacker == P1, \
        f'⚠️ 行动权必须**还在施法者自己手上**（不是直接给对手），实际 {room.current_attacker}'
    assert room.current_phase == 'preparation', \
        f'应停在自己的准备阶段，实际 {room.current_phase}'


def test_attacks_zero_after_placement(room):
    """★ 布完船后攻击次数为 0（这就是"跳过战斗阶段"的落地方式）。"""
    play_huiguang(room)
    place_six(room)
    assert room.attacks_remaining == 0, \
        f'攻击次数应为 0，实际 {room.attacks_remaining}'
    assert server._attacks_forced_zero(room), \
        '必须挂上"本大回合攻击为 0"的大回合级标记（否则进战斗阶段会被重算回 6）'


def test_no_rps_after_placement(room):
    """★ 布完船之后**不许**重新猜拳。"""
    play_huiguang(room)
    place_six(room)
    assert room.state != 'rock_paper_scissors', \
        '回光返照不该重新猜拳（卡面只说"跳过自己的战斗阶段"）'


def test_can_enter_battle_phase_with_zero_attacks(room):
    """★ 能进战斗阶段 —— 但进去之后攻击次数仍是 0（不是打不出去就卡住）。"""
    play_huiguang(room)
    place_six(room)
    room.attacks_remaining = 0
    res = server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert res.get('status') == 'success', f'应当能进战斗阶段，实际 {res}'
    assert room.current_phase == 'battle'
    assert room.attacks_remaining == 0, \
        f'进战斗阶段后仍必须是 0（不许被按船数重算回 6），实际 {room.attacks_remaining}'


def test_can_enter_end_phase_then_pass_turn(room):
    """★ 能进结束阶段，然后交回合 → 这才轮到对手。

    这是作者要的收尾：自己走完 准备→战斗(0 次)→结束，**再**把回合交给对方。
    """
    play_huiguang(room)
    place_six(room)

    # 进战斗阶段
    room.attacks_remaining = 0
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert room.current_phase == 'battle'

    # 进结束阶段
    res_end = server.handle_enter_end_phase({'room_id': room.id, 'player_id': P1})
    assert res_end.get('status') == 'success', f'应当能进结束阶段，实际 {res_end}'
    assert room.current_phase == 'end'

    # 交回合 → 轮到对手
    server.end_turn({'room_id': room.id, 'player_id': P1})
    assert room.current_attacker == P2, \
        f'交回合后应轮到对手，实际 {room.current_attacker}'
    assert room.round == 5, '本大回合内换人，不该翻大回合'


def test_last_chance_survives_placement(room):
    """★ `last_chance` 必须活到对手行动 —— 那正是它的作用窗口。

    卡面：「接下来如果对方**在这一个大回合内**对任何一艘自己的船造成了伤害，
    那么自己直接判负」。
    """
    play_huiguang(room)
    place_six(room)
    lc = room.game_effects.get('last_chance')
    assert isinstance(lc, dict) and lc.get('caster') == P1, \
        'last_chance 不该在布船完成时被清掉（对手还没行动呢）'
    assert lc.get('round') == room.round


def test_opponent_can_still_act_and_lose_trigger(room, events):
    """★ 完整链路：布完船 → 走完自己的阶段 → 交回合 → 对手攻击 → 施法者判负。"""
    play_huiguang(room)
    place_six(room, P1, y=3)

    # 自己走完 准备→战斗→结束
    room.attacks_remaining = 0
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    server.handle_enter_end_phase({'room_id': room.id, 'player_id': P1})
    server.end_turn({'room_id': room.id, 'player_id': P1})

    assert room.current_attacker == P2, '应轮到对手'

    # 对手攻击施法者的船 → 触发回光返照判负
    room.current_phase = 'battle'
    room.attacks_remaining = 1
    res = server.handle_attack({'room_id': room.id, 'player_id': P2, 'x': 0, 'y': 3})
    assert res.get('game_over') is True, f'造成伤害应当判施法者负，实际 {res}'
    assert room.state == 'game_over'
    assert room.winner == P2


def test_zero_attacks_cleared_next_round(room):
    """★ "本回合攻击为 0"只属于这一个回合 —— 下一回合要恢复正常。"""
    play_huiguang(room)
    place_six(room)
    assert server._attacks_forced_zero(room) is True

    # 进入下一个大回合
    room.round += 1
    assert server._attacks_forced_zero(room) is False, \
        '新大回合不该继续被"攻击为 0"压着'


def test_max_ships_set_explicitly(room):
    """★ `max_ships` 必须是个正数 —— 否则前端点格子没反应。

    `Player.max_ships` 初值是 `None`，`reset_gameboard` 的 `new_max_ships`
    会被前端写进 `gameState.maxShips`。传 None 过去 →
    `placedShips >= maxShips` 恒成立 → **点击没反应** + 「布船数据无效」。
    """
    room.players[P1].max_ships = None       # 模拟初值
    play_huiguang(room)
    assert room.players[P1].max_ships == 6, \
        f'必须显式给出船数，实际 {room.players[P1].max_ships!r}'


def test_reset_gameboard_payload_has_valid_max_ships(room, events):
    """★ 下发给前端的 `new_max_ships` 必须是正数（前端据此判断能放几艘）。"""
    room.players[P1].max_ships = None
    play_huiguang(room)
    payloads = [d for (ev, d, _to, _r) in events if ev == 'reset_gameboard']
    assert payloads, '必须发 reset_gameboard'
    for p in payloads:
        v = p.get('new_max_ships')
        assert isinstance(v, int) and v > 0, \
            f'new_max_ships 必须是正整数，实际 {v!r}（前端会把 0/None 当成"一艘都不能放"）'


def test_huiguang_enters_placing_ships_state(room):
    """★ 打出后必须显式进入 `placing_ships`（否则收尾判据恒真 → 不重新猜拳）。"""
    play_huiguang(room)
    assert room.state == 'placing_ships', \
        f'打出回光返照后应进入摆放阶段，实际 {room.state}'
    assert getattr(room, 'huiguang_awaiting_placement', False) is True


def test_reset_gameboard_sent_only_to_caster(room, events):
    """★ `reset_gameboard` 只发给施法者（与败者食尘同机制，按 sid 单发）。"""
    play_huiguang(room)
    cards = [ev for (ev, _d, _to, _r) in events if ev == 'reset_gameboard']
    assert cards, '必须给施法者发 reset_gameboard（那是驱动布船界面的唯一入口）'
    recips = [to for (ev, _d, to, _r) in events if ev == 'reset_gameboard']
    assert all(to == 'sid-p1' for to in recips), \
        f'只能发给施法者，实际收件人: {recips}'


# ===========================================================================
# B. ★ 本回合攻击为 0（这是"跳过战斗阶段"的落地方式）
# ===========================================================================
def test_huiguang_sets_zero_attacks_for_this_round(room):
    """★ 回光返照**必须**让施法者本大回合攻击次数恒为 0。

    卡面「跳过自己的战斗阶段」的落地方式就是：能进战斗阶段，但一次都打不出去。
    ⚠️ 用的必须是**玩家级**标记（`zero_attacks_for`），不是房间级
       （`zero_attacks_round` 是败者食尘的"双方攻击都为 0"）。
    """
    play_huiguang(room)
    place_six(room)
    assert server._attacks_forced_zero(room) is True, \
        '回光返照之后施法者本大回合的攻击次数必须恒为 0'
    assert room.attacks_remaining == 0


def test_opponent_attacks_not_zeroed(room):
    """★★ 对手的攻击次数**不许**被归零（作者实测报的 bug）。

    卡面只写「跳过**自己的**战斗阶段」—— 对手的攻击次数完全不该受影响。
    第一版借用了 `zero_attacks_round`（房间级 = 双方归零），
    于是回合交到对手手上时，他一次也打不出去。
    """
    play_huiguang(room)
    place_six(room)

    # 施法者走完自己的阶段 → 交回合
    room.attacks_remaining = 0
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    server.handle_enter_end_phase({'room_id': room.id, 'player_id': P1})
    server.end_turn({'room_id': room.id, 'player_id': P1})

    assert room.current_attacker == P2, '应轮到对手'
    # ★ 对手的攻击次数必须按他自己的船数正常给出
    expected = room.players[P2].remaining_ships
    assert not server._attacks_forced_zero(room), \
        '轮到对手时，"攻击次数为 0"的规则**不该**再生效（那是施法者自己的限制）'
    assert room.attacks_remaining == expected, (
        f'对手的攻击次数应等于其船数 {expected}，实际 {room.attacks_remaining}'
    )
    assert room.attacks_remaining > 0


def test_caster_zero_attacks_does_not_leak_to_opponent(room):
    """★ 反向：施法者自己的 0 不许"传染"给对手。"""
    play_huiguang(room)
    place_six(room)
    # 施法者行动时：0
    assert server._attacks_forced_zero(room) is True
    # 换成对手行动：不再是 0
    room.current_attacker = P2
    assert server._attacks_forced_zero(room) is False, \
        '玩家级标记只该对施法者生效'


def test_zero_attacks_is_round_scoped_not_permanent(room):
    """★ 归零只属于**这一个**大回合 —— 下一回合必须恢复正常。

    `zero_attacks_round` 存的是回合号，`_attacks_forced_zero` 按 `room.round` 比对。
    如果它变成了永久标记，玩家以后每个回合都打不出去。
    """
    play_huiguang(room)
    place_six(room)
    assert server._attacks_forced_zero(room) is True

    room.round += 1
    assert server._attacks_forced_zero(room) is False, \
        '新大回合不该继续被"攻击为 0"压着'


# ===========================================================================
# C. 反向守卫：败者食尘的归零机制不许被弄坏
# ===========================================================================
def test_baizhe_zero_attacks_still_works(room):
    """★ 反向守卫：败者食尘的"本大回合双方攻击为 0"必须照旧生效。"""
    room.game_effects['zero_attacks_round'] = room.round
    assert server._attacks_forced_zero(room) is True
    # 归零标记只对**生效的那个大回合**有效
    room.round += 1
    assert server._attacks_forced_zero(room) is False


def test_baizhe_sets_zero_attacks(room):
    """败者食尘打出后必须挂上归零标记（既有行为）。"""
    room.current_phase = 'preparation'
    res = server.apply_magic_effect(room, P1, MagicCard('败者食尘'), {})
    assert res.success is not False
    assert room.game_effects.get('zero_attacks_round') == room.round, \
        '败者食尘必须挂上本大回合的攻击归零标记'


# ===========================================================================
# D. 回光返照自己的标记（last_chance）生命周期
# ===========================================================================
def test_last_chance_set_by_huiguang(room):
    """回光返照要挂 `last_chance`（对方本大回合内伤害我即我判负）。"""
    play_huiguang(room)
    lc = room.game_effects.get('last_chance')
    assert isinstance(lc, dict) and lc.get('caster') == P1
    assert lc.get('round') == room.round


def test_restore_due_shenwei_not_broken_by_this_batch(room):
    """反向守卫：本批改动不许影响神威归还那条路（Bug 1 的修复）。"""
    sent = []
    room.game_effects.setdefault('excluded_ships', []).append(
        {'player': P1, 'ships': [PlayerShip([Position(2, 2)], [])], 'return_turn': 1})
    server._restore_due_shenwei(room, current_round=6)
    assert room.players[P1].remaining_ships == 7      # 6 + 归还的 1
