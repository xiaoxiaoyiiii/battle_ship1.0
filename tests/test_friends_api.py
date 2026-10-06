# -*- coding: utf-8 -*-
r"""好友功能回归测试（社交批：`db.py` 的 `user_friends` DAO + `api.py` 的六个接口）。

对应任务里的冻结契约。**本文件只管"接口这一层 + DAO 的存储语义"**，
覆盖 12 块：

  1. 未登录调每个接口都 401 `{'error': '未登录'}`
  2. 申请 → 对方 `GET /api/friends` 的 `incoming` 能看到、我方 `outgoing` 能看到
  3. 接受后双方 `friends` 都有对方、`counts.friends` 各 1；**重复接受幂等**
  4. 删除后两边都空；删除不存在的边返回 `ok`（幂等）
  5. 拉黑后对方**不能**再申请（`status='blocked'`），且原好友边消失
  6. 自己加自己 → `self`
  7. 重复申请 → `already_pending`；已是好友再申请 → `already_friends`
  8. 上限：好友数打满 50 → 再申请 400
  9. 限流：窗口内申请数到 `FRIEND_REQUESTS_PER_HOUR` → 429
 10. 隐私：响应里**不含** `password_hash` / `token` / `wins` / `losses` / `history`
 11. `presence.py` 不存在或抛异常时 `GET /api/friends` 仍 200（`online` 全 false）
 12. 同一秒连发两次申请只产生**一条** pending

⚠️ 本文件**不创建 `presence.py`**（同批另一个智能体负责）：第 11 块用
   `monkeypatch.setitem(sys.modules, 'presence', <替身>)` 注入假模块，
   覆盖"模块炸了"这一路；"模块根本不存在"那一路靠 `sys.modules.pop`。

⚠️ 用例造的好友边会**自己回收**（夹具 teardown 里按本用例的 uid 删）。
   `user_friends` 是整个测试会话共用的一张表，第 8 块要造 50 条边 ——
   不回收的话，任何一条依赖"好友数为 0"的用例都会在后面假红，
   而且失败点不在本文件里（`tests/test_ranked_api.py` 的 user_rank 同形状踩过）。

跑测试必须重定向临时目录（本机 Temp 的 ACL 坏了）：
    New-Item -ItemType Directory -Force .tmp\pytemp | Out-Null
    $env:TMP="$PWD\.tmp\pytemp"; $env:TEMP=$env:TMP
    python -m pytest tests/ -q -p no:cacheprovider
"""
import sys
import time
import types
import uuid

import pytest

import api
import db as db_module
import server

# `GET /api/friends` 的顶层键（**冻结**：多一个少一个都算契约漂移）
PAYLOAD_KEYS = {'friends', 'incoming', 'outgoing', 'limits', 'counts'}
# friends 每一项的键（冻结）
# ⚠️ 私聊批（2026-09-19）按契约 §4 加了 `unread`。这里是**本次唯一一处改动**：
#    这份测试原本把 `unread` 当"多出来的键"判漂移，而契约明文要求它存在
#    （`docs/FRIEND_DM_2026_09_19.md` §4：「每个 friend 行**新增 `unread`**」）。
FRIEND_KEYS = {'user_id', 'username', 'avatar', 'level', 'rank_label', 'online', 'in_game',
               'unread'}
# incoming / outgoing 每一项的键（冻结）
REQUEST_KEYS = {'user_id', 'username', 'avatar', 'created_at'}
# 任何响应里都不许出现的字段（本项目硬教训：接口整行下发会泄露凭证）
FORBIDDEN_FIELDS = ('password_hash', 'token', 'wins', 'losses', 'history', 'signature')


# ===========================================================================
# 夹具与助手
# ===========================================================================


@pytest.fixture
def make_user():
    """建一个真账号（走 `db.create_user`），返回 `(uid, username)`。

    用例结束**回收本用例造出来的好友边**（见 `_delete_friend_edges`）。
    """
    created = []

    def _make():
        uid = None
        for _ in range(20):
            username = 'fr_' + uuid.uuid4().hex[:10]
            uid = db_module.create_user(username, 'x')
            if uid:
                break
        assert uid, '建号失败（用户名冲突？）'
        created.append(uid)
        return uid, username

    yield _make
    _delete_friend_edges(created)


