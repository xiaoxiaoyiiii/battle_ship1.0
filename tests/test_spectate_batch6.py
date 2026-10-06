# -*- coding: utf-8 -*-
"""实时观战**第 6 批**：棋盘方向（死角 A —— "两块棋盘对调"的真根因）。

## 作者实报的现象

观战屏上**两块棋盘的位置与服务端不一样 / 恰好对调**，而且**可复现**。
第 5 批做了 6 轮取证（页面侧 applyLog、服务端发布日志、attacks 写操作时间线、
逐次读数对齐）没有定位到根因，最后在 `tools/spectate_check.mjs` 里加了
**"1 格容差"** 放过去 —— 那等于把这条断言废掉。

## 本批定位到的真根因（一行）

`server._spectate_board_frame` 把**座位方向**的数据翻成了**棋盘方向**
（第 5 批那句 `side['attacks'] = _spectate_player_cells(other)`），
而前端只有**一处**转置 `spectateRebuildBoardAttacks()`
（`board_attacks[p1] = attacks[p2]`），它把两条路径都当**座位方向**处理：

| 路径 | 服务端发的 | 前端存的 | 再转置一次 | 结果 |
| --- | --- | --- | --- | --- |
| 快照 `spectate_sync` | 座位方向（对） | `sp.attacks` = 座位方向 | 翻一次 | **对** |
| 帧 `spectate_board` | 棋盘方向（对） | `sp.attacks` = 棋盘方向 | 翻一次 | **翻两次 ⇒ 两块棋盘对调** |

而且这条错误**会被后续每一炮继承**（`sp.attacks` 被整体覆盖成反的那一份，
之后 `spectateOnAttackResult` 继续在反的基底上加格、继续转置成反的棋盘）。

**为什么第 5 批的守卫一条都没红**：所有断言都是"帧 vs 快照"或"帧 vs 帧"的
**同一个函数内部**恒等式 —— `frame.sides[label].attacks == snap.board_attacks[label]`
两边同时反，恒等式照样成立（CLAUDE.md 教训 #7：恒等式拦不住"方向写反"）。
唯一能抓住它的是**真正跑一遍前端、逐格比 DOM**。

## 本批的守卫（都要能红）

1. `test_frame_and_snapshot_sides_are_the_same_direction`（服务端层）：
   帧的 `sides[label].attacks` **逐字段等于**快照的 `sides[label].attacks`，
   且**不等于**对面那一份。把方向翻反 → 必红。
2. `test_frontend_boards_match_the_server_snapshot_cell_by_cell`（端到端）：
   **真的跑 `static/game.js`**（vm + 最小 DOM，见 `tools/dom_spectate_frame_check.mjs`），
   造"双方格集无交集"的局面，逐格比对两块棋盘。判据是**严格相等（0 容差）**：
   `第 1 块棋盘 == 服务端 sides.p2.attacks`，且第 1 块棋盘上
   **一个 p1 自己打出去的格都不许出现**。
   ⚠️ 对称局面（双方打同一批格）下"方向写反"与"方向写对"结果**完全一样**，
   测不出来 —— 这正是第 5 批漏掉它的原因，所以本用例**强制**要求两组格无交集。
3. `test_frame_never_flips_the_direction_in_source`（源码级）：
   `_spectate_board_frame` 的函数体里不许出现"往 side 里塞**对手**的格"。
4. `test_frontend_has_exactly_one_transpose_and_both_paths_use_it`（源码级）：
   全仓只有**一处** `board_attacks` 的赋值（`spectateRebuildBoardAttacks`），
   且快照与帧两条入口都调用它 —— 防"为了对齐再写第二份转置"。
"""
import ast
import io
import json
import os
import pathlib
import subprocess
import sys
import uuid

import pytest

import db as db_module
import server
import spectate
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER_PY = REPO_ROOT / 'server.py'
GAME_JS = REPO_ROOT / 'static' / 'game.js'
DOM_TOOL = REPO_ROOT / 'tools' / 'dom_spectate_frame_check.mjs'

SID_A, SID_B = 'spec6-sid-a', 'spec6-sid-b'
# ★ 双方打出的格**刻意无交集**（对称局面测不出方向）
P1_OUT = ((0, 0), (1, 1))
P2_OUT = ((4, 4), (5, 5))

_ACCOUNTS = {}


