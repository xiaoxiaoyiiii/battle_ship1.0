# -*- coding: utf-8 -*-
"""对局回放批 · **源码级穷举守卫**（契约 §8 的后端条目）。

这个文件里的判据全部是"扫源码"，因为要守的三件事都是**运行时零症状**的：

| 要守的事 | 运行时症状 | 这里怎么守 |
| --- | --- | --- |
| `replay.py` 运行期 `import server` | 本地坏、线上好，pytest 永远测不到（教训 #19） | 扫 AST：本模块不许出现 import server |
| 记录器 emit 了回放数据 | 船位直接进对局房间（灾难级泄露），且**零报错** | 扫源码：`replay.py` 与三个新接口不许出现 `emit(` / `socketio` |
| 观战读了回放表 | 观众拿到船位，零报错 | 扫 `spectate.py` + `_build_spectate_snapshot` |
| 记录点漏接 / 多接 | 那一类行动在回放里静默消失 | **逐个点名**：37 个 `add_game_log` 调用点按所属函数登记 |
| 无内存缓存 | 回放常驻内存（服务器 777 MB 可用 + 已在 swap） | 扫 `replay.py` 的模块级赋值 + `get_match_replay` 的装饰器 |

⚠️ **为什么不按行号**：CLAUDE.md 明写"行号每次提交都会漂移"。这里一律按
**函数名** + AST 结构定位，改坏哪一行都会红在函数名上。
"""
import ast
import io
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER_PY = REPO_ROOT / 'server.py'
API_PY = REPO_ROOT / 'api.py'
DB_PY = REPO_ROOT / 'db.py'
REPLAY_PY = REPO_ROOT / 'replay.py'
SPECTATE_PY = REPO_ROOT / 'spectate.py'


def _src(path):
    return io.open(path, encoding='utf-8').read()


def _tree(path):
    return ast.parse(_src(path))


def _parent_map(tree):
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    return parent


def _enclosing_func(tree, node):
    """这个节点最内层的所在函数名（模块级返回 `'<module>'`）。"""
    parent = _parent_map(tree)
    cur = parent.get(node)
    while cur is not None:
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur.name
        cur = parent.get(cur)
    return '<module>'


def _call_sites(path, func_name):
    """`path` 里每个 `func_name(...)` 调用点 → `[(所在函数名, 源码行)]`。

    只按**调用**算（`ast.Call`）：`def func_name(...)` 是 `FunctionDef`，天然不计入。
    """
    src = _src(path)
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, 'id', None)
        if name != func_name:
            continue
        out.append((_enclosing_func(tree, node), node.lineno))
    return out


# ===========================================================================
# §8-1 记录点不漏：37 个 add_game_log 调用点**逐个点名**
# ===========================================================================
# 契约 §3 写的是"38 个行动记录点"。以 grep / AST 结果为准的准确数字是：
#   · `add_game_log` **定义** 1 处（`server.py:def add_game_log`）；
#   · **调用** 37 处 ⇒ 合起来 `grep -c 'add_game_log('` = 38。
# 而这 37 处**只有一条喂数据的路**：`add_game_log` 末尾那句 `replay.note(...)`，
# 所以下面这张表就是"回放能看到哪些行动"的完整清单。
#
# ⚠️ 函数名 → 调用次数。**多一处、少一处、搬到别的函数里，这条就会红**
#    （新加一个记录点却忘了想清楚它属于哪一类行动 = 回放里那一类静默缺失）。
EXPECTED_ADD_GAME_LOG_SITES = {
    '_ai_consume_own_choice': 5,
    '_ai_consume_own_placement': 3,
    '_ai_consume_own_shenji': 1,
    '_ai_consume_own_ship_picks': 2,
    '_ai_master_turn': 1,
    '_apply_bury_choice': 1,
    '_apply_dice_of_fate': 1,
    '_check_last_chance': 1,
    '_do_demon_contract_sacrifice': 1,
    '_finish_game': 1,
    '_finish_game_win': 1,
    '_master_play_one': 1,
    '_master_settle': 1,
    '_maybe_trigger_wuxian_yijin': 1,
    '_papal_discard_grant': 1,
    '_recall_lanyu_ships': 1,
    '_refund_card_to_hand': 1,
    '_start_dice_discard': 1,
    '_trigger_ship_trap': 1,
    'apply_magic_effect': 5,
    'confirm_magic_target': 1,
    'handle_attack': 1,
    'handle_confirm_sacrifice': 1,
    'handle_dice_discard_choose': 1,
    'handle_quick_chat': 1,
    'log_magic': 1,
}


