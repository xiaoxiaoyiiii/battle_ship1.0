# -*- coding: utf-8 -*-
r"""个人信息名片（第 1 批）回归测试 —— 对应 `docs/PROFILE_CARD_2026_09_17_PLAN.md` §4.2。

覆盖三块：
  1. `profile_spec.py` 的解锁规则与边界（纯函数，不碰库）
  2. `POST /api/profile/card` 的逐项校验（**服务端裁决**，前端灰掉不算数）
  3. `/user_stats` 的公开字段 + 隐私过滤 + 凭证不下发

⚠️ 跑测试必须重定向临时目录（本机 `%LOCALAPPDATA%\Temp\pytest-of-Administrator`
的 ACL 坏了，不重定向会有一批用例在 setup 阶段假红）：
    $env:TMP="$PWD\\.tmp\\pytemp"; $env:TEMP=$env:TMP; python -m pytest tests/ -q
"""
import json
import sqlite3
import time
import uuid

import pytest

import db as db_module
import profile_spec
import server
from db import Database


# ---------------------------------------------------------------------------
# 夹具与助手
# ---------------------------------------------------------------------------
@pytest.fixture
def make_user():
    """在（已由 conftest 隔离的）全局库上建账号。

    `create_user` 只写 id/username/password_hash/created_at，
    战绩字段要用 `update_user` 补；`created_at` 不在 update_user 的白名单里
    （它是注册时间，本来就不该被随便改），需要时直接改库。
    """
    def _make(wins=0, losses=0, longest_streak=0, current_streak=0,
              created_at=None, card_uses=None):
        username = 'pc' + uuid.uuid4().hex[:10]
        uid = db_module.create_user(username, 'x')
        assert uid, '建号失败（用户名冲突？）'
        assert db_module.update_user(uid, wins=wins, losses=losses,
                                     longest_streak=longest_streak,
                                     current_streak=current_streak), '更新战绩失败'
        if created_at is not None:
            con = db_module.db
            with con._lock:
                con.cursor.execute('UPDATE users SET created_at = ? WHERE id = ?',
                                   (int(created_at), uid))
                con.conn.commit()
        for name, uses in (card_uses or {}).items():
            db_module.record_user_card_use(uid, name, uses)
        return uid, username

    return _make


def _login(client, uid, username):
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['username'] = username
    return client


def _payload(**over):
    """一份合法的保存请求（**9 个字段**齐全）。

    第 3 批 D 票把 `show_guestbook`（留言板公开，默认 1）并进了同一条保存通道 ——
    它和另外三个 `show_*` 一样"必须全发"，所以这里的形状也跟着从 8 个变 9 个。
    契约来源：`docs/BATCH_2_3_4_PLAN.md` §3.4 + 主会话对写入通道的裁决。
    """
    body = {'title_id': 'rookie', 'tags': [], 'status_text': '', 'frame_id': 'none',
            'card_bg_id': 'deep', 'show_stats': 1, 'show_fav_cards': 1,
            'show_history': 0, 'show_guestbook': 1, 'show_rank': 1, 'friend_requests_open': 1}
    body.update(over)
    return body


def _stats(**over):
    """解锁判定用的 stats（原始形状，和 api.py 组装的一致）。"""
    base = {'wins': 0, 'losses': 0, 'longest_streak': 0,
            'created_at': int(time.time()), 'card_uses_total': 0}
    base.update(over)
    return base


# ===========================================================================
# 0. 契约形状：池子条目与 catalog
# ===========================================================================




# ===========================================================================
# 7. 解锁边界：差 1 场一律不解锁
# ===========================================================================










