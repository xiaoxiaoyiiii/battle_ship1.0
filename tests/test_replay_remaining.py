# -*- coding: utf-8 -*-
"""回放审计批（2026-09-24）· **「剩余战舰数」这一项：回放与观战/实战必须是同一个数**。

## 为什么单独为它写一份守卫

回放屏上「剩余战舰 N」原来是从**船位时间线数格子**出来的（`replayAliveShips`），
而同一个 N 在实战界面（`attack_result` 的 `attacker_remaining_ships`）、观战
（`_spectate_side_payload`）与重连快照里读的都是 `Player.remaining_ships` ——
**同一件事两份实现**（CLAUDE.md 教训 #1）。

实测（审计批，真对局 seed 4242）：AI 的 `remaining_ships=1`，而回放数出来是 **3**
（船格 `alive` 用的是 `len(hits) < len(positions)`，与那份计数**不是同一份记账**）。
⇒ 同一个座位，回放屏写 3、其它屏写 1。

本批的收敛口径：**回放记 `Player.remaining_ships`（权威计数）**，前端读它。
船格只表达"船在哪、沉没没沉"。**两者对不上时错在游戏侧的记账**，回放不替它二次推导。
"""

import ast
import io
import re

import replay
import server
from server import GameRoom, Player, PlayerShip, Position, room_manager

P1, P2 = 'rembuf-p1', 'rembuf-p2'      # ⚠️ 与座位代号 `p1`/`p2` 故意取不同的串（教训 #20）
SIDE1, SIDE2 = 'p1', 'p2'


def _ships(shape):
    return [PlayerShip(positions=[Position(x, y) for (x, y) in cells], hits=[])
            for cells in shape]


def _room(p1_shape, p2_shape):
    room = GameRoom('rembuf')
    room.id = 'rembuf-%d' % id(room)
    room.players[P1] = Player(name='甲', ships=_ships(p1_shape), attacks=[],
                              remaining_ships=len(p1_shape), sid=P1)
    room.players[P2] = Player(name='乙', ships=_ships(p2_shape), attacks=[],
                              remaining_ships=len(p2_shape), sid=P2)
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
    room.attacks_remaining = len(p1_shape)
    room.round = 3
    room.game_logs = []
    room.game_effects = {}
    room.magic_temp_data = {}
    room_manager.rooms[room.id] = room
    return room


def _fold_remaining(room):
    """前端 `replayComputeFrame` 叠 `payload.remaining` 的那一段（逐字等价）。"""
    out = {SIDE1: None, SIDE2: None}
    for row in replay.build(room)['remaining']:
        for side in (SIDE1, SIDE2):
            if isinstance(row.get(side), int):
                out[side] = row[side]
    return out


def _cells_alive(room, side):
    """旧口径（**从船格数**）—— 就是本批改掉的那一份。"""
    cells = []
    for row in replay.build(room)['ships']:
        if isinstance(row.get(side), list):
            cells = row[side]
    seen, n = set(), 0
    for c in cells:
        key = (c['x'], c['y'])
        if key in seen:
            continue
        seen.add(key)
        if c.get('alive') is True or c.get('sunk') is not True:
            n += 1
    return n


# ---------------------------------------------------------------------------
# ① 记录器：`remaining` 时间线记的必须是**权威计数**（不是船格数）
# ---------------------------------------------------------------------------
def test_remaining_timeline_is_a_sparse_incremental_timeline():
    """★ `remaining` 与其它三条时间线同一种"稀疏 + 增量"：只记变了的座位。"""
    room = _room([[(0, 4)], [(5, 4)]], [[(1, 1)], [(4, 4)]])
    try:
        replay.note(room, {'type': 'system', 'text': '开局', 'detail': {}})
        rows = replay.build(room)['remaining']
        assert rows, '剩余战舰数时间线是空的'
        for row in rows:
            assert set(row) - {'step'}, '空行没意义'
            assert set(row) <= {'step', 'p1', 'p2'}, sorted(row)
            for side in (SIDE1, SIDE2):
                if side in row:
                    assert isinstance(row[side], int), row
        assert rows[0][SIDE1] == 2 and rows[0][SIDE2] == 2, rows[0]
        before = len(rows)
        replay.note(room, {'type': 'system', 'text': '什么都没变', 'detail': {}})
        assert len(replay.build(room)['remaining']) == before, '船数没变却又记了一条'
    finally:
        room_manager.rooms.pop(room.id, None)


