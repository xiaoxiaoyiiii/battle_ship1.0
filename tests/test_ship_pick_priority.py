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
# ★ G. 仁王之盾场景：handle_confirm_sacrifice 不该把护盾选择走成牺牲
# ===========================================================================
# 作者 2026-09-21 报的恶性 bug：
#   「当任意需要选船的效果发动的时候 比如仁王之盾 克苏鲁之眼等等
#     在自己棋盘上选船的时候 居然会判定为恶魔契约的牺牲！
#     但是场上根本没有恶魔契约在生效！尤其是使用仁王之盾
#     第一次的点击直接让自己的船牺牲了 第二次点击弹出了当前没有待牺牲的船」
#
# 根因（逐行核实过）────────────────────────────────────────────────
# `handle_confirm_sacrifice` 只对 `kraken_eye` / `trap_setup` 两个 reason
# 显式分支处理，其它一律 fall-through 到 `_do_demon_contract_sacrifice`：
#
#     if reason == 'kraken_eye':  ...  return
#     if reason == 'trap_setup':  ...  return
#     _do_demon_contract_sacrifice(room, player_id, ship, reason)  ← 这里
#
# 而 `_do_demon_contract_sacrifice` **会移除船 + 标沉 + 扣 remaining_ships**，
# 与 reason 是不是"恶魔契约"完全无关 —— 它只是把 reason 当日志文案用。
#
# 仁王之盾登记的是 `shield_choice`（silent entry，走 confirm_magic_target 的
# 多选）。但如果前端某个分支误把点船 emit 成了 `confirm_sacrifice`（例如上一轮
# 恶魔契约的 onClick 没清干净、与 bindRenwangBoardClick 同时活着），就会走到
# `_do_demon_contract_sacrifice`，把"要保护的船"当场沉掉。
# 第一次点击：消费 shield_choice → 船牺牲；第二次：队列空 → "当前没有待牺牲的战舰"。
#
# 修复方向：handle_confirm_sacrifice 对**不该走牺牲路径**的 reason
# （目前只有 `shield_choice`）一律拒绝并保留队列条目，让玩家走正确的提交入口
# （confirm_magic_target 的 ship_indices）。同时同步修场地魔法被替换时
# 残留的 demon_contract 队列条目（见 test_demon_contract_pending_cleared_when_field_replaced）。
# ===========================================================================
def test_renwang_shield_choice_not_sacrificed_via_confirm_sacrifice(room):
    """★ 仁王之盾（shield_choice）即使误走 confirm_sacrifice 也不该牺牲船。

    场上没有恶魔契约生效（game_effects['demon_contract'] 已 pop 掉）。
    玩家打出仁王之盾 → shield_choice 入队（silent）。
    现在前端某种原因 emit 了 confirm_sacrifice（用户实测报的那一下）：
      · 服务端必须**拒绝**，给出明确指引「请用确认按钮提交仁王之盾的选择」；
      · 队列里的 shield_choice 条目**必须保留**（否则玩家再点确认就报"无待选"）；
      · 船**绝不能被牺牲**（remaining_ships 不变、ships 不变）。
    """
    # 模拟"场上根本没有恶魔契约在生效"
    room.game_effects.pop('demon_contract', None)

    # 玩家打出仁王之盾 → 登记一条 silent 的 shield_choice
    server._register_simple_ship_pick(room, P1, 'shield_choice',
                                      '仁王之盾：请选择要保护的战舰（至多 3 艘）')

    before_ships = len(room.players[P1].ships)
    before_remaining = room.players[P1].remaining_ships
    top_before = server._top_ship_pick(room, P1)
    assert top_before is not None and top_before['reason'] == 'shield_choice'

    # ★ 前端误 emit 了 confirm_sacrifice（这正是用户报的那一下）
    r = server.handle_confirm_sacrifice({
        'room_id': room.id, 'player_id': P1, 'position': {'x': 0, 'y': 0}})

    # 1) 必须拒绝
    assert r['status'] == 'error', (
        f'仁王之盾的护盾选择不该走 confirm_sacrifice 牺牲路径，实际: {r}')
    assert '仁王之盾' in (r.get('message') or '') or '护盾' in (r.get('message') or ''), (
        f'错误文案应指引玩家走确认按钮，实际: {r.get("message")!r}')

    # 2) 队列条目必须仍在（玩家还能继续选船 + 点确认提交）
    top_after = server._top_ship_pick(room, P1)
    assert top_after is not None and top_after['reason'] == 'shield_choice', \
        'shield_choice 条目不该被这次错误调用消费掉'

    # 3) 船绝不能被牺牲
    assert len(room.players[P1].ships) == before_ships, \
        '船不该被牺牲（ships 不变）'
    assert room.players[P1].remaining_ships == before_remaining, \
        '船不该被牺牲（remaining_ships 不变）'


