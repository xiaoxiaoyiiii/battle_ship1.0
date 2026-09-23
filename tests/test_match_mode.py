# -*- coding: utf-8 -*-
"""战绩模式批 · `matches.mode`（后端）。

作者新提的需求：**战绩界面里看不出这一局是「排位赛 / 匹配 / 打人机」**。
那是数据缺口 —— `matches` 表原先只有 `id / winner_id / loser_id / timestamp`，
界面只能靠 `isAiOpponent(matchId)` **从 id 猜人机**（猜测，不是记录）。

## 取值表（唯一一份 = `server.MATCH_HISTORY_MODES`）

| 值 | 含义 | 判据 |
| --- | --- | --- |
| `'ai'` | 人机局 | `room.is_ai_room` |
| `'ranked'` | 排位赛 | `_room_match_mode(room) == 'ranked'`（**复用**，不重判） |
| `'custom'` | 自定义房 / 好友邀战 | `not room.matchmade` |
| `'casual'` | 匹配出来的休闲局 | 其余 |

优先级就是上表顺序：人机房恒 `ranked=False`，所以先判人机。

## 为什么加了个房间级布尔 `matchmade`

"这间房是匹配出来的"应该是**被记录的事实**，不是从 `room.players` 的 key 形状反推的判据
（CLAUDE.md §6：key 有两套约定，而且历史上漂移过一次；形状判据一旦漂移，症状是
"匹配局被静默标成自定义局"，**零报错**）。

全项目所有配对都汇到 `handle_find_match` 里那个消费 `match_queue` 的循环，
所以 `matchmade = True` **只有那一处**（源码级穷举守卫见下）。
形状判据降级成这里的**交叉校验**：将来谁改了 key 约定，是**测试先红**。

## 老数据

生产库那 342 行（其中 152 行两侧都是真实用户）的 `mode` 是 **NULL**。
NULL = "不知道"，**绝不许兜底成 `'casual'`**（教训 #21）。前后端都要能优雅处理。
"""
import ast
import io
import pathlib
import uuid

import pytest

import db as db_module
import server
from server import GameRoom, Player, room_manager

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER_PY = REPO_ROOT / 'server.py'
DB_PY = REPO_ROOT / 'db.py'


def _account():
    uid = db_module.create_user('mode-%s' % uuid.uuid4().hex[:10], 'x' * 12)
    assert uid
    return uid


@pytest.fixture
def room():
    """匹配房形状的房间（key = sid，真人 uid 在 `Player.user_id` 上）。"""
    r = GameRoom('mode-' + uuid.uuid4().hex[:6])
    r.players['mode-sid-a'] = Player(name='甲', ships=[], attacks=[], remaining_ships=0,
                                     sid='mode-sid-a', user_id=_account())
    r.players['mode-sid-b'] = Player(name='乙', ships=[], attacks=[], remaining_ships=0,
                                     sid='mode-sid-b', user_id=_account())
    r.game_logs = []
    room_manager.rooms[r.id] = r
    yield r
    room_manager.rooms.pop(r.id, None)


# ===========================================================================
# 取值表：四个格子逐个钉住
# ===========================================================================
def test_ai_room_is_ai(room):
    """★ 人机局 ⇒ `'ai'`（判据 `room.is_ai_room`，不是从 id 猜）。"""
    room.is_ai_room = True
    assert server._match_history_mode(room) == 'ai'


def test_ranked_room_is_ranked(room):
    """★ 排位局 ⇒ `'ranked'`。"""
    room.ranked = True
    assert server._match_history_mode(room) == 'ranked'


def test_matched_casual_room_is_casual(room):
    """★ 匹配出来的休闲局 ⇒ `'casual'`。"""
    room.matchmade = True
    room.ranked = False
    assert server._match_history_mode(room) == 'casual'


def test_custom_room_is_custom(room):
    """★ 自定义房 / 好友邀战 ⇒ `'custom'`（不是匹配出来的）。"""
    room.matchmade = False
    room.ranked = False
    assert server._match_history_mode(room) == 'custom'


def test_ai_wins_over_everything(room):
    """★ 优先级：人机房即使被标成 matchmade / ranked 也仍然是 `'ai'`。

    （线上人机房恒 `ranked=False`，但优先级必须写死 —— 免得将来某条路顺手置了别的标记，
    人机局就被标成排位局。）
    """
    room.is_ai_room = True
    room.ranked = True
    room.matchmade = True
    assert server._match_history_mode(room) == 'ai'


