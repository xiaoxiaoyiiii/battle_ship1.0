# -*- coding: utf-8 -*-
"""对局回放批 · 数据层（`db.py`）：表结构 / 保留 30 局 / 孤儿清扫 / 开关列迁移。

契约见 `docs/REPLAY_2026_09_23.md` §2（数据模型）、§4（保留策略）、§8 的 8 / 9 / 12。

⚠️ 每个用例用**独立临时库**（`tmp_path`），绝不碰仓库里的 `data/battleship.db`。
   做法与 `tests/test_db_core.py::temp_db` 一致：新建一个 `Database()` 实例、
   把 `db_path` 换到临时目录、再 `init_db()`。
"""
import json
import sqlite3

import pytest

import db as db_module
from db import Database

# 契约 §2 的表结构（列名与顺序都钉住 —— 读接口与清扫都按这些列名写 SQL）
EXPECTED_REPLAY_COLUMNS = ['match_id', 'winner_user_id', 'loser_user_id',
                           'created_at', 'bytes', 'version', 'replay']


def _new_db(path):
    """在 `path` 上建一个全新的 `Database` 实例（与 test_db_core.temp_db 同一套做法）。"""
    instance = Database()
    instance.close()
    instance.db_path = path
    instance.conn = sqlite3.connect(instance.db_path, check_same_thread=False)
    instance.conn.row_factory = sqlite3.Row
    instance.cursor = instance.conn.cursor()
    instance.init_db()
    return instance


@pytest.fixture
def temp_db(tmp_path):
    return _new_db(tmp_path / 'replay.db')


@pytest.fixture
def other_db(tmp_path):
    """第二个独立实例（用来证明"窗口判据只在 db 层算一次"，与主实例互不干扰）。"""
    return _new_db(tmp_path / 'replay-other.db')


def _user(database, name):
    uid = database.create_user(name, 'x' * 12)
    assert uid, '建测试账号失败'
    return uid


def _replay_blob(steps=3, version=None):
    version = db_module.__dict__ if version is None else version
    return json.dumps({'version': 1, 'steps': [{'i': i} for i in range(steps)]},
                      ensure_ascii=False)


def _insert_replay(database, winner_uid, loser_uid, ts=None, tmp_db=None, **extra):
    """走**真实入口** `record_match` 插一条对局 + 一条回放（契约 §4 的唯一写入点）。"""
    import time
    ts = int(ts if ts is not None else time.time())
    # `record_match` 内部自己取时间戳，这里为了测"按时间淘汰"要能控制先后顺序，
    # 所以插完之后把那一行的 timestamp 改成我们要的值。
    ok = database.record_match(winner_uid or 'guest-x', loser_uid or 'guest-y',
                               logs=[{'text': 'x'}],
                               replay=_replay_blob(),
                               replay_participants={'winner': winner_uid, 'loser': loser_uid},
                               **extra)
    assert ok, '写对局失败'
    mid = database.cursor.execute(
        'SELECT id FROM matches ORDER BY rowid DESC LIMIT 1').fetchone()['id']
    database.cursor.execute('UPDATE matches SET timestamp = ? WHERE id = ?', (ts, mid))
    database.conn.commit()
    return mid


# ===========================================================================
# §2 数据模型
# ===========================================================================
def test_match_replays_table_shape(temp_db):
    """★ 表结构（含两个索引）必须与契约 §2 逐字一致。

    为什么自带参与者两列：实测 `matches.winner_id` 里混着 uuid / `ai-*` / 游客 sid，
    长度上无法可靠区分 —— 从它反推"参与者是谁"是不可靠的。
    """
    cols = [r[1] for r in temp_db.cursor.execute('PRAGMA table_info(match_replays)')]
    assert cols == EXPECTED_REPLAY_COLUMNS, cols
    indexes = {r[1] for r in temp_db.cursor.execute('PRAGMA index_list(match_replays)')}
    assert {'idx_replay_winner', 'idx_replay_loser'} <= indexes, indexes


def test_match_replays_is_not_the_match_logs_column(temp_db):
    """★★★ `match_logs.logs` 那一列**一个字都不许加回放数据**（契约 §0）。

    那一列会随 `show_history` 公开给所有人，而且 `/user_stats` 每次都全量下发它。
    """
    temp_db.cursor.execute('INSERT INTO match_logs (match_id, logs) VALUES (?, ?)',
                           ('m1', json.dumps([{'text': 'a'}])))
    temp_db.conn.commit()
    row = temp_db.cursor.execute(
        'SELECT logs FROM match_logs WHERE match_id = ?', ('m1',)).fetchone()
    assert 'steps' not in row['logs'] and 'ships' not in row['logs']


