# -*- coding: utf-8 -*-
"""神机妙算三处缺陷的回归测试（2026-09-16）。

作者实测报的三个问题：

  ① 宣言过程中**没有等待窗口、也不冻结对方** —— 对方能照常开炮/出牌/交回合。
  ② 结算判定失败：宣言「减少 1 艘」，实际被打沉 2 艘，回合一结束却报**预言成功**。
  ③ 预言成功后的重新部署**只能点原位置**，对方没打过的空格点不了。

根因（复现见 docs/superpowers/specs/2026-09-16-shenji-fixes-design.md）：

  ①② 是同一条链条：快照在**宣言确认那一刻**才拍（应为**出牌那一刻**），
     再加上宣言窗口不冻结对方 → 确认之前打掉的船被并进基线 → diff 少算 → 误判成功。
  ③ `allowed` 字段一个字段两种语义：绝处逢生用它当白名单，神机妙算用它当豁免名单，
     前端 game.js:5699 对两者一律按白名单处理，于是只有原位置可点。
"""
import pytest

import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def events(monkeypatch):
    """捕获 emit，并切断后台任务（超时调度不该在单测里真的等）。"""
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append({'event': event, 'data': data, 'to': to, 'room': room})

    monkeypatch.setattr(server, 'emit', fake_emit)
    # raising=False：修复前这些符号还不存在，测试应当因"断言失败"变红，
    # 而不是因为 fixture 自己报 AttributeError 变 ERROR。
    monkeypatch.setattr(server, '_schedule_shenji_declare_timeout',
                        lambda *a, **k: None, raising=False)
    monkeypatch.setattr(server.socketio, 'start_background_task', lambda target, *a, **k: None)
    return captured


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def make_room():
    room = GameRoom('shenji-fix')
    room.players[P1] = Player(
        name='p1', ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(6)],
        attacks=[], remaining_ships=6, sid='sid-p1')
    room.players[P2] = Player(
        name='p2', ships=[PlayerShip(positions=[Position(i, 5)], hits=[]) for i in range(6)],
        attacks=[], remaining_ships=6, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P2
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 1
    room_manager.rooms[room.id] = room
    return room


def card(name):
    return MagicCard(name)


def play_shenji(room):
    """打出神机妙算（宣言窗口就此打开，尚未宣言）。"""
    return server.apply_magic_effect(room, P1, card('神机妙算'), {})


def declare(room, x):
    return server.handle_confirm_shenji_declare(
        {'room_id': room.id, 'player_id': P1, 'prediction': x})


def attack(room, x, y, player=P2):
    return server.handle_attack({'room_id': room.id, 'player_id': player, 'x': x, 'y': y})


def end_big_round(room):
    room.current_phase = 'end'
    return server.end_turn({'room_id': room.id, 'player_id': P2})


def redeploy_started(room):
    return bool(room.magic_temp_data.get('pending_placement')) or bool(
        room.game_effects.get('shenji_redeploy'))


# ===========================================================================
# 问题 ①：宣言窗口必须冻结对方（但不能冻结施法者自己）
# ===========================================================================
def test_opponent_cannot_attack_while_declaration_pending(room):
    """★ 宣言还没确认时，对方不许开炮（旧实现放行 → 直接造成问题 ②）。"""
    play_shenji(room)
    assert room.magic_temp_data.get('pending_shenji'), '宣言窗口应当已打开'

    res = attack(room, 0, 0)
    assert res.get('status') == 'error', (
        f'宣言窗口开着时对方仍能攻击（返回 {res}）—— 这正是问题 ①')
    assert len(room.players[P1].sunken_ships) == 0


def test_opponent_cannot_end_turn_while_declaration_pending(room):
    play_shenji(room)
    room.current_phase = 'end'
    res = server.end_turn({'room_id': room.id, 'player_id': P2})
    assert res.get('status') == 'error', f'宣言窗口开着时对方仍能交回合（返回 {res}）'


def test_opponent_cannot_play_magic_while_declaration_pending(room):
    play_shenji(room)
    room.players[P2].magic_hand = [card('冻结')]
    res = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P2,
        'card': {'name': '冻结'}, 'targets': {},
    })
    # ⚠️ 必须断言【拒绝的理由是宣言窗口】，不能只断言 status=error ——
    # 这张牌本来就可能因为别的原因被拒（比如缺目标），那样这条用例会假通过。
    assert res.get('status') == 'error', f'宣言窗口开着时对方仍能出牌（返回 {res}）'
    assert '神机妙算' in str(res.get('message') or ''), (
        f'拒绝理由不是"对方正在宣言神机妙算"（返回 {res}）')


def test_caster_can_still_declare_while_window_open(room):
    """反向保护：冻结只能冻对方，施法者自己必须还能宣言。"""
    play_shenji(room)
    res = declare(room, 1)
    assert res.get('status') == 'success', f'施法者被自己的窗口冻住了（返回 {res}）'
    assert room.players[P1].effect_flags.prediction == 1
    assert not room.magic_temp_data.get('pending_shenji')


def test_opponent_gets_waiting_notice_and_release(room, events):
    """对方要收到「等待宣言中」与解除通知，前端据此显示/撤下横幅。"""
    play_shenji(room)
    assert any(e['event'] == 'shenji_waiting' for e in events), \
        '出牌时应当通知对方进入等待'
    declare(room, 1)
    assert any(e['event'] == 'shenji_waiting_end' for e in events), \
        '宣言完成后应当解除等待'


def test_opponent_frozen_only_while_pending(room):
    """宣言完成后，对方的行动必须恢复自由（别冻过头）。"""
    play_shenji(room)
    declare(room, 1)
    res = attack(room, 0, 0)
    assert res.get('status') == 'success', f'宣言结束后对方仍被冻结（返回 {res}）'