def test_missing_room_is_none_not_casual():
    """★★ 取不到房间 ⇒ `None`（= 落库写 NULL）。

    "不知道"**不能退化成"匹配"**（教训 #21）—— 那会让老数据/异常局在界面上
    显示成一个**确定的错**答案。
    """
    assert server._match_history_mode(None) is None


def test_all_values_are_in_the_declared_table(room):
    """★ 产出的值必须都在 `MATCH_HISTORY_MODES` 里（前端按这张表分支）。"""
    for flag in ({}, {'is_ai_room': True}, {'ranked': True}, {'matchmade': True}):
        for k, v in flag.items():
            setattr(room, k, v)
        assert server._match_history_mode(room) in server.MATCH_HISTORY_MODES
        for k in flag:
            setattr(room, k, False)


# ===========================================================================
# 与 `_room_match_mode` 永不矛盾（★ 教训 #1：同一判断不许两份实现）
# ===========================================================================
def test_history_mode_never_contradicts_game_state_mode(room):
    """★★★ `_match_history_mode` 说是排位 ⇔ `_room_match_mode` 说是排位。

    对局内 `game_state` 的 `mode` 字段走 `_room_match_mode`，战绩里的 `'ranked'`
    走本批新加的 `_match_history_mode` —— 两者必须是**同一个判断**的两个出口。
    不然会出现"结算屏写着排位赛、战绩里写着匹配"这种没人能复现的错。

    穷举四种标记组合 + 人机，两种口径逐一对齐。
    """
    combos = [
        {},
        {'ranked': True},
        {'matchmade': True},
        {'matchmade': True, 'ranked': True},
        {'is_ai_room': True},
        {'is_ai_room': True, 'matchmade': True},
        # ⚠️ `{'is_ai_room': True, 'ranked': True}` **故意不列**：那个组合在本项目里
        #    不可能出现（`create_ai_room` 显式 `room.ranked = False`），
        #    而"人机优先于排位"是本函数的**有意优先级**（见 `test_ai_wins_over_everything`）。
        #    把它列进来只会让这条守卫去断言一个不存在的状态。
    ]
    for combo in combos:
        room.ranked = False
        room.matchmade = False
        room.is_ai_room = False
        for k, v in combo.items():
            setattr(room, k, v)
        history = server._match_history_mode(room)
        game = server._room_match_mode(room)
        # **排位那个轴**两种口径必须一致（`custom`/`casual` 是战绩口径多出来的细分，
        # 它们在对局内都属于非排位 —— 这一点也在下面那条断言里钉住）。
        assert (history == 'ranked') == (game == 'ranked'), (
            '排位那个轴两种口径对不上：标记=%s，战绩=%s、对局内=%s' % (combo, history, game))
        if history != 'ai':
            assert history in (game, 'custom'), history
        else:
            # 人机局：战绩口径把人机排在排位**之前**（人机房恒 ranked=False，
            # 所以线上不会出现矛盾；这条只钉住优先级是写死的，不是碰巧）
            assert room.is_ai_room is True
    # 反向校准：非人机的那几种确实两种口径都算过（否则上面是空转）。
    # 这一间是**匹配出来的休闲房**（`matchmade=True`）⇒ 两种口径都是 casual。
    room.is_ai_room = room.ranked = False
    room.matchmade = True
    assert server._match_history_mode(room) == server._room_match_mode(room) == 'casual'
    # 自定义房只在**战绩口径**里细分出来，对局内一律 casual
    room.matchmade = False
    assert server._match_history_mode(room) == 'custom'
    assert server._room_match_mode(room) == 'casual'


def test_room_match_mode_itself_is_untouched():
    """★★ 本批**不许改** `_room_match_mode` / `_rank_payload`（对局内 payload 靠它们）。

    判据：那两个函数的函数体必须与"只看 room.ranked"这一句完全一致 ——
    多一个 `matchmade` / `is_ai_room` 分支就说明有人把两个轴混进对局内语义了。
    """
    src = io.open(SERVER_PY, encoding='utf-8').read()
    tree = ast.parse(src)
    bodies = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in ('_room_match_mode',
                                                               '_rank_payload'):
            bodies[node.name] = ast.get_source_segment(src, node) or ''
    assert set(bodies) == {'_room_match_mode', '_rank_payload'}
    for name, body in bodies.items():
        assert 'matchmade' not in body, '%s 里混进了 matchmade（那是战绩的轴）' % name
        assert 'is_ai_room' not in body, '%s 里混进了 is_ai_room（那是战绩的轴）' % name
    assert "getattr(room, 'ranked', False)" in bodies['_room_match_mode']