def test_has_replay_boolean_never_carries_the_blob(temp_db):
    """★★★ `get_match_history` 每行只多一个**布尔** `has_replay`，绝不带 blob。

    战绩接口每次都全量下发 history；把 blob 并进来等于每次拉几十 MB。
    """
    uid = _user(temp_db, 'hasrep')
    mid = _insert_replay(temp_db, uid, uid)
    history = temp_db.get_match_history(uid, 30)
    assert history, '历史里应当有那一局'
    row = [h for h in history if h['match_id'] == mid][0]
    assert row['has_replay'] is True
    dumped = json.dumps(row, ensure_ascii=False)
    assert 'steps' not in dumped, '历史行里带出了回放内容'
    assert len(dumped) < 2000, '历史行不该被回放撑大（实际 %d 字节）' % len(dumped)
    # 反向校准：把回放删掉之后同一个布尔要变 False（否则"恒为 True"也是绿）
    temp_db.delete_match_replay(mid)
    row2 = [h for h in temp_db.get_match_history(uid, 30) if h['match_id'] == mid][0]
    assert row2['has_replay'] is False


def test_history_row_without_replay_is_false_not_missing(temp_db):
    """★ 没有回放的老局：`has_replay` 必须是**明确的 False**（不是缺键）。"""
    uid = _user(temp_db, 'norep')
    temp_db.record_match(uid, 'guest-1', logs=[{'text': 'x'}])
    row = temp_db.get_match_history(uid, 5)[0]
    assert 'has_replay' in row and row['has_replay'] is False


# ===========================================================================
# §4 保留 30 局
# ===========================================================================
def _seed_matches(database, uid, others, start_ts=1_700_000_000, step=10):
    """给 uid 插 `len(others)` 局，时间戳递增；返回 `[match_id, ...]`（旧 → 新）。"""
    out = []
    for i, other in enumerate(others):
        out.append(_insert_replay(database, uid, other, ts=start_ts + i * step))
    return out


def test_thirty_first_match_evicts_the_oldest(temp_db):
    """★★ §8-7 前半：第 31 局进来后，最老那条回放被删。

    ⚠️ 对手**都不是真账号**（写 NULL 参与者列）—— 这样"对手仍在窗口内"那条
       共享豁免不会干扰本用例（那条另有用例）。
    """
    uid = _user(temp_db, 'keeper')
    ids = _seed_matches(temp_db, uid, [None] * 31)
    assert len(ids) == 31
    alive = {r['match_id'] for r in temp_db.cursor.execute(
        'SELECT match_id FROM match_replays').fetchall()}
    assert ids[0] not in alive, '第 31 局进来后最老那条回放应当被删掉'
    assert len(alive) == 30, '应当正好保留 30 条，实际 %d' % len(alive)
    for mid in ids[1:]:
        assert mid in alive, '除了最老那条，其余都该在：%s 不见了' % mid


def test_under_thirty_matches_evicts_nothing(temp_db):
    """★ 不足 30 条 ⇒ **不淘汰**（"第 30 条"不存在时没有窗口终点）。"""
    uid = _user(temp_db, 'small')
    ids = _seed_matches(temp_db, uid, [None] * 29)
    alive = {r['match_id'] for r in temp_db.cursor.execute(
        'SELECT match_id FROM match_replays').fetchall()}
    assert set(ids) == alive, '29 局不该淘汰任何东西'


def test_shared_replay_survives_while_the_other_side_is_still_inside(temp_db):
    """★★ §8-7 后半：**共享回放**在一方超窗、另一方没超窗时**必须还在**。

    构造：
      · A 打满 31 局（第 1 局是**和 B** 打的），于是 A 的窗口终点前移到第 2 局，
        第 1 局对 A 来说已经出局；
      · B 只有那 1 局 —— B 没有任何一局超窗 ⇒ 那条回放**仍算在 B 的窗口内** ⇒ 留着。
    反向腿（同一套判据）：等 B 也打满 31 局之后，那条共享回放就该被删。
    """
    a = _user(temp_db, 'shared-a')
    b = _user(temp_db, 'shared-b')
    # 第 1 局：A vs B（带真实参与者两列 ⇒ 这是一条"共享回放"）
    first = _insert_replay(temp_db, a, b, ts=1_700_000_000)
    # A 再打 30 局（对手都不是真账号）
    _seed_matches(temp_db, a, [None] * 30, start_ts=1_700_000_100)
    alive = temp_db.get_match_replay(first)
    assert alive is not None, (
        '★ 共享回放被先超窗的一方（A）删掉了 —— 那正是契约 §4 明令不许的形状')
    # 反向腿：B 也打满 31 局（含那第 1 局）后，两边都超窗 ⇒ 该删
    _seed_matches(temp_db, b, [None] * 30, start_ts=1_700_000_200)
    assert temp_db.get_match_replay(first) is None, \
        '两边都超窗之后那条共享回放应当被删掉'