def test_remaining_timeline_reads_the_game_counter_not_the_ship_cells():
    """★★ 记录的**就是** `Player.remaining_ships` —— 权威计数，不是从船格数出来的。

    判据必须是"两者**不等**时看谁赢"：只动权威计数（船格不动），时间线必须跟着动。
    改坏法（= 本批之前的行为）：把 `_remaining_snapshot` 写成按 `_ship_cells` 数格子
    ⇒ 下面第二条断言会红（它会停在 1）。
    """
    room = _room([[(0, 4)], [(5, 4)]], [[(1, 1)], [(4, 4)]])
    try:
        replay.note(room, {'type': 'system', 'text': '开局', 'detail': {}})
        assert _fold_remaining(room)[SIDE2] == 2
        # 只动**权威计数**，一个船格都不动 ⇒ 时间线必须跟着变成 1
        room.players[P2].remaining_ships = 1
        replay.refresh_ships(room)
        folded = _fold_remaining(room)
        assert folded[SIDE2] == 1, (
            '权威计数变了（1），时间线必须跟着变 —— 记成船格数会停在 2：%s' % folded)
        assert room.players[P2].remaining_ships == 1
        # 对照：同一帧的船格数照旧是 2（船格口径**没有**被这条时间线影响）
        assert _cells_alive(room, SIDE2) == 2, '船格口径不该被改动'
    finally:
        room_manager.rooms.pop(room.id, None)


def test_remaining_timeline_follows_a_real_sink():
    """★ 走真产品路径（`_apply_ship_sunk_effects`：实战击沉共用的一份收尾）逐帧对齐。"""
    room = _room([[(0, 4)], [(5, 4)], [(3, 3)]], [[(1, 1)], [(4, 4)], [(2, 2)]])
    try:
        replay.note(room, {'type': 'system', 'text': '开局', 'detail': {}})
        victim = room.players[P2].ships[0]
        server._apply_ship_sunk_effects(room, room.id, P1, P2, victim, 1, 1)
        replay.note(room, {'type': 'attack', 'text': '炮击',
                           'detail': {'attacker': P1, 'target': {'x': 1, 'y': 1}}})
        folded = _fold_remaining(room)
        assert folded[SIDE2] == room.players[P2].remaining_ships == 2, (
            '时间线里 p2 的剩余战舰数 = %s，游戏里 = %s'
            % (folded[SIDE2], room.players[P2].remaining_ships))
        assert folded[SIDE1] == 3, folded
    finally:
        room_manager.rooms.pop(room.id, None)


# ---------------------------------------------------------------------------
# ② 前端源码级：`replayAliveShips` 必须读权威计数
# ---------------------------------------------------------------------------
def _function_body(src, name):
    start = src.index('function ' + name + '(')
    depth = 0
    for i in range(start, len(src)):
        if src[i] == '{':
            depth += 1
        elif src[i] == '}':
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise AssertionError('找不到 %s 的函数体' % name)


def _strip_comments(text):
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return re.sub(r'//[^\n]*', '', text)


def test_frontend_ship_counter_reads_the_authoritative_timeline():
    """★★ `replayAliveShips` 的第一数据源必须是 `frame.alive[side]`（权威计数）。"""
    src = io.open('static/game.js', encoding='utf-8').read()
    body = _strip_comments(_function_body(src, 'replayAliveShips'))
    assert 'frame.alive' in body, (
        '剩余战舰数必须读权威计数（`frame.alive`，来自 `payload.remaining`）：%s' % body[:400])
    assert 'isFinite' in body, '权威计数必须判"拿得到才用"（缺了才退回数船格）'
    head = body.split('var ships')[0]
    assert 'return' in head, '必须**先**用权威计数返回（退回数船格只算兜底）'


def test_compute_frame_folds_the_remaining_timeline():
    """★★ 帧解算必须把 `payload.remaining` 叠进 `frame.alive`（否则前端拿不到权威值）。"""
    src = io.open('static/game.js', encoding='utf-8').read()
    body = _strip_comments(_function_body(src, 'replayComputeFrame'))
    assert 'payload.remaining' in body, '帧解算没有读 `payload.remaining`'
    assert 'frame.alive' in body, '帧解算没有写 `frame.alive`'
    # 老 blob 不许被当成"0 艘"（`null` 才走退回路径）
    assert 'typeof rrow.p1' in body and 'typeof rrow.p2' in body, \
        '只许接受数字（老 blob 没有这个键 ⇒ 保持 null ⇒ 退回数船格）'