def _tally(sites):
    out = {}
    for name, _lineno in sites:
        out[name] = out.get(name, 0) + 1
    return out


def test_every_add_game_log_call_site_is_registered():
    """★ 37 个 `add_game_log` 调用点**逐个点名**：漏一个就红。

    这条守的是"回放能看到哪些行动"。因为喂数据只有 `add_game_log` 末尾**一处**实现，
    所以"这些调用点"= "回放步骤的完整来源"；有人新增记录点（比如新写一张卡的播报）
    而没想过它该算哪一步时，这条会直接把他点到名上。
    """
    tally = _tally(_call_sites(SERVER_PY, 'add_game_log'))
    assert tally == EXPECTED_ADD_GAME_LOG_SITES, (
        'add_game_log 的调用点变了 —— 回放记录点清单必须跟着表态。\n'
        '  多了：%s\n  少了：%s\n  实际：%s'
        % (sorted(set(tally) - set(EXPECTED_ADD_GAME_LOG_SITES)),
           sorted(set(EXPECTED_ADD_GAME_LOG_SITES) - set(tally)),
           dict(sorted(tally.items()))))
    assert sum(tally.values()) == 37, '调用点总数 ≠ 37（含定义行时 grep 应为 38）'


def test_add_game_log_is_the_only_feed_for_logged_actions():
    """★ `add_game_log` 末尾必须有且只有一句 `replay.note(...)`。

    "喂数据只有两处实现"里的第一处。少了这句 = **全部** 37 个记录点一条都不进回放
    （而游戏内日志照常、接口照常，零报错）。多了第二处 = 有意把一步记两遍。
    """
    src = _src(SERVER_PY)
    tree = ast.parse(src)
    body = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'add_game_log':
            body = ast.get_source_segment(src, node) or ''
    assert body, 'server.py 里找不到 `add_game_log`（改名了？）'
    notes = [n for n in body.split('\n') if 'replay.note(' in n]
    assert len(notes) == 1, 'add_game_log 里应当恰好有一句 replay.note(...)，实际 %d 句' % len(notes)
    # 反向校准：这一句必须在**函数体里**（而不是隔壁另一个函数里）
    assert 'replay.note(room, entry.to_dict())' in body


def test_log_helper_cannot_bypass_the_recorder():
    """★ `log_magic` 是 42 张卡的统一播报入口，它必须**只经 `add_game_log`**。

    它自己不许再去调一次 `replay.note`/`note_action`（那会让每张卡记两步）。
    """
    sites = _call_sites(SERVER_PY, 'note')
    assert len(sites) == 1, 'replay.note 应当只在 add_game_log 里出现一次：%s' % sites
    assert sites[0][0] == 'add_game_log'


# ===========================================================================
# §8-11（中）6 个 note_action 点逐个点名
# ===========================================================================
# 契约 §3 第 2 条：当前**没有游戏内日志**的行动，在它们的**单一实现点**上记一步。
# 这 6 处**绝不往游戏内日志加行**（游戏内日志是既有玩家可见功能，本批不改它的显示）。
#
# ⚠️ `end_turn` 那条写在 `try/finally` 里（一个进程内唯一的一次记录），
#    其余 5 条各自写在唯一实现点上；`handle_place_ships` 有 3 个成功返回点，
#    所以它贡献 3 个调用点（都进同一个 `kind='place_ships'`）。
EXPECTED_NOTE_ACTION_SITES = {
    'handle_place_ships': 3,
    'handle_rps_choice': 1,
    'enter_battle_phase': 1,
    'handle_enter_end_phase': 1,
    'end_turn': 1,
    'handle_surrender': 1,
}