def test_match_history_mode_reuses_room_match_mode():
    """★★ 源码级：`_match_history_mode` 必须**调用** `_room_match_mode`，不许自己再判一次。"""
    src = io.open(SERVER_PY, encoding='utf-8').read()
    body = ''
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == '_match_history_mode':
            body = ast.get_source_segment(src, node) or ''
    assert body, 'server.py 里找不到 _match_history_mode'
    assert '_room_match_mode(room)' in body, \
        '排位这件事必须在 _match_history_mode 里**复用** _room_match_mode（教训 #1）'
    # 反向校准：它自己不许再写一遍 ranked 判据
    assert "getattr(room, 'ranked'" not in body, \
        '_match_history_mode 自己又判了一次 ranked —— 两份判据必然漂移'


# ===========================================================================
# `matchmade` 的置位点：源码级穷举 + 三条反例
# ===========================================================================
def _src():
    return io.open(SERVER_PY, encoding='utf-8').read()


def _pairing_loop_sources():
    """扫出所有**消费 `match_queue` 完成配对**的 while 循环（按缩进切块）。

    判据 = 代码里出现了 **两个** `match_queue.pop(` —— 配对要取**两个人**。
    （一个 pop 的是"出队"（`remove_from_match_queue` / `cancel_match`），不是配对；
    这条是实测校准出来的：第一版只用"出现 pop"当判据，把出队也扫进来了。）

    将来新增第二条匹配入口（比如按段位分池），它必然也要 pop 两个人，
    于是会被这条守卫扫到。
    """
    src = _src()
    lines = src.split('\n')
    blocks = []
    for i, line in enumerate(lines):
        if 'match_queue.pop(' not in line:
            continue
        indent = len(line) - len(line.lstrip())
        # 往上找那个 while（缩进更小的最近一行）
        start = i
        for j in range(i, -1, -1):
            stripped = lines[j].strip()
            if stripped.startswith('while ') and (len(lines[j]) - len(lines[j].lstrip())) < indent:
                start = j
                break
        # 往下找到缩进回到 while 那一层为止
        while_indent = len(lines[start]) - len(lines[start].lstrip())
        end = start + 1
        for k in range(start + 1, len(lines)):
            if not lines[k].strip():
                continue
            if (len(lines[k]) - len(lines[k].lstrip())) <= while_indent:
                break
            end = k
        block = '\n'.join(lines[start:end + 1])
        if block.count('match_queue.pop(') >= 2:      # 取两个人 = 配对
            blocks.append((start + 1, block))
    return blocks


def test_every_pairing_loop_sets_matchmade():
    """★★★ 源码级穷举：**每一个**配对循环都必须置 `room.matchmade = True`。

    漏一个的症状：那条路匹配出来的对局在战绩里被标成"自定义房"，
    而且**零报错**（没人会去比对"这一局其实是匹配打的"）。
    """
    blocks = _pairing_loop_sources()
    assert blocks, '一个配对循环都没扫到 —— 这条守卫自己失效了，必须修'
    for lineno, block in blocks:
        assert 'matchmade = True' in block, (
            '第 %d 行那个配对循环没有置 matchmade（那条匹配路的战绩会被标成自定义房）：\n%s'
            % (lineno, block))
    # 反向校准：确实扫到了那个真实的配对循环（它里面有 match_guard.pick_pair）
    assert any('match_guard.pick_pair' in b for _l, b in blocks), \
        '扫到的循环里没有真正的配对逻辑 —— 判据失效了'


def test_matchmade_true_appears_exactly_once_in_the_whole_file():
    """★ 「一处置位」也是契约：全文件只许有一处 `matchmade = True`。"""
    src = _src()
    hits = [i + 1 for i, line in enumerate(src.split('\n'))
            if 'matchmade = True' in line and not line.strip().startswith('#')]
    assert len(hits) == 1, 'matchmade = True 应当只有一处，实际在第 %s 行' % hits


