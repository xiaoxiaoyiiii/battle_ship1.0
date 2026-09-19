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
FRIEND_KEYS = {'user_id', 'username', 'avatar', 'level', 'rank_label', 'online', 'in_game'}
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
def test_request_shows_up_in_incoming_and_outgoing(make_user):
    a, a_name = make_user()
    b, b_name = make_user()

    assert _post_json(_client(a, a_name), '/api/friends/request', username=b_name) == {'status': 'sent'}

    mine = _get(_client(a, a_name))
    assert _names(mine['outgoing']) == [b], mine['outgoing']
    assert mine['incoming'] == []
    assert mine['counts'] == {'friends': 0, 'incoming': 0}

    theirs = _get(_client(b, b_name))
    assert _names(theirs['incoming']) == [a], theirs['incoming']
    assert theirs['outgoing'] == []
    assert theirs['counts'] == {'friends': 0, 'incoming': 1}

    # incoming 的 user_id 是**发起人**（前端拿它显示"谁要加你"）
    assert theirs['incoming'][0]['username'] == a_name
    assert set(theirs['incoming'][0]) == REQUEST_KEYS


# ===========================================================================
# 3. 接受：双方互为好友 + 幂等
# ===========================================================================
def test_accept_makes_both_directions_friends_and_is_idempotent(make_user):
    a, a_name = make_user()
    b, b_name = make_user()
    ca, cb = _client(a, a_name), _client(b, b_name)

    _post_json(ca, '/api/friends/request', username=b_name)

    first = _post_json(cb, '/api/friends/respond', username=a_name, accept=True)
    assert first == {'status': 'accepted'}

    # **两条**对称边（accepted 的定义就是两条）
    assert len(_edge_rows(a, 'accepted')) == 1
    assert len(_edge_rows(b, 'accepted')) == 1

    for client, other in ((ca, b), (cb, a)):
        payload = _get(client)
        assert _names(payload['friends']) == [other]
        assert payload['counts']['friends'] == 1
        assert payload['incoming'] == [] and payload['outgoing'] == []
        assert set(payload['friends'][0]) == FRIEND_KEYS
        assert payload['friends'][0]['level'] >= 1
        assert isinstance(payload['friends'][0]['rank_label'], str)
        assert payload['friends'][0]['online'] is False
        assert payload['friends'][0]['in_game'] is False

    # 重复接受：幂等 —— 不报错、不产生重复边
    again = _post_json(cb, '/api/friends/respond', username=a_name, accept=True)
    assert again == {'status': 'accepted'}
    assert len(_edge_rows(a, 'accepted')) == 1
    assert len(_edge_rows(b, 'accepted')) == 1
    assert _get(ca)['counts']['friends'] == 1

    # 反向"接受"（我申请了别人却去点接受）不该成功：方向是死的
    assert db_module.accept_friend_request(a, b) is True      # 已是好友 → 幂等成功
    c, c_name = make_user()
    assert db_module.accept_friend_request(a, c) is False     # 没有 c→a 的 pending
    assert _edge_rows(a, 'accepted') == _edge_rows(a, 'accepted')   # 没写出多余边
    assert c not in _names(_get(ca)['friends'])


def test_decline_removes_pending_and_can_be_requested_again(make_user):
    """拒绝 = 删掉那条 pending（不是拉黑）：对方还能再申请。"""
    a, a_name = make_user()
    b, b_name = make_user()
    ca, cb = _client(a, a_name), _client(b, b_name)

    _post_json(ca, '/api/friends/request', username=b_name)
    assert _post_json(cb, '/api/friends/respond', username=a_name, accept=False) == {'status': 'declined'}
    assert _edge_rows(a, 'pending') == []
    assert _get(ca)['outgoing'] == [] and _get(cb)['incoming'] == []

    # 还能再申请（拒绝与拉黑是两回事）
    assert _post_json(ca, '/api/friends/request', username=b_name) == {'status': 'sent'}
    assert len(_edge_rows(a, 'pending')) == 1