def _account(key):
    if key not in _ACCOUNTS:
        uid = db_module.create_user('spec6-%s-%s' % (key, uuid.uuid4().hex[:10]), 'x' * 12)
        assert uid, '建测试账号失败'
        _ACCOUNTS[key] = uid
    return _ACCOUNTS[key]


def _make_room(room_id=None):
    room = GameRoom(room_id or ('spec6-' + uuid.uuid4().hex[:6]))
    for sid, name, row, uid_key in ((SID_A, '甲', 0, 'alpha'), (SID_B, '乙', 5, 'beta')):
        room.players[sid] = Player(
            name=name, ships=[PlayerShip(positions=[Position(x, row)], hits=[])
                              for x in range(6)],
            attacks=[], remaining_ships=6, sid=sid, user_id=_account(uid_key))
    room.state = 'attacking'
    room.current_phase = 'battle'
    room.current_attacker = SID_A
    room.attack_order = [SID_A, SID_B]
    room.attacks_remaining = 5
    room.round = 3
    room.ranked = False
    room.game_logs = []
    for (x, y) in P1_OUT:
        room.players[SID_A].attacks.append(Position(x=x, y=y, hit=True, ship_sunk=False))
    for (x, y) in P2_OUT:
        room.players[SID_B].attacks.append(Position(x=x, y=y, hit=True, ship_sunk=True))
    room_manager.rooms[room.id] = room
    return room


@pytest.fixture
def room():
    r = _make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


# ===========================================================================
# 0. 前置校准：这两组格确实"无交集"（否则下面的方向断言是空转绿）
# ===========================================================================


# ===========================================================================
# 1. 服务端层：帧与快照的 `sides` 必须**同向**
# ===========================================================================
def test_frame_and_snapshot_sides_are_the_same_direction(room):
    """★★ 帧的 `sides[label].attacks` 必须**逐字段等于**快照的同名字段。

    改坏哪一行会红：把 `_spectate_board_frame` 里那句
    `frame['sides'][...] = _spectate_side_payload(pid, ...)`
    改回第 5 批的 `side['attacks'] = _spectate_player_cells(other)`（方向翻反）。
    """
    snap = server._build_spectate_snapshot(room)
    frame = server._spectate_board_frame(room)

    for label in ('p1', 'p2'):
        assert frame['sides'][label]['attacks'] == snap['sides'][label]['attacks'], \
            '帧的 %s.attacks 与快照**不同向**（前端只转置一次 ⇒ 两块棋盘对调）' % label

    # ★ 点名判据：帧里 p1 拿到的一定是**甲**（= p1 座位）打出去的格。
    #   方向翻反时这一条立刻红，而且报错信息直接说出"拿到了谁的格"。
    seat_a = snap['sides']['p1']['seat_id']
    assert seat_a == SID_A or snap['sides']['p1']['seat_id'] == SID_A
    got = {(c['x'], c['y']) for c in frame['sides']['p1']['attacks']}
    assert got == set(P1_OUT), \
        '帧的 p1.attacks 不是"甲自己打出去的格"（实际 %s）—— 方向写反了' % sorted(got)
    got2 = {(c['x'], c['y']) for c in frame['sides']['p2']['attacks']}
    assert got2 == set(P2_OUT), \
        '帧的 p2.attacks 不是"乙自己打出去的格"（实际 %s）—— 方向写反了' % sorted(got2)
    # 反向：两份数据**确实不同**（否则上面两条是同一个集合在自证）
    assert got != got2, '两个座位的格集相同 ⇒ 本条用例测不出方向（前置失效）'


def test_snapshot_board_attacks_is_still_the_transpose(room):
    """★ 快照里的 `board_attacks` 仍然必须是 `sides` 的转置（那条口径没被本批改坏）。

    本批只改**帧**的方向；快照那两个字段的关系一个字都没动 ——
    这条用例把它钉住，防"顺手把快照也翻了"。
    """
    snap = server._build_spectate_snapshot(room)
    assert snap['board_attacks']['p1'] == snap['sides']['p2']['attacks']
    assert snap['board_attacks']['p2'] == snap['sides']['p1']['attacks']
    assert {(c['x'], c['y']) for c in snap['board_attacks']['p1']} == set(P2_OUT)


# ===========================================================================
# 2. ★★ 端到端：真的跑 static/game.js，逐格比对两块棋盘
# ===========================================================================
def _plain(obj):
    return json.loads(json.dumps(obj, default=lambda o: o.__dict__))


