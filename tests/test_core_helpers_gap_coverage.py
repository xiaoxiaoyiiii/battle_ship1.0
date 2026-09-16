# -*- coding: utf-8 -*-
"""核心辅助函数的覆盖缺口补齐（2026-09-17 自动化缺口分析）。

识别出的、此前没有任何直接单测覆盖的高风险辅助函数：

  ① _identity_check          —— 全量 handler 的权限校验底座（安全关键）
  ② _bury_choice_target      —— 明智埋葬的下标解析（含 bool 陷阱、扁平/来源内双下标）
  ③ _pick_cell_from_target   —— 目标格子提取（兼容两种前端形态）
  ④ find_safe_position       —— AI/卡牌找空位的共享工具，棋盘打满时返回 None
  ⑤ _discard_excluded_ships  —— 神威除外在棋盘重摆时的清理（None 清全部 / 指定玩家）
  ⑥ _reveal_cells_to         —— 疗愈原地复活显形（新增函数，仅被间接覆盖）

这些函数要么是权限/解析类的安全关键路径，要么是被多条业务链路复用的共享工具，
一旦回归会波及大量 handler。此前它们只在端到端流程里被顺带跑到，边界条件
（非法来源、bool 下标、棋盘打满、玩家不存在等）没有被显式断言。
"""
import pytest

import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'


# ---------------------------------------------------------------------------
# 通用夹具
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def events(monkeypatch):
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append({'event': event, 'data': data, 'to': to, 'room': room})

    monkeypatch.setattr(server, 'emit', fake_emit)
    yield captured
    captured.clear()