# ===========================================================================
# 4. 删除：两边都空 + 幂等
# ===========================================================================
def test_remove_clears_both_sides_and_is_idempotent(make_user):
    a, a_name = make_user()
    b, b_name = make_user()
    ca, cb = _client(a, a_name), _client(b, b_name)

    _post_json(ca, '/api/friends/request', username=b_name)
    _post_json(cb, '/api/friends/respond', username=a_name, accept=True)
    assert _get(ca)['counts']['friends'] == 1

    assert _post_json(ca, '/api/friends/remove', username=b_name) == {'status': 'ok'}
    for client in (ca, cb):
        payload = _get(client)
        assert payload['friends'] == [] and payload['counts']['friends'] == 0
    assert _edge_rows(a) == [] and _edge_rows(b) == []

    # 删一个**不存在**的边：仍然 ok（幂等，"本来就不是好友"不是失败）
    assert _post_json(ca, '/api/friends/remove', username=b_name) == {'status': 'ok'}
    assert _post_json(ca, '/api/friends/remove', username=b_name) == {'status': 'ok'}
    # 删自己 → 400（不是 200 的 ok，也不是静默什么都不做）
    self_resp = _post(ca, '/api/friends/remove', username=a_name)
    assert self_resp.status_code == 400 and self_resp.get_json()['status'] == 'error'


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


def test_block_also_clears_pending_in_both_directions(make_user):
    """拉黑时**两个方向**的 pending/accepted 都清掉（只清一侧 = 对方列表里还有你）。"""
    a, a_name = make_user()
    b, b_name = make_user()
    ca, cb = _client(a, a_name), _client(b, b_name)

    _post_json(ca, '/api/friends/request', username=b_name)      # a → b pending
    assert _post_json(ca, '/api/friends/block', username=b_name) == {'status': 'ok'}

    assert _edge_rows(a, 'pending') == [] and _edge_rows(b, 'pending') == []
    assert _get(cb)['incoming'] == [], '被拉黑方不该还看到"某人的申请"'
    assert _get(ca)['outgoing'] == []


# ===========================================================================
# 6. / 7. 自己加自己、重复申请、已是好友再申请
# ===========================================================================
def test_add_self_is_self_status(make_user):
    a, a_name = make_user()
    resp = _post(_client(a, a_name), '/api/friends/request', username=a_name)
    assert resp.status_code == 400
    assert resp.get_json() == {'status': 'self'}
    # DAO 直调也是 'self'（两条路都不许写出边）
    assert db_module.send_friend_request(a, a) == 'self'
    assert _edge_rows(a) == []


def test_duplicate_request_and_request_when_already_friends(make_user):
    a, a_name = make_user()
    b, b_name = make_user()
    ca, cb = _client(a, a_name), _client(b, b_name)

    assert _post_json(ca, '/api/friends/request', username=b_name) == {'status': 'sent'}
    assert _post_json(ca, '/api/friends/request', username=b_name) == {'status': 'already_pending'}
    # 反向申请也算 already_pending：不该造出两条相反的 pending
    assert _post_json(cb, '/api/friends/request', username=a_name) == {'status': 'already_pending'}
    assert len(_edge_rows(a, 'pending')) == 1 and _edge_rows(b, 'pending') == []
    assert db_module.get_friend_relation(a, b) == 'pending_out'
    assert db_module.get_friend_relation(b, a) == 'pending_in'

    _post_json(cb, '/api/friends/respond', username=a_name, accept=True)
    assert _post_json(ca, '/api/friends/request', username=b_name) == {'status': 'already_friends'}
    assert _post_json(cb, '/api/friends/request', username=a_name) == {'status': 'already_friends'}
    assert len(_edge_rows(a, 'accepted')) == 1


def test_request_unknown_username_is_404_and_writes_nothing(make_user):
    a, a_name = make_user()
    missing = 'no_such_' + uuid.uuid4().hex[:8]
    resp = _post(_client(a, a_name), '/api/friends/request', username=missing)
    assert resp.status_code == 404, '目标不存在要 404，不要静默成功'
    assert _edge_rows(a) == []