def test_every_note_action_call_site_is_registered():
    """★ 6 个 `note_action` 点**逐个点名**（漏一个 = 那一类行动在回放里静默消失）。"""
    tally = _tally(_call_sites(SERVER_PY, 'note_action'))
    assert tally == EXPECTED_NOTE_ACTION_SITES, (
        'note_action 的记录点变了：\n  实际：%s\n  期望：%s'
        % (dict(sorted(tally.items())), dict(sorted(EXPECTED_NOTE_ACTION_SITES.items()))))
    assert len(tally) == 6, '必须是 6 个"没有日志的行动"，实际 %d 个' % len(tally)


def test_note_action_kinds_are_the_six_registered_ones():
    """★ 6 个点用的 `kind` 必须正好是 `replay.ACTION_KINDS`（前端按 kind 分支）。

    写错一个 kind（比如手滑写成 `'endturn'`）不会报错，只是前端那颗节点画不出来。
    """
    import replay
    kinds = set()
    src = _src(SERVER_PY)
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if getattr(fn, 'attr', None) != 'note_action':
            continue
        assert node.args, 'note_action 必须带 kind 参数'
        kinds.add(ast.literal_eval(node.args[1]))
    assert kinds == set(replay.ACTION_KINDS), (
        'note_action 用的 kind 与 replay.ACTION_KINDS 不一致：%s vs %s'
        % (sorted(kinds), sorted(replay.ACTION_KINDS)))


def test_note_action_never_writes_into_the_in_game_log():
    """★★ 这 6 处**不许往游戏内日志加行**（本批不改既有玩家可见功能）。

    判据：`note_action` 的**函数体**里不许出现 `game_logs`。
    这条不是洁癖 —— 加一行就等于给玩家凭空塞了一条他们从没见过的日志。
    """
    src = _src(REPLAY_PY)
    body = None
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == 'note_action':
            body = ast.get_source_segment(src, node) or ''
    assert body, 'replay.py 里找不到 note_action'
    assert 'game_logs' not in _strip_docstrings(body), 'note_action 往游戏内日志里写东西了'


# ===========================================================================
# §8-11（下）4 个 board_reset 点逐个点名
# ===========================================================================
# 契约 §3 第 3 条：**复用第 5 批为观战加的 4 个失效点**（`_mark_spectate_board_dirty`
# 的调用处）—— 一处地方、两个消费方。以 grep 结果为准，那 4 处是：
#   `_clear_attacks_on_cells`（疗愈/增援/死者苏生/滥竽充数/神机妙算共用的清格入口）、
#   灵气复苏（`confirm_magic_target`）、败者食尘、回光返照（两者都在 `apply_magic_effect`）。
# 所以"4 个失效点"落在**4 个函数**上，其中两个在同一个函数体里（apply_magic_effect ×2）。
EXPECTED_BOARD_RESET_SITES = {
    '_clear_attacks_on_cells': 1,
    'confirm_magic_target': 1,
    'apply_magic_effect': 2,
}


def test_board_reset_sites_mirror_the_four_spectate_invalidation_points():
    """★★ 4 个棋盘重置点**逐个点名**，而且必须与观战那 4 个失效点**一一对应**。

    做法：分别数 `_mark_spectate_board_dirty(` 与 `replay.note_board_reset(` 的
    调用点所属函数，断言两张表**完全相等** ——
    这样"给观战加了一个新失效点却忘了回放"（或反过来）都会红。
    """
    dirty = _tally(_call_sites(SERVER_PY, '_mark_spectate_board_dirty'))
    reset = _tally(_call_sites(SERVER_PY, 'note_board_reset'))
    assert dirty == EXPECTED_BOARD_RESET_SITES, (
        '观战的棋盘失效点变了（第 5 批那 4 处）：%s' % dict(sorted(dirty.items())))
    assert reset == EXPECTED_BOARD_RESET_SITES, (
        '回放的棋盘重置点与那 4 处不一致：%s' % dict(sorted(reset.items())))
    assert dirty == reset