@pytest.fixture
def room():
    r = GameRoom('core-helpers-gap')
    r.players[P1] = Player(
        name='p1',
        ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(6)],
        attacks=[], remaining_ships=6, sid='sid-p1', user_id='u1')
    r.players[P2] = Player(
        name='p2',
        ships=[PlayerShip(positions=[Position(i, 5)], hits=[]) for i in range(6)],
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


def card(name):
    return MagicCard(name)


# ===========================================================================
# ① _identity_check —— 权限校验底座
# ===========================================================================
def test_identity_check_rejects_none_room():
    """房间对象为空时绝不能放行（防御性）。"""
    assert server._identity_check(None, P1, 'u1', 'sid-p1') is False


def test_identity_check_rejects_unknown_player(room):
    """声称的 player_id 不在房间里 → 拒绝。"""
    assert server._identity_check(room, 'intruder', 'u1', 'sid-p1') is False


def test_identity_check_accepts_matching_session_user_id(room):
    """登录态：声称的 player_id 等于会话 user_id 即放行（容忍重连后 sid 变化）。

    真实约定：自定义房/人机房的房间 key 就是登录用户的 user_id，因此
    claimed_player_id == server_pid 即代表「本人会话」。"""
    assert server._identity_check(room, P1, server_pid=P1, sid='totally-different-sid') is True


def test_identity_check_accepts_matching_socket_sid(room):
    """无登录态（匹配房）：该座位登记的连接 == 当前连接即放行。"""
    assert server._identity_check(room, P1, server_pid=None, sid='sid-p1') is True


def test_identity_check_rejects_when_neither_matches(room):
    """既不是本人会话、也不是本人连接 → 拒绝（防伪造他人 player_id 操作）。"""
    assert server._identity_check(room, P1, server_pid='u2', sid='sid-p2') is False
    assert server._identity_check(room, P1, server_pid=None, sid='sid-p2') is False
    assert server._identity_check(room, P1, server_pid='u2', sid=None) is False


def test_identity_check_server_pid_takes_precedence_over_sid(room):
    """两个身份都给时：会话 user_id 命中就放行，不再要求 sid 也对。"""
    assert server._identity_check(room, P1, server_pid=P1, sid='sid-p2') is True


# ===========================================================================
# ② _bury_choice_target —— 明智埋葬下标解析
# ===========================================================================
def test_bury_target_invalid_source(room):
    """来源只能是 deck / opponent_hand，其它一律拒绝。

    注意 source=None 不算非法——函数会把它兜底成 'deck'（向后兼容旧前端）。"""
    room.magic_temp_data = {'candidates': []}
    for bad in ('hand', 'discard', '', 0):
        resolved, err = server._bury_choice_target(room, {'source': bad, 'source_index': 0})
        assert resolved is None and err, f'source={bad!r} 应被拒绝'


def test_bury_target_default_source_is_deck(room):
    """不传 source 时按牌堆处理（向后兼容旧前端）。"""
    room.magic_temp_data = {'candidates': [
        {'source': 'deck', 'index': 0, 'name': '轰炸'}]}
    resolved, err = server._bury_choice_target(room, {'source_index': 0})
    assert err is None
    source, index, expected = resolved
    assert (source, index) == ('deck', 0)


def test_bury_target_rejects_bool_index(room):
    """bool 是 int 的子类，True/False 绝不能当下标（否则会埋到第 0/1 张）。"""
    room.magic_temp_data = {'candidates': []}
    for bad in (True, False):
        resolved, err = server._bury_choice_target(room, {'source': 'deck', 'source_index': bad})
        assert resolved is None and err, f'bool 下标 {bad!r} 应被拒绝'


def test_bury_target_rejects_negative_and_non_int_index(room):
    room.magic_temp_data = {'candidates': []}
    for bad in (-1, -5, '0', [], {}):
        resolved, err = server._bury_choice_target(room, {'source': 'deck', 'source_index': bad})
        assert resolved is None and err, f'下标 {bad!r} 应被拒绝'


def test_bury_target_source_index_resolves_expected_name(room):
    """带 source_index 时，从候选表里反查卡名（用于牌堆被改动后按名找回）。"""
    room.magic_temp_data = {'candidates': [
        {'source': 'deck', 'index': 0, 'name': '轰炸'},
        {'source': 'opponent_hand', 'index': 0, 'name': '冻结'},
    ]}
    resolved, err = server._bury_choice_target(
        room, {'source': 'opponent_hand', 'source_index': 0})
    assert err is None
    source, index, expected = resolved
    assert (source, index, expected) == ('opponent_hand', 0, '冻结')


def test_bury_target_flat_index_fallback(room):
    """只传扁平下标（无 source_index）：候选来源一致时用候选的 index。"""
    room.magic_temp_data = {'candidates': [
        {'source': 'deck', 'index': 0, 'name': '轰炸'},
        {'source': 'opponent_hand', 'index': 0, 'name': '冻结'},
    ]}
    resolved, err = server._bury_choice_target(
        room, {'source': 'opponent_hand', 'card_index': 1})
    assert err is None
    source, index, expected = resolved
    assert (source, index, expected) == ('opponent_hand', 0, '冻结')


def test_bury_target_flat_index_source_mismatch_falls_back(room):
    """扁平下标对应的候选来源与声明不一致 → 退回「来源列表内下标」约定。"""
    room.magic_temp_data = {'candidates': [
        {'source': 'deck', 'index': 0, 'name': '轰炸'},
        {'source': 'opponent_hand', 'index': 0, 'name': '冻结'},
    ]}
    # 声明 opponent_hand 但扁平下标 0 指向 deck → 退回用 card_index 当来源内下标
    resolved, err = server._bury_choice_target(
        room, {'source': 'opponent_hand', 'card_index': 0})
    assert err is None
    source, index, expected = resolved
    assert source == 'opponent_hand'
    assert index == 0          # 退回约定：card_index 即来源内下标
    assert expected is None    # 候选表里没有 (opponent_hand, 0) 之外的匹配 → None


def test_bury_target_legacy_no_candidates_uses_card_index(room):
    """没有候选表（旧数据/直调）：card_index 直接当作来源列表内下标。"""
    room.magic_temp_data = {}   # 无 candidates
    resolved, err = server._bury_choice_target(
        room, {'source': 'deck', 'card_index': 2})
    assert err is None
    source, index, expected = resolved
    assert (source, index) == ('deck', 2)
    assert expected is None


def test_bury_target_no_index_at_all_rejected(room):
    """既没有 source_index 也没有 card_index → 拒绝。"""
    room.magic_temp_data = {'candidates': []}
    resolved, err = server._bury_choice_target(room, {'source': 'deck'})
    assert resolved is None and err


# ===========================================================================
# ③ _pick_cell_from_target —— 目标格子提取
# ===========================================================================
def test_pick_cell_from_target_area():
    """target_area 形态：取 x1/y1。"""
    assert server._pick_cell_from_target({'target_area': {'x1': 3, 'y1': 4}}) == (3, 4)


def test_pick_cell_from_xy():
    """直接 {x, y} 形态。"""
    assert server._pick_cell_from_target({'x': 1, 'y': 2}) == (1, 2)


def test_pick_cell_string_coerced():
    """坐标是字符串时也能取到（前端可能传字符串数字）。"""
    assert server._pick_cell_from_target({'x': '1', 'y': '2'}) == (1, 2)


def test_pick_cell_none_for_non_dict():
    assert server._pick_cell_from_target(None) is None
    assert server._pick_cell_from_target([1, 2]) is None
    assert server._pick_cell_from_target('x') is None


def test_pick_cell_none_for_missing_keys():
    """缺字段或类型错误时返回 None，不抛异常。"""
    assert server._pick_cell_from_target({}) is None
    assert server._pick_cell_from_target({'x': 1}) is None
    assert server._pick_cell_from_target({'target_area': {}}) is None
    assert server._pick_cell_from_target({'target_area': {'x1': 'a', 'y1': 1}}) is None


# ===========================================================================
# ④ find_safe_position —— 找安全空位
# ===========================================================================
def test_find_safe_position_returns_first_untouched(room):
    """按行优先顺序返回第一个没被对手打过的格子。"""
    # 对手打过 (0,0) 和 (1,0)，(2,0) 应是第一个安全格
    room.players[P2].attacks = [Position(0, 0), Position(1, 0)]
    assert server.find_safe_position(room, P1) == {'x': 2, 'y': 0}


def test_find_safe_position_returns_none_when_board_full(room):
    """★ 棋盘 36 格全被打过时返回 None（调用方必须判空，否则 .get 会 AttributeError）。"""
    room.players[P2].attacks = [Position(x, y) for y in range(6) for x in range(6)]
    assert server.find_safe_position(room, P1) is None


def test_find_safe_position_checks_opponent_attacks_only(room):
    """只看【对手】的攻击记录，自己棋盘上的船不影响安全格判定。"""
    room.players[P1].attacks = [Position(0, 0)]   # 自己打过的不算
    room.players[P2].attacks = []
    assert server.find_safe_position(room, P1) == {'x': 0, 'y': 0}


# ===========================================================================
# ⑤ _discard_excluded_ships —— 神威除外清理
# ===========================================================================
def test_discard_excluded_noop_when_empty(room):
    """没有除外记录时调用不报错、不改 game_effects。"""
    assert 'excluded_ships' not in room.game_effects
    server._discard_excluded_ships(room)
    assert 'excluded_ships' not in room.game_effects


def test_discard_excluded_all_when_player_id_none(room):
    """棋盘双方一起重摆（败者食尘）：player_id=None 清空全部除外记录。"""
    room.game_effects['excluded_ships'] = [
        {'player': P1, 'ships': [], 'return_turn': 5},
        {'player': P2, 'ships': [], 'return_turn': 5},
    ]
    server._discard_excluded_ships(room, player_id=None)
    assert 'excluded_ships' not in room.game_effects


def test_discard_excluded_specific_player_only(room):
    """只重摆某一方棋盘：只移除该玩家的除外记录，保留对方。"""
    p2_entry = {'player': P2, 'ships': [], 'return_turn': 5}
    room.game_effects['excluded_ships'] = [
        {'player': P1, 'ships': [], 'return_turn': 5},
        p2_entry,
    ]
    server._discard_excluded_ships(room, player_id=P1)
    assert room.game_effects['excluded_ships'] == [p2_entry]


def test_discard_excluded_last_entry_pops_key(room):
    """移除最后一条后，excluded_ships 键也要一起清掉（避免空列表残留）。"""
    room.game_effects['excluded_ships'] = [
        {'player': P1, 'ships': [], 'return_turn': 5}]
    server._discard_excluded_ships(room, player_id=P1)
    assert 'excluded_ships' not in room.game_effects


# ===========================================================================
# ⑥ _reveal_cells_to —— 疗愈原地复活显形（新增函数）
# ===========================================================================
def test_reveal_cells_noop_for_nonexistent_player(room, events):
    """玩家不存在时静默返回，不抛异常、不 emit。"""
    server._reveal_cells_to(room, 'nobody', [Position(0, 0)], kind='heal')
    assert [e for e in events if e['event'] == 'revealed_positions'] == []


def test_reveal_cells_noop_for_empty_positions(room, events):
    """空位置列表不 emit。"""
    server._reveal_cells_to(room, P2, [], kind='heal')
    assert [e for e in events if e['event'] == 'revealed_positions'] == []


def test_reveal_cells_dedup_revealed_positions(room, events):
    """同一格重复显形不重复写入 revealed_positions（重连快照会膨胀）。"""
    server._reveal_cells_to(room, P2, [Position(1, 1), Position(1, 1)], kind='heal')
    revealed = room.players[P2].revealed_positions
    assert sum(1 for p in revealed if p.x == 1 and p.y == 1) == 1


def test_reveal_cells_emits_with_kind(room, events):
    """kind 字段必须透传给前端（前端据此区分疗愈显形 vs 雷达显形）。"""
    server._reveal_cells_to(room, P2, [Position(3, 3)], kind='heal')
    sent = [e for e in events if e['event'] == 'revealed_positions']
    assert sent, '没有发出 revealed_positions 事件'
    assert sent[-1]['to'] == 'sid-p2'
    assert sent[-1]['data']['kind'] == 'heal'
    assert {'x': 3, 'y': 3} in sent[-1]['data']['positions']


def test_reveal_cells_default_kind_is_none(room, events):
    """不传 kind 时为 None（旧的通用显形，前端按缺省处理）。"""
    server._reveal_cells_to(room, P2, [Position(0, 0)])
    sent = [e for e in events if e['event'] == 'revealed_positions']
    assert sent[-1]['data']['kind'] is None
