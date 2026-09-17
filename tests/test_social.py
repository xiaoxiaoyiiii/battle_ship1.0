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
def test_new_tables_and_indexes_exist():
    """§3.1 的两张表必须真的建出来了，且带索引。"""
    assert set(_table_columns('profile_likes')) >= {
        'from_user_id', 'to_user_id', 'kind', 'created_at'}
    assert set(_table_columns('profile_messages')) >= {
        'id', 'to_user_id', 'from_user_id', 'from_name', 'content', 'created_at', 'deleted'}

    conn = sqlite3.connect(db_module.db.db_path)
    try:
        indexes = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    finally:
        conn.close()
    for name in ('idx_profile_messages_box', 'idx_profile_messages_pair',
                 'idx_profile_likes_to'):
        assert name in indexes, f'缺少索引 {name}'


def test_reaction_dao_is_idempotent_and_counts(make_user):
    """点两次仍只有一条；取消一次就归零 —— 主键幂等。"""
    me, _ = make_user()
    you, _ = make_user()

    assert db_module.set_profile_reaction(me, you, 'like', True) is True
    assert db_module.set_profile_reaction(me, you, 'like', True) is True
    assert db_module.get_profile_reaction_counts(you) == {'like': 1, 'flower': 0}

    assert db_module.set_profile_reaction(me, you, 'flower', True) is True
    assert db_module.get_profile_reaction_counts(you) == {'like': 1, 'flower': 1}

    assert db_module.set_profile_reaction(me, you, 'like', False) is True
    assert db_module.get_profile_reaction_counts(you) == {'like': 0, 'flower': 1}
    # 取消一个本来就不存在的反应：幂等成功，不是失败
    assert db_module.set_profile_reaction(me, you, 'like', False) is True

    assert db_module.get_my_reactions(me, you) == {'like': False, 'flower': True}
    assert db_module.get_my_reactions(you, me) == {'like': False, 'flower': False}


def test_message_dao_lifecycle_and_cursor_paging(make_user):
    """add → list（id 倒序）→ 游标分页 → 软删后 list 不含但行还在。"""
    me, _ = make_user()
    you, _ = make_user()
    ids = [db_module.add_profile_message(you, me, '甲', f'第{i}条') for i in range(5)]
    assert all(ids), '写留言应返回自增 id'

    page = db_module.list_profile_messages(you, limit=2)
    assert [m['id'] for m in page['messages']] == [ids[4], ids[3]], '应按 id 倒序'
    assert page['has_more'] is True and page['total'] == 5

    page2 = db_module.list_profile_messages(you, limit=2, before_id=ids[3])
    assert [m['id'] for m in page2['messages']] == [ids[2], ids[1]]
    assert page2['has_more'] is True
    page3 = db_module.list_profile_messages(you, limit=2, before_id=ids[1])
    assert [m['id'] for m in page3['messages']] == [ids[0]]
    assert page3['has_more'] is False, '最后一页不该说还有更多'

    assert db_module.soft_delete_profile_message(ids[4]) is True
    after = db_module.list_profile_messages(you, limit=10)
    assert ids[4] not in [m['id'] for m in after['messages']]
    assert after['total'] == 4

    # ★ 软删 = 保留审计：行还在表里，只是 deleted=1
    row = _raw_row('profile_messages', 'id = ?', (ids[4],))
    assert row is not None, '软删不该把行删掉'
    assert row['deleted'] == 1
    assert row['content'] == '第4条'
    # 重复软删幂等
    assert db_module.soft_delete_profile_message(ids[4]) is True


def test_message_dao_daily_counter_counts_deleted_too(make_user):
    """每日计数**含已软删的** —— 否则「发 20 条→全删→再发 20 条」就绕过了限制。"""
    me, _ = make_user()
    you, _ = make_user()
    first = db_module.add_profile_message(you, me, '甲', 'a')
    db_module.soft_delete_profile_message(first)
    assert db_module.count_profile_messages_since(me, you, 0) == 1
    # 计数是 from → to 单向的
    assert db_module.count_profile_messages_since(you, me, 0) == 0