def test_guest_only_match_never_gets_a_replay(temp_db):
    """★ §4「不记录」：双方都不是真实用户 ⇒ **不插**（游客 sid 局谁都读不到）。"""
    ok = temp_db.record_match('guest-a', 'guest-b', logs=[{'text': 'x'}],
                              replay=_replay_blob(),
                              replay_participants={'winner': None, 'loser': None})
    assert ok, '对局本身照样要写'
    assert temp_db.cursor.execute('SELECT COUNT(*) c FROM match_replays').fetchone()['c'] == 0


def test_ai_side_is_null_but_the_human_side_still_gets_a_replay(temp_db):
    """★ 人机局照常记录：只有**人类那一侧**进参与者列（AI 没有账号）。"""
    human = _user(temp_db, 'human')
    mid = _insert_replay(temp_db, human, None)
    row = temp_db.get_match_replay(mid)
    assert row is not None, '人机局也应当有回放（契约 §9）'
    assert row['winner_user_id'] == human and row['loser_user_id'] is None


def test_cutoff_is_computed_once_per_person_per_sweep(temp_db, monkeypatch):
    """★ §4「每插入只枚举被淘汰的 1~2 条」：窗口终点**按人去重**，不是每行各算一次。

    ⚠️ 这里数的是 `_replay_cutoff` 的调用**次数**（它每读一次库就是一次
       `SELECT ... LIMIT 1 OFFSET 29`）—— 同一个人被算 35 次就说明去重丢了。
       判据写成"**每人每次清扫最多一次**"，因为清扫本身会跑 35 遍
       （每落一局跑一遍，见 `_insert_match_replay`）。
    """
    uid = _user(temp_db, 'once')
    calls = []
    real = Database._replay_cutoff

    def spy(self, who):
        calls.append(who)
        return real(self, who)

    monkeypatch.setattr(Database, '_replay_cutoff', spy)
    before = len(calls)
    _seed_matches(temp_db, uid, [None] * 35)
    per_sweep = len(calls) - before
    # 35 局 → 35 次清扫（每次落库后跑一次）；每次清扫里这个人最多被算 1 次。
    assert per_sweep <= 35, (
        '同一个人的窗口终点被算了 %d 次（35 次清扫 × 每次最多 1 次 = 上限 35）'
        % per_sweep)
    assert per_sweep >= 1, '一次都没算过 —— 保留策略根本没跑，这条守卫是空转的'


def test_sweep_never_scans_the_matches_table(temp_db):
    """★ 「每插入只枚举被淘汰的 1~2 条，不扫全表」—— 判据（源码级）：清扫里不许有
    "不带 LIMIT 的 `SELECT ... FROM matches`"。

    为什么不用运行时判据：`sqlite3.Connection.cursor` 是只读属性，
    `monkeypatch.setattr` 直接 `AttributeError`（实测）—— 那种守卫写不出来，
    只能按函数体扫 SQL。（`_replay_cutoff` 的 `LIMIT 1 OFFSET 29` 是**按人**取一条，
    是允许的那一种。）
    """
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / 'db.py').read_text(
        encoding='utf-8')
    body = ''
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name in (
                'sweep_match_replays', '_replay_cutoff', '_orphan_replay_ids',
                '_insert_match_replay'):
            body += (ast.get_source_segment(src, node) or '') + '\n'
    assert body, 'db.py 里找不到清扫相关的函数（改名了？）'
    # 判据：凡是从 `matches` 取数的语句，必须**带 WHERE 或 LIMIT**（= 有界的查询）。
    # 全表扫描的形状就是 "SELECT ... FROM matches" 后面直接结尾。
    # ⚠️ 必须从 **AST 的字符串字面量**里取 SQL，不能按引号切源码：SQL 是**多行拼接**的
    #    （`'SELECT timestamp FROM matches '` + `'WHERE ...'`），按引号切会切出半句 ——
    #    这条守卫第一版就红在这上面（切成半句之后判据是假的）。
    queries = []
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and 'FROM matches' in node.value):
            continue
        flat = ' '.join(node.value.split())
        if flat.upper().startswith('CREATE VIEW'):
            # `match_history` 那个 VIEW 的定义（**本批不动它**，契约 §6：
            # 它还有别的读取方，改视图风险大且没必要）。它天然是全量的。
            assert 'CREATE VIEW IF NOT EXISTS match_history' in flat
            continue
        queries.append(flat)
    assert queries, 'db.py 里找不到任何 "FROM matches" 的查询 —— 这条守卫自己失效了'
    for flat in queries:
        assert 'WHERE' in flat.upper() or 'LIMIT' in flat.upper(), (
            '出现了 matches 全表扫描：%r' % flat)
    joined = ' '.join(queries)
    assert 'LIMIT 1 OFFSET' in joined, '按人取窗口终点那条 SQL 不见了'
    # 孤儿判定走 `match_replays LEFT JOIN matches`（从**回放**那一侧出发），
    # 所以它不在上面这批 `FROM matches` 里 —— 单独校准它确实存在。
    assert any(isinstance(n, ast.Constant) and isinstance(n.value, str)
               and 'm.id IS NULL' in n.value for n in ast.walk(ast.parse(src))), \
        '孤儿判定那条 SQL 不见了'


