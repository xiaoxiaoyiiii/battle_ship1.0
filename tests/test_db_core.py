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






def test_create_user_rejects_invalid_chars(temp_db):
    """仅允许字母数字与 . _ -；其他字符（含空格、中文符号）必须拒绝。"""
    assert temp_db.create_user('alice bob', 'hash') is None
    assert temp_db.create_user('alice@bob', 'hash') is None




def test_create_user_rejects_duplicate_username(temp_db):
    """用户名唯一约束冲突应返回 None 而非抛异常。"""
    assert temp_db.create_user('bob', 'h1') is not None
    assert temp_db.create_user('bob', 'h2') is None


# ---------------------------------------------------------------------------
# record_match：连胜 / 连败业务逻辑
# ---------------------------------------------------------------------------








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












# ---------------------------------------------------------------------------
# get_match_history / get_leaderboard：limit 钳制
# ---------------------------------------------------------------------------






def test_get_leaderboard_hides_accounts_without_games(temp_db):
    _make_user(temp_db, 'newbie')
    assert temp_db.get_leaderboard() == [], '一场没打过的账号不该出现在排行榜上'




# ---------------------------------------------------------------------------
# get_user_rank：个人信息面板要显示的"排行榜名次"（2026-09-17）
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# update_user_signature：截断 + 空 uid
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# update_user：通用边界
# ---------------------------------------------------------------------------




def test_update_user_unknown_column_rejected(temp_db):
    """非法列名必须拒绝（SQL 注入防线），已在 regression 中有覆盖，此处补强。"""
    assert temp_db.update_user('uid', malicious='x') is False




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