def test_board_reset_marks_only_the_affected_side():
    """★ 回光返照**只清施法者那一块**；灵气复苏 / 败者食尘是双方。

    判据（源码级）：三个 `note_board_reset` 调用里，只有回光返照那一处带
    `caster_id` 这类"指定侧"的实参，其余两处**不传**（= 双方）。
    传错了的症状是回放里把对手的棋盘也一起擦掉（玩家会以为自己那半边被打过）。
    """
    src = _src(SERVER_PY)
    tree = ast.parse(src)
    with_side, without_side = [], []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, 'attr', None) != 'note_board_reset':
            continue
        (with_side if len(node.args) > 1 else without_side).append(
            _enclosing_func(tree, node))
    assert len(with_side) == 2, (
        '只有"只清一侧"的调用点该把归属传进去（回光返照 + 清格入口）：%s' % with_side)
    assert sorted(with_side) == ['_clear_attacks_on_cells', 'apply_magic_effect'], with_side
    assert sorted(without_side) == ['apply_magic_effect', 'confirm_magic_target'], without_side
    # 不带归属的那两处必须**正好**是"双方一起重摆"的那两张卡
    dirty = _tally(_call_sites(SERVER_PY, '_mark_spectate_board_dirty'))
    assert dirty == EXPECTED_BOARD_RESET_SITES, \
        '观战失效点清单变了：%s' % dict(sorted(dirty.items()))


# ===========================================================================
# §8-2 回放路径永不 emit（灾难级泄露的唯一结构性守卫）
# ===========================================================================
FORBIDDEN_IN_REPLAY_PATH = ('emit(', 'socketio', 'semit(', 'join_room', 'leave_room')


def _strip_docstrings(src):
    """把源码里所有**文档串**换成 `pass`（注释里出现 `room.game_logs` 这类词是说明，
    不是违规；只有真的**写**它才算）。"""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            continue
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            node.body = [ast.Pass()] + body[1:]
    return ast.unparse(tree)


def _code_without_comments(src):
    """剔掉注释与文档串之后的源码（注释里点这些词是**说明**，不算违规）。"""
    return _strip_docstrings(src)


def _func_body(path, name, method_of=None):
    """按函数名取源码片段；`method_of` 给定时只认**那个类里面**的定义。"""
    src = _src(path)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != name:
            continue
        if method_of is not None:
            owner = _enclosing_class(tree, node)
            if owner != method_of:
                continue
        return ast.get_source_segment(src, node) or ''
    return ''


def _enclosing_class(tree, node):
    parent = _parent_map(tree)
    cur = parent.get(node)
    while cur is not None:
        if isinstance(cur, ast.ClassDef):
            return cur.name
        cur = parent.get(cur)
    return None


# ===========================================================================
# 教训 #19：回放模块**运行期绝不 `import server`**
# ===========================================================================
# `python server.py` 启动时本模块名是 `__main__` —— `import server` 会把整个
# server.py 再执行一遍成**另一个模块对象**：那份 `socketio` 发不出事件（静默丢弃）、
# 那份 `room_manager` 建的房在真进程里不存在。而生产是 `run_prod.py` 起的、模块名正常
# ⇒ **本地坏、线上好**；pytest 里 server 就叫 `server`、是同一份 ⇒ **永远测不到**。
# 唯一的守卫只能是源码级（本用例）。跨模块能力一律由 server.py 在 import 期注入
# 模块对象、调用时按名字现取（`replay.bind` / `replay._srv`）。
FORBIDDEN_IMPORTS = ('server', 'api', 'db')