# ===========================================================================
# 8. 上限：好友打满 → 400
# ===========================================================================
def test_friend_limit_blocks_new_requests(make_user):
    a, a_name = make_user()
    target, target_name = make_user()
    ca = _client(a, a_name)

    # 直接把 accepted 计数打到上限（造数据走 DAO 之外的直写，快且与接口无关）
    for _ in range(api.MAX_FRIENDS):
        other, _name = make_user()
        _accept_via_dao(a, other)
    assert db_module.count_friends(a) == api.MAX_FRIENDS

    resp = _post(ca, '/api/friends/request', username=target_name)
    assert resp.status_code == 400, resp.get_data(as_text=True)
    assert resp.get_json() == {'error': '好友数量已达上限'}
    # 没写出任何边（400 是拒绝，不是"先记下来"）
    assert db_module.get_friend_relation(a, target) == 'none'
    assert _edge_rows(a, 'pending') == []

    # 上限来自**常量**，接口要把同一个值下发（前端靠它提前灰按钮）
    assert _get(ca)['limits'] == {'max_friends': api.MAX_FRIENDS,
                                  'requests_per_hour': api.FRIEND_REQUESTS_PER_HOUR}


def test_friend_limit_follows_the_constant(make_user, monkeypatch):
    """上限判据引用 `api.MAX_FRIENDS` 常量本身（不是写死的 50）。"""
    a, a_name = make_user()
    target, target_name = make_user()
    monkeypatch.setattr(api, 'MAX_FRIENDS', 2, raising=False)

    for _ in range(2):
        other, _name = make_user()
        _accept_via_dao(a, other)
    assert db_module.count_friends(a) == 2

    resp = _post(_client(a, a_name), '/api/friends/request', username=target_name)
    assert resp.status_code == 400, resp.get_data(as_text=True)
    assert _get(_client(a, a_name))['limits']['max_friends'] == 2


def test_requests_and_remove_still_work_under_the_limit(monkeypatch, make_user):
    """上限只拦"新申请"，不拦删除/接受（别把门禁做成"好友满了什么都做不了"）。"""
    a, a_name = make_user()
    b, b_name = make_user()
    ca, cb = _client(a, a_name), _client(b, b_name)
    _post_json(ca, '/api/friends/request', username=b_name)
    _post_json(cb, '/api/friends/respond', username=a_name, accept=True)

    # 已经满员（上限临到 1，且当前好友数就是 1）
    monkeypatch.setattr(api, 'MAX_FRIENDS', 1, raising=False)
    assert db_module.count_friends(a) == 1
    assert _post_json(ca, '/api/friends/remove', username=b_name) == {'status': 'ok'}
    assert db_module.count_friends(a) == 0


# ===========================================================================
# 9. 限流：窗口内到上限 → 429
# ===========================================================================
def test_request_rate_limit_returns_429(make_user, monkeypatch):
    """窗口内申请数到达 `FRIEND_REQUESTS_PER_HOUR` 之后 → 429。

    ⚠️ `count_requests_since` 只数 **pending**：被接受/拉黑的不再占配额
    （所以下面每发一条都造一个"全新目标"，pending 才会真的累积）。
    """
    a, a_name = make_user()
    ca = _client(a, a_name)
    monkeypatch.setattr(api, 'FRIEND_REQUESTS_PER_HOUR', 2, raising=False)

    sent = 0
    for _ in range(2):
        _other, other_name = make_user()
        assert _post_json(ca, '/api/friends/request', username=other_name) == {'status': 'sent'}
        sent += 1
    assert db_module.count_requests_since(a, 0) == sent

    _third, third_name = make_user()
    resp = _post(ca, '/api/friends/request', username=third_name)
    assert resp.status_code == 429, resp.get_data(as_text=True)
    assert resp.get_json() == {'error': '申请太频繁，请稍后再试'}
    assert db_module.get_friend_relation(a, _third) == 'none'      # 被拦下的申请不写边

    # 窗口外的旧申请不算数：把它们的 created_at 拨回两小时前，立刻又能发
    conn = db_module.db.conn
    conn.execute("UPDATE user_friends SET created_at = created_at - 7200 "
                 "WHERE user_id = ? AND status = 'pending'", (a,))
    conn.commit()
    assert db_module.count_requests_since(a, int(time.time()) - 3600) == 0
    assert _post_json(ca, '/api/friends/request', username=third_name) == {'status': 'sent'}

    # 限流判据只在**我**身上：别人不受影响
    b, b_name = make_user()
    _t, t_name = make_user()
    assert _post_json(_client(b, b_name), '/api/friends/request', username=t_name) == {'status': 'sent'}