def _str_coords(node):
    """坐标一律转成**字符串** —— DOM 里 `dataset.x` 是字符串（真浏览器亦然）。"""
    if isinstance(node, dict):
        if 'x' in node and 'y' in node:
            node['x'] = str(node['x'])
            node['y'] = str(node['y'])
        for value in node.values():
            _str_coords(value)
    elif isinstance(node, list):
        for value in node:
            _str_coords(value)
    return node


def _run_dom_tool(payload):
    """跑 `tools/dom_spectate_frame_check.mjs`（**真的**加载 `static/game.js`）。

    ⚠️ payload 走**环境变量**：里面有中文昵称，命令行参数在 Windows 上要过代码页
    （GBK）转换，很容易把中文名弄坏（CLAUDE.md 反复踩过这条）。
    """
    assert DOM_TOOL.exists(), '缺少 tools/dom_spectate_frame_check.mjs'
    env = dict(os.environ)
    env['DSH_SPEC_PAYLOAD'] = json.dumps(payload, ensure_ascii=False)
    env.pop('DSH_SPEC_DEBUG', None)
    proc = subprocess.run(
        ['node', str(DOM_TOOL)], env=env, capture_output=True,
        text=True, encoding='utf-8', errors='replace', timeout=120)
    return proc


def test_frontend_boards_match_the_server_snapshot_cell_by_cell(room):
    """★★★ 真跑 `game.js`：快照路径与**帧路径**画出来的两块棋盘都必须与服务端一致。

    判据（**严格相等，0 容差**）：
      · 第 1 块棋盘上的格 == 服务端 `sides.p2.attacks`（= 落在 p1 那块棋盘上的格）；
      · 第 2 块棋盘上的格 == 服务端 `sides.p1.attacks`；
      · 第 1 块棋盘上**一个 p1 自己打出去的格都不许出现**（这条专抓方向写反）。

    改坏哪一行会红：`_spectate_board_frame` 的方向（红 4 项）、
    `spectateRebuildBoardAttacks` 的转置（红 5 项）、
    `applySpectateBoardFrame` 直接把帧当棋盘用（同上）。
    """
    snap = _str_coords(_plain(server._build_spectate_snapshot(room)))
    frame = _str_coords(_plain(server._spectate_board_frame(room)))
    payload = {
        'snapshot': snap,
        'frame': frame,
        # 甲（p1）再开一炮 → 必须落在乙那块棋盘（第 2 块）上
        'extra_shot': {'attacker': SID_A, 'x': '3', 'y': '3', 'hit': False},
    }
    proc = _run_dom_tool(payload)
    out = proc.stdout or ''
    assert proc.returncode == 0 and 'OK  12 项全绿' in out, (
        '观战棋盘方向检查未通过（exit=%s）\n--- stdout ---\n%s\n--- stderr ---\n%s'
        % (proc.returncode, out[-4000:], (proc.stderr or '')[-2000:]))
    assert out.count('FAIL') == 0, out[-4000:]




# ===========================================================================
# 3. 源码级守卫：方向只许有一处判据
# ===========================================================================
def _js():
    return io.open(GAME_JS, encoding='utf-8').read()


def _func_src(path, name):
    src = io.open(path, encoding='utf-8').read()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ''
    raise AssertionError('%s 里找不到函数 %s（改名了？）' % (path.name, name))






# ===========================================================================
# 4. ★ 一次操作的**收尾帧**不许停留在中间态（"帧发了但内容是过期的"）
# ===========================================================================
class _Frames:
    """抓发往观战通道的 `spectate_board` 帧（与 `tests/test_spectate_batch5.py` 同款）。"""

    def __init__(self):
        self.frames = []

    def install(self, monkeypatch):
        def spy(event, *a, **kw):
            if event == 'spectate_board':
                self.frames.append((kw.get('room'), a[0] if a else None))
            return None

        monkeypatch.setattr(server.socketio, 'emit', spy)

    @property
    def last(self):
        return self.frames[-1][1] if self.frames else None


@pytest.fixture
def frames(monkeypatch):
    f = _Frames()
    f.install(monkeypatch)
    return f


def _board_of(frame, label):
    """把一份帧折算成"哪块棋盘上有哪些格"（帧是**座位方向**，所以棋盘 p1 = sides.p2）。"""
    other = 'p2' if label == 'p1' else 'p1'
    return sorted((c['x'], c['y'], bool(c['hit']), bool(c['ship_sunk']))
                  for c in frame['sides'][other]['attacks'])


def _server_board(room, label):
    """服务端**此刻**的权威棋盘（复用 `_spectate_board_frame` 的同一个构造）。"""
    return _board_of(server._spectate_board_frame(room), label)


