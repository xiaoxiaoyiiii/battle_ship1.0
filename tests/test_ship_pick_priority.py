# -*- coding: utf-8 -*-
"""选船类效果的优先级仲裁（2026-09-20）。

作者实测症状：
  「当需要选船的多个效果同时发生的时候，在选船的时候就会卡住选不了。
    尤其是当恶魔契约生效的时候，如果自己在战斗阶段使用了克苏鲁之眼要自己选船的时候，
    一点击船在的格子就会弹出『当前没有待牺牲的船』，无法正常让克苏鲁之眼被用出去。」

── 根因（逐行核实过）────────────────────────────────────────────────

① 服务端**单槽覆盖**：`room.magic_temp_data['pending_sacrifice']` 是一个 dict，
   `_request_ship_pick()` 无条件覆写。三个效果共用这一个槽
   （恶魔契约 / 神之宣告·效果一 / 克苏鲁之眼）。

   复现链：
     1. 恶魔契约是持续场地效果，在 6 处船损路径上触发；
     2. 某船沉没 → 向另一方 X 发请求 → 槽 = {player: X, reason: 'demon_contract'}；
     3. X 打出克苏鲁之眼 → 向 Y 发请求 → **覆盖**成 {player: Y, reason: 'kraken_eye'}；
     4. X 点自己船的格子 → `handle_confirm_sacrifice` 读到 player != X
        → 返回「当前没有待牺牲的战舰」。

② 存储位置不安全：`magic_temp_data` 有 8 处被整体覆写成 `{}`，
   待选状态放在里面，等待期间打出别的卡就会把待选**静默抹掉**。

③ 前端 `selectingOnBoard` 是单个全局布尔，恶魔契约与单格点选器都往同一块棋盘
   挂捕获阶段监听，先注册的赢。

本文件按**优先级仲裁**后的设计断言（先红后绿）。
"""
import itertools

import pytest

import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'
_seq = itertools.count(1)


def card(name):
    return MagicCard(name)


def ship(*cells):
    return PlayerShip(positions=[Position(x, y) for x, y in cells], hits=[])