def test_three_non_matching_paths_keep_matchmade_false():
    """★★ 反例：`create_room` / `create_ai_room` / 好友邀战建房**都必须是 False**。

    判据用**行为**（真的建一间房来看），不是看源码 ——
    `matchmade` 的初值在 `GameRoom.__init__` 里，任何一条路漏了都会在这里现形。
    """
    rid = room_manager.create_room()
    try:
        assert room_manager.get_room(rid).matchmade is False, '自定义房不该是匹配房'
    finally:
        room_manager.delete_room(rid)

    rid = room_manager.create_ai_room('human-x', '玩家', _account(), 'normal')
    try:
        assert room_manager.get_room(rid).matchmade is False, '人机房不该是匹配房'
    finally:
        room_manager.delete_room(rid)

    rid = server.create_custom_room_for_invite()
    try:
        assert room_manager.get_room(rid).matchmade is False, '好友邀战的房不该是匹配房'
    finally:
        room_manager.delete_room(rid)


def test_new_room_defaults_to_not_matchmade():
    """★ 三件齐：`GameRoom.__init__` 必须初始化这个字段（漏了会 AttributeError）。"""
    fresh = GameRoom('fresh-' + uuid.uuid4().hex[:6])
    assert fresh.matchmade is False


def test_matchmade_survives_the_shape_cross_check(room):
    """★★ 形状判据降级成**交叉校验**：将来谁改了 `room.players` 的 key 约定，
    是这条先红，而不是线上悄悄标错。

    形状判据（只用在这里，**不许进生产代码**）：
      * 匹配房：key 一律是入队时的 socket sid，真人账号只在 `Player.user_id` 上
        ⇒ `key != room.players[key].sid`；
      * 自定义房：key = `session['user_id']`（游客是入座 sid）⇒ `key == Player.sid`。

    这条用例断言"**匹配房形状**的房间被置 matchmade 之后确实是 casual"，
    并且形状判据与 `matchmade` 在两种形状上给出**同一批**答案。
    """
    # 匹配房形状（本 fixture）：key != Player.sid
    room.matchmade = True
    room.players['mode-sid-a'].sid = 'socket-conn-a'
    room.players['mode-sid-b'].sid = 'socket-conn-b'
    shape_says_match = all(pid != p.sid for pid, p in room.players.items())
    assert shape_says_match is True, '这个 fixture 应当长得像匹配房'
    assert server._match_history_mode(room) == 'casual'

    # 自定义房形状：key == Player.sid
    custom = GameRoom('custom-' + uuid.uuid4().hex[:6])
    custom.players['u1'] = Player(name='甲', ships=[], attacks=[], remaining_ships=0,
                                  sid='conn-1', user_id='u1')
    custom.players['u2'] = Player(name='乙', ships=[], attacks=[], remaining_ships=0,
                                  sid='conn-2', user_id='u2')
    shape_says_custom = bool(custom.players) and all(
        pid == p.sid or p.user_id == pid for pid, p in custom.players.items())
    assert shape_says_custom is True
    assert custom.matchmade is False
    assert server._match_history_mode(custom) == 'custom'


# ===========================================================================
# 落库 / 读回 / NULL 老行（§8 的 ①②③）
# ===========================================================================
def _last_match_id():
    return db_module.db.cursor.execute(
        'SELECT id FROM matches ORDER BY rowid DESC LIMIT 1').fetchone()['id']


def test_ranked_match_stores_ranked_in_the_database():
    """★★ 守卫①：**排位局**落库之后 `matches.mode = 'ranked'`。"""
    room = GameRoom('ranked-' + uuid.uuid4().hex[:6])
    room.ranked = True
    room.matchmade = True
    uid = _account()
    db_module.record_match(uid, _account(), logs=[{'text': 'x'}],
                           mode=server._match_history_mode(room))
    row = db_module.db.cursor.execute(
        'SELECT mode FROM matches WHERE id = ?', (_last_match_id(),)).fetchone()
    assert row['mode'] == 'ranked', row['mode']


def test_ai_match_stores_ai_in_the_database():
    """★★ 守卫②：**人机局**落库之后 `matches.mode = 'ai'`。"""
    room = GameRoom('ai-' + uuid.uuid4().hex[:6])
    room.is_ai_room = True
    uid = _account()
    db_module.record_match(uid, 'ai-xxxx', logs=[{'text': 'x'}],
                           mode=server._match_history_mode(room))
    row = db_module.db.cursor.execute(
        'SELECT mode FROM matches WHERE id = ?', (_last_match_id(),)).fetchone()
    assert row['mode'] == 'ai', row['mode']