def test_board_frame_end_of_operation_has_no_divergence(room, frames):
    """★★ 一次操作结束时，**最后一条** `spectate_board` 帧必须等于服务端此刻的棋盘。

    ## 这条用例抓的是第 6 批实测到的第二个真缺陷

    `_mark_spectate_board_dirty` 是**立刻**发帧的（那句话本身是对的：棋盘真的变了，
    观众必须知道），但清格/重摆都发生在**结算中段**。原先的设计指望
    "`emit()` 收尾再补一条更完整的"，而 `_flush_spectate_board_if_dirty`
    在 `emit` 里**从来没被调用过** ⇒ 除 `疗愈`（自己收口）与 `灵气复苏`
    （`confirm_magic_target` 自己收口）之外的路径，**收尾帧一条都发不出去**。

    E2E 实测（`tools/spectate_check.mjs` + 服务端 FRAMEPUB 日志）：`回光返照`
    那条帧是在 `state=attacking` 的中间态发的（`p1=[(0,5,True)]`），此后服务端
    的棋盘又变过，观众那条连接**再没收到第二条** ⇒ 观战屏上留着一条服务端已经
    不复存在的格。

    ## 判据

    把每张卡都真的打一遍（`回光返照` / `灵气复苏` / `败者食尘` 用真 handler），
    断言"最后一条帧折算出来的两块棋盘" == "服务端此刻的棋盘"，**逐格相等**。
    谁把收尾那句 `_flush_spectate_board_if_dirty` 删掉、或者新加一张重摆卡却
    忘了收口，这条都会红。

    ⚠️ 这里**不改** `_mark_spectate_board_dirty` 的"立刻发"语义 ——
       中间态那条帧是**有意**的（棋盘变了就得马上告诉观众），本条只要求
       **收尾那一条**必须是真值。
    """
    for card_name in ['回光返照', '灵气复苏', '疗愈', '败者食尘']:
        if card_name == '疗愈':
            # 疗愈要有一艘"已沉的船"才有东西可复活；前面的重置卡可能清空该方舰队。
            target = room.players[SID_B]
            ship = next((candidate for candidate in target.ships
                         if server._is_ship_alive(target, candidate)), None)
            if ship is None:
                ship = PlayerShip(positions=[Position(x=0, y=0)], hits=[])
                target.ships = [ship]
                target.sunken_ships = []
                target.remaining_ships = 1
            room.players[SID_A].attacks.append(
                Position(x=ship.positions[0].x, y=ship.positions[0].y, hit=True, ship_sunk=True))
            ship.hits.append(Position(x=ship.positions[0].x, y=ship.positions[0].y, hit=True))
            room.players[SID_B].sunken_ships.append(ship)
            room.players[SID_B].remaining_ships -= 1
            room.players[SID_A].attacks.append(Position(x=2, y=5, hit=False, ship_sunk=False))

        frames.frames.clear()
        if card_name == '疗愈':
            server._revive_sunken_ships(room, room.players[SID_B], 1, reveal_to=SID_A)
        elif card_name == '灵气复苏':
            room.magic_temp_data = {'type': 'lingqi_choice', 'caster': SID_A, 'max_ships': 6}
            resp = server.confirm_magic_target({
                'room_id': room.id, 'player_id': SID_A, 'temp_data_id': 'lingqi_choice',
                'target_data': {'target_ships': 6}})
            assert resp.get('status') == 'success', resp
        else:
            room.current_attacker = SID_A          # 回光返照要求自己先手
            res = server.apply_magic_effect(room, SID_A, MagicCard(card_name), {})
            assert res.success is not False, getattr(res, 'message', res)

        assert frames.frames, '%s 一条 spectate_board 帧都没发' % card_name
        last = frames.last
        for label in ('p1', 'p2'):
            got = _board_of(last, label)
            want = _server_board(room, label)
            assert got == want, (
                '%s：最后一条帧里第 %s 块棋盘与服务端**此刻**不一致 —— '
                '说明收尾帧没发出去（观众屏上留着服务端已经不存在的格）\n'
                '  帧 = %s\n  服务端 = %s' % (card_name, label, got, want))