def test_rate_limit_count_is_per_sender(make_user, monkeypatch):
    """`count_requests_since` 只数**我发出的** pending（收到的申请不占我的配额）。"""
    monkeypatch.setattr(api, 'FRIEND_REQUESTS_PER_HOUR', 1, raising=False)
    a, a_name = make_user()
    b, b_name = make_user()
    ca, cb = _client(a, a_name), _client(b, b_name)

    _post_json(cb, '/api/friends/request', username=a_name)      # b → a，占的是 **b** 的配额
    assert db_module.count_requests_since(a, 0) == 0
    assert db_module.count_requests_since(b, 0) == 1
    _c, c_name = make_user()
    assert _post_json(ca, '/api/friends/request', username=c_name) == {'status': 'sent'}


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
        assert set(payload['counts']) == {'friends', 'incoming'}


# ===========================================================================
# 11. presence 缺失 / 抛异常：降级不 500
# ===========================================================================
def test_friends_endpoint_survives_missing_presence(monkeypatch, make_user):
    """`presence.py` 根本不存在（import 失败）时仍然 200，online 全 false。"""
    a, a_name = make_user()
    b, b_name = make_user()
    ca = _client(a, a_name)
    _post_json(ca, '/api/friends/request', username=b_name)
    _post_json(_client(b, b_name), '/api/friends/respond', username=a_name, accept=True)

    # 让 `import presence` 直接失败（同批另一个智能体还没落地时的真实情形）
    monkeypatch.setitem(sys.modules, 'presence', None)
    payload = _get(ca)
    assert _names(payload['friends']) == [b]
    assert payload['friends'][0]['online'] is False
    assert payload['friends'][0]['in_game'] is False

    # 邀请：对方"不在线" → error，而不是 500
    resp = _post(ca, '/api/friends/invite', username=b_name)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json() == {'status': 'error', 'error': '对方不在线'}


def test_friends_endpoint_survives_broken_presence(monkeypatch, make_user):
    """`presence` 在，但每个函数都抛异常 → 仍然 200、online 全 false。"""
    a, a_name = make_user()
    b, b_name = make_user()
    ca, cb = _client(a, a_name), _client(b, b_name)
    _post_json(ca, '/api/friends/request', username=b_name)
    _post_json(cb, '/api/friends/respond', username=a_name, accept=True)

    def _boom(*args, **kwargs):
        raise RuntimeError('presence 炸了')

    fake = types.ModuleType('presence')
    fake.is_online = _boom
    fake.is_in_game = _boom
    fake.online_uids = _boom
    monkeypatch.setitem(sys.modules, 'presence', fake)

    payload = _get(ca)
    assert _names(payload['friends']) == [b]
    assert payload['friends'][0]['online'] is False
    assert payload['friends'][0]['in_game'] is False
    # 收到的申请那一份也要在（降级只影响绿点，不影响列表）
    assert _names(_get(cb)['friends']) == [a]
    resp = _post(ca, '/api/friends/invite', username=b_name)
    assert resp.status_code == 200
    assert resp.get_json() == {'status': 'error', 'error': '对方不在线'}