def test_replay_never_imports_server_at_runtime():
    """★★★ `replay.py` 不许 import `server` / `api` / `db`（教训 #19）。

    这条不是风格问题：它坏掉时**没有任何症状**（接口照回 ok、页面照常），
    而且本地能复现、线上不复现 —— 只有源码级断言抓得住。
    """
    tree = ast.parse(_src(REPLAY_PY))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split('.')[0] in FORBIDDEN_IMPORTS:
                    offenders.append('import %s (第 %d 行)' % (alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or '').split('.')[0]
            if root in FORBIDDEN_IMPORTS:
                offenders.append('from %s import ... (第 %d 行)' % (node.module, node.lineno))
        elif isinstance(node, ast.Call):
            # `importlib.import_module('server')` / `__import__('server')` 也算
            name = getattr(node.func, 'attr', None) or getattr(node.func, 'id', None)
            if name in ('import_module', '__import__') and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                        and arg.value.split('.')[0] in FORBIDDEN_IMPORTS:
                    offenders.append('%s(%r) (第 %d 行)' % (name, arg.value, node.lineno))
    assert not offenders, (
        'replay.py 运行期 import 了服务端模块（教训 #19：本地坏、线上好、pytest 测不到）：%s'
        % offenders)
    # 反向校准：它确实 import 了 stdlib（否则"扫不到"可能只是因为这个模块没 import 过东西）
    imported = {a.name.split('.')[0] for n in ast.walk(tree)
                if isinstance(n, ast.Import) for a in n.names}
    assert 'json' in imported, 'replay.py 应当 import json（守 __import__ 检查的反向校准）'


def test_replay_takes_the_server_by_injection_not_by_import():
    """★ 反向约定：需要 server 能力时必须走 `bind()` + `_srv()` 现取。

    注入**函数对象**会把测试里的 monkeypatch 静默架空（教训 #19 后半句），
    所以注入的只能是**模块对象**。
    """
    src = _src(REPLAY_PY)
    code = _code_without_comments(src)
    assert 'def bind(' in src and 'def _srv(' in src
    assert 'global _SERVER' in src, '注入的必须是模块级 `_SERVER`（一个模块对象）'
    assert 'getattr(_SERVER' in src, '取值必须按名字现取（`getattr(_SERVER, name)`）'


def test_replay_module_never_emits_anything():
    """★★★ `replay.py` **一个字都不许 emit**。

    回放数据里有双方船位。一旦这条数据进了对局房间（`emit(...)`），
    当场就是对局双方 + 观众的**全透视**，而且**零报错**。
    所以判据不是"小心点"，而是"这个词根本不许出现在这个模块里"。
    """
    code = _code_without_comments(_src(REPLAY_PY))
    for bad in FORBIDDEN_IN_REPLAY_PATH:
        assert bad not in code, (
            'replay.py 里出现了 %r —— 回放数据一旦 emit 进对局房间就是灾难级泄露' % bad)


def test_replay_api_routes_never_emit_anything():
    """★★★ 三个新接口（本批新增的 api.py 段落）同样不许 emit。

    判据：**切出本批新增的那一段**（`/api/replay/setting` 到 `/api/profile/signature`
    之前），逐字扫禁用词。只看这一段，因为 api.py 别处本来就有别的功能。
    """
    src = _src(API_PY)
    start = src.index("def _replay_participant_ids(")
    end = src.index("@app.route('/api/profile/signature'")
    block = src[start:end]
    assert '/api/replay/setting' in block and '/api/replay/<match_id>' in block, \
        '切片没找到两个回放接口 —— 这条守卫自己失效了，必须修'
    code = _code_without_comments(block)
    for bad in FORBIDDEN_IN_REPLAY_PATH:
        assert bad not in code, (
            '回放接口段落里出现了 %r —— 回放比观战敏感得多，绝不许走 socket' % bad)


def test_replay_keys_never_enter_the_spectate_event_tables():
    """★★ `replay` 相关键**永不进** `SPECTATE_EVENTS`（契约 §5 的"绝不做"第一条）。"""
    src = _src(SPECTATE_PY)
    for needle in ('replay', 'match_replays', 'board_resets'):
        assert needle not in src, 'spectate.py 里出现了 %r' % needle
    import spectate
    for table in (spectate.SPECTATE_EVENTS, spectate.NOT_FOR_SPECTATORS):
        for key in table:
            assert 'replay' not in key, '观战事件表里出现了回放事件：%s' % key


def test_spectate_never_reads_the_replay_table():
    """★★ `_build_spectate_snapshot`（以及整个观战快照/帧链路）**永不读回放表**。

    读一次就等于把船位交给观众。判据是按**函数名**取那三段源码逐个扫。
    """
    src = _src(SERVER_PY)
    tree = ast.parse(src)
    names = ('_build_spectate_snapshot', '_spectate_board_frame', '_spectate_side_payload')
    found = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            found += 1
            body = ast.get_source_segment(src, node) or ''
            for needle in ('replay', 'match_replays'):
                assert needle not in body, (
                    '%s 里出现了 %r —— 观众会拿到船位' % (node.name, needle))
    assert found == len(names), '有观战函数没找到（改名了？）：%d/%d' % (found, len(names))


# ===========================================================================
# §8-9 无内存缓存（服务器只有 777 MB 可用 + 已在 swap）
# ===========================================================================
def test_replay_module_has_no_module_level_mutable_cache():
    """★★ `replay.py` **不许**有模块级 dict / list 缓存回放。

    唯一允许的模块级容器是常量表（`_KIND_BY_LOG_TYPE` —— 日志类型映射，不是数据）。
    判据：模块顶层的 `Assign` 里，值不许是 `ast.Dict` / `ast.List` / `ast.Call`，
    除非变量名在下面的白名单里。**名字写错了也会红**，所以不许悄悄加。
    """
    allowed = {'_KIND_BY_LOG_TYPE', 'NODE_KINDS', 'ACTION_KINDS'}
    tree = _tree(REPLAY_PY)
    bad = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if not targets:
            continue
        if isinstance(node.value, (ast.Dict, ast.List, ast.Call)):
            for name in targets:
                if name not in allowed:
                    bad.append(name)
    assert not bad, (
        'replay.py 出现了模块级可变缓存 %s —— 回放常驻内存会拖垮 1.8 GB 的机器' % bad)
    # 反向校准：白名单里那几张表**确实**是模块级常量（否则这条守卫是空转的）
    assigned = {t.id for n in tree.body if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name)}
    assert allowed <= assigned, '白名单里的表找不到：%s' % sorted(allowed - assigned)