def _delete_friend_edges(uids):
    """删掉本文件造出来的边（**只是测试卫生**，不是断言的一部分）。

    ⚠️ 为什么非要删：`user_friends` 是整个测试会话共用的一张表，第 8 块要造
    50 条边。留在表里会让后面任何"好友数为 0 / 列表为空"的用例当场假红，
    而失败点**不在本文件里**（`tests/test_ranked_api.py` 的 `user_rank`
    同形状踩过一次，排查很费劲）。造什么回收什么，不碰别人的数据。
    """
    ids = [str(u) for u in (uids or []) if u]
    if not ids:
        return
    try:
        conn = db_module.db.conn
        marks = ','.join('?' for _ in ids)
        conn.execute(f'DELETE FROM user_friends WHERE user_id IN ({marks})', ids)
        conn.execute(f'DELETE FROM user_friends WHERE friend_id IN ({marks})', ids)
        conn.commit()
    except Exception as e:      # noqa: BLE001 —— 清理失败不该把用例判红
        print(f'[test] 回收 user_friends 失败（不影响断言）: {e}')


def _client(uid=None, username=None):
    """一个 test_client；给了 uid 就顺手登录。

    ⚠️ 每个 `test_client()` 各带各的 cookie jar —— 同一用例里要**复用同一个
    client**，另起一个会丢 session（表现为"明明登录了却读到 401"）。
    """
    client = server.app.test_client()
    if uid:
        with client.session_transaction() as sess:
            sess['user_id'] = uid
            sess['username'] = username
    return client


def _get(client):
    resp = client.get('/api/friends')
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _post(client, path, **payload):
    return client.post(path, json=payload)


def _post_json(client, path, **payload):
    resp = _post(client, path, **payload)
    assert resp.status_code == 200, (path, resp.status_code, resp.get_data(as_text=True))
    return resp.get_json()


def _names(rows):
    return [row['user_id'] for row in rows]


def _edge_rows(uid, status=None):
    """直接读表里的边（绕开 DAO，用于"到底写了几行"这类断言）。"""
    conn = db_module.db.conn
    if status is None:
        rows = conn.execute('SELECT * FROM user_friends WHERE user_id = ?', (uid,)).fetchall()
    else:
        rows = conn.execute('SELECT * FROM user_friends WHERE user_id = ? AND status = ?',
                            (uid, status)).fetchall()
    return [dict(r) for r in rows]


def _accept_via_dao(me, other, created_at=None):
    """直接往库里写一条 accepted 边（造"已经是好友"的存量数据，快且不绕接口）。"""
    now = int(created_at if created_at is not None else 0)
    conn = db_module.db.conn
    conn.execute(
        'INSERT OR REPLACE INTO user_friends '
        '(user_id, friend_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)',
        (str(me), str(other), 'accepted', now, now))
    conn.commit()


# ===========================================================================
# 1. 未登录 → 401（每个接口都要，逐个表态，别漏）
# ===========================================================================
def test_every_friend_endpoint_requires_login():
    """六个接口匿名访问一律 401 `{'error': '未登录'}`。"""
    client = server.app.test_client()          # 不登录、干净 cookie
    calls = [
        ('GET', '/api/friends', None),
        ('POST', '/api/friends/request', {'username': 'whoever'}),
        ('POST', '/api/friends/respond', {'username': 'whoever', 'accept': True}),
        ('POST', '/api/friends/remove', {'username': 'whoever'}),
        ('POST', '/api/friends/block', {'username': 'whoever'}),
        ('POST', '/api/friends/invite', {'username': 'whoever'}),
    ]
    for method, path, payload in calls:
        resp = (client.get(path) if method == 'GET'
                else client.post(path, json=payload or {}))
        assert resp.status_code == 401, f'{method} {path} 未登录应当 401'
        assert resp.get_json() == {'error': '未登录'}, f'{method} {path} 响应体不对'


# ===========================================================================
# 2. 申请 → incoming / outgoing
# ===========================================================================


