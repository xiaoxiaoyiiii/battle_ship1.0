# -*- coding: utf-8 -*-
r"""好友私聊回归测试（2026-09-19 私聊批）。

对应冻结契约 `docs/FRIEND_DM_2026_09_19.md`（§2 数据层 / §3 纯规则 / §4 接口）。
覆盖 9 块：

  1. `dm.py` 纯规则：`normalize_body` 的控制字符与换行、`body_error` 点名 300 字、
     `stamp` 的跨年规则、`check_rate` 的窗口与上限；
  2. 关系门禁：非好友 403、拉黑 403（**两个方向都测**）、自己私聊 400、账号不存在 404；
  3. 正文校验：空 / 纯空白 / 超长 → 400 且中文原因里点名「300 字」；
  4. 限流：一分钟内到 `dm.PER_MINUTE` 条 → 429，且**被拒的那条不许写库**；
  5. 会话合成：A→B 与 B→A **同一条会话**，`mine` 按视角正确（两个方向各断言一次）；
  6. 分页：`before` 游标往更早翻、`has_more` 在边界上正确（恰好剩一页那种）；
  7. 未读：`read` 标记计数、重复标记归零、好友行 `unread` 与 `counts.unread_total`；
  8. ★ 推送：模块级断言 `server.push_friend_message` **真的被调用**（打桩在 server 上）；
  9. 契约守卫：`GET /api/friends` 的 friends 行多了 `unread`、counts 多了 `unread_total`，
     且**入口红点（`counts.incoming`）不被未读私聊污染**。

⚠️ 第 8 块为什么必须有：本项目栽过"推送函数写了、接口也回 ok，但**从来没被调用**"
   （`tests/test_friends_api.py` 里那几条 `test_*_pushes_*` 就是为它补的）。
   纯行为测试只看数据库与返回值，**永远发现不了**——对方在线也收不到任何东西。

⚠️ 本文件造的消息与好友边**自己回收**（见 `_cleanup`）：`friend_messages` 与
   `user_friends` 是整个测试会话共用的表，不回收的话任何依赖"未读为 0 / 会话为空"
   的用例都会在后面假红，而失败点**不在本文件里**（test_friends_api.py 的注释
   记过同形状的坑）。

跑测试必须重定向临时目录（本机 Temp 的 ACL 坏了）：
    New-Item -ItemType Directory -Force .tmp\pytemp | Out-Null
    $env:TMP="$PWD\.tmp\pytemp"; $env:TEMP=$env:TMP
    python -m pytest tests/ -q -p no:cacheprovider
"""
import time
import uuid

import pytest

import api
import db as db_module
import dm
import server

# POST / 推送消息里的字段（**逐字段冻结**：多一个少一个都算契约漂移）
MESSAGE_KEYS = {'id', 'from_uid', 'to_uid', 'body', 'created_at', 'stamp', 'mine'}
# socket 推送 payload 的字段（契约 §4：GET 那条的形状 **外加** 两个展示字段）
PUSH_KEYS = {'id', 'from_uid', 'from_username', 'from_avatar',
             'body', 'created_at', 'stamp'}
# `GET /api/friends` 顶层与 friends 行的键（私聊批各新增一个）
PAYLOAD_KEYS = {'friends', 'incoming', 'outgoing', 'limits', 'counts'}
FRIEND_KEYS = {'user_id', 'username', 'avatar', 'level', 'rank_label',
               'online', 'in_game', 'unread'}
COUNT_KEYS = {'friends', 'incoming', 'unread_total'}


# ===========================================================================
# 夹具与助手
# ===========================================================================
@pytest.fixture
def make_user():
    """建一个真账号，返回 `(uid, username)`；用例结束回收本用例的数据。"""
    created = []

    def _make():
        uid = None
        for _ in range(20):
            username = 'dm_' + uuid.uuid4().hex[:10]
            uid = db_module.create_user(username, 'x')
            if uid:
                break
        assert uid, '建号失败（用户名冲突？）'
        created.append(uid)
        return uid, username

    yield _make
    _cleanup(created)


def _cleanup(uids):
    """删掉本文件造出来的私聊消息与好友边（**测试卫生**，不是断言的一部分）。

    只碰本用例自己造出来的 uid，不扫全表删（那会把并行/其它文件的用例打坏）。
    """
    ids = [str(u) for u in (uids or []) if u]
    if not ids:
        return
    marks = ','.join('?' for _ in ids)
    try:
        conn = db_module.db.conn
        conn.execute(f'DELETE FROM friend_messages WHERE from_uid IN ({marks})', ids)
        conn.execute(f'DELETE FROM friend_messages WHERE to_uid IN ({marks})', ids)
        conn.execute(f'DELETE FROM user_friends WHERE user_id IN ({marks})', ids)
        conn.execute(f'DELETE FROM user_friends WHERE friend_id IN ({marks})', ids)
        conn.commit()
    except Exception as e:      # noqa: BLE001 —— 清理失败不该把用例判红
        print(f'[test] 回收私聊/好友数据失败（不影响断言）: {e}')


def _client(uid=None, username=None):
    """一个 test_client；给了 uid 就顺手登录。

    ⚠️ 每个 `test_client()` 各带各的 cookie jar —— 同一用例里**复用同一个 client**，
    另起一个会丢 session（表现为"明明登录了却读到 401"）。
    """
    client = server.app.test_client()
    if uid:
        with client.session_transaction() as sess:
            sess['user_id'] = uid
            sess['username'] = username
    return client