def test_friends_presence_marks_online_and_sorts_them_first(monkeypatch, make_user):
    """`presence` 正常时：在线的排前面、在局中的排后面（契约里的排序规则）。"""
    a, a_name = make_user()
    online_idle, online_idle_name = make_user()       # 在线且不在局中
    online_busy, online_busy_name = make_user()       # 在线但在局中
    offline, offline_name = make_user()               # 离线

    for _uid, name in ((online_idle, online_idle_name), (online_busy, online_busy_name),
                       (offline, offline_name)):
        _accept_via_dao(a, _uid)

    fake = types.ModuleType('presence')
    fake.online_uids = lambda: {str(online_idle), str(online_busy)}
    fake.is_online = lambda uid: str(uid) in {str(online_idle), str(online_busy)}
    fake.is_in_game = lambda uid: str(uid) == str(online_busy)
    monkeypatch.setitem(sys.modules, 'presence', fake)

    payload = _get(_client(a, a_name))
    assert _names(payload['friends']) == [online_idle, online_busy, offline]
    flags = {row['user_id']: (row['online'], row['in_game']) for row in payload['friends']}
    assert flags[online_idle] == (True, False)
    assert flags[online_busy] == (True, True)
    assert flags[offline] == (False, False)


def test_invite_creates_room_and_pushes_when_friend_is_online(monkeypatch, make_user):
    """对方在线：建房 + `friend_invite` 事件推到**对方的所有连接**上。

    用假 presence（给 `sids_of`）+ 假 socketio（记录 emit），把"推给谁、
    推了什么"钉住 —— 推错 sid 在真环境里是**静默丢弃**（socket.io 对不存在的
    房间不报错），只能靠这种断言拦。
    """
    a, a_name = make_user()
    b, b_name = make_user()

    fake = types.ModuleType('presence')
    fake.online_uids = lambda: {str(b)}
    fake.is_online = lambda uid: str(uid) == str(b)
    fake.is_in_game = lambda uid: False
    fake.sids_of = lambda uid: ['sid-b1', 'sid-b2'] if str(uid) == str(b) else []
    monkeypatch.setitem(sys.modules, 'presence', fake)

    # ⚠️ 推送**只有一份实现**：api 侧统一走 `server.push_friend_invite`
    #    （api 曾经自己 emit 一份，那份已删除 —— 两份实现必然漂移）。
    #    所以桩要打在 server 的 push 函数上，而不是 socketio 上。
    pushed = []

    def _fake_push(to_uid, room_id, from_uid, from_username):
        pushed.append((str(to_uid), room_id, str(from_uid), from_username))
        return True

    monkeypatch.setattr(server, 'push_friend_invite', _fake_push, raising=False)

    resp = _post(_client(a, a_name), '/api/friends/invite', username=b_name)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body['status'] == 'ok' and body['room_id'], body

    # 推给了谁、推的是哪个房间
    assert len(pushed) == 1, pushed
    to_uid, room_id, from_uid, from_username = pushed[0]
    assert to_uid == str(b) and from_uid == str(a) and from_username == a_name, pushed
    assert room_id == body['room_id']
    # 房间真的建出来了（邀请的 room_id 必须能在 server 里查到）
    assert server.room_manager.get_room(body['room_id']) is not None
    server.room_manager.delete_room(body['room_id'])


def test_invite_reports_error_when_presence_has_no_sids(monkeypatch, make_user):
    """`presence` 没有 `sids_of` 能力时**不硬编 sid** → 明确回"对方不在线"。"""
    a, a_name = make_user()
    b, b_name = make_user()

    fake = types.ModuleType('presence')
    fake.online_uids = lambda: {str(b)}
    fake.is_online = lambda uid: True
    fake.is_in_game = lambda uid: False
    # ⚠️ 刻意**不给** sids_of
    monkeypatch.setitem(sys.modules, 'presence', fake)

    emitted = []

    class _FakeSocketIO:
        def emit(self, event, data=None, room=None, **kwargs):
            emitted.append(room)

    monkeypatch.setitem(server.app.extensions, 'socketio', _FakeSocketIO())

    resp = _post(_client(a, a_name), '/api/friends/invite', username=b_name)
    assert resp.status_code == 200
    assert resp.get_json() == {'status': 'error', 'error': '对方不在线'}
    assert emitted == [], '拿不到 sid 就不许猜一个发出去（会静默丢弃）'


