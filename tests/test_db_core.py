# -*- coding: utf-8 -*-
"""db 核心数据层回归测试。

db.py 是被 api.py / server.py 广泛依赖的核心模块，但既有测试仅覆盖了
update_user 的列名白名单。本文件补齐其中涉及数据校验、连胜业务逻辑、
输入截断与 limit 钳制的关键路径，这些都是回归高风险区。

每个测试使用独立的临时数据库实例，保证确定性与隔离。
"""
import sqlite3

import pytest

import db as db_module
from db import Database


@pytest.fixture
def temp_db(tmp_path):
    """在临时文件上构造一个全新的 Database 实例，避免污染真实库。"""
    instance = Database()
    instance.close()
    instance.db_path = tmp_path / 'test.db'
    instance.conn = sqlite3.connect(instance.db_path, check_same_thread=False)
    instance.conn.row_factory = sqlite3.Row
    instance.cursor = instance.conn.cursor()
    instance.init_db()
    return instance


def _make_user(db, username='alice', password_hash='hash'):
    uid = db.create_user(username, password_hash)
    assert uid is not None
    return uid


# ---------------------------------------------------------------------------
# create_user：用户名校验
# ---------------------------------------------------------------------------
def test_create_user_rejects_short_username(temp_db):
    """用户名长度 < 3 必须拒绝（存储层二次校验，不依赖前端）。"""
    assert temp_db.create_user('ab', 'hash') is None


def test_create_user_rejects_empty_username(temp_db):
    assert temp_db.create_user('', 'hash') is None


def test_create_user_rejects_empty_password(temp_db):
    assert temp_db.create_user('alice', '') is None


def test_create_user_rejects_invalid_chars(temp_db):
    """仅允许字母数字与 . _ -；其他字符（含空格、中文符号）必须拒绝。"""
    assert temp_db.create_user('alice bob', 'hash') is None
    assert temp_db.create_user('alice@bob', 'hash') is None


def test_create_user_accepts_valid_chars(temp_db):
    """合法字符集（字母数字 . _ -）可正常创建并返回 uuid。"""
    uid = temp_db.create_user('a.b-c_d1', 'hash')
    assert uid is not None
    assert temp_db.get_user(uid=uid)['username'] == 'a.b-c_d1'


def test_create_user_rejects_duplicate_username(temp_db):
    """用户名唯一约束冲突应返回 None 而非抛异常。"""
    assert temp_db.create_user('bob', 'h1') is not None
    assert temp_db.create_user('bob', 'h2') is None


# ---------------------------------------------------------------------------
# record_match：连胜 / 连败业务逻辑
# ---------------------------------------------------------------------------
def test_record_match_increments_winner_streak(temp_db):
    """胜者 current_streak +1，wins +1，longest_streak 同步刷新。"""
    w = _make_user(temp_db, 'winner')
    l = _make_user(temp_db, 'loser')
    assert temp_db.record_match(w, l) is True
    row = temp_db.get_user(uid=w)
    assert row['wins'] == 1
    assert row['current_streak'] == 1
    assert row['longest_streak'] == 1


def test_record_match_resets_loser_streak(temp_db):
    """败者 current_streak 归零，losses +1。"""
    w = _make_user(temp_db, 'winner')
    l = _make_user(temp_db, 'loser')
    # 先让 loser 赢两局建立连胜
    temp_db.record_match(l, w)
    temp_db.record_match(l, w)
    # 再输一局
    temp_db.record_match(w, l)
    row = temp_db.get_user(uid=l)
    assert row['losses'] == 1
    assert row['current_streak'] == 0


def test_record_match_updates_longest_streak(temp_db):
    """longest_streak 应取历史最大值，不因后续失败而回退。"""
    w = _make_user(temp_db, 'winner')
    l1 = _make_user(temp_db, 'loser1')
    l2 = _make_user(temp_db, 'loser2')
    temp_db.record_match(w, l1)
    temp_db.record_match(w, l2)
    row = temp_db.get_user(uid=w)
    assert row['longest_streak'] == 2
    # 输掉一局后 longest 仍应保持 2
    temp_db.record_match(l1, w)
    row = temp_db.get_user(uid=w)
    assert row['longest_streak'] == 2
    assert row['current_streak'] == 0


def test_record_match_handles_guest_ids(temp_db):
    """游客（users 表中不存在的 id）参赛：比赛可记录，但不更新 stats。"""
    assert temp_db.record_match('guest-winner', 'guest-loser') is True
    # 游客不存在，get_user 返回 None
    assert temp_db.get_user(uid='guest-winner') is None


def test_record_match_rejects_empty_ids(temp_db):
    assert temp_db.record_match('', 'loser') is False
    assert temp_db.record_match('winner', '') is False


def test_record_match_persists_logs(temp_db):
    """logs 参数应被序列化存入 match_logs，并可通过历史查询还原。"""
    w = _make_user(temp_db, 'winner')
    l = _make_user(temp_db, 'loser')
    logs = [{'turn': 1, 'event': 'attack'}]
    assert temp_db.record_match(w, l, logs=logs) is True
    history = temp_db.get_match_history(w)
    assert len(history) == 1
    assert history[0]['logs'] == logs


# ---------------------------------------------------------------------------
# get_chat_messages / add_chat_message：输入截断 + limit 钳制
# ---------------------------------------------------------------------------
def test_add_chat_message_truncates_content(temp_db):
    """内容超过 500 字应被截断，避免单行过大。"""
    assert temp_db.add_chat_message('u1', 'name', 'x' * 600) is True
    msgs = temp_db.get_chat_messages()
    assert len(msgs[0]['content']) == 500