def make_room():
    room = GameRoom('ship-pick')
    room.players[P1] = Player(
        name='p1', ships=[ship((0, 0)), ship((1, 1)), ship((2, 2))],
        attacks=[], remaining_ships=3, sid='sid-p1', user_id='u1')
    room.players[P2] = Player(
        name='p2', ships=[ship((0, 5)), ship((1, 5)), ship((2, 5))],
        attacks=[], remaining_ships=3, sid='sid-p2', user_id='u2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 3
    room.round = 5
    room.magic_temp_data = {}
    room.game_effects['demon_contract'] = True
    room_manager.rooms[room.id] = room
    return room


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


def requests_for(events, sid):
    """筛出某个 sid 收到的 sacrifice_request。"""
    return [d for (ev, d, to, _r) in events if ev == 'sacrifice_request' and to == sid]


# ===========================================================================
# ★ A. 复现链：恶魔契约 + 克苏鲁之眼（作者报的那条）
# ===========================================================================
def test_demon_contract_and_kraken_eye_can_both_be_resolved(room, events):
    """★ 复现作者报的 bug：两个待选同时存在时，两边的选择都必须能完成。

    旧实现：第二次请求覆盖第一次 → 第一个玩家点船时报
    「当前没有待牺牲的战舰」。
    """
    # 1) 恶魔契约触发 → 让 P1 选一艘船牺牲
    server._request_demon_contract_sacrifice(room, P2)

    # 2) P1 打出克苏鲁之眼 → 让 P2 选一艘船暴露（这一步会覆盖旧实现的那个槽）
    #    ⚠️ 目标是 `{x, y}`（single 选择器）或 `target_area`，**不是** selected_cells
    #       —— 见 `_pick_cell_from_target`。
    res = server.apply_magic_effect(room, P1, card('克苏鲁之眼'),
                                   {'x': 0, 'y': 0})
    assert res.success is not False, f'克苏鲁之眼应能打出: {res.message}'

    # 3) ★ P1 点自己的船完成牺牲 —— 这正是作者报的那一下
    r1 = server.handle_confirm_sacrifice({
        'room_id': room.id, 'player_id': P1, 'position': {'x': 0, 'y': 0}})
    assert r1['status'] == 'success', (
        f"P1 的牺牲不该被 P2 的请求挤掉，实际: {r1.get('message')}")

    # 4) P2 也要能完成自己的暴露
    r2 = server.handle_confirm_sacrifice({
        'room_id': room.id, 'player_id': P2, 'position': {'x': 0, 'y': 5}})
    assert r2['status'] == 'success', f"P2 的暴露也该能完成，实际: {r2.get('message')}"


def test_both_players_get_their_own_request(room, events):
    """★ 两个玩家各收到自己的请求（按 sid 分别投递，不互相覆盖）。"""
    server._request_demon_contract_sacrifice(room, P2)      # → P1
    server.apply_magic_effect(room, P1, card('克苏鲁之眼'), {'x': 0, 'y': 0})   # → P2
    assert requests_for(events, 'sid-p1'), 'P1 应收到牺牲请求'
    assert requests_for(events, 'sid-p2'), 'P2 应收到暴露请求'


# ===========================================================================
# ★ B. 按玩家独立：一个人的待选不影响另一个人的
# ===========================================================================
def test_pending_picks_are_per_player(room):
    """★ 队列按玩家分组：A 的待选与 B 的待选同时挂起都成立。"""
    server._request_ship_pick(room, P1, 'demon_contract', 'm1')
    server._request_ship_pick(room, P2, 'kraken_eye', 'm2')
    a = server._top_ship_pick(room, P1)
    b = server._top_ship_pick(room, P2)
    assert a and a['reason'] == 'demon_contract'
    assert b and b['reason'] == 'kraken_eye'


def test_consuming_one_player_does_not_clear_the_other(room):
    """★ 消费 A 的待选后，B 的仍在。"""
    server._request_ship_pick(room, P1, 'demon_contract', 'm1')
    server._request_ship_pick(room, P2, 'kraken_eye', 'm2')
    server._consume_ship_pick(room, P1, 'demon_contract')
    assert server._top_ship_pick(room, P1) is None, 'A 的已消费'
    assert server._top_ship_pick(room, P2) is not None, 'B 的不该被牵连'


# ===========================================================================
# ★ C. 同玩家多待选：按优先级依次交付
# ===========================================================================
def test_priority_order_within_player(room, events):
    """★ 同一玩家排了两项时，**高优先级先交付**。"""
    # 先排低优先级（克苏鲁之眼），后排高优先级（恶魔契约）
    server._request_ship_pick(room, P1, 'kraken_eye', '低')
    server._request_ship_pick(room, P1, 'demon_contract', '高')
    top = server._top_ship_pick(room, P1)
    assert top['reason'] == 'demon_contract', (
        f'应先交付恶魔契约（优先级更高），实际 {top["reason"]}')


def test_next_pick_dispatched_after_consume(room, events):
    """★ 消费高优先级后，低优先级那项自动投递。"""
    server._request_ship_pick(room, P1, 'kraken_eye', '低')
    server._request_ship_pick(room, P1, 'demon_contract', '高')
    events.clear()
    server._consume_ship_pick(room, P1, 'demon_contract')
    top = server._top_ship_pick(room, P1)
    assert top and top['reason'] == 'kraken_eye', '应接着交付剩下那一项'
    assert requests_for(events, 'sid-p1'), '交付时要发事件给玩家'


def test_same_priority_is_first_come(room):
    """同优先级按先到先得（用 seq 保证顺序确定，可测）。"""
    server._request_ship_pick(room, P1, 'kraken_eye', '第一个')
    server._request_ship_pick(room, P1, 'kraken_eye', '第二个')
    top = server._top_ship_pick(room, P1)
    assert top['message'] == '第一个', '同优先级应先到先得'


def test_priority_table_is_single_source():
    """★ 优先级表只有一份，且恶魔契约最高。"""
    t = server.SHIP_PICK_PRIORITY
    assert t['demon_contract'] > t['divine_decree'] > t['kraken_eye'], \
        f'优先级顺序应为 恶魔契约 > 神之宣告 > 克苏鲁之眼，实际 {t}'
    assert t['kraken_eye'] > t['shield_choice']


# ===========================================================================
# ★ D. 待选不许被 magic_temp_data 的整体覆写抹掉
# ===========================================================================
def test_pending_survives_magic_temp_data_wipe(room):
    """★ 待选状态必须独立于 `magic_temp_data`。

    `magic_temp_data` 有 8 处被整体覆写成 `{}`；待选放在里面的话，
    等待玩家点船期间只要打出别的会结算的牌，待选就被静默抹掉。
    """
    server._request_ship_pick(room, P1, 'demon_contract', 'm')
    room.magic_temp_data = {}          # 模拟别的卡结算时的整体覆写
    assert server._top_ship_pick(room, P1) is not None, \
        '待选不该被 magic_temp_data 的整体覆写清掉'


def test_pending_survives_renwang_shield_overwrite(room):
    """★ 具体场景：待选期间打出仁王之盾（它自己会 `magic_temp_data = {...}`）。"""
    server._request_ship_pick(room, P1, 'demon_contract', 'm')
    room.magic_temp_data = {'type': 'shield_choice', 'caster': P1, 'ships': []}
    r = server.handle_confirm_sacrifice({
        'room_id': room.id, 'player_id': P1, 'position': {'x': 1, 'y': 1}})
    assert r['status'] == 'success', f'待选应仍在，实际: {r.get("message")}'


# ===========================================================================
# ★ E. 低优先级选船卡被挡住时：明确提示，不静默失败
# ===========================================================================
def test_low_priority_card_blocked_with_message(room):
    """★ 恶魔契约待选中 → 打克苏鲁之眼应被拒绝，且给出明确文案。"""
    server._request_ship_pick(room, P1, 'demon_contract', 'm')
    reason = server._ship_pick_blocked_reason(room, P1, '克苏鲁之眼')
    assert reason, '应返回拒绝文案（不能静默失败）'
    assert '恶魔契约' in reason, f'文案应点明是谁挡着，实际 {reason!r}'


def test_high_priority_card_not_blocked(room):
    """反向：没有更高优先级的待选时，不该拦。"""
    assert server._ship_pick_blocked_reason(room, P1, '克苏鲁之眼') == ''


def test_card_without_ship_pick_never_blocked(room):
    """非选船类卡（如轰炸）任何时候都不该被这道闸门拦。"""
    server._request_ship_pick(room, P1, 'demon_contract', 'm')
    assert server._ship_pick_blocked_reason(room, P1, '轰炸') == ''


# ===========================================================================
# F. 反向守卫：单效果（无冲突）流程与现在完全一致
# ===========================================================================
def test_single_demon_contract_flow_unchanged(room):
    """单个恶魔契约待选：点船 → 正常牺牲（既有行为不许坏）。"""
    server._request_ship_pick(room, P1, 'demon_contract', 'm')
    before = room.players[P1].remaining_ships
    r = server.handle_confirm_sacrifice({
        'room_id': room.id, 'player_id': P1, 'position': {'x': 0, 'y': 0}})
    assert r['status'] == 'success'
    assert room.players[P1].remaining_ships == before - 1, '应真的牺牲掉一艘'


def test_kraken_eye_reveals_without_destroying(room):
    """克苏鲁之眼的选船只暴露位置，**不摧毁**船（既有行为）。"""
    server._request_ship_pick(room, P2, 'kraken_eye', 'm')
    before = room.players[P2].remaining_ships
    r = server.handle_confirm_sacrifice({
        'room_id': room.id, 'player_id': P2, 'position': {'x': 0, 'y': 5}})
    assert r['status'] == 'success'
    assert room.players[P2].remaining_ships == before, '暴露不该摧毁船'


def test_ai_room_still_auto_picks(monkeypatch):
    """AI 房间：AI 不参与交互，直接代选（既有行为）。"""
    room = make_room()
    room.is_ai_room = True
    ai_id = 'ai-' + room.id
    room.players[ai_id] = Player(
        name='AI', ships=[ship((3, 3))], attacks=[], remaining_ships=1,
        sid='sid-ai', user_id=None)
    try:
        picked = server._request_ship_pick(room, ai_id, 'demon_contract', 'm')
        assert picked is not None, 'AI 应直接返回代选的船'
    finally:
        room_manager.rooms.pop(room.id, None)


def test_no_pending_returns_error(room):
    """没有任何待选时点船 → 既有错误文案（不许变成静默成功）。"""
    r = server.handle_confirm_sacrifice({
        'room_id': room.id, 'player_id': P1, 'position': {'x': 0, 'y': 0}})
    assert r['status'] == 'error'


def test_dead_ship_still_rejected(room):
    """★ 反向守卫：点自己**沉船**的格子仍然要被拒（不许拿沉船抵账）。"""
    room.players[P1].ships[0].hits = list(room.players[P1].ships[0].positions)
    server._request_ship_pick(room, P1, 'demon_contract', 'm')
    r = server.handle_confirm_sacrifice({
        'room_id': room.id, 'player_id': P1, 'position': {'x': 0, 'y': 0}})
    assert r['status'] == 'error', '沉船不能用来抵账'


# ===========================================================================
# G. 仁王之盾走 _register_simple_ship_pick：静默登记、去重、不发事件
# ===========================================================================
def test_renwang_registers_silent_shield_choice_pick(room, events):
    """★ 仁王之盾打出后必须在优先队列里登记一条 shield_choice，
    且这条是 **silent** 的（不发 sacrifice_request，前端走自己的多选 UI）。"""
    events.clear()
    res = server.apply_magic_effect(room, P1, card('仁王之盾'), {})
    assert res.success is True

    picks = [p for p in (getattr(room, 'pending_ship_picks', None) or [])
             if p.get('player') == P1 and p.get('reason') == 'shield_choice']
    assert len(picks) == 1, '仁王之盾应登记一条 shield_choice 待办'
    assert picks[0].get('silent') is True, 'shield_choice 必须是静默项（前端自有点选 UI）'
    # 静默项不该弹 sacrifice_request
    assert not requests_for(events, 'sid-p1'), '静默项不该发 sacrifice_request'


def test_renwang_shield_choice_is_deduplicated(room):
    """★ 同一玩家连打两次仁王之盾，队列里只留一条 shield_choice（去重）。"""
    server.apply_magic_effect(room, P1, card('仁王之盾'), {})
    server.apply_magic_effect(room, P1, card('仁王之盾'), {})
    picks = [p for p in (getattr(room, 'pending_ship_picks', None) or [])
             if p.get('player') == P1 and p.get('reason') == 'shield_choice']
    assert len(picks) == 1, '同玩家同 reason 不应重复登记'


def test_register_simple_ship_pick_dedups_across_players(room):
    """同 reason 但不同玩家可以各排一条；同一玩家重复登记只留一条。"""
    server._register_simple_ship_pick(room, P1, 'shield_choice', 'm')
    server._register_simple_ship_pick(room, P2, 'shield_choice', 'm')
    server._register_simple_ship_pick(room, P1, 'shield_choice', 'm')  # 重复
    p1 = [p for p in room.pending_ship_picks
          if p.get('player') == P1 and p.get('reason') == 'shield_choice']
    p2 = [p for p in room.pending_ship_picks
          if p.get('player') == P2 and p.get('reason') == 'shield_choice']
    assert len(p1) == 1
    assert len(p2) == 1


# ===========================================================================
# H. 静默项不出现在重连快照的 pending_sacrifice 里
# ===========================================================================
def test_silent_pick_is_hidden_from_reconnect_snapshot(room):
    """★ shield_choice 是静默项：重连快照里 pending_sacrifice 必须为 None。

    否则前端会以为有"点一艘船"的待办，弹一个永远点不掉的牺牲提示。
    """
    server._register_simple_ship_pick(room, P1, 'shield_choice', 'm')
    snap = server._build_room_sync(room, P1)
    assert snap['pending_sacrifice'] is None, '静默项不该出现在重连快照'
    assert snap['pending_sacrifice_ships'] == []


def test_non_silent_pick_appears_in_reconnect_snapshot(room):
    """反向：非静默项（恶魔契约）必须出现在重连快照里。"""
    server._request_ship_pick(room, P1, 'demon_contract', 'm')
    snap = server._build_room_sync(room, P1)
    assert snap['pending_sacrifice'] is not None
    assert snap['pending_sacrifice']['reason'] == 'demon_contract'


# ===========================================================================
# I. _clear_ship_picks 按玩家精确清理
# ===========================================================================
def test_clear_ship_picks_for_one_player_leaves_other_intact(room):
    """★ 只清 P1 的待选，P2 的不受影响。"""
    server._request_ship_pick(room, P1, 'demon_contract', 'm1')
    server._request_ship_pick(room, P2, 'kraken_eye', 'm2')
    server._clear_ship_picks(room, P1)
    assert server._top_ship_pick(room, P1) is None
    assert server._top_ship_pick(room, P2) is not None


def test_clear_ship_picks_all_when_player_id_none(room):
    """不传 player_id 时清空全部。"""
    server._request_ship_pick(room, P1, 'demon_contract', 'm1')
    server._request_ship_pick(room, P2, 'kraken_eye', 'm2')
    server._clear_ship_picks(room)
    assert server._top_ship_pick(room, P1) is None
    assert server._top_ship_pick(room, P2) is None


# ===========================================================================
# J. _consume_ship_pick 的 reason 校验：不匹配就不消费
# ===========================================================================
def test_consume_with_mismatched_reason_does_not_remove(room):
    """★ 栈顶是 demon_contract 时，用 shield_choice 去消费必须失败且不动队列。

    这是仁王之盾确认分支的安全栏：高优先级待选还在时，不能把 shield_choice
    那条也误吃掉（否则 shield_choice 的确认会"假装成功"但队列状态错乱）。
    """
    server._request_ship_pick(room, P1, 'demon_contract', '高')
    server._register_simple_ship_pick(room, P1, 'shield_choice', '低')
    before = len(room.pending_ship_picks)
    ok = server._consume_ship_pick(room, P1, 'shield_choice')
    assert ok is False, 'reason 不匹配必须返回 False'
    assert len(room.pending_ship_picks) == before, '不匹配时一条都不该少'
    # 栈顶仍然是 demon_contract
    assert server._top_ship_pick(room, P1)['reason'] == 'demon_contract'


def test_consume_matching_reason_removes_only_top(room):
    """匹配 reason 时只消费栈顶那一条，其余不动。"""
    server._register_simple_ship_pick(room, P1, 'shield_choice', '低')
    server._request_ship_pick(room, P1, 'demon_contract', '高')
    # 栈顶是 demon_contract（优先级高）
    ok = server._consume_ship_pick(room, P1, 'demon_contract')
    assert ok is True
    remaining = [p for p in room.pending_ship_picks if p.get('player') == P1]
    assert len(remaining) == 1
    assert remaining[0]['reason'] == 'shield_choice'