# ---------------------------------------------------------------------------
# ③ ★ 反向腿：本批**没有**去改船格口径（改了会动玩家看到的棋盘）
# ---------------------------------------------------------------------------
def test_ship_cells_liveness_rule_is_unchanged_by_this_batch():
    """★ 船格的 `alive` 仍旧只按 `len(hits) < len(positions)` —— 本批一个字没改它。

    ⚠️ 这条是**故意钉现状**的：把 `_is_alive` 换成游戏那份 `_is_ship_alive`
    （多一条 `ship in sunken_ships`）会改掉**玩家在回放棋盘上看到的船**，
    属于需要作者拍板的产品取舍（见 `docs/REPLAY_2026_09_23.md` §I 的"停下未修"清单）。
    """
    room = _room([[(0, 4)]], [[(1, 1)]])
    try:
        ship = room.players[P2].ships[0]
        server._mark_ship_sunken(room.players[P2], ship)     # 登记沉没，但 hits 还是空
        cells = replay._ship_cells(room, P2, room.players[P2])
        assert cells == [{'x': 1, 'y': 1, 'alive': True, 'src': 'ships'}], (
            '船格口径变了（本批不该动它）：%s' % cells)
        # 而游戏那份存活判据认为它已经死了 —— 两份记账**本来就可能不等**，
        # 这正是"剩余战舰数必须读权威计数"的理由。
        assert server._is_ship_alive(room.players[P2], ship) is False
    finally:
        room_manager.rooms.pop(room.id, None)


# ---------------------------------------------------------------------------
# ④ ★★ 全项目"写 remaining_ships"的点：穷举登记（与 `test_attack_records` 同一套路）
# ---------------------------------------------------------------------------
#: `(函数名, 操作)` —— 每一处写 `remaining_ships` 的地方都必须在这里交代。
#: 判据：新增一处却没登记 ⇒ 红（防止"新增一条改船数的路径"时忘了回放这条时间线）。
WRITE_SITES = {
    ('__init__', 'assign'),                              # Player.__init__(remaining_ships)
    ('handle_place_ships', 'assign'),
    ('_ai_place_ships', 'assign'),
    ('_ai_place_ships', 'augassign'),
    ('handle_confirm_reinforcement', 'augassign'),
    ('_revive_sunken_ships', 'augassign'),
    ('_restore_due_shenwei', 'augassign'),
    ('_do_demon_contract_sacrifice', 'assign'),
    ('_apply_ship_sunk_effects', 'augassign'),
    ('_recall_lanyu_ships', 'augassign'),
    ('apply_magic_effect', 'assign'),
    ('apply_magic_effect', 'augassign'),
    ('confirm_magic_target', 'assign'),
    ('test_auto_attack', 'augassign'),
    ('test_set_player_ships', 'assign'),
    ('test_set_player_ships', 'augassign'),
    ('test_reset_game', 'assign'),
    ('test_set_opponent_ships', 'assign'),
    ('test_set_opponent_ships', 'augassign'),
}


def _scan_remaining_writes():
    """`server.py` 里所有写 `<某物>.remaining_ships` 的 `(最外层函数名, 操作)`。"""
    tree = ast.parse(io.open('server.py', encoding='utf-8').read())
    found = set()

    def walk_func(name, node):
        # ⚠️ `ast.walk` 会**连嵌套的函数/类一起走** —— 外层那次会把类体里
        #    `__init__` 的赋值算到类名头上（实测抓到过 `('Player', 'assign')` 这个
        #    不存在的"点"）。所以这里用 `iter_child_nodes` 逐层下钻，自己控制归属。
        for sub in ast.iter_child_nodes(node):
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                walk_func(sub.name, sub)
                continue
            for inner in ast.walk(sub):
                targets = []
                if isinstance(inner, ast.Assign):
                    targets = inner.targets
                    op = 'assign'
                elif isinstance(inner, ast.AugAssign):
                    targets = [inner.target]
                    op = 'augassign'
                elif isinstance(inner, ast.AnnAssign) and inner.value is not None:
                    # ⚠️ 只有**带值**的注解赋值才算写（`remaining_ships: int` 纯声明不算）
                    targets = [inner.target]
                    op = 'assign'
                else:
                    continue
                for tgt in targets:
                    if isinstance(tgt, ast.Attribute) and tgt.attr == 'remaining_ships':
                        found.add((name, op))

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            walk_func(node.name, node)
    return found


def test_every_write_to_remaining_ships_is_registered():
    """★★ 穷举左腿：`server.py` 里每一处写 `remaining_ships` 都必须在 `WRITE_SITES` 里。"""
    found = _scan_remaining_writes()
    new = sorted(found - WRITE_SITES)
    assert not new, (
        '这些"改剩余战舰数"的点没有交代（新增改船数的路径 ⇒ 回放的 remaining '
        '时间线要跟着确认）：%s' % new)
    assert WRITE_SITES - found == set(), (
        '登记表里有已经不存在的点（表不许烂在原地，与 `test_attack_records` 同一条腿）：%s'
        % sorted(WRITE_SITES - found))