def test_add_chat_message_truncates_username(temp_db):
    """用户名超过 50 字应被截断。"""
    assert temp_db.add_chat_message('u1', 'n' * 100, 'hi') is True
    msgs = temp_db.get_chat_messages()
    assert len(msgs[0]['username']) == 50


def test_add_chat_message_default_username(temp_db):
    """用户名为空时落库为「匿名」。"""
    assert temp_db.add_chat_message('u1', None, 'hi') is True
    msgs = temp_db.get_chat_messages()
    assert msgs[0]['username'] == '匿名'


def test_add_chat_message_rejects_empty_content(temp_db):
    assert temp_db.add_chat_message('u1', 'name', '') is False
    assert temp_db.get_chat_messages() == []


def test_get_chat_messages_clamps_limit(temp_db):
    """limit 必须钳制在 1-100，负数/零/超大值不得破坏查询。"""
    for i in range(5):
        temp_db.add_chat_message(f'u{i}', f'n{i}', f'msg{i}')
    assert len(temp_db.get_chat_messages(limit=0)) >= 1
    assert len(temp_db.get_chat_messages(limit=-5)) >= 1
    assert len(temp_db.get_chat_messages(limit=9999)) == 5


def test_get_chat_messages_returns_oldest_first(temp_db):
    """查询结果应为时间正序（最新的在末尾）。"""
    for i in range(3):
        temp_db.add_chat_message('u', 'n', f'msg{i}')
    msgs = temp_db.get_chat_messages()
    assert [m['content'] for m in msgs] == ['msg0', 'msg1', 'msg2']


# ---------------------------------------------------------------------------
# get_match_history / get_leaderboard：limit 钳制
# ---------------------------------------------------------------------------
def test_get_match_history_clamps_limit(temp_db):
    w = _make_user(temp_db, 'win')
    l = _make_user(temp_db, 'lose')
    for _ in range(5):
        temp_db.record_match(w, l)
    # 超限应被钳制，不应报错
    assert len(temp_db.get_match_history(w, limit=9999)) == 5
    assert len(temp_db.get_match_history(w, limit=0)) >= 1


def test_get_match_history_empty_uid(temp_db):
    assert temp_db.get_match_history('') == []


def test_get_leaderboard_clamps_limit(temp_db):
    # 每个账号都要真打过一局才会进榜（0 局账号会被过滤，见 db._get_leaderboard）
    winner = _make_user(temp_db, 'winner0')
    for i in range(4):
        other = _make_user(temp_db, f'user{i}')
        temp_db.record_match(winner, other)
    assert len(temp_db.get_leaderboard(limit=9999)) == 5
    assert len(temp_db.get_leaderboard(limit=0)) >= 1


def test_get_leaderboard_hides_accounts_without_games(temp_db):
    _make_user(temp_db, 'newbie')
    assert temp_db.get_leaderboard() == [], '一场没打过的账号不该出现在排行榜上'


def test_get_leaderboard_orders_by_wins(temp_db):
    w = _make_user(temp_db, 'winner')
    l = _make_user(temp_db, 'loser')
    temp_db.record_match(w, l)
    board = temp_db.get_leaderboard()
    assert board[0]['username'] == 'winner'
    assert board[0]['wins'] == 1


# ---------------------------------------------------------------------------
# update_user_signature：截断 + 空 uid
# ---------------------------------------------------------------------------
def test_update_user_signature_truncates(temp_db):
    uid = _make_user(temp_db)
    assert temp_db.update_user_signature(uid, 's' * 600) is True
    assert len(temp_db.get_user_profile(uid)['signature']) == 500


def test_update_user_signature_rejects_empty_uid(temp_db):
    assert temp_db.update_user_signature('', 'sig') is False


def test_update_user_signature_handles_none(temp_db):
    uid = _make_user(temp_db)
    # signature 为 None 时应存空串而非崩溃
    assert temp_db.update_user_signature(uid, None) is True
    assert temp_db.get_user_profile(uid)['signature'] == ''


# ---------------------------------------------------------------------------
# update_user：通用边界
# ---------------------------------------------------------------------------
def test_update_user_empty_kwargs_returns_true(temp_db):
    """无字段更新时应直接返回 True（幂等空操作）。"""
    assert temp_db.update_user('any-uid') is True


def test_update_user_empty_uid_returns_false(temp_db):
    assert temp_db.update_user('', signature='x') is False


def test_update_user_unknown_column_rejected(temp_db):
    """非法列名必须拒绝（SQL 注入防线），已在 regression 中有覆盖，此处补强。"""
    assert temp_db.update_user('uid', malicious='x') is False


def test_update_user_accepts_allowed_column(temp_db):
    uid = _make_user(temp_db)
    assert temp_db.update_user(uid, signature='hello') is True
    assert temp_db.get_user_profile(uid)['signature'] == 'hello'


# ---------------------------------------------------------------------------
# get_user_by_token / get_token_by_password：token 链路
# ---------------------------------------------------------------------------
def test_token_round_trip(temp_db):
    """用密码换 token，再用 token 反查用户应一致。"""
    from werkzeug.security import generate_password_hash
    uid = _make_user(temp_db, 'tokenuser', generate_password_hash('secret'))
    token = temp_db.get_token_by_password('tokenuser', 'secret')
    assert token is not None
    user = temp_db.get_user_by_token(token)
    assert user is not None
    assert user['id'] == uid


def test_get_token_by_password_rejects_wrong_password(temp_db):
    from werkzeug.security import generate_password_hash
    _make_user(temp_db, 'tokenuser2', generate_password_hash('secret'))
    assert temp_db.get_token_by_password('tokenuser2', 'wrong') is None


def test_get_user_by_token_empty(temp_db):
    assert temp_db.get_user_by_token('') is None