def test_message_dao_row_shape_is_whitelisted(make_user):
    """下发行形状只含契约字段（id / from_uid / from_name / content / created_at）。"""
    me, _ = make_user()
    you, _ = make_user()
    db_module.add_profile_message(you, me, '甲', '你好')
    item = db_module.list_profile_messages(you, limit=1)['messages'][0]
    assert set(item) == {'id', 'from_uid', 'from_name', 'content', 'created_at'}


# ===========================================================================
# 1. POST /api/profile/like
# ===========================================================================
def test_like_requires_login(make_user):
    you, name = make_user()
    resp = _client().post('/api/profile/like', json={'username': name, 'kind': 'like'})
    assert resp.status_code == 401, '未登录必须 401'


def test_like_target_missing_is_404(make_user):
    me, _ = make_user()
    resp = _like(_client(me, 'x'), 'nobody_' + uuid.uuid4().hex[:8])
    assert resp.status_code == 404, '目标账号不存在必须 404（不能静默成功）'


def test_like_missing_username_param_is_400(make_user):
    me, _ = make_user()
    resp = _client(me, 'x').post('/api/profile/like', json={'kind': 'like', 'on': True})
    assert resp.status_code == 400
    assert 'username' in (_json(resp) or {}).get('error', '')


def test_like_self_is_rejected_with_reason(make_user):
    """★ 不能给自己点赞/送花 —— 服务端裁决，前端灰按钮只是辅助。"""
    me, name = make_user()
    resp = _like(_client(me, name), name, 'like')
    assert resp.status_code == 400
    assert '自己' in (_json(resp) or {}).get('error', ''), '要给出明确原因'

    resp = _like(_client(me, name), name, 'flower')
    assert resp.status_code == 400
    assert db_module.get_profile_reaction_counts(me) == {'like': 0, 'flower': 0}, '不能写入'


def test_like_kind_whitelist(make_user):
    me, _ = make_user()
    you, you_name = make_user()
    client = _client(me, 'x')
    for bad in ('', 'LIKE', 'star', 'flowers', None, 123):
        resp = client.post('/api/profile/like',
                           json={'username': you_name, 'kind': bad, 'on': True})
        assert resp.status_code == 400, f'kind={bad!r} 必须拒绝'
    assert db_module.get_profile_reaction_counts(you) == {'like': 0, 'flower': 0}
    assert _like(client, you_name, 'flower').status_code == 200, '白名单内的照常通过'


def test_like_on_is_normalized_to_bool_and_response_shape(make_user):
    """`on` 归一化为 bool；响应回读计数（不是本地加减），形状按 §3.3。"""
    me, me_name = make_user()
    you, you_name = make_user()
    client = _client(me, me_name)

    resp = _like(client, you_name, 'like', True)
    assert resp.status_code == 200
    body = _json(resp)
    assert body['success'] is True
    assert body['counts'] == {'like': 1, 'flower': 0}
    assert body['mine'] == {'like': True, 'flower': False}

    # 重复点 = 幂等（计数不涨）
    assert _json(_like(client, you_name, 'like', True))['counts'] == {'like': 1, 'flower': 0}
    # '1' / 'true' 这类前端字符串形式也要认
    assert _json(_like(client, you_name, 'like', 'false'))['mine'] == {
        'like': False, 'flower': False}
    assert _like(client, you_name, 'like', 'true').status_code == 200
    # 垃圾值一律当「取消」（不能把垃圾当点赞）
    assert _json(_like(client, you_name, 'like', 'maybe'))['counts'] == {
        'like': 0, 'flower': 0}


def test_like_counts_are_per_target_and_per_kind(make_user):
    me, me_name = make_user()
    a, a_name = make_user()
    b, b_name = make_user()
    client = _client(me, me_name)
    _like(client, a_name, 'like')
    _like(client, a_name, 'flower')
    _like(client, b_name, 'flower')
    assert db_module.get_profile_reaction_counts(a) == {'like': 1, 'flower': 1}
    assert db_module.get_profile_reaction_counts(b) == {'like': 0, 'flower': 1}