def test_invite_to_self_and_missing_username(make_user):
    a, a_name = make_user()
    ca = _client(a, a_name)
    resp = _post(ca, '/api/friends/invite', username=a_name)
    assert resp.status_code == 400 and resp.get_json()['status'] == 'error'
    missing = 'no_such_' + uuid.uuid4().hex[:8]
    assert _post(ca, '/api/friends/invite', username=missing).status_code == 404


# ===========================================================================
# 12. 幂等与并发：同一秒连发两次只产生一条 pending
# ===========================================================================
def test_two_requests_in_the_same_second_write_one_pending_row(make_user):
    """同一秒内连发两次申请 → 表里**只有一条** pending（主键 + INSERT OR IGNORE）。"""
    a, a_name = make_user()
    b, b_name = make_user()
    ca = _client(a, a_name)

    first = _post_json(ca, '/api/friends/request', username=b_name)
    second = _post_json(ca, '/api/friends/request', username=b_name)
    third = _post_json(ca, '/api/friends/request', username=b_name)
    assert [first['status'], second['status'], third['status']] == [
        'sent', 'already_pending', 'already_pending']

    rows = _edge_rows(a, 'pending')
    assert len(rows) == 1, rows
    assert rows[0]['friend_id'] == b
    assert rows[0]['created_at'] == rows[0]['updated_at']
    # 限流计数也只算一条（重复申请不该把配额刷掉）
    assert db_module.count_requests_since(a, 0) == 1
    assert _get(_client(b, b_name))['counts']['incoming'] == 1


def test_dao_send_is_idempotent_even_when_called_directly(make_user):
    """DAO 直调也幂等（`INSERT OR IGNORE` 是存储层的保证，不是接口层的巧合）。"""
    a, _a_name = make_user()
    b, _b_name = make_user()
    assert db_module.send_friend_request(a, b) == 'sent'
    assert db_module.send_friend_request(a, b) == 'already_pending'
    assert len(_edge_rows(a, 'pending')) == 1


# ===========================================================================
# 附：DAO 的存储层硬事实（方向、行数、失败不抛）
# ===========================================================================
def test_dao_reads_return_safe_defaults_and_never_raise():
    """读接口给空值、写接口给 False/'error'，一律不抛（照 `db.py` 既有风格）。"""
    nobody = 'no_such_user_' + uuid.uuid4().hex[:8]
    assert db_module.get_friend_edges(nobody) == []
    assert db_module.get_friend_ids(nobody) == []
    assert db_module.list_friends(nobody) == []
    assert db_module.list_incoming_requests(nobody) == []
    assert db_module.list_outgoing_requests(nobody) == []
    assert db_module.count_friends(nobody) == 0
    assert db_module.count_requests_since(nobody, 0) == 0
    assert db_module.get_friend_relation(nobody, '') == 'none'
    assert db_module.get_friend_relation(nobody, nobody) == 'self'
    assert db_module.accept_friend_request(nobody, '') is False
    assert db_module.remove_friend('', '') is False
    assert db_module.block_user(nobody, nobody) is False


def test_relation_values_cover_every_contracted_state(make_user):
    """`get_friend_relation` 七种取值逐个表态（方向写反不会报错，只能靠断言拦）。"""
    a, a_name = make_user()
    b, b_name = make_user()
    c, c_name = make_user()
    ca, cb = _client(a, a_name), _client(b, b_name)

    assert db_module.get_friend_relation(a, a) == 'self'
    assert db_module.get_friend_relation(a, b) == 'none'
    assert db_module.get_friend_relation(a, '') == 'none'

    _post_json(ca, '/api/friends/request', username=b_name)
    assert db_module.get_friend_relation(a, b) == 'pending_out'
    assert db_module.get_friend_relation(b, a) == 'pending_in'

    _post_json(cb, '/api/friends/respond', username=a_name, accept=True)
    assert db_module.get_friend_relation(a, b) == 'friends'
    assert db_module.get_friend_relation(b, a) == 'friends'

    _post_json(ca, '/api/friends/block', username=b_name)
    assert db_module.get_friend_relation(a, b) == 'blocked_by_me'
    assert db_module.get_friend_relation(b, a) == 'blocked_me'
    # 与第三方无关（别把"有人被拉黑"做成全局状态）
    assert db_module.get_friend_relation(a, c) == 'none'
    assert db_module.get_friend_relation(c, a) == 'none'