def test_renwang_shield_choice_still_works_via_confirm_magic_target(room):
    """★ 反向守卫：修复后，仁王之盾的正确入口（confirm_magic_target）仍要能用。

    防止把 handle_confirm_sacrifice 改"严"以后顺手把正确的提交路径也堵死。
    """
    room.game_effects.pop('demon_contract', None)
    server._register_simple_ship_pick(room, P1, 'shield_choice',
                                      '仁王之盾：请选择要保护的战舰（至多 3 艘）')

    # 玩家通过 confirm_magic_target 提交选中的 ship_indices（这是仁王之盾的正确入口）
    ship_idx = 0  # P1 的第一艘船，位于 (0, 0)
    r = server.confirm_magic_target({
        'room_id': room.id, 'player_id': P1,
        'temp_data_id': 'shield_choice',
        'target_data': {'ship_indices': [ship_idx]},
    })

    assert r['status'] == 'success', f'仁王之盾正确入口应能用，实际: {r}'
    assert room.players[P1].ships[ship_idx].shield is True, '船应该有护盾了'
    # 队列条目应被正确消费
    assert server._top_ship_pick(room, P1) is None, 'shield_choice 应已消费'


# ===========================================================================
# ★ H. 场地魔法被替换时，残留的 demon_contract 队列条目必须清掉
# ===========================================================================
def test_demon_contract_pending_cleared_when_field_replaced(room):
    """★ 恶魔契约场地被替换后，残留的 demon_contract 队列条目必须清掉。

    复现场景：
      1. 恶魔契约作为场地魔法生效（room.field_magic = 恶魔契约），
         期间 P2 击沉 P1 一艘船 → 触发 P2 牺牲一艘船的待选
         （demon_contract 入队，priority=100）；
      2. 之后某玩家打出新场地魔法（如「伊甸园」）顶替了恶魔契约：
         `_clear_field_magic_effects` 会 pop 掉 `game_effects['demon_contract']`，
         但**不清 pending_ship_picks** → demon_contract 条目残留；
      3. P2 现在打出仁王之盾 → shield_choice 入队（priority=40）；
      4. 任意 confirm_sacrifice 都会取 priority 最高的 demon_contract 那一项
         → P2 的船被错误牺牲（这正是用户报的"场上根本没有恶魔契约在生效
         但船还是被牺牲了"的那条根因）。

    修复：`_clear_field_magic_effects` 在 pop `demon_contract` 时一并撤掉
    `pending_ship_picks` 里所有 reason='demon_contract' 的条目。
    """
    from server import MagicCard
    # 0) 先把恶魔契约作为场地魔法摆上（这样 _place_field_magic 替换时才会
    #    触发 _clear_field_magic_effects —— 旧实现只在 old != None 时才调）
    server._place_field_magic(room, P1, MagicCard('恶魔契约'))
    assert 'demon_contract' in room.game_effects

    # 1) 恶魔契约生效，P2 击沉 P1 一艘船 → P2 收到 demon_contract 待选
    sunken = room.players[P1].ships[0]
    server._mark_ship_sunken(room.players[P1], sunken)
    room.players[P1].remaining_ships -= 1
    server._request_demon_contract_sacrifice(room, P1)   # → 让 P2 牺牲一艘
    top = server._top_ship_pick(room, P2)
    assert top is not None and top['reason'] == 'demon_contract'

    # 2) 顶替恶魔契约场地 → 残留条目应被一并清掉
    server._place_field_magic(room, P1, MagicCard('伊甸园'))

    # game_effects['demon_contract'] 已 pop
    assert 'demon_contract' not in room.game_effects, \
        '场地被顶替后 game_effects[\'demon_contract\'] 应该被清掉'

    # ★ pending_ship_picks 里的 demon_contract 条目也必须清掉
    leftover = [p for p in room.pending_ship_picks
                if isinstance(p, dict) and p.get('reason') == 'demon_contract']
    assert leftover == [], (
        f'场地被顶替后 pending_ship_picks 不该残留 demon_contract 条目，实际: {leftover}')