# ===========================================================================
# 1. 越权挂未解锁称号 → 400 且库里没被改
# ===========================================================================
def test_locked_title_rejected_and_nothing_written(make_user):
    uid, username = make_user(wins=0, losses=0)
    client = _login(server.app.test_client(), uid, username)

    # 先存一份合法内容（rookie 无门槛）
    ok = client.post('/api/profile/card', json=_payload(title_id='rookie',
                                                        status_text='原来的状态'))
    assert ok.status_code == 200 and ok.get_json()['success'] is True

    bad = client.post('/api/profile/card', json=_payload(title_id='immortal',
                                                         status_text='偷偷改掉'))
    assert bad.status_code == 400, bad.get_json()
    body = bad.get_json()
    assert body['success'] is False
    assert '未解锁的称号' in body['error'] and '不败神话' in body['error']

    # 整次保存被拒 → 连合法的 status_text 也不许落库
    stored = db_module.get_user_profile_extra(uid)
    assert stored['title_id'] == 'rookie', stored
    assert stored['status_text'] == '原来的状态', stored






# ===========================================================================
# 2. 标签：4 个只存 3 个 / 池外 400
# ===========================================================================








# ===========================================================================
# 3. 一句话状态：截断 + 清控制字符
# ===========================================================================






# ===========================================================================
# 4. 未解锁的头像框 / 名片底色 → 400
# ===========================================================================














# ===========================================================================
# 5. 隐私：show_history 两种视角
# ===========================================================================
def test_history_privacy_two_views(make_user):
    owner_uid, owner_name = make_user(wins=1, losses=0)
    other_uid, other_name = make_user(wins=1, losses=0)
    db_module.record_match(owner_uid, other_uid, count_stats=False)

    owner = _login(server.app.test_client(), owner_uid, owner_name)
    other = _login(server.app.test_client(), other_uid, other_name)
    anon = server.app.test_client()

    # 默认 show_history=0 → 只有本人看得到
    assert db_module.get_user_profile_extra(owner_uid)['show_history'] == 0
    assert len(owner.get(f'/user_stats?username={owner_name}').get_json()['history']) == 1
    assert other.get(f'/user_stats?username={owner_name}').get_json()['history'] == []
    assert anon.get(f'/user_stats?username={owner_name}').get_json()['history'] == []

    # 本人主动公开后，别人也能看到
    assert owner.post('/api/profile/card',
                      json=_payload(show_history=1)).status_code == 200
    assert len(other.get(f'/user_stats?username={owner_name}').get_json()['history']) == 1

    # 关回去：本人仍然完整（否则"我的对局记录"就废了）
    assert owner.post('/api/profile/card',
                      json=_payload(show_history=0)).status_code == 200
    assert len(owner.get(f'/user_stats?username={owner_name}').get_json()['history']) == 1
    assert other.get(f'/user_stats?username={owner_name}').get_json()['history'] == []




# --- 三个展示开关必须一起下发（2026-09-17 裁决补上 show_stats / show_fav_cards）---






# ===========================================================================
# 6. /user_stats 字段白名单：绝不下发凭证
# ===========================================================================








# ===========================================================================
# 8. user_card_usage：累加 / Top3 排序 / 合计
# ===========================================================================
@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv('BATTLESHIP_DB_PATH', str(tmp_path / 'profile.db'))
    d = Database()
    yield d
    d.close()




















# ===========================================================================
# server.py：出牌时同时写全局表与个人表
# ===========================================================================






# ===========================================================================
# 9. 老库兼容：重复 init_db() 不报错、老数据还在
# ===========================================================================
_OLD_SCHEMA = '''
CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT,
    wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0, current_streak INTEGER DEFAULT 0,
    longest_streak INTEGER DEFAULT 0, created_at INTEGER, signature TEXT DEFAULT '',
    avatar TEXT DEFAULT '', token TEXT DEFAULT '');
CREATE TABLE matches (id TEXT PRIMARY KEY, winner_id TEXT, loser_id TEXT, timestamp INTEGER);
CREATE TABLE match_logs (match_id TEXT PRIMARY KEY, logs TEXT);
CREATE TABLE chat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT,
    username TEXT, content TEXT, timestamp INTEGER);
CREATE TABLE active_games (user_id TEXT PRIMARY KEY, room_id TEXT, updated_at INTEGER);
CREATE TABLE card_usage (card_name TEXT PRIMARY KEY, uses INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER);
'''






# ===========================================================================
# 10. 未登录 → 401
# ===========================================================================
