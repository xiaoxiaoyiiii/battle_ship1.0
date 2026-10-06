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




# ===========================================================================
# F. 反向守卫：单效果（无冲突）流程与现在完全一致
# ===========================================================================


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


# ===========================================================================
# ★ I. 端到端复现：用户报的"仁王之盾 + 第二次点击弹当前没有待牺牲的船"
# ===========================================================================
