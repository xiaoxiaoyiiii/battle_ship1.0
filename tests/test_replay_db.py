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






# ===========================================================================
# §4 孤儿清扫（§8-8）
# ===========================================================================




# ===========================================================================
# §6 读一条 / 删坏回放
# ===========================================================================




# ===========================================================================
# §8-12 allow_replay 列迁移幂等 + 老库能升级
# ===========================================================================


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






def test_saving_the_profile_card_does_not_reset_the_replay_switch(temp_db):
    """★★ 存名片**不许**把回放开关静默改回「允许」（同观战开关那条守卫）。"""
    uid = _user(temp_db, 'cardio')
    temp_db.set_allow_replay(uid, False)
    temp_db.save_user_profile_extra(uid, {'status_text': '换个签名', 'title_id': 't1'})
    assert temp_db.get_allow_replay(uid) is False, \
        '存一次名片就把隐私开关打开了 —— 这类故障没有报错，只在隐私上失守'