# ===========================================================================
# 2. GET /api/profile/messages —— 分页契约
# ===========================================================================
def test_messages_requires_login(make_user):
    you, name = make_user()
    assert _client().get(f'/api/profile/messages?username={name}').status_code == 401


def test_messages_target_missing_is_404(make_user):
    me, _ = make_user()
    resp = _client(me, 'x').get('/api/profile/messages?username=ghost_' + uuid.uuid4().hex[:6])
    assert resp.status_code == 404


def test_messages_paging_contract(make_user):
    """limit / before_id / has_more / total 一条不落（§3.3）。"""
    me, me_name = make_user()
    you, you_name = make_user()
    client = _client(me, me_name)
    ids = [_json(_msg(client, you_name, f'#{i}'))['message']['id'] for i in range(5)]

    body = _json(client.get(f'/api/profile/messages?username={you_name}&limit=2'))
    assert [m['id'] for m in body['messages']] == [ids[4], ids[3]]
    assert body['has_more'] is True
    assert body['total'] == 5
    assert body['guestbook_private'] is False

    body2 = _json(client.get(
        f'/api/profile/messages?username={you_name}&limit=2&before_id={ids[3]}'))
    assert [m['id'] for m in body2['messages']] == [ids[2], ids[1]]

    body3 = _json(client.get(
        f'/api/profile/messages?username={you_name}&limit=2&before_id={ids[1]}'))
    assert [m['id'] for m in body3['messages']] == [ids[0]]
    assert body3['has_more'] is False


def test_messages_limit_is_clamped_and_bad_values_do_not_crash(make_user):
    """limit 负数 / 0 / 超大 / 非数字都必须被钳住，不能 500。"""
    me, me_name = make_user()
    you, you_name = make_user()
    client = _client(me, me_name)
    for i in range(3):
        _msg(client, you_name, f'x{i}')

    assert len(_json(client.get(
        f'/api/profile/messages?username={you_name}&limit=0'))['messages']) == 1
    assert len(_json(client.get(
        f'/api/profile/messages?username={you_name}&limit=-5'))['messages']) == 1
    assert len(_json(client.get(
        f'/api/profile/messages?username={you_name}&limit=9999'))['messages']) == 3
    body = _json(client.get(f'/api/profile/messages?username={you_name}&limit=abc'))
    assert body['total'] == 3, '非法 limit 退回默认值'
    body = _json(client.get(f'/api/profile/messages?username={you_name}&before_id=abc'))
    assert len(body['messages']) == 3, '非法 before_id 当「第一页」'


# ===========================================================================
# 3. POST /api/profile/message
# ===========================================================================
def test_message_requires_login(make_user):
    you, name = make_user()
    assert _msg(_client(), name, '你好').status_code == 401


def test_message_target_missing_is_404(make_user):
    me, _ = make_user()
    resp = _msg(_client(me, 'x'), 'ghost_' + uuid.uuid4().hex[:6], '你好')
    assert resp.status_code == 404


def test_message_to_self_is_rejected_with_reason(make_user):
    """★ 不能给自己留言（服务端裁决）。"""
    me, name = make_user()
    resp = _msg(_client(me, name), name, '自己夸自己')
    assert resp.status_code == 400
    assert '自己' in (_json(resp) or {}).get('error', '')
    assert db_module.list_profile_messages(me, limit=10)['total'] == 0


def test_message_content_length_boundary_100_vs_101(make_user):
    """★ 100 字通过、101 字 400 —— 边界写错一位就是「多发一个字就失败」。"""
    me, me_name = make_user()
    you, you_name = make_user()
    client = _client(me, me_name)

    ok = _msg(client, you_name, '字' * 100)
    assert ok.status_code == 200, _json(ok)
    assert len(_json(ok)['message']['content']) == 100

    bad = _msg(client, you_name, '字' * 101)
    assert bad.status_code == 400
    assert '100' in (_json(bad) or {}).get('error', ''), '要点明上限'
    assert db_module.list_profile_messages(you, limit=10)['total'] == 1, '超长那条不该写进去'