# ===========================================================================
# ★ I. 端到端复现：用户报的"仁王之盾 + 第二次点击弹当前没有待牺牲的船"
# ===========================================================================
def test_e2e_renwang_after_demon_contract_resolved_then_replaced(room):
    """★ 完整复现用户报的 bug，验证修复后整条链都不再误牺牲船。

    用户场景：
      1. 克苏鲁之眼先发动并完成（这一步会把 onClick 残留在前端棋盘上 ——
         旧实现的 bug 根因：onClick 内部只 clearSacrificeSelection 不解绑自己）
      2. 玩家打出仁王之盾 → shield_choice 入队（silent, priority 40）
      3. 玩家点自己船格（前端残留的 onClick 又被触发 → emit confirm_sacrifice）
      4. 旧实现：服务端走 _do_demon_contract_sacrifice → 船被错误牺牲
      5. 玩家再点一次 → 队列空 → "当前没有待牺牲的战舰"

    修复后：
      · 服务端：reason=shield_choice 不在 _SACRIFICE_REASONS 白名单 → 拒绝并保留条目
      · 前端：onClick 调 selectionCleanup 把自己 removeEventListener 掉，第二次点击不再 emit
      · 队列条目保留 → 玩家还能继续走 confirm_magic_target 完成仁王之盾
    """
    # 1) 克苏鲁之眼发动 + 完成（模拟用户报的"先用了别的选船卡"那一步）
    res = server.apply_magic_effect(room, P1, card('克苏鲁之眼'), {'x': 0, 'y': 0})
    assert res.success is not False, f'克苏鲁之眼应能打出: {res.message}'
    # P2 完成克苏鲁之眼的选船
    r_eye = server.handle_confirm_sacrifice({
        'room_id': room.id, 'player_id': P2, 'position': {'x': 0, 'y': 5}})
    assert r_eye['status'] == 'success', f'克苏鲁之眼选船应成功: {r_eye}'
    # 队列应为空
    assert server._top_ship_pick(room, P1) is None
    assert server._top_ship_pick(room, P2) is None

    # 2) 玩家打出仁王之盾 → shield_choice 入队
    server._register_simple_ship_pick(room, P1, 'shield_choice',
                                      '仁王之盾：请选择要保护的战舰（至多 3 艘）')
    before_ships = len(room.players[P1].ships)
    before_remaining = room.players[P1].remaining_ships

    # 3) ★ 玩家点船格 → 前端残留的 onClick 误 emit confirm_sacrifice
    r1 = server.handle_confirm_sacrifice({
        'room_id': room.id, 'player_id': P1, 'position': {'x': 0, 'y': 0}})

    # 修复后：拒绝、不牺牲、保留条目
    assert r1['status'] == 'error', (
        f'仁王之盾的护盾选择不该走牺牲路径，实际: {r1}')
    assert len(room.players[P1].ships) == before_ships, '船不该被牺牲'
    assert room.players[P1].remaining_ships == before_remaining, 'remaining_ships 不变'
    top = server._top_ship_pick(room, P1)
    assert top is not None and top['reason'] == 'shield_choice', '条目应保留'

    # 4) ★ 第二次点（用户报的"第二次弹当前没有待牺牲的船"那一下）
    #    修复后队列里仍有 shield_choice → 继续拒绝（而不是"没有待选"）
    r2 = server.handle_confirm_sacrifice({
        'room_id': room.id, 'player_id': P1, 'position': {'x': 1, 'y': 1}})
    assert r2['status'] == 'error', f'第二次点击也不该牺牲船: {r2}'
    assert len(room.players[P1].ships) == before_ships, '船不该被牺牲'
    top = server._top_ship_pick(room, P1)
    assert top is not None and top['reason'] == 'shield_choice', '条目应仍在'

    # 5) 玩家走正确入口完成仁王之盾
    r_ok = server.confirm_magic_target({
        'room_id': room.id, 'player_id': P1,
        'temp_data_id': 'shield_choice',
        'target_data': {'ship_indices': [0]},
    })
    assert r_ok['status'] == 'success', f'正确入口应能用: {r_ok}'
    assert room.players[P1].ships[0].shield is True, '船应该有护盾'
    assert server._top_ship_pick(room, P1) is None, 'shield_choice 应已消费'