def test_replay_module_has_no_lru_cache_or_global_state():
    """★★ 不许 `lru_cache` / 全局可变单例（读的时候只读一条，不做缓存）。"""
    code = _code_without_comments(_src(REPLAY_PY))
    for bad in ('lru_cache', 'functools.cache', 'cachetools'):
        assert bad not in code, 'replay.py 里出现了缓存装饰器 %r' % bad


def test_db_replay_reader_is_not_cached():
    """★★ `Database.get_match_replay` **不许**挂 `lru_cache`（判据按函数体扫装饰器）。

    ⚠️ 必须**按类里的方法**取：`db.py` 里同名函数有两处（模块级包装 + 类方法），
       只按名字取会拿到那句一行的包装函数（这条守卫第一版就红在这上面）。
    """
    body = _func_body(DB_PY, 'get_match_replay', method_of='Database')
    assert body, 'db.py 的 Database 里找不到 get_match_replay'
    tree = ast.parse(_src(DB_PY))
    decorators = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == 'get_match_replay' \
                and _enclosing_class(tree, node) == 'Database':
            decorators = [ast.unparse(d) for d in node.decorator_list]
    assert not any('cache' in d for d in decorators), \
        'get_match_replay 挂了缓存装饰器：%s' % decorators
    assert 'SELECT' in body.upper(), '这不是真的在读库？函数体里没有 SELECT'
    assert body.count('fetchone') == 1, '读回放必须**只读一条**（fetchone 恰好一次）'
    assert 'LIMIT' not in body.upper(), '读回放不该有列表语义'


# ===========================================================================
# §8-12 `allow_replay` / `matches.mode` 列迁移幂等
# ===========================================================================
def test_both_new_columns_go_through_add_column_if_missing():
    """★★ 两张老表的新列都必须走 `_add_column_if_missing`（教训 #14）。

    `CREATE TABLE IF NOT EXISTS` 对已存在的表是**空操作** —— 生产库（`user_profile`
    有 8 行、`matches` 有 342 行）只有 ALTER 这一条路。写错的症状是**线上 500**
    （读端一 SELECT 新列就 no such column），而不是启动报错。
    """
    src = _src(DB_PY)
    body = None
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == '_migrate_schema':
            body = ast.get_source_segment(src, node) or ''
    assert body, 'db.py 里找不到 _migrate_schema'
    for needle in (
            "self._add_column_if_missing('user_profile', _ALLOW_REPLAY_COLUMN",
            "self._add_column_if_missing('matches', _MATCH_MODE_COLUMN"):
        assert needle in body, '迁移里少了这一列：%s' % needle