def test_message_content_is_trimmed_and_control_chars_removed(make_user):
    me, me_name = make_user()
    you, you_name = make_user()
    client = _client(me, me_name)

    resp = _msg(client, you_name, '  a\x00b\x07c\t\n  ')
    assert resp.status_code == 200
    content = _json(resp)['message']['content']
    # 控制字符清掉了；结尾空白（含 tab / 换行）被 strip —— 与 status_text 的口径一致
    assert content == 'abc', repr(content)
    assert '\x00' not in content and '\x07' not in content

    # 中间的控制字符同样要清（只去首尾等于没去）
    resp = _msg(client, you_name, 'a\x00b\x07c')
    assert _json(resp)['message']['content'] == 'abc'

    # 多行留言要保留换行（留言是多行文本框）
    resp = _msg(client, you_name, '第一行\n第二行')
    assert _json(resp)['message']['content'] == '第一行\n第二行'

    # 只由控制字符与空白组成 → 等于空内容
    assert _msg(client, you_name, '\x00\x01   ').status_code == 400


def test_message_empty_content_is_400_not_silently_dropped(make_user):
    """空内容必须明确 400（计划 §3.2：「不是静默丢弃」）。"""
    me, me_name = make_user()
    you, you_name = make_user()
    client = _client(me, me_name)
    for bad in ('', '   ', '\n\t', None):
        resp = client.post('/api/profile/message',
                           json={'username': you_name, 'content': bad})
        assert resp.status_code == 400, f'content={bad!r} 必须 400'
    assert _msg(client, you_name, '  正常内容  ').status_code == 200


def test_message_daily_limit_20_vs_21(make_user, monkeypatch):
    """★ 每人对同一人每天 ≤ 20 条：第 20 条通过、第 21 条拒。

    这里把 `_rate_limited` 打桩成「永不触发」，单独钉**每日上限**这一条规则
    （否则 IP 限流会先把第 11 条拦成 429，测不到每日上限）。
    """
    me, me_name = make_user()
    you, you_name = make_user()
    client = _client(me, me_name)
    monkeypatch.setattr(api, '_rate_limited', lambda scope: False)

    for i in range(20):
        resp = _msg(client, you_name, f'第{i + 1}条')
        assert resp.status_code == 200, f'第 {i + 1} 条应当通过：{_json(resp)}'

    resp = _msg(client, you_name, '第21条')
    assert resp.status_code == 429, '第 21 条必须被拒'
    assert '20' in (_json(resp) or {}).get('error', '')
    assert db_module.list_profile_messages(you, limit=50)['total'] == 20, '被拒的不该写进去'

    # 换个收件人不受影响（上限是「每人对同一人」）
    _other, other_name = make_user()
    assert _msg(client, other_name, '给别人的').status_code == 200


def test_message_daily_limit_ignores_yesterday(make_user):
    """昨天的 20 条不算今天的 —— 每日窗口是本地零点，不是「最近 24 小时」。"""
    me, me_name = make_user()
    you, you_name = make_user()
    client = _client(me, me_name)
    for i in range(20):
        db_module.add_profile_message(you, me, me_name, f'昨天第{i}条')
    # 把 20 条时间戳挪到昨天
    conn = sqlite3.connect(db_module.db.db_path)
    try:
        conn.execute('UPDATE profile_messages SET created_at = ? WHERE from_user_id = ?',
                     (int(time.time()) - 86400, me))
        conn.commit()
    finally:
        conn.close()
    assert db_module.count_profile_messages_since(me, you, api._day_start_ts()) == 0
    assert _msg(client, you_name, '今天第一条').status_code == 200