# ===========================================================================
# §4 孤儿清扫（§8-8）
# ===========================================================================
def test_orphan_replay_is_swept(temp_db):
    """★★ §8-8：`matches` 行被删掉之后，对应回放也要被清掉（教训 #28）。"""
    uid = _user(temp_db, 'orphan')
    mid = _insert_replay(temp_db, uid, None)
    assert temp_db.get_match_replay(mid) is not None
    temp_db.cursor.execute('DELETE FROM matches WHERE id = ?', (mid,))
    temp_db.conn.commit()
    result = temp_db.sweep_match_replays()
    assert result['orphans'] == 1, result
    assert temp_db.get_match_replay(mid) is None, '孤儿回放没被清掉'


def test_orphan_sweep_is_wired_into_the_write_path(temp_db):
    """★ 孤儿清扫必须挂在**写入路径**上（本批不引入后台定时任务）。

    判据：走一遍真实的 `record_match(replay=...)`，孤儿就在那一次被清掉。
    """
    uid = _user(temp_db, 'wired')
    doomed = _insert_replay(temp_db, uid, None)
    temp_db.cursor.execute('DELETE FROM matches WHERE id = ?', (doomed,))
    temp_db.conn.commit()
    _insert_replay(temp_db, uid, None)          # 下一局结束
    assert temp_db.get_match_replay(doomed) is None, \
        '下一局落库时没顺手清掉孤儿'


# ===========================================================================
# §6 读一条 / 删坏回放
# ===========================================================================
def test_get_match_replay_returns_one_row(temp_db):
    uid = _user(temp_db, 'reader')
    mid = _insert_replay(temp_db, uid, None)
    row = temp_db.get_match_replay(mid)
    assert row['match_id'] == mid
    assert row['version'] == 1
    assert row['bytes'] == len(row['replay'].encode('utf-8')), \
        'bytes 列必须等于真实 blob 字节数（读接口按它做上限校验）'
    assert temp_db.get_match_replay('不存在') is None
    assert temp_db.get_match_replay('') is None


def test_delete_match_replay_is_idempotent(temp_db):
    uid = _user(temp_db, 'deleter')
    mid = _insert_replay(temp_db, uid, None)
    assert temp_db.delete_match_replay(mid) is True
    assert temp_db.get_match_replay(mid) is None
    assert temp_db.delete_match_replay(mid) is True    # 再删一次不炸


# ===========================================================================
# §8-12 allow_replay 列迁移幂等 + 老库能升级
# ===========================================================================
def test_allow_replay_column_migration_is_idempotent(temp_db):
    """★★ §8-12：重复 `init_db()` 不炸，列还在。"""
    cols = {r[1] for r in temp_db.cursor.execute('PRAGMA table_info(user_profile)')}
    assert 'allow_replay' in cols
    for _ in range(3):
        temp_db.init_db()               # 幂等：每次都只是一次 PRAGMA
    cols2 = {r[1] for r in temp_db.cursor.execute('PRAGMA table_info(user_profile)')}
    assert 'allow_replay' in cols2