# ===========================================================================
# ★ 推送守卫（2026-09-18 补）：接口写完库**必须**推事件
#
# 为什么单独一组：第一版 `api.py` 里 `push_friend_request` / `push_friend_accepted`
# **一个都没被调用** —— `server.py` 提供了函数、前端也注册了处理函数，但真链路上
# 那两个事件**永远不会到达**（对方在线也看不到任何提示），而且**不报错**。
# 这是"功能看着有、其实永远不触发"的典型：纯函数测试全绿、接口测试也全绿
# （它们只断言了数据库与返回值），只有"断言事件被推出去"才能发现。
# ===========================================================================
def test_request_pushes_friend_request_event(monkeypatch, make_user):
    """发申请成功后，必须给**对方**推 `friend_request`（含我的用户名/头像）。"""
    a, a_name = make_user()
    b, b_name = make_user()
    pushed = []
    monkeypatch.setattr(server, 'push_friend_request',
                        lambda *args: (pushed.append(args), True)[1], raising=False)

    resp = _post(_client(a, a_name), '/api/friends/request', username=b_name)
    assert resp.status_code == 200 and resp.get_json()['status'] == 'sent', resp.get_data(as_text=True)
    assert len(pushed) == 1, pushed
    to_uid, from_uid, from_name, from_avatar = pushed[0]
    assert str(to_uid) == str(b) and str(from_uid) == str(a) and from_name == a_name, pushed
    assert isinstance(from_avatar, str)


def test_request_still_succeeds_when_target_is_offline(monkeypatch, make_user):
    """对方离线时申请**照样成功**（申请是异步的，他下次打开就能看到）。

    ⚠️ 与 invite 的区别：邀请必须是实时的（推不到就是失败），申请不是。
    """
    a, a_name = make_user()
    b, b_name = make_user()
    monkeypatch.setattr(server, 'push_friend_request', lambda *args: False, raising=False)

    resp = _post(_client(a, a_name), '/api/friends/request', username=b_name)
    assert resp.status_code == 200 and resp.get_json()['status'] == 'sent'
    # 库里真的有那条 pending
    # ⚠️ incoming 里那条的 user_id 是**申请人**（a），不是我自己（b）——\n    #    契约里 user_id 一律表示对方，这里差点写反。\n    assert any(r['user_id'] == a for r in db_module.list_incoming_requests(b))


def test_accept_pushes_friend_accepted_event(monkeypatch, make_user):
    """接受之后必须告诉**发起人**（他可能正开着页面等结果）。"""
    a, a_name = make_user()
    b, b_name = make_user()
    assert db_module.send_friend_request(a, b) == 'sent'

    pushed = []
    monkeypatch.setattr(server, 'push_friend_accepted',
                        lambda *args: (pushed.append(args), True)[1], raising=False)

    resp = _post(_client(b, b_name), '/api/friends/respond', username=a_name, accept=True)
    assert resp.status_code == 200 and resp.get_json()['status'] == 'accepted'
    assert len(pushed) == 1, pushed
    to_uid, from_uid, from_name, from_avatar = pushed[0]
    assert str(to_uid) == str(a) and str(from_uid) == str(b) and from_name == b_name


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


def test_request_to_blocked_target_gives_a_chinese_reason(make_user):
    """拉黑关系下申请被拒时，**必须带一句中文原因**（不能只回 status）。

    ⚠️ 前端 `apiReason()` 只认 `error`/`message`：只回 `{status:'blocked'}` 的话，
    页面上只会弹一句通用的「发送好友申请失败」，用户不知道发生了什么。
    """
    a, a_name = make_user()
    b, b_name = make_user()
    assert db_module.block_user(b, a) is True      # b 拉黑了 a

    resp = _post(_client(a, a_name), '/api/friends/request', username=b_name)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body['status'] == 'blocked', body
    assert body.get('error'), f'只回 status 的话前端兜不到原因：{body}'
    assert db_module.list_outgoing_requests(a) == []