def test_message_rate_limit_is_reused(make_user):
    """复用 `api._rate_limited('profile_message')`：同一 IP 超过窗口上限 → 429。"""
    me, me_name = make_user()
    you, you_name = make_user()
    client = _client(me, me_name)
    codes = []
    for _ in range(api._LOGIN_MAX_ATTEMPTS + 1):
        # 用「内容为空」的请求打满窗口：它们总是 400（不写库），
        # 第 N+1 次开始才应当是 429
        codes.append(_msg(client, you_name, '').status_code)
    assert codes[:api._LOGIN_MAX_ATTEMPTS] == [400] * api._LOGIN_MAX_ATTEMPTS
    assert codes[-1] == 429, f'超过窗口上限必须是 429，实际 {codes}'
    # 列表接口**不限流**（翻页读不该被限）
    assert client.get(f'/api/profile/messages?username={you_name}').status_code == 200


def test_message_response_shape_and_can_delete(make_user):
    """新增留言的响应形状与列表同形状，`can_delete` 由服务端算好。"""
    me, me_name = make_user()
    you, you_name = make_user()
    body = _json(_msg(_client(me, me_name), you_name, '你好呀'))
    assert body['success'] is True
    msg = body['message']
    assert set(msg) == {'id', 'from_name', 'content', 'created_at', 'can_delete'}
    assert msg['from_name'] == me_name
    assert msg['content'] == '你好呀'
    assert msg['can_delete'] is True, '自己发的留言自己可以删'
    assert 'to_user_id' not in msg and 'deleted' not in msg, '内部字段不该下发'


def test_message_bad_body_is_400(make_user):
    me, me_name = make_user()
    you, you_name = make_user()
    client = _client(me, me_name)
    assert client.post('/api/profile/message', data='not json',
                       content_type='text/plain').status_code == 400
    assert client.post('/api/profile/message', json=['a']).status_code == 400
    # 表单也能收（与名片保存同一套兜底）
    assert client.post('/api/profile/message',
                       data={'username': you_name, 'content': '表单来的'}).status_code == 200


# ===========================================================================
# 4. POST /api/profile/message/delete
# ===========================================================================
def test_delete_requires_login(make_user):
    me, me_name = make_user()
    you, you_name = make_user()
    mid = _json(_msg(_client(me, me_name), you_name, '你好'))['message']['id']
    resp = _client().post('/api/profile/message/delete', json={'id': mid})
    assert resp.status_code == 401


def test_delete_unknown_message_is_404(make_user):
    me, me_name = make_user()
    resp = _client(me, me_name).post('/api/profile/message/delete', json={'id': 99999999})
    assert resp.status_code == 404


def test_delete_bad_id_is_400(make_user):
    me, me_name = make_user()
    client = _client(me, me_name)
    for bad in (None, 'abc', {}):
        assert client.post('/api/profile/message/delete', json={'id': bad}).status_code == 400


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


def test_delete_by_author_and_by_owner_both_allowed(make_user):
    """★ 留言本人可删、页面主人可删（§3.2 权限规则）。"""
    me, me_name = make_user()
    you, you_name = make_user()
    other, other_name = make_user()

    m1 = _json(_msg(_client(me, me_name), you_name, '自己删'))['message']['id']
    assert _client(me, me_name).post('/api/profile/message/delete',
                                     json={'id': m1}).status_code == 200
    assert _raw_row('profile_messages', 'id = ?', (m1,))['deleted'] == 1

    m2 = _json(_msg(_client(other, other_name), you_name, '主人删'))['message']['id']
    assert _client(you, you_name).post('/api/profile/message/delete',
                                       json={'id': m2}).status_code == 200
    assert _raw_row('profile_messages', 'id = ?', (m2,))['deleted'] == 1


def test_delete_is_idempotent_for_authorized_user(make_user):
    """已删过的留言：有权限的人再删一次仍 200（幂等），行保持 deleted=1。"""
    me, me_name = make_user()
    you, you_name = make_user()
    mid = _json(_msg(_client(me, me_name), you_name, '你好'))['message']['id']
    client = _client(me, me_name)
    assert client.post('/api/profile/message/delete', json={'id': mid}).status_code == 200
    assert client.post('/api/profile/message/delete', json={'id': mid}).status_code == 200