# ===========================================================================
# 问题 ②：基线（快照）必须在【出牌那一刻】拍，而不是宣言确认时
# ===========================================================================
def test_baseline_snapshot_taken_when_card_is_played(room):
    """★ 出牌就该拍基线 —— 否则宣言确认前打掉的船会被并进基线，diff 少算。"""
    assert f'prediction_initial_{P1}' not in room.game_effects
    play_shenji(room)
    snap = room.game_effects.get(f'prediction_initial_{P1}')
    assert snap is not None, '出牌那一刻就该拍基线（旧实现等到 confirm 才拍 → 问题 ②）'
    assert snap['sunken'] == len(room.players[P1].sunken_ships)
    assert snap['ships'] == room.players[P1].remaining_ships


def test_declare_does_not_rewrite_baseline(room):
    """宣言只写数值 x，不许重拍基线。"""
    room.players[P1].ships[0].hits = [Position(0, 0)]
    server._mark_ship_sunken(room.players[P1], room.players[P1].ships[0])
    room.players[P1].remaining_ships = 5
    play_shenji(room)
    before = dict(room.game_effects[f'prediction_initial_{P1}'])

    declare(room, 1)
    after = room.game_effects.get(f'prediction_initial_{P1}')
    assert after is not None and after['sunken'] == before['sunken'], \
        '宣言把基线重拍了 —— 基线必须固定在出牌那一刻'


def test_two_losses_with_prediction_one_fails(room):
    """★ 问题 ② 的正确语义：宣言 1 艘、实际被沉 2 艘 → 必须判【失败】。"""
    play_shenji(room)
    declare(room, 1)
    assert attack(room, 0, 0).get('status') == 'success'
    assert attack(room, 1, 0).get('status') == 'success'
    assert len(room.players[P1].sunken_ships) == 2

    end_big_round(room)

    assert not redeploy_started(room), '打了 2 艘却判成预言成功（问题 ② 复现）'
    assert room.players[P1].remaining_ships == 4, '预言失败时船数不该被恢复'
    assert room.players[P1].effect_flags.prediction in (0, False)


def test_exact_prediction_still_succeeds(room):
    """回归保护：宣言 1 艘、实际正好 1 艘 → 仍然判成功并给出重新部署。"""
    play_shenji(room)
    declare(room, 1)
    assert attack(room, 0, 0).get('status') == 'success'

    end_big_round(room)

    assert redeploy_started(room), '预言命中却没能进入重新部署'


# ===========================================================================
# 问题 ③：重新部署要能放在"对方没打过的空格"，不能只给原位置
# ===========================================================================
def _emit_redeploy_payload(room, events):
    """让 P1 进入一次神机妙算重新部署，返回发给他的 placement_request 载荷。"""
    # 对方打过 (0,0)（打沉 P1 那艘）与 (3,3)（放空炮）
    room.players[P2].attacks = [Position(0, 0), Position(3, 3)]
    ship = room.players[P1].ships[0]
    server._mark_ship_sunken(room.players[P1], ship)
    room.players[P1].remaining_ships = 5

    server._begin_shenji_redeploy(room, P1, 1, already_sunken_ids=[])

    payloads = [e['data'] for e in events if e['event'] == 'placement_request']
    assert payloads, '没有发出 placement_request'
    return payloads[-1]


def test_redeploy_allows_unhit_empty_cells(room, events):
    """★ 对方没打过、也没被活船占用的空格，必须可放置（问题 ③）。"""
    payload = _emit_redeploy_payload(room, events)
    blocked = {(b['x'], b['y']) for b in payload.get('blocked', [])}

    assert (2, 3) not in blocked, '对方没打过的空格被挡住 —— 这正是问题 ③'
    assert (0, 0) not in blocked, '原位置（已被打过）应当仍可放回'
    assert (3, 3) in blocked, '对方打过、又不是原位置的格子才该被挡'


def test_redeploy_does_not_send_whitelist(room, events):
    """★ 不能再下发 allowed 白名单：前端会据此把其余格子全部禁点。"""
    payload = _emit_redeploy_payload(room, events)
    assert not payload.get('allowed'), (
        '神机妙算仍在下发 allowed —— 前端 game.js:5699 会把它当白名单，'
        '于是只有原位置可点（问题 ③）')


# ===========================================================================
# 宣言超时：不能因为冻结把两边一起卡死
# ===========================================================================
def test_declaration_timeout_clears_pending_and_baseline(room):
    play_shenji(room)
    token = (room.magic_temp_data.get('pending_shenji') or {}).get('token')
    assert token is not None, '宣言窗口应当带一个超时代际令牌'

    server._shenji_declare_timeout_fired(room.id, token)

    assert not room.magic_temp_data.get('pending_shenji'), '超时后应清掉宣言窗口'
    assert f'prediction_initial_{P1}' not in room.game_effects, '超时后不该留下基线'
    assert not room.players[P1].effect_flags.prediction
    # 冻结必须随之解除
    assert attack(room, 0, 0).get('status') == 'success', '超时后对方仍被冻结'


def test_stale_timeout_token_is_ignored(room):
    """代际令牌：宣言成功后，旧定时器不得再动状态。"""
    play_shenji(room)
    token = (room.magic_temp_data.get('pending_shenji') or {}).get('token')
    declare(room, 2)

    server._shenji_declare_timeout_fired(room.id, token)

    assert room.players[P1].effect_flags.prediction == 2, '旧定时器不该清掉已生效的宣言'
    assert f'prediction_initial_{P1}' in room.game_effects