def test_request_refused_when_target_closed_requests(make_user):
    """对方关掉申请开关 → 403 + 中文原因，且**一行都不许写库**。"""
    a, a_name = make_user()
    b, b_name = make_user()
    _close_requests(b)

    resp = _post(_client(a, a_name), '/api/friends/request', username=b_name)
    assert resp.status_code == 403, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body['status'] == 'error' and body['error'], body
    # 两侧都断言：接口回失败、库里却真写了 pending，同样是坏的
    assert db_module.list_outgoing_requests(a) == []
    assert db_module.list_incoming_requests(b) == []


def test_closing_requests_does_not_kill_already_received_ones(make_user):
    """已经收到的申请**照样能接受**。

    ⚠️ 关掉开关的意思是"别再有人来加我"，不是"我之前收到的也作废" ——
    一刀切会把用户本来打算同意的那条申请一起锁死，而且页面上看不出原因。
    """
    a, a_name = make_user()
    b, b_name = make_user()
    assert db_module.send_friend_request(a, b) == 'sent'
    _close_requests(b)

    resp = _post(_client(b, b_name), '/api/friends/respond', username=a_name, accept=True)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()['status'] == 'accepted'
    assert str(a) in [str(r['user_id']) for r in db_module.list_friends(b)]


def test_switch_value_round_trips_through_the_card_endpoint(make_user):
    """★ 开关必须能**经名片保存接口**写进去、再读回来。

    ⚠️ 上面几条走的是 DAO（直接写库），**没覆盖**"接口 → `profile_spec` 校验 → 落库"这条路，
    而真实用户走的正是这条路（浏览器的保存按钮就发这一个 POST）。
    字段在任一环被丢掉，"关掉开关"就变成**静默无效**：页面上的勾去掉了、服务端照样接受申请。
    """
    a, a_name = make_user()
    client = _client(a, a_name)
    # 按真实前端的方式发**全部 11 个字段**
    body = {'title_id': '', 'tags': [], 'status_text': '', 'frame_id': 'none',
            'card_bg_id': 'deep', 'show_stats': 1, 'show_fav_cards': 1, 'show_history': 0,
            'show_guestbook': 1, 'show_rank': 1, 'friend_requests_open': 0}

    resp = client.post('/api/profile/card', json=body)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert int(resp.get_json()['profile']['friend_requests_open']) == 0
    # 不信响应里的回显，**下一次直读**才算数
    again = client.get('/api/profile').get_json()['profile']
    assert int(again['friend_requests_open']) == 0, again.get('friend_requests_open')
    # 而且真的生效：别人这时候申请要被拒
    other, other_name = make_user()
    refused = _post(_client(other, other_name), '/api/friends/request', username=a_name)
    assert refused.status_code == 403, refused.get_data(as_text=True)


def test_requests_switch_is_not_exposed_to_other_viewers(make_user):
    """这个开关**只下发给本人**：别人（以及游客）不能在 /user_stats 里看到。

    ⚠️ 必须**以别人的身份直读接口**来断言 —— 前端断言会假绿（CLAUDE.md 坑 #12），
    而且两侧都断言：本人看得到（否则设置面初始不了那个勾）、别人看不到。
    """
    a, a_name = make_user()
    b, b_name = make_user()
    _close_requests(b)

    mine = _client(b, b_name).get('/api/profile').get_json()['profile']
    assert int(mine['friend_requests_open']) == 0, mine.get('friend_requests_open')

    seen = _client(a, a_name).get(f'/user_stats?username={b_name}').get_json()['stats']
    assert 'friend_requests_open' not in seen
    anon = server.app.test_client().get(f'/user_stats?username={b_name}').get_json()['stats']
    assert 'friend_requests_open' not in anon, pushed
