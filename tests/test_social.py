# -*- coding: utf-8 -*-
r"""点赞 / 送花 / 留言板（第 3 批 D 票）回归测试。

对应 `docs/BATCH_2_3_4_PLAN.md` §3.1（数据）/ §3.2（内容与权限）/ §3.3（四个接口契约）/ §3.4（隐私）。

覆盖七块：
  0. 数据层本身：两表 + DAO（幂等增删、软删、分页游标、每日计数）
  1. `POST /api/profile/like`：登录 / 目标存在 / **不能给自己点** / kind 白名单 / on 归一化
  2. `GET  /api/profile/messages`：分页契约（has_more / total / before_id / limit 钳制）
  3. `POST /api/profile/message`：**长度边界 100 vs 101** / 控制字符 / 空内容 /
     **每人对同一人每天 20 vs 21** / 复用 `_rate_limited` / 不能给自己留言
  4. `POST /api/profile/message/delete`：**留言本人或页面主人可删，其余 403** / 软删保留行
  5. 隐私：`show_guestbook=0` 时**他人视角空 + guestbook_private=true**，本人仍完整，
     而**点赞/送花计数始终可见**
  6. 两个展示接口（`/user_stats`、`/api/profile`）都带互动数据与 `show_guestbook`，
     且继续走字段白名单（**不泄露 password_hash / token**）
  7. **老库兼容**：对「第 1 批那种没有 `show_guestbook` 列的库」跑 `init_db()`，
     确认不抛异常、新列被 ALTER 补上（老行 = 默认公开）、老数据仍在

⚠️ 跑测试必须重定向临时目录（本机 Temp 的 ACL 坏了，不重定向会有一批用例在 setup 阶段假红）：
    New-Item -ItemType Directory -Force .tmp\pytemp | Out-Null
    $env:TMP="$PWD\.tmp\pytemp"; $env:TEMP=$env:TMP
    python -m pytest tests/ -q -p no:cacheprovider
"""
import sqlite3
import threading
import time
import uuid

import pytest

import api
import db as db_module
import server

# ===========================================================================
# 夹具与助手
# ===========================================================================


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """每个用例前清空限流计数。

    `api._login_attempts` 是**模块级**字典（按 IP 记窗口），pytest 所有用例
    共用同一个 remote_addr，于是「上一个用例打了 10 次」会把下一个用例顶成 429。
    不清的话本文件里几条正常用例会假红。
    """
    api._login_attempts.clear()
    yield
    api._login_attempts.clear()


@pytest.fixture
def make_user():
    """建一个真账号（走 db.create_user，用户名唯一）。"""
    def _make(wins=0, losses=0):
        for _ in range(20):
            username = 'soc_' + uuid.uuid4().hex[:10]
            uid = db_module.create_user(username, 'x')
            if uid:
                if wins or losses:
                    db_module.update_user(uid, wins=wins, losses=losses)
                return uid, username
        raise AssertionError('建号失败（用户名冲突？）')

    return _make


def _login(client, uid, username):
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['username'] = username
    return client


def _client(uid=None, username=None):
    """一个 test_client；给了 uid 就顺手登录。

    ⚠️ 每个 `test_client()` 各带各的 cookie jar —— 同一个用例里要**复用同一个
    client**，否则另起一个会丢 session（表现为「保存成功却读回旧值」）。
    """
    client = server.app.test_client()
    if uid:
        _login(client, uid, username)
    return client


def _json(resp):
    """响应体当 dict/list 读（不是 JSON 就返回 None，便于断言报得清楚）。"""
    try:
        return resp.get_json()
    except Exception:      # noqa: BLE001
        return None


def _msg(client, username, content):
    return client.post('/api/profile/message', json={'username': username, 'content': content})


def _like(client, username, kind='like', on=True):
    return client.post('/api/profile/like',
                       json={'username': username, 'kind': kind, 'on': on})


def _raw_row(table, where, params, conn=None):
    """直接读库拿【未经过白名单】的行，用来断言「行还在、只是被软删」。

    `conn`：传入某个实例的连接时用**它**读（WAL 下另开一条连接看不到
    对方尚未 commit 的写 —— 迁移用例里就是靠这条才会读到 None）。
    """
    own = conn is None
    conn = conn or sqlite3.connect(db_module.db.db_path)
    prev_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(f'SELECT * FROM {table} WHERE {where}', params).fetchone()
    finally:
        conn.row_factory = prev_factory
        if own:
            conn.close()


def _table_columns(table, path=None):
    """读某张表的列名（默认读本用例的临时库）。

    ⚠️ 参数顺序是 (表名, 库路径)。早先写错过一次 —— 把路径当表名传进去会拼出
    `PRAGMA table_info(C:\\...\\legacy.db)` 这种 SQL，报 `unrecognized token: ":"`。
    表名只接受字面量，所以这里加一道 isidentifier 断言把它钉死。
    """
    assert table.isidentifier(), f'表名必须是简单标识符: {table!r}'
    conn = sqlite3.connect(path or db_module.db.db_path)
    try:
        return [row[1] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()]
    finally:
        conn.close()


def _open_instance(path):
    """构造一个指向指定库文件的 Database 实例（不走 __init__，避免它连自己的库）。"""
    instance = db_module.Database.__new__(db_module.Database)
    instance.db_path = path
    instance._lock = threading.RLock()
    instance.conn = sqlite3.connect(str(path), check_same_thread=False)
    instance.conn.row_factory = sqlite3.Row
    instance.cursor = instance.conn.cursor()
    return instance


# ===========================================================================
# 0. 数据层：两表 + DAO
# ===========================================================================










# ===========================================================================
# 1. POST /api/profile/like
# ===========================================================================














