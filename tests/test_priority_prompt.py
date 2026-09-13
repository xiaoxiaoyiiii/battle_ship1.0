# -*- coding: utf-8 -*-
"""阶段转换「优先权询问」的回归测试（2026-09-14）。

背景：速阶3卡牌"任何时候都能使用"，双方都能在任意时刻插牌，
而游戏只有连锁响应窗口这一个仲裁点 —— 它 ① 对方没速阶3时自动跳过、
不给选择权；② 不覆盖阶段推进这类非出牌操作。
实测：P2 在 P1 的准备阶段出速阶3，P1 随后仍能直接 enter_battle_phase，
两张牌的效果落地顺序没有任何定义。

方案 D（作者选定）：保留现有窗口机制，把"自动跳过"改成"总是询问"，
参照游戏王 YGO 的优先权确认；并新增「拒绝」开关防占时间。
只问两个入口：进战斗 / 进结束（交回合与攻击不问）。

⚠️ 本文件的 fixture 会把 `_has_request_context` 置为 True，
否则 `_should_ask_priority` 会因"无 socket 上下文"直接放行（那是给单测的惯例）。
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
    # ⚠️ 后台任务桩必须【同步执行】：
    # _priority_continue 把"重放阶段转换"丢进 start_background_task，
    # 是为了脱离响应者的请求上下文（否则 _identity_ok 拿响应者的 sid
    # 去比对发起者的座位，必然失败——2026-09-13 实测的线上级 bug）。
    # 单测里没有 eventlet hub，若桩成 no-op，被拦下的操作就永远不会执行，
    # "取消后继续"这类断言会假红。这里同步跑，等价于 hub 立刻调度。
    monkeypatch.setattr(server.socketio, 'start_background_task',
                        lambda target, *a, **k: target(*a, **k))
    monkeypatch.setattr(server, '_schedule_chain_timeout', lambda *a, **k: None)
    monkeypatch.setattr(server, '_schedule_priority_timeout', lambda *a, **k: None)
    # 关键：模拟"处于真实 socket 请求上下文"
    monkeypatch.setattr(server, '_has_request_context', lambda: True)
    return captured


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def make_room(ai=False):
    room = GameRoom('test-room')
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
    room.round = 5
    room.is_ai_room = ai
    room.magic_deck = [MagicCard(n) for n in ['冻结', '轰炸', '疗愈', '饮血']]
    room_manager.rooms[room.id] = room
    return room


def card(name):
    return MagicCard(name)


def pri_requests(events):
    return [d for e, d, to, r in events if e == 'priority_request']


# ===========================================================================
# 核心：进战斗阶段要询问，阶段暂不推进
# ===========================================================================
def test_enter_battle_asks_priority(room, events):
    """★ 进战斗阶段前必须询问对方，且阶段【暂不推进】。"""
    room.players[P2].magic_hand = [card('失灵！')]

    res = server.enter_battle_phase({'room_id': room.id, 'player_id': P1})

    assert res.get('awaiting_priority') is True, f'应进入等待状态，实际 {res}'
    assert room.current_phase == 'preparation', '阶段不该被推进'
    assert room.priority_pending is not None, '应记录待响应状态'


def test_enter_battle_emits_request(room, events):
    """要推送 priority_request 且发给【对方】。"""
    room.players[P2].magic_hand = [card('失灵！')]
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})

    reqs = pri_requests(events)
    assert reqs, '必须推送 priority_request'
    assert reqs[-1]['action'] == 'enter_battle'
    assert reqs[-1]['countdown'] == server.PRIORITY_SECONDS
    targets = [to for e, d, to, r in events if e == 'priority_request']
    assert targets == ['sid-p2'], '应发给对方，不是发起者'


def test_priority_request_includes_speed3_list(room, events):
    """请求里要带上对方手上的速阶3卡（前端据此渲染可选项）。"""
    room.players[P2].magic_hand = [card('失灵！'), card('冻结')]
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})

    names = [getattr(c, 'name', str(c)) for c in pri_requests(events)[-1]['speed3_cards']]
    assert names == ['失灵！'], f'只应列出速阶3，实际 {names}'


def test_no_speed3_still_asked(room, events):
    """★ 作者裁定：对方没有速阶3也照样询问（玩家要有选择权）。"""
    assert room.players[P2].magic_hand == []
    res = server.enter_battle_phase({'room_id': room.id, 'player_id': P1})

    assert res.get('awaiting_priority') is True, '没有速阶3也要问'
    assert pri_requests(events), '必须推送'


# ===========================================================================
# 响应：取消 → 继续；出牌 → 结算后再继续
# ===========================================================================
def test_decline_continues_operation(room):
    """对方取消 → 阶段继续推进。"""
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert room.current_phase == 'preparation'

    res = server.priority_response({'room_id': room.id, 'player_id': P2, 'respond': False})

    assert res.get('status') == 'success'
    assert room.current_phase == 'battle', '取消后应继续推进'
    assert room.priority_pending is None


def test_respond_speed3_then_phase_advances(room):
    """★ 对方打出速阶3 → 先结算，再继续推进阶段。"""
    room.players[P2].magic_hand = [card('饮血')]
    room.players[P1].ships[0].hits = list(room.players[P1].ships[0].positions)
    room.players[P1].sunken_ships.append(room.players[P1].ships[0])
    room.players[P1].remaining_ships = 5
    room.players[P1].last_attack = None

    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    res = server.priority_response({'room_id': room.id, 'player_id': P2, 'respond': True,
                                    'card': {'name': '饮血'}, 'targets': []})

    assert res.get('status') == 'success', res
    assert room.current_phase == 'battle', '结算完后阶段应推进'


def test_respond_with_invalid_card_falls_back_to_decline(room):
    """响应时出牌失败（没这张牌）→ 视为取消，阶段仍要推进，不能卡住。"""
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    res = server.priority_response({'room_id': room.id, 'player_id': P2, 'respond': True,
                                    'card': {'name': '冻结'}, 'targets': []})

    assert res.get('status') == 'success'
    assert room.current_phase == 'battle', '不能把对局卡在这里'


def test_continue_must_escape_responder_request_context(room, monkeypatch):
    """★ 复现并锁死 2026-09-13 的线上级 bug：续做动作必须脱离响应者的请求上下文。

    症状：玩家点「取消」后，priority_pending 被清空、但阶段永远停在
    preparation —— 整个回合死掉，双方都没有任何提示。

    根因：_resolve_priority 是在【响应者】的 socket 请求里被调用的，
    而 _priority_continue 要代【发起者】重放 enter_battle_phase。
    那个 handler 开头的 _identity_ok 会拿 request.sid（响应者的连接）
    去比对发起者座位的 sid —— 必然不匹配，重放静默返回 error。

    断言分两半：
      ① 若续做同步执行（= 仍在响应者的请求里）→ 阶段必须【推进不了】（复现 bug）
      ② 续做走后台任务（= 脱离上下文）     → 阶段必须推进（修复后的行为）
    """
    # ---- ① 复现：续做同步执行（= 仍在响应者的请求里），身份校验只认响应者 P2 ----
    # 注意：不能从一开始就把 _identity_ok 设成"只认 P2"——那样 enter_battle_phase
    # 在函数开头就被拒了，根本发不出询问。这里让询问正常发出，
    # 只在【续做重放】那一刻切成"响应者上下文"。
    strict = {'on': False}
    monkeypatch.setattr(server, '_identity_ok',
                        lambda r, claimed: (claimed == P2) if strict['on']
                        else claimed in r.players)
    monkeypatch.setattr(server.socketio, 'start_background_task',
                        lambda target, *a, **k: target(*a, **k))

    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert room.priority_pending, '前提：已发出询问'

    strict['on'] = True
    server.priority_response({'room_id': room.id, 'player_id': P2, 'respond': False})
    assert room.current_phase == 'preparation', (
        '前提：续做若留在响应者的请求上下文里，会被 _identity_ok 拦下（这就是那个 bug）')

    # ---- ② 修复后的行为：续做脱离请求上下文 → 正常推进 ----
    strict['on'] = False
    seen = {'detached': False}

    def run_detached(target, *a, **k):
        seen['detached'] = True
        # 后台任务里没有请求上下文：_identity_ok 只做成员校验
        return target(*a, **k)

    monkeypatch.setattr(server.socketio, 'start_background_task', run_detached)

    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert room.priority_pending, '前提：第二次询问已发出'
    server.priority_response({'room_id': room.id, 'player_id': P2, 'respond': False})

    assert seen['detached'], '续做动作必须走后台任务（脱离响应者的请求上下文）'
    assert room.current_phase == 'battle', '脱离上下文后阶段必须推进'
    assert room.priority_pending is None, '询问状态要清干净'


def test_priority_continue_is_initialized(room):
    """priority_continue 必须在 GameRoom.__init__ 里就有——不能靠现赋。"""
    assert hasattr(room, 'priority_continue')
    assert room.priority_continue is None


def test_respond_without_card_rejected(room):
    """respond=True 但没给卡 → 明确报错。"""
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    res = server.priority_response({'room_id': room.id, 'player_id': P2, 'respond': True})
    assert res.get('status') == 'error'
    assert room.priority_pending is not None, '状态不该被清掉'


def test_wrong_player_cannot_respond(room):
    """只有被询问的一方能响应。"""
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    res = server.priority_response({'room_id': room.id, 'player_id': P1, 'respond': False})
    assert res.get('status') == 'error'
    assert room.priority_pending is not None


def test_timeout_treated_as_decline(room):
    """超时视为放弃，继续推进。"""
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    server._resolve_priority(room, respond=False)
    assert room.current_phase == 'battle'


def test_stale_response_after_clear_is_rejected(room):
    """已经处理过的询问再响应 → 报错（防重复触发操作）。"""
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    server.priority_response({'room_id': room.id, 'player_id': P2, 'respond': False})
    res = server.priority_response({'room_id': room.id, 'player_id': P2, 'respond': False})
    assert res.get('status') == 'error'


# ===========================================================================
# 进结束阶段
# ===========================================================================
def test_enter_end_asks_priority(room, events):
    """战斗 → 结束同样要询问。"""
    room.current_phase = 'battle'
    room.attacks_remaining = 0

    res = server.handle_enter_end_phase({'room_id': room.id, 'player_id': P1})

    assert res.get('awaiting_priority') is True
    assert room.current_phase == 'battle', '阶段不该被推进'
    assert pri_requests(events)[-1]['action'] == 'enter_end'


def test_enter_end_continues_after_decline(room):
    room.current_phase = 'battle'
    room.attacks_remaining = 0
    server.handle_enter_end_phase({'room_id': room.id, 'player_id': P1})

    server.priority_response({'room_id': room.id, 'player_id': P2, 'respond': False})
    assert room.current_phase == 'end'


# ===========================================================================
# 拒绝开关
# ===========================================================================
def test_decline_switch_skips_asking(room, events):
    """★ 开启拒绝开关后不再询问，直接推进。"""
    server.set_decline_priority({'room_id': room.id, 'player_id': P2, 'decline': True})

    res = server.enter_battle_phase({'room_id': room.id, 'player_id': P1})

    assert res.get('awaiting_priority') is not True
    assert room.current_phase == 'battle'
    assert not pri_requests(events), '开关开启时不该弹窗'


def test_decline_switch_can_be_turned_back_on(room, events):
    """★ 开关可随时切回（作者要求开关而非一次性按钮）。"""
    server.set_decline_priority({'room_id': room.id, 'player_id': P2, 'decline': True})
    server.set_decline_priority({'room_id': room.id, 'player_id': P2, 'decline': False})

    res = server.enter_battle_phase({'room_id': room.id, 'player_id': P1})

    assert res.get('awaiting_priority') is True, '关掉开关后应重新询问'
    assert pri_requests(events)


def test_decline_switch_emits_update(room, events):
    """切换开关要回执给本人。"""
    server.set_decline_priority({'room_id': room.id, 'player_id': P2, 'decline': True})
    updates = [d for e, d, to, r in events if e == 'priority_setting_updated']
    assert updates and updates[-1]['decline'] is True


def test_decline_via_response_payload(room, events):
    """响应时也可以顺带勾上开关。"""
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    server.priority_response({'room_id': room.id, 'player_id': P2,
                              'respond': False, 'decline_all': True})
    assert room.decline_priority.get(P2) is True

    # 下一次不再询问
    room.current_phase = 'battle'
    room.attacks_remaining = 0
    events.clear()
    res = server.handle_enter_end_phase({'room_id': room.id, 'player_id': P1})
    assert res.get('awaiting_priority') is not True
    assert not pri_requests(events)


def test_decline_is_per_player(room):
    """开关只影响自己，不影响对方。"""
    server.set_decline_priority({'room_id': room.id, 'player_id': P2, 'decline': True})
    assert room.decline_priority.get(P2) is True
    assert room.decline_priority.get(P1) is None


# ===========================================================================
# 不询问的阻断条件
# ===========================================================================
def test_ai_room_skips_asking(room, events):
    """★ 人机房不询问（AI 不会响应，弹窗只会让人干等）。"""
    room.is_ai_room = True
    res = server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert res.get('awaiting_priority') is not True
    assert room.current_phase == 'battle'
    assert not pri_requests(events)


def test_chain_pending_skips_asking(room, events):
    """已有连锁窗口挂起时不叠加询问（连锁窗口优先）。"""
    room.chain = [ChainItem(P1, card('冻结'), {}, 0)]
    room.chain_waiting = True
    res = server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert res.get('awaiting_priority') is not True


def test_disconnected_opponent_skips_asking(room, events):
    """对方掉线时不询问。

    注意：对方掉线时整个房间本来就会被 _frozen_reason 冻结（既有机制），
    所以阶段不会推进 —— 这里只断言"没有弹询问窗口"，不假设阶段会推进。
    """
    room.disconnected[P2] = {'deadline': 1e18, 'token': 1}
    events.clear()
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert not pri_requests(events), '对方掉线时不该弹询问窗口'


def test_should_ask_returns_false_when_opponent_disconnected(room):
    """直接测判定函数本身：对方在掉线宽限期内 → 不询问。"""
    room.disconnected[P2] = {'deadline': 1e18, 'token': 1}
    assert server._should_ask_priority(room, P1, P2) is False


def test_existing_pending_does_not_stack(room):
    """已有未处理的询问时不叠加。"""
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert room.priority_pending is not None
    room.current_phase = 'battle'
    room.attacks_remaining = 0
    res = server.handle_enter_end_phase({'room_id': room.id, 'player_id': P1})
    assert res.get('awaiting_priority') is not True, '不该叠加第二次询问'


def test_no_request_context_skips_asking(room, monkeypatch):
    """无 socket 上下文（单测直调）时直接放行 —— 否则所有既有测试都会挂。"""
    monkeypatch.setattr(server, '_has_request_context', lambda: False)
    res = server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert res.get('awaiting_priority') is not True
    assert room.current_phase == 'battle'


def test_game_over_skips_asking(room):
    room.state = 'game_over'
    assert server._should_ask_priority(room, P1, P2) is False


# ===========================================================================
# 反证：交回合与攻击【不】询问（作者裁定）
# ===========================================================================
def test_end_turn_does_not_ask_priority(room, events):
    """交回合不询问 —— 它本来就被连锁窗口拦着。"""
    room.current_phase = 'end'
    room.attacks_remaining = 0
    events.clear()
    server.end_turn({'room_id': room.id, 'player_id': P1})
    assert not pri_requests(events), '交回合不该弹优先权询问'


def test_attack_does_not_ask_priority(room, events):
    """攻击不询问 —— 每回合 3-6 次，一局上百次弹窗会毁掉体验。"""
    room.current_phase = 'battle'
    room.attacks_remaining = 6
    events.clear()
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 5, 'y': 5})
    assert not pri_requests(events), '攻击不该弹优先权询问'