def test_deleted_message_disappears_from_list_but_row_stays(make_user):
    """软删后 list 不含它、total 减一，但**行还在表里**（保留审计）。"""
    me, me_name = make_user()
    you, you_name = make_user()
    client = _client(me, me_name)
    keep = _json(_msg(client, you_name, '留着'))['message']['id']
    drop = _json(_msg(client, you_name, '删掉'))['message']['id']

    assert client.post('/api/profile/message/delete', json={'id': drop}).status_code == 200
    body = _json(client.get(f'/api/profile/messages?username={you_name}'))
    assert [m['id'] for m in body['messages']] == [keep]
    assert body['total'] == 1
    row = _raw_row('profile_messages', 'id = ?', (drop,))
    assert row is not None and row['deleted'] == 1 and row['content'] == '删掉'


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
        'show_history': 0, 'show_guestbook': 1 if on else 0,
    })
    assert resp.status_code == 200, _json(resp)
    return resp


def test_guestbook_defaults_to_public(make_user):
    """默认公开（§3.4）：新账号 `show_guestbook` 读出 1，老行由 DEFAULT 1 兜底。"""
    me, me_name = make_user()
    you, you_name = make_user()
    assert db_module.get_user_profile_extra(you)['show_guestbook'] == 1
    client = _client(me, me_name)
    assert _msg(client, you_name, '第一条').status_code == 200
    body = _json(client.get(f'/api/profile/messages?username={you_name}'))
    assert body['guestbook_private'] is False
    assert len(body['messages']) == 1


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


def test_reaction_counts_are_visible_even_when_guestbook_private(make_user):
    """★ 点赞/送花计数**始终可见**（那是「人气」不是「内容」，§3.4）。"""
    me, me_name = make_user()
    you, you_name = make_user()
    mine = _client(me, me_name)
    owner = _client(you, you_name)

    _like(mine, you_name, 'like')
    _set_guestbook(owner, False)

    stats = _json(mine.get(f'/user_stats?username={you_name}'))['stats']
    assert stats['counts'] == {'like': 1, 'flower': 0}
    assert stats['mine'] == {'like': True, 'flower': False}
    assert stats['show_guestbook'] == 0

    body = _json(mine.get(f'/api/profile/messages?username={you_name}'))
    assert body['counts'] == {'like': 1, 'flower': 0}, '列表响应里计数同样可见'


def test_guestbook_flag_round_trips_and_owner_sees_others_messages(make_user):
    """开关能关能开；关掉期间别人留的言，主人一直看得见。"""
    me, me_name = make_user()
    you, you_name = make_user()
    mine = _client(me, me_name)
    owner = _client(you, you_name)

    _msg(mine, you_name, '第一句')
    _set_guestbook(owner, False)
    _msg(mine, you_name, '关闭期间的第二句')
    _set_guestbook(owner, True)

    body = _json(mine.get(f'/api/profile/messages?username={you_name}'))
    assert body['guestbook_private'] is False
    assert [m['content'] for m in body['messages']] == ['关闭期间的第二句', '第一句']
    assert len(_json(owner.get(
        f'/api/profile/messages?username={you_name}'))['messages']) == 2


def test_card_save_requires_show_guestbook_and_validates_its_value(make_user):
    """契约：第 9 个字段必须发（缺 → 400 点名），且只接受 0/1。"""
    me, me_name = make_user()
    client = _client(me, me_name)
    body = {'title_id': '', 'tags': [], 'status_text': '', 'frame_id': 'none',
            'card_bg_id': 'deep', 'show_stats': 1, 'show_fav_cards': 1, 'show_history': 0}

    resp = client.post('/api/profile/card', json=body)
    assert resp.status_code == 400
    err = (_json(resp) or {}).get('error', '')
    assert '缺少字段' in err and 'show_guestbook' in err, err

    for bad in ('随便', 2, -1, [1]):
        resp = client.post('/api/profile/card', json=dict(body, show_guestbook=bad))
        assert resp.status_code == 400, f'show_guestbook={bad!r} 必须拒绝'
    assert '留言板公开' in (_json(resp) or {}).get('error', ''), '错误提示要用中文键名'

    for good in (0, 1, True, False, '0', '1'):
        resp = client.post('/api/profile/card', json=dict(body, show_guestbook=good))
        assert resp.status_code == 200, good
    assert db_module.get_user_profile_extra(me)['show_guestbook'] in (0, 1)