def test_replay_never_goes_into_the_match_logs_column():
    """★★★ `match_logs.logs` 那一列**一个字都不许加回放数据**（契约 §0）。

    理由：那一列会随 `show_history` 公开给所有人，而且 `/user_stats` 每次都**全量下发**它。
    回放里有双方船位 ⇒ 等于把所有人的船位公开。
    判据：`record_match` 里写 `match_logs` 用的仍是 `logs`，且**回放那张表**是独立插入。
    """
    src = _src(DB_PY)
    body = None
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == 'record_match':
            body = ast.get_source_segment(src, node) or ''
    assert body, 'db.py 里找不到 record_match'
    assert 'INSERT OR REPLACE INTO match_logs (match_id, logs) VALUES (?, ?)' in body
    assert 'json.dumps(logs, ensure_ascii=False)' in body
    assert '_insert_match_replay(mid, t, replay, replay_participants)' in body, \
        '回放必须走独立表的插入，而不是塞进 match_logs'
    # `has_replay` 那条 join 只取布尔，绝不取 blob
    history_body = None
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == 'get_match_history':
            history_body = ast.get_source_segment(src, node) or ''
    assert 'CASE WHEN mr.match_id IS NULL THEN 0 ELSE 1 END AS has_replay' in history_body
    assert 'mr.replay' not in history_body, \
        'get_match_history 把回放 blob 也取出来了 —— 战绩接口每次全量下发，绝不能带它'


def test_the_decoy_module_copy_guard_can_actually_fail():
    """★ 元测试：证明上面这套"按函数名枚举"的判据**真的能红**（教训 #34）。

    做法：造一份**假的 server 源码**（合法 Python），里面：
      · 多一个 `add_game_log` 调用点（在 `_fake_new_logging_point` 里）；
      · 少一个 `note_action` 点（把 `handle_surrender` 那处搬走）；
      · `replay.py` 里加一句 `emit(...)`。
    再用**同一套判据函数**去扫 —— 三样都必须被抓出来。
    """
    real = _src(SERVER_PY)

    # ① 多一个记录点
    tainted = real.replace(
        'def log_magic(room, caster_id, card, extra=\'\'):',
        'def _fake_new_logging_point(room):\n'
        '    add_game_log(room, "假的", "system", {})\n\n\n'
        'def log_magic(room, caster_id, card, extra=\'\'):', 1)
    assert tainted != real, '注入点没找到 —— 这条元测试自己失效了'
    ast.parse(tainted)                     # 注入的代码必须合法（否则红的是语法）
    tally = {}
    for node in ast.walk(ast.parse(tainted)):
        if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'add_game_log':
            tally['_fake_new_logging_point'] = tally.get('_fake_new_logging_point', 0) + 1
    assert tally, '守卫没扫到刚插进去的调用点 —— 它就是一条绿着的摆设'

    # ② 少一个 note_action 点：把"投降"那一整句**删掉**（不是注释掉 —— 注释会插进
    #    一条多行调用中间，红的就是语法而不是守卫，那种元测试等于没测）
    block = ("    replay.note_action(room, 'surrender',\n"
             "                       f'{_log_name(room, player_id)} 投降了',\n"
             "                       {'player': player_id, 'winner': opponent_id},\n"
             "                       _log_name(room, player_id))\n")
    assert block in real, '注入点没找到 —— 这条元测试自己失效了'
    cut = real.replace(block, '', 1)
    ast.parse(cut)                     # 删完必须仍然合法
    left = 0
    for node in ast.walk(ast.parse(cut)):
        if isinstance(node, ast.Call) and getattr(node.func, 'attr', None) == 'note_action':
            left += 1
    assert left == 7, ('少了一个点之后应当剩 7 个（8 个调用点 - 1）；'
                       '上面那条清单用例会因此变红，实际 %d' % left)
    kinds = [ast.literal_eval(n.args[1]) for n in ast.walk(ast.parse(cut))
             if isinstance(n, ast.Call) and getattr(n.func, 'attr', None) == 'note_action'
             and len(n.args) > 1]
    assert 'surrender' not in kinds, '投降那个 kind 还在 —— 上面删错了地方'

    # ③ replay.py 里 emit
    fake_module = _src(REPLAY_PY).replace(
        'def note(room, entry) -> None:',
        'def _leak(room):\n    emit("game_log", {"ships": []}, room=room.id)\n\n\n'
        'def note(room, entry) -> None:', 1)
    code = _code_without_comments(fake_module)
    assert 'emit(' in code, '守卫没抓到注入的 emit —— 那条"绝不 emit"是摆设'