# ===========================================================================
# 3. 接受：双方互为好友 + 幂等
# ===========================================================================




# ===========================================================================
# 4. 删除：两边都空 + 幂等
# ===========================================================================


# ===========================================================================
# 5. 拉黑：好友边消失 + 对方不能再申请
# ===========================================================================
def test_block_kills_friendship_and_stops_the_other_side_from_requesting(make_user):
    a, a_name = make_user()
    b, b_name = make_user()
    ca, cb = _client(a, a_name), _client(b, b_name)

    # 先做成好友，再加一条反向 pending（造出"两向边都在"的最坏情况）
    _post_json(ca, '/api/friends/request', username=b_name)
    _post_json(cb, '/api/friends/respond', username=a_name, accept=True)
    assert _get(ca)['counts']['friends'] == 1

    assert _post_json(ca, '/api/friends/block', username=b_name) == {'status': 'ok'}

    # 原好友边**两边都**没了
    assert _get(ca)['friends'] == [] and _get(cb)['friends'] == []
    assert _edge_rows(a, 'accepted') == [] and _edge_rows(b, 'accepted') == []
    # 只剩一条 blocked（拉黑方 → 被拉黑方）
    blocked = _edge_rows(a, 'blocked')
    assert len(blocked) == 1 and blocked[0]['friend_id'] == b
    assert _edge_rows(b) == []

    # 被拉黑方**不能**再申请（契约：`status='blocked'`，且**必须带一句中文原因**）
    # ⚠️ 原因不能少：前端 `apiReason()` 只认 error/message，只回 status 的话
    #    页面上只有一句通用文案（端到端验证钉出来的 PB3）。
    blocked_resp = _post_json(cb, '/api/friends/request', username=a_name)
    assert blocked_resp['status'] == 'blocked', blocked_resp
    assert blocked_resp.get('error'), blocked_resp
    assert _edge_rows(b, 'pending') == []
    # 拉黑方自己也不能反着申请（同一格里也不许再拉回来）；同样要带原因
    reverse_resp = _post_json(ca, '/api/friends/request', username=b_name)
    assert reverse_resp['status'] == 'blocked', reverse_resp
    assert reverse_resp.get('error'), reverse_resp

    # 关系判断按视角分（`blocked_by_me` / `blocked_me`）
    assert db_module.get_friend_relation(a, b) == 'blocked_by_me'
    assert db_module.get_friend_relation(b, a) == 'blocked_me'

    # 拉黑是幂等的
    assert _post_json(ca, '/api/friends/block', username=b_name) == {'status': 'ok'}
    assert len(_edge_rows(a, 'blocked')) == 1
    self_block = _post(ca, '/api/friends/block', username=a_name)
    assert self_block.status_code == 400 and self_block.get_json()['status'] == 'error'




# ===========================================================================
# 6. / 7. 自己加自己、重复申请、已是好友再申请
# ===========================================================================






# ===========================================================================
# 8. 上限：好友打满 → 400
# ===========================================================================






# ===========================================================================
# 9. 限流：窗口内到上限 → 429
# ===========================================================================