# ===========================================================================
# 2. GET /api/profile/messages —— 分页契约
# ===========================================================================








# ===========================================================================
# 3. POST /api/profile/message
# ===========================================================================
def test_message_requires_login(make_user):
    you, name = make_user()
    assert _msg(_client(), name, '你好').status_code == 401






















# ===========================================================================
# 4. POST /api/profile/message/delete
# ===========================================================================






def test_delete_by_third_party_is_403(make_user):
    """★ 非本人非主人删别人留言 → 403（不是 404，也不是静默成功）。"""
    me, me_name = make_user()
    you, you_name = make_user()
    stranger, stranger_name = make_user()
    mid = _json(_msg(_client(me, me_name), you_name, '你好'))['message']['id']

    resp = _client(stranger, stranger_name).post('/api/profile/message/delete',
                                                 json={'id': mid})
    assert resp.status_code == 403
    assert '权限' in (_json(resp) or {}).get('error', '')
    assert _raw_row('profile_messages', 'id = ?', (mid,))['deleted'] == 0, '不能被删掉'








# ===========================================================================
# 5. 隐私：show_guestbook
# ===========================================================================
def _set_guestbook(client, on):
    """按**契约通道**改留言板开关：`POST /api/profile/card` 发 9 个字段。

    ⚠️ 必须传入**已有的** client —— 另起一个 client 会丢 session。
    """
    resp = client.post('/api/profile/card', json={
        'title_id': '', 'tags': [], 'status_text': '', 'frame_id': 'none',
        'card_bg_id': 'deep', 'show_stats': 1, 'show_fav_cards': 1,
        'show_history': 0, 'show_guestbook': 1 if on else 0, 'show_rank': 1, 'friend_requests_open': 1,
    })
    assert resp.status_code == 200, _json(resp)
    return resp




def test_guestbook_private_hides_messages_from_others_but_not_owner(make_user):
    """★ 别人视角：messages=[] + guestbook_private=true；本人视角照旧完整。"""
    me, me_name = make_user()
    you, you_name = make_user()
    mine = _client(me, me_name)
    owner = _client(you, you_name)

    assert _msg(mine, you_name, '别人留的').status_code == 200
    _set_guestbook(owner, False)

    others = _json(mine.get(f'/api/profile/messages?username={you_name}'))
    assert others['messages'] == [], '别人视角不该看到任何留言'
    assert others['guestbook_private'] is True, '★ 必填字段：前端靠它显示「未开放」'
    assert others['total'] == 0, '连条数都不该透露'

    self_view = _json(owner.get(f'/api/profile/messages?username={you_name}'))
    assert self_view['guestbook_private'] is False
    assert len(self_view['messages']) == 1, '本人永远完整'

    # 隐私开关只影响**读取可见性**，不改变写入是否被允许（计划没禁止继续留言）
    assert _msg(mine, you_name, '关了也能留').status_code == 200








# ===========================================================================
# 6. 两个展示接口都带互动数据，且不泄露凭据
# ===========================================================================






def test_no_credentials_leak_in_social_views(make_user):
    """★ 凭据不外泄：`password_hash` / `token` 的**值**都不许出现在响应里。"""
    me, me_name = make_user()
    you, you_name = make_user()
    joined = _client(me, me_name)
    _msg(joined, you_name, '你好')
    _like(joined, you_name, 'like')

    for resp in (joined.get(f'/api/profile/messages?username={you_name}'),
                 joined.get(f'/user_stats?username={you_name}'),
                 joined.get('/api/profile'),
                 joined.post('/api/profile/message',
                             json={'username': you_name, 'content': 'hi'})):
        text = resp.get_data(as_text=True)
        assert 'password_hash' not in text, resp.request.path
        assert 'token' not in text, resp.request.path


# ===========================================================================
# 7. 老库兼容：第 1 批那种没有 show_guestbook 列的库
# ===========================================================================
def _build_legacy_db(path):
    """造一个**第 1 批形状**的老库：user_profile 没有 show_guestbook 列，且已有数据。

    ⚠️ 逐条 execute + 参数绑定（不用 executescript 拼一大段 SQL）：
    整段字符串可读可查，改动时不容易被转义弄坏。
    """
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            'CREATE TABLE users ('
            ' id TEXT PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT,'
            ' wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0,'
            ' current_streak INTEGER DEFAULT 0, longest_streak INTEGER DEFAULT 0,'
            ' created_at INTEGER, signature TEXT DEFAULT \'\', avatar TEXT DEFAULT \'\','
            ' token TEXT DEFAULT \'\')')
        conn.execute(
            'CREATE TABLE user_profile ('
            ' user_id TEXT PRIMARY KEY, title_id TEXT DEFAULT \'\','
            ' tags TEXT DEFAULT \'[]\', status_text TEXT DEFAULT \'\','
            ' frame_id TEXT DEFAULT \'none\', card_bg_id TEXT DEFAULT \'deep\','
            ' show_stats INTEGER DEFAULT 1, show_fav_cards INTEGER DEFAULT 1,'
            ' show_history INTEGER DEFAULT 0, updated_at INTEGER)')
        conn.execute(
            'INSERT INTO users (id, username, password_hash, wins, created_at)'
            ' VALUES (?, ?, ?, ?, ?)',
            ('u-old', 'olduser', 'pbkdf2:sha256:legacy', 7, 1700000000))
        conn.execute(
            'INSERT INTO user_profile (user_id, title_id, tags, status_text, frame_id,'
            ' card_bg_id, show_stats, show_fav_cards, show_history, updated_at)'
            ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ('u-old', 'veteran', '["pro"]', '老玩家', 'gold', 'cyber', 1, 0, 1, 1700000001))
        conn.commit()
    finally:
        conn.close()