# ===========================================================================
# 6. 两个展示接口都带互动数据，且不泄露凭据
# ===========================================================================
def test_user_stats_carries_interaction_data(make_user):
    me, me_name = make_user(wins=1)
    you, you_name = make_user(losses=1)
    _like(_client(me, me_name), you_name, 'flower')

    stats = _json(_client(me, me_name).get(f'/user_stats?username={you_name}'))['stats']
    assert stats['counts'] == {'like': 0, 'flower': 1}
    assert stats['mine'] == {'like': False, 'flower': True}
    assert stats['show_guestbook'] == 1


def test_user_stats_anonymous_viewer_gets_counts_without_mine(make_user):
    """未登录=他人视角：计数照给，`mine` 全 false（没有「我」），开关照给。"""
    me, me_name = make_user()
    you, you_name = make_user()
    _like(_client(me, me_name), you_name, 'like')

    stats = _json(_client().get(f'/user_stats?username={you_name}'))['stats']
    assert stats['counts'] == {'like': 1, 'flower': 0}
    assert stats['mine'] == {'like': False, 'flower': False}
    assert stats['show_guestbook'] == 1


def test_profile_endpoint_carries_own_interaction_data(make_user):
    """`/api/profile`（自己视角）也带 counts / mine / show_guestbook。

    自己看自己时 `mine` 恒 false —— 不能给自己点赞/送花。
    """
    me, me_name = make_user()
    you, you_name = make_user()
    mine = _client(me, me_name)
    _like(_client(you, you_name), me_name, 'like')

    profile = _json(mine.get('/api/profile'))['profile']
    assert profile['counts'] == {'like': 1, 'flower': 0}
    assert profile['mine'] == {'like': False, 'flower': False}
    assert profile['show_guestbook'] == 1

    # 关掉之后本人也读得到真实值（前端编辑面靠它回显复选框）
    _set_guestbook(mine, False)
    profile = _json(mine.get('/api/profile'))['profile']
    assert profile['show_guestbook'] == 0


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


def test_legacy_db_gets_new_column_without_error(tmp_path):
    """★ 老库兼容：连跑三次 init_db() 不能抛，新列要被 ALTER 补上，老数据一个不变。

    这是本票最容易出线上 500 的一步 —— `CREATE TABLE IF NOT EXISTS` 对**已存在**的表
    是空操作，只有 `ALTER TABLE ADD COLUMN` 才能把 `show_guestbook` 加进老库。
    """
    path = tmp_path / 'legacy.db'
    _build_legacy_db(path)
    assert 'show_guestbook' not in _table_columns('user_profile', str(path)), \
        '前提：老库确实没有这一列'

    instance = _open_instance(path)
    try:
        instance.init_db()
        instance.init_db()          # 幂等：第二次也不许抛、不许重复加列
        instance.init_db()          # 第三次同上
        instance.conn.commit()

        cols = _table_columns('user_profile', str(path))
        assert 'show_guestbook' in cols, '新列必须被 ALTER 补上'
        assert cols.count('show_guestbook') == 1, '不能重复加列'

        # 老行 = 默认公开（DEFAULT 1），老数据一字未动
        # （用 instance.conn 读：WAL 下另开一条连接看不到尚未 commit 的写）
        row = _raw_row('user_profile', 'user_id = ?', ('u-old',), conn=instance.conn)
        assert row['show_guestbook'] == 1, '老行应当被默认成「公开」'
        assert row['title_id'] == 'veteran' and row['frame_id'] == 'gold'
        assert row['card_bg_id'] == 'cyber' and row['status_text'] == '老玩家'
        assert row['show_stats'] == 1 and row['show_fav_cards'] == 0
        assert row['show_history'] == 1 and row['updated_at'] == 1700000001
        assert row['tags'] == '["pro"]'
        legacy_user = _raw_row('users', 'id = ?', ('u-old',), conn=instance.conn)
        assert legacy_user['wins'] == 7
        assert legacy_user['password_hash'] == 'pbkdf2:sha256:legacy'

        # 老库上也能直接读名片（新列不再让 SELECT 报 no such column）
        extra = instance.get_user_profile_extra('u-old')
        assert extra['show_guestbook'] == 1
        assert extra['title_id'] == 'veteran' and extra['tags'] == ['pro']
        # 老库里没有名片的账号：读默认值（不写库），也不炸
        assert instance.get_user_profile_extra('u-missing')['show_guestbook'] == 1
    finally:
        instance.conn.close()