# ===========================================================================
# 10. 隐私：只下发白名单字段
# ===========================================================================
def test_friends_payload_never_leaks_credentials_or_stats(make_user):
    """响应里**不含** `password_hash` / `token` / `wins` / `losses` / `history`。

    ⚠️ 用**可辨识**的假哈希/假头像名：拿一个字符去断言"响应里不含它"会假绿
    （`'x'` 会出现在 `"index"` 里 —— `tests/test_ranked_api.py` 的注释里记过）。
    """
    secret_hash = 'pbkdf2:sha256:friends-batch-deadbeef'
    a, a_name = make_user()
    b, b_name = make_user()
    # 给双方写上可辨识的凭证与战绩，任何一处整行下发都会命中
    conn = db_module.db.conn
    conn.execute("UPDATE users SET password_hash = ?, token = ?, wins = 7, losses = 9, "
                 "signature = 'sigfriendsdeadbeef' WHERE id IN (?, ?)",
                 (secret_hash, 'token-friends-deadbeef', a, b))
    conn.commit()

    ca, cb = _client(a, a_name), _client(b, b_name)
    _post_json(ca, '/api/friends/request', username=b_name)
    _post_json(cb, '/api/friends/respond', username=a_name, accept=True)
    _c, c_name = make_user()
    _post_json(ca, '/api/friends/request', username=c_name)      # 留一条 outgoing

    for client in (ca, cb):
        resp = client.get('/api/friends')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert secret_hash not in body, '泄露了 password_hash'
        assert 'token-friends-deadbeef' not in body, '泄露了 token'
        assert 'sigfriendsdeadbeef' not in body, '泄露了 signature'
        payload = resp.get_json()
        assert set(payload) == PAYLOAD_KEYS, payload.keys()
        for key in FORBIDDEN_FIELDS:
            assert key not in body, f'响应里出现了 {key}'
        for row in payload['friends']:
            assert set(row) == FRIEND_KEYS, row
        for row in payload['incoming'] + payload['outgoing']:
            assert set(row) == REQUEST_KEYS, row
        assert set(payload['limits']) == {'max_friends', 'requests_per_hour'}
        # ⚠️ 私聊批（2026-09-19）按契约 §4 加了 `unread_total`（未读私聊总数）。
        #    入口红点**不读它** —— 红点仍是 `incoming`（见本文件第 8 块与那一行注释）。
        assert set(payload['counts']) == {'friends', 'incoming', 'unread_total'}


# ===========================================================================
# 11. presence 缺失 / 抛异常：降级不 500
# ===========================================================================












# ===========================================================================
# 12. 幂等与并发：同一秒连发两次只产生一条 pending
# ===========================================================================




# ===========================================================================
# 附：DAO 的存储层硬事实（方向、行数、失败不抛）
# ===========================================================================




# ===========================================================================
# ★ 推送守卫（2026-09-18 补）：接口写完库**必须**推事件
#
# 为什么单独一组：第一版 `api.py` 里 `push_friend_request` / `push_friend_accepted`
# **一个都没被调用** —— `server.py` 提供了函数、前端也注册了处理函数，但真链路上
# 那两个事件**永远不会到达**（对方在线也看不到任何提示），而且**不报错**。
# 这是"功能看着有、其实永远不触发"的典型：纯函数测试全绿、接口测试也全绿
# （它们只断言了数据库与返回值），只有"断言事件被推出去"才能发现。
# ===========================================================================


    # 库里真的有那条 pending
    # ⚠️ incoming 里那条的 user_id 是**申请人**（a），不是我自己（b）——\n    #    契约里 user_id 一律表示对方，这里差点写反。\n    assert any(r['user_id'] == a for r in db_module.list_incoming_requests(b))




# ===========================================================================
# 「是否允许他人加我好友」开关（决策④的"设置里可关"）
#
# ⚠️ 这三条守的是"关掉之后**真的**挡住了"。这类开关最容易"看着有、其实永远不触发"
#    （本项目栽过：判定上下文少注入一个字段 → 一件都解不开、而接口/前端/测试全绿）；
#    另一个同形状的坑是拿**带兜底的取数函数**当门禁（取不到就恒非 0 → 门禁失效）。
# ===========================================================================
def _close_requests(uid):
    """关掉某人的"允许他人加我好友"（走真 DAO，不打桩）。"""
    assert db_module.save_user_profile_extra(uid, {'friend_requests_open': 0}) is True












# ===========================================================================
# 邀战的护栏：**发起方自己正在局中时不许邀战**
#
# ⚠️ 背景（用户实测报的"约战开不了局"）：`POST /api/friends/invite` 建出来的是一间
#    **空房**，而 `handle_join_room` 只在**满 2 人**时才把阶段推到 `placing_ships`。
#    所以前端修成"邀请成功后**发起方也进这间房**"（`sendFriendInvite` → `joinRoomById`）。
#    既然发起方会被带进新房，就必须先拦住"他正在打一局"的情况 —— 否则他那一局的对手
#    会一直干等（而服务端这边没有任何机制会发现）。
# ===========================================================================