def _be_friends(a, b):
    """把 a、b 变成好友（走真 DAO：申请 + 接受，不直接写边）。"""
    assert db_module.send_friend_request(a, b) == 'sent'
    assert db_module.accept_friend_request(b, a) is True


def _send(client, username, body):
    return client.post('/api/friends/messages', json={'username': username, 'body': body})


def _send_ok(client, username, body):
    resp = _send(client, username, body)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()['message']


def _history(client, username, **params):
    resp = client.get('/api/friends/messages', query_string={'username': username, **params})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _read(client, username):
    return client.post('/api/friends/messages/read', json={'username': username})


def _friends(client):
    resp = client.get('/api/friends')
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _unread_of(payload, uid):
    """`GET /api/friends` 里某个好友行的 `unread`（找不到那一行就是失败）。"""
    for row in payload['friends']:
        if str(row['user_id']) == str(uid):
            return row['unread']
    raise AssertionError(f'好友行里没有 {uid}: {payload["friends"]}')


# ===========================================================================
# 1 · `dm.py` 纯规则（单一真源）
# ===========================================================================














# ===========================================================================
# 2 · 关系门禁：只有好友能私聊
# ===========================================================================
def test_plain_strangers_cannot_send_or_read(make_user):
    """非好友：发、读、拉会话三条路**全部 403**（陌生人能私聊 = 骚扰面）。"""
    a, a_name = make_user()
    b, b_name = make_user()
    ca = _client(a, a_name)

    resp = _send(ca, b_name, '在吗')
    assert resp.status_code == 403, resp.get_data(as_text=True)
    assert resp.get_json()['status'] == 'error'

    resp = _read(ca, b_name)
    assert resp.status_code == 403, resp.get_data(as_text=True)

    resp = ca.get('/api/friends/messages', query_string={'username': b_name})
    assert resp.status_code == 403, resp.get_data(as_text=True)

    # 一行都不许写库
    assert db_module.list_friend_messages(a, b) == []








def test_blocked_relation_is_403_in_both_directions(make_user):
    """★ **两个方向都测**：我拉黑了他、他拉黑了我，都 403，且原因**不区分方向**。

    ⚠️ 为什么两条都要：`get_friend_relation` 的返回值在两个方向上**字符串不同**
    （`blocked_by_me` / `blocked_me`）—— 只判其中一个字符串的写法会在另一个方向
    静默放行（方向写反不会报错，只会让拉黑形同虚设）。这正是本项目
    "恒等式断言拦不住方向写反"那条教训。
    ⚠️ 文案不许告诉客户端"是谁拉黑了谁"：否则被拉黑的人能确定自己被谁拉黑了，
    换个号继续骚扰即可。所以只要求"有中文原因"，且**两个方向的文案相同**。
    """
    for blocker_is_me in [True, False]:
        a, a_name = make_user()
        b, b_name = make_user()
        _be_friends(a, b)

        if blocker_is_me:
            assert db_module.block_user(a, b) is True      # 我拉黑了他
            ca, cb = _client(a, a_name), _client(b, b_name)
        else:
            assert db_module.block_user(b, a) is True      # 他拉黑了我
            ca, cb = _client(b, b_name), _client(a, a_name)

        # 拉黑方自己也不能发（拉黑后双方都不能聊，契约 §1）
        r1 = _send(ca, b_name if blocker_is_me else a_name, '在吗')
        assert r1.status_code == 403, r1.get_data(as_text=True)
        r2 = _send(cb, a_name if blocker_is_me else b_name, '在吗')
        assert r2.status_code == 403, r2.get_data(as_text=True)

        reason_1 = r1.get_json().get('error') or ''
        reason_2 = r2.get_json().get('error') or ''
        assert reason_1 and reason_2, '必须给中文原因'
        assert reason_1 == reason_2, (
            f'两个方向的文案必须一致（不能泄露是谁拉黑了谁）: {reason_1!r} vs {reason_2!r}'
        )




# ===========================================================================
# 3 · 正文校验
# ===========================================================================




# ===========================================================================
# 4 · 限流
# ===========================================================================
def test_rate_limit_returns_429_and_the_rejected_one_is_not_stored(make_user):
    """一分钟内第 `PER_MINUTE + 1` 条 → 429，且被拒的那条**不占配额、不落库**。

    ⚠️ "被拒的不落库"很重要：否则拒绝本身也会把窗口占满，
    连点几次之后要等一分钟才能再发（`quick_chat.check_rate` 的注释记过这个坑）。
    """
    a, a_name = make_user()
    b, b_name = make_user()
    _be_friends(a, b)
    ca = _client(a, a_name)

    for i in range(dm.PER_MINUTE):
        _send_ok(ca, b_name, f'第{i}条')
    assert len(db_module.list_friend_messages(a, b)) == dm.PER_MINUTE

    resp = _send(ca, b_name, '再来一条')
    assert resp.status_code == 429, resp.get_data(as_text=True)
    assert resp.get_json().get('error'), '必须有中文原因'
    # 被拒的那条不落库
    assert len(db_module.list_friend_messages(a, b)) == dm.PER_MINUTE






# ===========================================================================
# 5 · 会话合成（两个方向 = 同一条会话）
# ===========================================================================




# ===========================================================================
# 6 · 分页
# ===========================================================================






# ===========================================================================
# 7 · 未读与已读
# ===========================================================================








# ===========================================================================
# 8 · ★ 推送（接口写完库**必须**真的推事件）
# ===========================================================================












# ===========================================================================
# 9 · 契约守卫（形状冻结）
# ===========================================================================