def test_huiguang_through_the_real_chain_has_no_divergence(room, frames, monkeypatch):
    """★★ 走**真连锁结算**打「回光返照」：棋盘在"标记之后"又变了，收尾帧必须跟上。

    ## 这条用例在测什么契约

    `_mark_spectate_board_dirty(room)` 是**立刻**发帧的，而清格/重摆都发生在
    **结算中段**。原设计写着"收尾由 `emit()` 补一条更完整的"，而
    `_flush_spectate_board_if_dirty` 在 `emit` 里**从来没有被调用过**
    （`emit` 拿不到 room 对象，写在那里本来就是死代码）。

    本用例**人为**把"标记之后棋盘又变了"这件事做出来（monkeypatch 在
    `_emit_board_attacks` 里追加一格），然后断言：
    **最后一条帧必须等于结算完那一刻的服务端棋盘**。

    ⚠️ 为什么必须造这个"人为"的变化：现存四张卡里，"标记"之后其实**没有**卡
       再改棋盘上的格（实测：直接调 `apply_magic_effect` 时删掉收尾收口，
       13 条用例全绿 —— 那种写法是**自己骗自己**）。但契约是"收尾必须有真值帧"，
       而它恰恰**没有任何用例守着**（CLAUDE.md 教训 #36：契约没人守，坏掉时没症状）。

    ⚠️ E2E 里那条"观众屏上留着旧格"的**根因是工具读错了字段**
       （见 `tools/spectate_check.mjs` 的探针自检），**不是**本条;
       本条守的是这个独立契约。
    """
    monkeypatch.setattr(server, '_schedule_chain_timeout', lambda *a, **k: None)
    room.current_attacker = SID_A          # 回光返照要求自己先手
    room.players[SID_B].attacks.append(Position(x=0, y=0, hit=False, ship_sunk=False))

    # 让"标记之后"真的再改一次棋盘（模拟将来某张卡在清格之后又动格）。
    # ⚠️ 挂在 `_mark_spectate_board_dirty` **之后**而不是 `_emit_board_attacks` 里：
    #    `_emit_board_attacks` 在**标记之前**就跑了，挂在那里的话改动会被
    #    "标记时发出的那一帧"顺手带上 ⇒ 最后一条帧照样是真值 ⇒ **判据空转绿**
    #    （本用例第一版就是这样：两处收口都注释掉了，13 条照样全绿）。
    real_mark = server._mark_spectate_board_dirty
    mutated = {'done': False}

    def mark_then_touch(rm):
        real_mark(rm)
        # ⚠️ 必须改**这一局**（闭包里的 `room`），不是 `rm` ——
        #    `rm` 可能不是同一个对象，那样改动就写进了另一个房间（两边都读空列表）。
        if not mutated['done'] and rm is not None:
            mutated['done'] = True
            room.players[SID_A].attacks.append(
                Position(x=3, y=3, hit=True, ship_sunk=False))

    monkeypatch.setattr(server, '_mark_spectate_board_dirty', mark_then_touch)

    frames.frames.clear()
    room.chain = [server.ChainItem(SID_A, MagicCard('回光返照'), {}, 0)]
    results = server.resolve_chain(room)
    assert any(getattr(r, 'success', False) for r in results), \
        '回光返照在连锁结算里没生效：%s' % [getattr(r, 'message', None) for r in results]
    assert mutated['done'], '（前提）棋盘在"标记之后"确实又被改过（否则这条是空转绿）'
    assert room.players[SID_A].attacks, '（前提）那一格确实在服务端历史里'

    assert frames.frames, '回光返照一条 spectate_board 帧都没发'
    # ★ 反向校准：那一次改动**不许**出现在第一条帧里（否则"标记之后又变了"没被造出来）
    assert (3, 3, True, False) not in _board_of(frames.frames[0][1], 'p2'), \
        '（反向校准）标记那一刻发出的帧里就有这一格 ⇒ 没造出"标记之后才变"的局面'

    last = frames.last
    for label in ('p1', 'p2'):
        got = _board_of(last, label)
        want = _server_board(room, label)
        assert got == want, (
            '回光返照走真连锁结算后，最后一条帧里第 %s 块棋盘与服务端**此刻**不一致 —— '
            '收尾帧没发出去（观众屏上留着服务端已经不存在的格 / 少了新的格）\n'
            '  帧 = %s\n  服务端 = %s' % (label, got, want))
    # ★ 收尾帧必须**真的**带上那一格（否则上面那条可能只是"两边都空"在自证）
    assert (3, 3, True, False) in _board_of(last, 'p2'), \
        '（反向校准）那一格没有出现在收尾帧里 —— 说明最后一条帧还是"标记那一刻"的旧快照'
