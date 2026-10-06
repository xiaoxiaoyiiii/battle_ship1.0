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
    '_apply_wuyou_dream': 1,
    # ★ 2026-09-25：兵粮寸断（判定卡）—— 与 `_apply_wuyou_dream` 同形状的两个记录点：
    #   判定摇骰子（_roll_bingliang）与"这个准备阶段的摸牌被跳过"（_bingliang_consume_skip）。
    #   两者都是**玩家可见**的行动，必须进回放；故在此点名登记。
    '_bingliang_consume_skip': 1,
    '_roll_bingliang': 1,
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






# ===========================================================================
# §8-12 `allow_replay` / `matches.mode` 列迁移幂等
# ===========================================================================


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