def test_legacy_db_init_creates_missing_social_tables(tmp_path):
    """老库启动时：两张新表与索引一并建出来（不停机、不需要迁移脚本）。"""
    path = tmp_path / 'legacy2.db'
    _build_legacy_db(path)
    instance = _open_instance(path)
    try:
        instance.init_db()
        assert set(_table_columns('profile_likes', str(path))) >= {
            'from_user_id', 'to_user_id', 'kind', 'created_at'}
        assert set(_table_columns('profile_messages', str(path))) >= {
            'id', 'to_user_id', 'from_user_id', 'from_name', 'content',
            'created_at', 'deleted'}
        # 老库里的账号还能正常发/读留言（跨表接缝）
        mid = instance.add_profile_message('u-old', 'u-new', '新来的', '你好')
        assert mid > 0
        page = instance.list_profile_messages('u-old', limit=5)
        assert page['total'] == 1 and page['messages'][0]['content'] == '你好'
    finally:
        instance.conn.close()


def test_add_column_helper_is_idempotent_and_safe(tmp_path):
    """迁移助手本身：已存在 → False（什么都不做）；表不存在 → False（只记日志）。"""
    path = tmp_path / 'helper.db'
    instance = _open_instance(path)
    try:
        instance.cursor.execute('CREATE TABLE user_profile (user_id TEXT PRIMARY KEY)')
        instance.conn.commit()
        assert db_module._add_column_if_missing(
            instance.cursor, 'user_profile', 'show_guestbook', 'INTEGER DEFAULT 1') is True
        cols = [r[1] for r in instance.cursor.execute(
            'PRAGMA table_info(user_profile)').fetchall()]
        assert cols.count('show_guestbook') == 1
        # 再跑一次：已经存在 → False（没做任何事）且不抛
        assert db_module._add_column_if_missing(
            instance.cursor, 'user_profile', 'show_guestbook', 'INTEGER DEFAULT 1') is False
        # 表不存在 → 不算致命
        assert db_module._add_column_if_missing(
            instance.cursor, 'no_such_table', 'x', 'INTEGER') is False
        # 可疑的表/列名一律拒绝（名字会拼进 SQL）
        assert db_module._add_column_if_missing(
            instance.cursor, 'user_profile; DROP TABLE users', 'x', 'INTEGER') is False
        assert db_module._add_column_if_missing(
            instance.cursor, 'user_profile', 'x; --', 'INTEGER') is False
    finally:
        instance.conn.close()


def test_migration_does_not_disturb_a_fresh_database(tmp_path):
    """全新库：init_db 一次到位（建表时就带 show_guestbook），迁移助手是空操作。"""
    path = tmp_path / 'fresh.db'
    instance = _open_instance(path)
    try:
        instance.init_db()
        cols = [r[1] for r in instance.cursor.execute(
            'PRAGMA table_info(user_profile)').fetchall()]
        assert cols.count('show_guestbook') == 1
        # ⚠️ 全新库也要能读默认名片（拿得到 1 = 公开），并且**不写库**
        extra = instance.get_user_profile_extra('nobody')
        assert extra['show_guestbook'] == 1
        assert instance.cursor.execute(
            'SELECT COUNT(*) FROM user_profile').fetchone()[0] == 0, '读默认值不该写库'
    finally:
        instance.conn.close()