def test_custom_and_casual_also_land_in_the_database():
    """★ 另外两个值也各落一次（别只测两个就以为四个都对）。"""
    for flag, expect in (({'matchmade': False}, 'custom'),
                         ({'matchmade': True}, 'casual')):
        room = GameRoom('x-' + uuid.uuid4().hex[:6])
        for k, v in flag.items():
            setattr(room, k, v)
        db_module.record_match(_account(), _account(), logs=[{'text': 'x'}],
                               mode=server._match_history_mode(room))
        row = db_module.db.cursor.execute(
            'SELECT mode FROM matches WHERE id = ?', (_last_match_id(),)).fetchone()
        assert row['mode'] == expect, (flag, row['mode'])


def test_old_rows_keep_null_and_are_not_backfilled():
    """★★★ 守卫③：**老数据**的 `mode` 是 NULL，读出来必须是 `None`，**不许兜底**。

    做法：造一条对局 → 把 `mode` 改回 NULL（模拟本批上线前的 342 行）→
    读战绩。判据是"原样给 None"，而不是 `'casual'`。

    ⚠️ 这是教训 #21 的形状：老数据是"**不知道**这一局是什么模式"，
       伪装成"匹配"就是一个确定的错答案（界面上 342 局全被标错）。
    """
    uid = _account()
    db_module.record_match(uid, _account(), logs=[{'text': 'x'}], mode='ranked')
    mid = _last_match_id()
    db_module.db.cursor.execute('UPDATE matches SET mode = NULL WHERE id = ?', (mid,))
    db_module.db.conn.commit()

    row = [h for h in db_module.get_match_history(uid, 5) if h['match_id'] == mid][0]
    assert 'mode' in row, 'history 每行都必须有 mode 键（老数据也要有）'
    assert row['mode'] is None, '老数据的 NULL 被兜底成了 %r' % row['mode']


def test_mode_column_migration_is_idempotent_and_upgrades_old_databases(tmp_path):
    """★★★ §8-12 的姊妹条：`matches.mode` 老表加列**幂等**，且老库能升级。

    ⚠️ `CREATE TABLE IF NOT EXISTS` 对已存在的表是**空操作** —— 生产库那 342 行
       所在的 `matches` 表只有 `ALTER TABLE` 一条路（教训 #14）。
       写错的症状是**线上 500**（读端一 SELECT 这一列就 no such column）。
    """
    import sqlite3
    path = tmp_path / 'old_matches.db'
    conn = sqlite3.connect(path)
    conn.executescript('''
        CREATE TABLE matches (id TEXT PRIMARY KEY, winner_id TEXT, loser_id TEXT,
                              timestamp INTEGER);
        INSERT INTO matches (id, winner_id, loser_id, timestamp)
        VALUES ('old-1', 'u1', 'u2', 1700000000);
    ''')
    conn.commit()
    conn.close()

    instance = db_module.Database()
    instance.close()
    instance.db_path = path
    instance.conn = sqlite3.connect(path, check_same_thread=False)
    instance.conn.row_factory = sqlite3.Row
    instance.cursor = instance.conn.cursor()
    instance.init_db()

    cols = {r[1] for r in instance.cursor.execute('PRAGMA table_info(matches)')}
    assert 'mode' in cols, '老库升级之后必须有这一列，否则线上 500'
    row = instance.cursor.execute(
        'SELECT mode FROM matches WHERE id = ?', ('old-1',)).fetchone()
    assert row['mode'] is None, '老行的 mode 必须是 NULL（不是 casual）'
    for _ in range(3):
        instance.init_db()              # 幂等
    assert instance.get_match_history('u1', 5)[0]['mode'] is None


def test_public_stats_still_work_with_null_mode():
    """★ 老行（NULL）走真接口不许崩 —— 前后端都要能优雅处理。"""
    uid = _account()
    db_module.record_match(uid, _account(), logs=[{'text': 'x'}])
    mid = _last_match_id()
    db_module.db.cursor.execute('UPDATE matches SET mode = NULL WHERE id = ?', (mid,))
    db_module.db.conn.commit()
    http = server.app.test_client()
    with http.session_transaction() as sess:
        sess['user_id'] = uid
        sess['username'] = uid
    resp = http.get('/user_stats')
    assert resp.status_code == 200, resp.get_data(as_text=True)
    row = [h for h in resp.get_json()['history'] if h['match_id'] == mid][0]
    assert row['mode'] is None