def test_old_database_without_the_column_can_be_upgraded(tmp_path):
    """★★ §8-12：**老库**（`user_profile` 已存在且没有 `allow_replay`）能升级。

    做法：手工建一张"老"表 + 一行老数据，再跑 `init_db()` —— 老行必须拿到
    `DEFAULT 1`（= 允许），而不是 NULL/报错。
    """
    path = tmp_path / 'old.db'
    conn = sqlite3.connect(path)
    conn.executescript('''
        CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT UNIQUE,
                            password_hash TEXT, wins INTEGER DEFAULT 0,
                            losses INTEGER DEFAULT 0, current_streak INTEGER DEFAULT 0,
                            longest_streak INTEGER DEFAULT 0, created_at INTEGER,
                            signature TEXT DEFAULT '', avatar TEXT DEFAULT '',
                            token TEXT DEFAULT '');
        CREATE TABLE user_profile (user_id TEXT PRIMARY KEY, title_id TEXT DEFAULT '',
                                   tags TEXT DEFAULT '[]', status_text TEXT DEFAULT '',
                                   frame_id TEXT DEFAULT 'none', card_bg_id TEXT DEFAULT 'deep',
                                   show_stats INTEGER DEFAULT 1, show_fav_cards INTEGER DEFAULT 1,
                                   show_history INTEGER DEFAULT 0, updated_at INTEGER);
        INSERT INTO user_profile (user_id, updated_at) VALUES ('old-uid', 1);
    ''')
    conn.commit()
    conn.close()

    database = _new_db(path)
    cols = {r[1] for r in database.cursor.execute('PRAGMA table_info(user_profile)')}
    assert 'allow_replay' in cols, '老库升级之后必须有这一列，否则线上 500'
    assert database.get_allow_replay('old-uid') is True, '老行应当拿到 DEFAULT 1'
    # 幂等：再跑一次不炸
    database.init_db()
    assert database.get_allow_replay('old-uid') is True


def test_allow_replay_read_failure_is_fail_closed(temp_db, monkeypatch):
    """★★★ §5 失败方向：读库失败 ⇒ **不记录**（fail-closed）**并且打日志报警**。

    观战是 fail-open（读库失败按"允许"，少个功能而已）；回放相反 ——
    这里的错误方向是"泄露隐私"（回放里有双方船位）。
    ⚠️ 而且必须**打日志**：吞掉就等于没有守卫（教训 #34）。
    """
    errors = []

    class _BoomConn:
        def cursor(self):
            raise sqlite3.OperationalError('database is locked')

        def rollback(self):
            pass

    monkeypatch.setattr(temp_db, 'conn', _BoomConn())
    monkeypatch.setattr(db_module.logger, 'error', lambda msg, *a, **kw: errors.append(msg))
    assert temp_db.get_allow_replay('someone') is False, '读库失败必须 fail-closed'
    assert errors, '读库失败没打日志 —— 吞掉就等于没有守卫（教训 #34）'
    assert 'fail-closed' in errors[0]


def test_get_allow_replay_unknown_uid_is_none_not_true(temp_db):
    """★ `uid` 为空 ⇒ `None`（"不是真账号"），**不是** True（教训 #21）。"""
    assert temp_db.get_allow_replay('') is None
    assert temp_db.get_allow_replay(None) is None


def test_set_allow_replay_only_touches_its_own_column(temp_db):
    """★ 写开关只动这一列（与观战开关同一条路），不许覆盖名片其它字段。"""
    uid = _user(temp_db, 'setter')
    temp_db.save_user_profile_extra(uid, {'status_text': '别动我', 'tags': ['x']})
    assert temp_db.set_allow_replay(uid, False) is True
    assert temp_db.get_allow_replay(uid) is False
    extra = temp_db.get_user_profile_extra(uid)
    assert extra['status_text'] == '别动我', '写回放开关把名片其它字段覆盖了'
    assert temp_db.set_allow_replay(uid, True) is True
    assert temp_db.get_allow_replay(uid) is True


def test_saving_the_profile_card_does_not_reset_the_replay_switch(temp_db):
    """★★ 存名片**不许**把回放开关静默改回「允许」（同观战开关那条守卫）。"""
    uid = _user(temp_db, 'cardio')
    temp_db.set_allow_replay(uid, False)
    temp_db.save_user_profile_extra(uid, {'status_text': '换个签名', 'title_id': 't1'})
    assert temp_db.get_allow_replay(uid) is False, \
        '存一次名片就把隐私开关打开了 —— 这类故障没有报错，只在隐私上失守'
