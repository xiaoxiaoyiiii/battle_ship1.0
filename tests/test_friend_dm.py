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
def test_normalize_body_strips_control_chars_and_flattens_newlines():
    """去控制字符、`\\n` 压成空格、去首尾空白（与 `profile_spec.normalize_status` 同口径）。

    ⚠️ 控制字符是前端渲染不出来却能进库的脏数据；换行必须压掉 ——
    私聊框是单行输入，保留的换行既会撑破渲染，也是刷屏工具。
    """
    assert dm.normalize_body('  在吗  ') == '在吗'
    assert dm.normalize_body('a\x00b') == 'ab', '控制字符必须清掉'
    assert dm.normalize_body('a\nb') == 'a b', '换行压成空格'
    assert dm.normalize_body('a\r\nb') == 'a b', '\\r 是控制字符，先清掉再压 \\n'
    assert dm.normalize_body('\n\n在吗\n\n') == '在吗', '首尾空白一起收掉'
    assert dm.normalize_body('  \t ') == '', '纯空白归一化成空串'
    # 非字符串不抛（调用点是一个 HTTP 请求，畸形 JSON 不该打成 500）
    assert dm.normalize_body(None) == ''
    assert dm.normalize_body(123) == ''
    assert dm.normalize_body(['在吗']) == ''
    # 中文与常见标点必须原样保留（别把「？」这种全角字符当控制字符清掉）
    assert dm.normalize_body('今晚还打吗？') == '今晚还打吗？'


def test_body_error_names_the_300_limit_and_accepts_exactly_300():
    """空/超长给中文原因，且**点名「300 字」**；恰好 300 字必须放行。

    ⚠️ 边界（300 通过 / 301 拒绝）必须显式钉住：写成 `>=` 会让满 300 字的消息
    发不出去，而前端 `maxlength=300` 又刚好卡在那个值上 —— 用户看到的是
    "输入框允许我打 300 字，点发送却说过长"。
    """
    assert dm.body_error('') == '消息不能为空'
    assert dm.body_error('在吗') == ''

    assert dm.MAX_BODY_LEN == 300, '契约 §3 冻结为 300'
    ok = '好' * 300
    assert dm.body_error(ok) == '', '恰好 300 字必须通过'
    assert dm.too_long(ok) is False

    too_long = '好' * 301
    reason = dm.body_error(too_long)
    assert '300' in reason, f'原因里必须点名 300 字：{reason!r}'
    assert reason, '超长必须有中文原因（不能静默截断）'
    assert dm.too_long(too_long) is True


def test_check_rate_counts_only_the_window_and_respects_the_limit():
    """窗口内条数到 `PER_MINUTE` 就拒绝；窗口外的旧时间戳不算数。

    ⚠️ 纯函数、不传真实时钟：不这样写这条测试就依赖跑测试时的具体时刻。
    """
    now = 1_000_000.0
    assert dm.PER_MINUTE == 20, '契约 §3 冻结为 20'
    assert dm.RATE_WINDOW_SECONDS == 60

    # 19 条都在窗口内 → 还没到上限
    recent = [now - 1 for _ in range(dm.PER_MINUTE - 1)]
    assert dm.check_rate(recent, now) is False
    # 第 20 条 → 该拒了
    assert dm.check_rate(recent + [now - 1], now) is True
    # 窗口外的旧条数一律不算（否则聊过一会儿就永久被限流）
    old = [now - 999 for _ in range(dm.PER_MINUTE * 3)]
    assert dm.check_rate(old, now) is False
    # 空 / 脏时间戳都不许抛
    assert dm.check_rate([], now) is False
    assert dm.check_rate([None, 'x', {}, now], now) is False


def test_check_rate_does_not_hold_state():
    """`dm` 里**没有任何可变状态**（限流账本在库里，不在进程内存里）。

    ⚠️ 这条守的是契约 §3 那句「频率状态不住在这里」。一旦有人往里加一个模块级
    dict 当账本，所有人就会被串成一条队列（甲刷屏、乙被 429），而且 pytest 里
    同一进程跑两条用例会互相污染 —— 症状是"单独跑绿、全量跑红"。
    """
    mutable = [k for k, v in vars(dm).items()
               if not k.startswith('__')
               and isinstance(v, (dict, list, set))
               and k not in ('_SHORT_FORMAT', '_FULL_FORMAT')]
    assert mutable == [], f'dm.py 里出现了可变模块级状态（限流账本该在库里）: {mutable}'


def test_stamp_hides_year_within_the_same_year():
    """同年只显示 `MM-DD HH:MM`（聊天列表里年份是噪声）。"""
    # 2026-09-19 15:40（本地时区）
    ts = int(time.mktime((2026, 9, 19, 15, 40, 0, 0, 0, -1)))
    now = time.mktime((2026, 9, 19, 16, 0, 0, 0, 0, -1))
    assert dm.stamp(ts, now) == '09-19 15:40'


def test_stamp_shows_full_year_when_the_message_is_from_another_year():
    """★ 跨年必须补上年份 —— 否则去年 12-31 的「23:59」与今年的长得一模一样。

    ⚠️ 这条是本文件里唯一钉"跨年"的用例，且**显式传 `now`**：
    不传的话它只在 12 月 31 日跑才有意义（其余时间永远测不到跨年分支）。
    """
    ts = int(time.mktime((2025, 12, 31, 23, 59, 0, 0, 0, -1)))
    now = time.mktime((2026, 1, 1, 0, 5, 0, 0, 0, -1))
    assert dm.stamp(ts, now) == '2025-12-31 23:59'

    # 反向：今年的消息在去年看，同样补年份（判据是"两个年份不同"，不是"更早"）
    ts2 = int(time.mktime((2026, 3, 1, 8, 0, 0, 0, 0, -1)))
    now2 = time.mktime((2025, 3, 1, 8, 0, 0, 0, 0, -1))
    assert dm.stamp(ts2, now2) == '2026-03-01 08:00'


def test_stamp_never_raises_on_dirty_input():
    """脏 `created_at`（None / 乱码 / 越界）返回空串，**不许抛**。

    一条读不出时间的旧行不该把整个会话打成 500 —— 前端渲染空串即可。
    """
    now = time.time()
    assert dm.stamp(None, now) == ''
    assert dm.stamp('', now) == ''
    assert dm.stamp('昨天', now) == ''
    assert dm.stamp(10 ** 20, now) == ''      # 超出平台 time_t 范围


def test_stamp_falls_back_to_message_year_when_now_is_unparseable():
    """`now` 脏到 `time.localtime(now)` 也抛时，用**消息自己的年份**判跨年。

    ⚠️ 这条守的是 `stamp()` 里第二段 `try/except`：`now` 不是脏到 `int(now)`
    抛（第一段已经兜住），而是 `int()` 成功但 `localtime()` 抛（例如一个巨大的
    整数超出平台 time_t）。这时不能回空串 —— 消息本身的时间是好的，只是"参考
    年份"算不出来。兜底用消息自己的年份，跨年规则退化成"同年"（不显示年份），
    总比把整条消息打成空 stamp 强。
    """
    ts = int(time.mktime((2026, 9, 19, 15, 40, 0, 0, 0, -1)))
    # 一个 `int()` 能过、但 `localtime()` 会 OverflowError 的值
    bad_now = 10 ** 20
    assert dm.stamp(ts, bad_now) == '09-19 15:40', 'now 坏了不该让整条 stamp 变空'


def test_push_payload_returns_exactly_the_push_keys():
    """`push_payload` 的输出字段**恰好**是 `PUSH_PAYLOAD_KEYS`（多一个少一个都不行）。

    ⚠️ 这是"推送给收件人的 payload 形状"的唯一真源。多一个内部字段（比如 `mine`）
    会把发送方视角的数据泄露给收件人；少一个字段前端就渲染不出来。
    """
    msg = {'id': 13, 'from_uid': 'u-a', 'from_username': '小红', 'from_avatar': '',
           'body': '在吗', 'created_at': 1758273605, 'stamp': '09-19 15:40'}
    out = dm.push_payload(msg)
    assert set(out) == set(dm.PUSH_PAYLOAD_KEYS), f'字段集漂移: {sorted(out)}'


def test_push_payload_coerces_numeric_fields_to_int_and_strings_to_str():
    """`id` / `created_at` 强制 int（脏值 → 0）；其余强制 str（None → ''）。

    ⚠️ 这条守的是"接口给的 dict 上带了什么类型都不该漏进 payload"。
    前端拿到 `null.body` 会静默显示成空，`null.created_at` 在某些 JSON 序列化
    路径下会变成字符串 'null' —— 类型收敛是推送形状契约的一部分。
    """
    msg = {'id': '13', 'from_uid': 7, 'from_username': None, 'from_avatar': None,
           'body': None, 'created_at': '1758273605', 'stamp': None}
    out = dm.push_payload(msg)
    assert out['id'] == 13 and isinstance(out['id'], int)
    assert out['created_at'] == 1758273605 and isinstance(out['created_at'], int)
    assert out['from_uid'] == '7'          # 非字符串一律 str()
    assert out['from_username'] == ''      # None → 空串
    assert out['from_avatar'] == ''
    assert out['body'] == ''
    assert out['stamp'] == ''


def test_push_payload_coerces_garbage_numeric_fields_to_zero():
    """`id` / `created_at` 给无法 int() 的值 → 0，**不许抛**。

    DAO 理论上不会产出这种值，但推送路径在 HTTP 请求的热路径上，一条脏行
    不该把整次发送打成 500。
    """
    msg = {'id': 'not-a-number', 'created_at': object(),
           'from_uid': '', 'from_username': '', 'from_avatar': '',
           'body': 'x', 'stamp': 'x'}
    out = dm.push_payload(msg)
    assert out['id'] == 0
    assert out['created_at'] == 0


def test_push_payload_fills_missing_fields_with_safe_defaults():
    """缺字段一律给安全空值（0 / ''），**不让 KeyError 冒出来**。

    `api.py` 传进来的是接口自己那份 dict，理论上字段齐全，但推送路径不该
    假设这件事 —— 缺一个字段就 500 的话，一条私聊能把整个发送链路打断。
    """
    out = dm.push_payload({})
    assert out == {'id': 0, 'from_uid': '', 'from_username': '', 'from_avatar': '',
                   'body': '', 'created_at': 0, 'stamp': ''}


def test_push_payload_accepts_none_and_returns_all_defaults():
    """`message=None` 不抛，返回全默认值的 dict。"""
    out = dm.push_payload(None)
    assert set(out) == set(dm.PUSH_PAYLOAD_KEYS)
    assert out['id'] == 0 and out['body'] == ''


def test_push_payload_does_not_mutate_the_input_dict():
    """返回**新 dict**，调用方（`api.py`）那份还要原样回给发送方。

    ⚠️ `push_payload` 内部用 `dict(message or {})` 浅拷贝输入，就地改它会让
    接口回给发送方的那条消息也被改掉（比如 `mine` 被 pop 掉、`id` 被改成 int）。
    """
    msg = {'id': 13, 'from_uid': 'u-a', 'from_username': '小红', 'from_avatar': '',
           'body': '在吗', 'created_at': 1758273605, 'stamp': '09-19 15:40',
           'mine': True, 'to_uid': 'u-b'}
    snapshot = dict(msg)
    dm.push_payload(msg)
    assert msg == snapshot, '输入 dict 不该被修改'


def test_push_payload_strips_sender_perspective_fields():
    """`mine` / `to_uid` 这类**发送方视角**字段不许出现在推送 payload 里。

    ⚠️ `mine` 是"是不是我发的"，对收件人恒为 False，推过去没意义还多一个可漂移
    的点；`to_uid` 是收件人自己，推给他等于告诉他"你是收件人"——废话。
    这两个字段在接口的 GET/POST 形状里有，但推送形状（`PUSH_PAYLOAD_KEYS`）
    故意没有它们，`push_payload` 必须按这份白名单裁。
    """
    msg = {'id': 1, 'from_uid': 'u-a', 'from_username': 'A', 'from_avatar': '',
           'body': 'hi', 'created_at': 100, 'stamp': 's',
           'mine': True, 'to_uid': 'u-b'}
    out = dm.push_payload(msg)
    assert 'mine' not in out
    assert 'to_uid' not in out


def test_conversation_key_is_sorted_and_direction_independent():
    """A→B 与 B→A 是**同一段**会话（排序后的二元组）。

    ⚠️ 这是"两个方向的消息合成同一条会话"的可读表达。库里没有会话表，
    会话由消息行本身表达；这个函数只用于日志/调试，但排序规则错了会让
    日志里同一段会话出现两个 key、排查时对不上。
    """
    assert dm.conversation_key('A', 'B') == ('A', 'B')
    assert dm.conversation_key('B', 'A') == ('A', 'B'), '方向不影响结果'
    # 非字符串归一化成空串；None 也不抛
    assert dm.conversation_key(None, 7) == ('', '7')


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


def test_message_requires_login(make_user):
    """未登录一律 401 `{'error':'未登录'}`（私聊内容是私密数据）。"""
    a, a_name = make_user()
    anon = server.app.test_client()

    assert anon.get('/api/friends/messages',
                    query_string={'username': a_name}).status_code == 401
    assert anon.post('/api/friends/messages',
                     json={'username': a_name, 'body': 'hi'}).status_code == 401
    assert anon.post('/api/friends/messages/read',
                     json={'username': a_name}).status_code == 401


def test_unknown_target_is_404(make_user):
    """账号不存在 → 404（**不静默成功**：静默成功会让用户以为发出去了）。"""
    a, a_name = make_user()
    ca = _client(a, a_name)
    resp = _send(ca, 'no_such_user_' + uuid.uuid4().hex[:8], '在吗')
    assert resp.status_code == 404, resp.get_data(as_text=True)


def test_cannot_message_yourself(make_user):
    """不能和自己私聊（自己给自己发消息会让未读计数自己给自己涨）。"""
    a, a_name = make_user()
    ca = _client(a, a_name)
    resp = _send(ca, a_name, '自言自语')
    assert resp.status_code == 400, resp.get_data(as_text=True)
    assert resp.get_json().get('error')


@pytest.mark.parametrize('blocker_is_me', [True, False])
def test_blocked_relation_is_403_in_both_directions(make_user, blocker_is_me):
    """★ **两个方向都测**：我拉黑了他、他拉黑了我，都 403，且原因**不区分方向**。

    ⚠️ 为什么两条都要：`get_friend_relation` 的返回值在两个方向上**字符串不同**
    （`blocked_by_me` / `blocked_me`）—— 只判其中一个字符串的写法会在另一个方向
    静默放行（方向写反不会报错，只会让拉黑形同虚设）。这正是本项目
    "恒等式断言拦不住方向写反"那条教训。
    ⚠️ 文案不许告诉客户端"是谁拉黑了谁"：否则被拉黑的人能确定自己被谁拉黑了，
    换个号继续骚扰即可。所以只要求"有中文原因"，且**两个方向的文案相同**。
    """
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


def test_blocked_target_404_wins_over_403(make_user):
    """账号不存在仍然是 404（先于关系判断）—— 顺序反了会把 404 变成 403。"""
    a, a_name = make_user()
    ca = _client(a, a_name)
    resp = _send(ca, 'ghost_' + uuid.uuid4().hex[:8], '在吗')
    assert resp.status_code == 404


# ===========================================================================
# 3 · 正文校验
# ===========================================================================
def test_empty_and_blank_bodies_are_400_and_write_nothing(make_user):
    """空 / 纯空白 / 只有换行 → 400，且**一行都不许写库**。

    ⚠️ 这是"先归一化再判长度"那条顺序的守门人：顺序反了的话 `'\\n' * 400`
    会先通过长度检查、归一化后成空串，库里就多一条渲染成空气的"空白消息"。
    """
    a, a_name = make_user()
    b, b_name = make_user()
    _be_friends(a, b)
    ca = _client(a, a_name)

    for blank in ('', '   ', '\n', '\n\n\n', '  \t  '):
        resp = _send(ca, b_name, blank)
        assert resp.status_code == 400, (blank, resp.get_data(as_text=True))
        assert resp.get_json().get('error'), f'必须给中文原因: {blank!r}'

    assert db_module.list_friend_messages(a, b) == [], '被拒的消息一行都不许落库'


def test_overlong_body_is_400_and_names_300(make_user):
    """超长 → 400，原因**点名 300 字**，并且当前字数也带上（用户才知道超了多少）。"""
    a, a_name = make_user()
    b, b_name = make_user()
    _be_friends(a, b)
    ca = _client(a, a_name)

    resp = _send(ca, b_name, '好' * 301)
    assert resp.status_code == 400, resp.get_data(as_text=True)
    reason = resp.get_json().get('error') or ''
    assert '300' in reason, f'必须在原因里点名 300 字：{reason!r}'
    assert '301' in reason, f'带上当前字数更好定位：{reason!r}'
    assert db_module.list_friend_messages(a, b) == []

    # 恰好 300 字必须发得出去
    msg = _send_ok(ca, b_name, '好' * 300)
    assert len(msg['body']) == 300


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


def test_rate_limit_is_per_sender_not_process_wide(make_user):
    """★ 限流**按发送者隔离**：甲被限流，乙照发不误。

    ⚠️ 这条守的是契约 §3 那句「频率状态别放进程级全局 dict 里串房间」。
    账本用的是**库里的真实行数**（`count_friend_messages_since` 按 `from_uid` 过滤），
    所以天然隔离；一旦有人改成模块级 list 当账本，这条会红 —— 而那种实现下
    受害者是**别人**（甲刷屏导致乙被 429），用户在线上只会觉得"我什么都没干就被限流"。

    顺带钉住：限流**不按会话**，所以甲连发也会堵住甲自己发给别人的路
    （群发式骚扰不能靠换个人头绕过）。
    """
    a, a_name = make_user()
    b, b_name = make_user()
    c, c_name = make_user()
    # 三个人两两互为好友：这样"甲换个收件人也发不出去"与"乙照发"才是**同一个收件人**可比的
    _be_friends(a, b)
    _be_friends(a, c)
    _be_friends(b, c)
    ca, cb, cc = _client(a, a_name), _client(b, b_name), _client(c, c_name)

    for i in range(dm.PER_MINUTE):
        _send_ok(ca, b_name, f'第{i}条')

    # 甲：换个人头也发不出去（限流只按发送者算，与收件人无关）
    assert _send(ca, c_name, '换个收件人').status_code == 429

    # 乙（另一个发送者）：完全不受影响 —— 发给同一个人 b 也照样能发
    _send_ok(cc, b_name, '我是另一个人')
    _send_ok(cb, a_name, '我还能连发好几条')


def test_rate_limit_does_not_count_messages_from_the_other_side(make_user):
    """限流只数**我发出去的**：对方发得再多也不该把我堵住。

    ⚠️ 数错方向的话（比如按会话总条数），一个话多的好友能把你的嘴封上。
    """
    a, a_name = make_user()
    b, b_name = make_user()
    _be_friends(a, b)
    cb = _client(b, b_name)

    for i in range(dm.PER_MINUTE):
        _send_ok(cb, a_name, f'他发的第{i}条')

    # b 自己已经被限流了……
    assert _send(cb, a_name, '再来').status_code == 429
    # ……但 a 一条都没发过，必须还能发
    ca = _client(a, a_name)
    _send_ok(ca, b_name, '我第一次发言')


# ===========================================================================
# 5 · 会话合成（两个方向 = 同一条会话）
# ===========================================================================
def test_both_directions_merge_into_one_conversation(make_user):
    """★ A→B 与 B→A **同一条会话**，`mine` 按视角正确（两边各断言一次）。

    ⚠️ 方向写反在 SQL 里不会报错、只会静默少一半消息，所以这里必须
    **两个视角都看**：只测一个方向时，"只查 `from=me`"这种错照样全绿。
    """
    a, a_name = make_user()
    b, b_name = make_user()
    _be_friends(a, b)
    ca, cb = _client(a, a_name), _client(b, b_name)

    _send_ok(ca, b_name, '在吗')
    _send_ok(cb, a_name, '在的')

    # A 的视角
    va = _history(ca, b_name)
    bodies_a = [m['body'] for m in va['messages']]
    assert bodies_a == ['在吗', '在的'], f'A 应当看到两个方向的全部消息: {bodies_a}'
    assert [m['mine'] for m in va['messages']] == [True, False], 'A 视角：自己发的 mine=True'

    # B 的视角（同一段会话，`mine` 正好相反）
    vb = _history(cb, a_name)
    bodies_b = [m['body'] for m in vb['messages']]
    assert bodies_b == ['在吗', '在的'], f'B 也应当看到同一条会话: {bodies_b}'
    assert [m['mine'] for m in vb['messages']] == [False, True], 'B 视角：自己发的 mine=True'

    # 两个方向的 from/to 都记着（会话段的基本事实）
    assert va['messages'][0]['from_uid'] == a and va['messages'][0]['to_uid'] == b
    assert va['messages'][1]['from_uid'] == b and va['messages'][1]['to_uid'] == a


def test_newest_message_is_last_and_stamp_is_filled_by_the_server(make_user):
    """列表**最新的在后**（前端直接追加渲染），每条都带服务端算好的 `stamp`。"""
    a, a_name = make_user()
    b, b_name = make_user()
    _be_friends(a, b)
    ca = _client(a, a_name)

    ids = [_send_ok(ca, b_name, f'第{i}条')['id'] for i in range(3)]
    page = _history(ca, b_name)
    assert [m['id'] for m in page['messages']] == sorted(ids), '最新的必须在最后'
    for m in page['messages']:
        assert m['stamp'], '服务端必须下发 stamp（前端只渲染、不重算）'
        assert m['stamp'] == dm.stamp(m['created_at']), 'stamp 与 created_at 必须自洽'
        assert set(m) == MESSAGE_KEYS, f'字段集漂移了: {sorted(m)}'


# ===========================================================================
# 6 · 分页
# ===========================================================================
def test_before_cursor_pages_backwards_and_reports_has_more(make_user):
    """`before=<id>` 往更早翻；`has_more` 在**最后一次**为假。

    ⚠️ `has_more` 不许由"这页取满了就算还有"推断：这里每一页都取满，
    所以那条推断会永远说 True（前端于是显示一个点了没反应的按钮）。
    """
    a, a_name = make_user()
    b, b_name = make_user()
    _be_friends(a, b)
    ca = _client(a, a_name)

    total = 12
    ids = [_send_ok(ca, b_name, f'第{i}条')['id'] for i in range(total)]

    page1 = _history(ca, b_name, limit=5)
    assert [m['id'] for m in page1['messages']] == ids[-5:], '第一页是最新的 5 条'
    assert page1['has_more'] is True, '前面还有 7 条'

    oldest = page1['messages'][0]['id']
    page2 = _history(ca, b_name, limit=5, before=oldest)
    assert [m['id'] for m in page2['messages']] == ids[-10:-5], '第二页接着往更早'
    assert page2['has_more'] is True

    page3 = _history(ca, b_name, limit=5, before=page2['messages'][0]['id'])
    assert [m['id'] for m in page3['messages']] == ids[:2], '最后只剩 2 条'
    assert page3['has_more'] is False, '★ 恰好取不满时必须是 False'

    # 再往更早：空页 + has_more=False（前端据此藏掉「加载更早」）
    page4 = _history(ca, b_name, limit=5, before=page3['messages'][0]['id'])
    assert page4['messages'] == []
    assert page4['has_more'] is False


def test_has_more_is_false_when_the_page_is_exactly_full(make_user):
    """★ `has_more` 的边界：**恰好剩一整页**时必须是 False。

    这是"取满了就推断还有"那条错实现唯一会露馅的地方（也是它最容易被漏测的地方）：
    恰好 5 条、limit=5 → 取满，但确实没有更早的了。
    """
    a, a_name = make_user()
    b, b_name = make_user()
    _be_friends(a, b)
    ca = _client(a, a_name)

    for i in range(5):
        _send_ok(ca, b_name, f'第{i}条')

    page = _history(ca, b_name, limit=5)
    assert len(page['messages']) == 5, '这一页正好取满'
    assert page['has_more'] is False, '取满 ≠ 还有更早的（这条是错实现的照妖镜）'


def test_limit_is_clamped_and_bad_cursor_degrades_to_latest(make_user):
    """`limit` 有上限（防一次把整段会话拉进内存）；坏 `before` 当"没给游标"。

    ⚠️ 坏游标不 400 是有意的：前端拼错 URL 时用户看到的是"最新消息"而不是报错框。
    """
    a, a_name = make_user()
    b, b_name = make_user()
    _be_friends(a, b)
    ca = _client(a, a_name)
    for i in range(3):
        _send_ok(ca, b_name, f'第{i}条')

    assert len(_history(ca, b_name, limit=10 ** 9)['messages']) == 3, '上限内正常返回'
    assert api.DM_MAX_PAGE_SIZE == dm.MAX_PAGE_SIZE

    bad = _history(ca, b_name, before='昨天')
    assert [m['body'] for m in bad['messages']] == ['第0条', '第1条', '第2条'], '坏游标 = 最新一页'


# ===========================================================================
# 7 · 未读与已读
# ===========================================================================
def test_read_marks_returns_count_and_zeroes_the_unread(make_user):
    """`POST /read` 返回标记条数、重复调用归零、好友行 `unread` 与总数一起归零。"""
    a, a_name = make_user()
    b, b_name = make_user()
    _be_friends(a, b)
    ca, cb = _client(a, a_name), _client(b, b_name)

    for i in range(3):
        _send_ok(ca, b_name, f'第{i}条')

    # B 侧：3 条未读（行内 + 总数都看得见）
    payload_b = _friends(cb)
    assert _unread_of(payload_b, a) == 3
    assert payload_b['counts']['unread_total'] == 3

    # ★ 入口红点仍是"待确认申请数"，**不被未读私聊污染**（契约 §1 明文）
    assert payload_b['counts']['incoming'] == 0, (
        '未读私聊绝不能混进 counts.incoming —— 那条契约被 friends_check T8b 钉着'
    )

    resp = _read(cb, a_name)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json() == {'status': 'ok', 'read': 3}

    payload_b2 = _friends(cb)
    assert _unread_of(payload_b2, a) == 0, '★ 好友行 unread 必须归零'
    assert payload_b2['counts']['unread_total'] == 0
    assert payload_b2['counts']['incoming'] == 0

    # 幂等：再标一次返回 0（而不是历史总数）
    assert _read(cb, a_name).get_json()['read'] == 0

    # A 侧不该有任何未读（B 一条都没发）
    payload_a = _friends(ca)
    assert payload_a['counts']['unread_total'] == 0


def test_read_only_marks_the_other_sides_messages(make_user):
    """★ 只标"他发给我的"：把自己发的也标了就永远没有未读（方向写反不报错）。

    三个发/收的组合一次钉住：
      · A→B 的不该被 B 的 `read` 影响 A 自己的账；
      · B→A 的在 A 侧是未读，直到 A 去 read；
      · A 去 read(B) 之后，**B 侧的未读不受影响**（那是 B 的账）。
    """
    a, a_name = make_user()
    b, b_name = make_user()
    _be_friends(a, b)
    ca, cb = _client(a, a_name), _client(b, b_name)

    _send_ok(ca, b_name, 'A 说的')          # B 侧未读 1
    _send_ok(cb, a_name, 'B 说的')          # A 侧未读 1

    assert _unread_of(_friends(cb), a) == 1
    assert _unread_of(_friends(ca), b) == 1

    # A 读"B 发来的" → 只清 A 侧的账
    assert _read(ca, b_name).get_json()['read'] == 1
    assert _unread_of(_friends(ca), b) == 0
    # ⚠️ B 侧那条 A→B 的仍未读（别人的 read 不许动我的账）
    assert _unread_of(_friends(cb), a) == 1, 'A 的 read 不该把 B 的未读清掉'

    # B 再读 → 归零
    assert _read(cb, a_name).get_json()['read'] == 1
    assert _unread_of(_friends(cb), a) == 0


def test_unread_is_zero_for_messages_i_sent_myself(make_user):
    """自己发的消息**不给自己**加未读（未读是收件人视角的事）。"""
    a, a_name = make_user()
    b, b_name = make_user()
    _be_friends(a, b)
    ca = _client(a, a_name)

    _send_ok(ca, b_name, '在吗')
    assert _friends(ca)['counts']['unread_total'] == 0, '自己发的不该给自己涨未读'
    assert _unread_of(_friends(ca), b) == 0


def test_new_message_after_reading_shows_unread_again(make_user):
    """已读之后**再来一条**必须重新变成未读（否则"谁又给我发了"看不见）。"""
    a, a_name = make_user()
    b, b_name = make_user()
    _be_friends(a, b)
    ca, cb = _client(a, a_name), _client(b, b_name)

    _send_ok(ca, b_name, '第一条')
    assert _read(cb, a_name).get_json()['read'] == 1
    assert _unread_of(_friends(cb), a) == 0

    _send_ok(ca, b_name, '第二条')
    assert _unread_of(_friends(cb), a) == 1, '★ 读完再来一条要重新算未读'
    assert _friends(cb)['counts']['unread_total'] == 1


# ===========================================================================
# 8 · ★ 推送（接口写完库**必须**真的推事件）
# ===========================================================================
def test_send_pushes_friend_message_to_the_recipient(monkeypatch, make_user):
    """★ 发消息成功后必须调 `server.push_friend_message`，收件人与 payload 内容逐字段对。

    ⚠️ 打桩打在 **`server` 上**（不是 api 内部）：`api._push_friend_event` 是
    **按名字现取**后端函数的，所以这里能真的拦到调用 —— 而"注入函数对象"的写法
    会把这个桩静默架空（测试还是绿的，但线上推送永远不触发）。
    ⚠️ 字段集在这里**只断言"契约要求的七个字段都在"**，`==` 的那条严格断言放在
    `test_push_friend_message_event_name_and_shape`（直调真函数的版本）——
    因为本用例把 `push_friend_message` 整个换掉了，跑的是**接口发出的那份**，
    不是"收件人最终看到的那份"（那由 `server` → `dm.push_payload` 决定）。
    """
    a, a_name = make_user()
    b, b_name = make_user()
    _be_friends(a, b)

    pushed = []
    monkeypatch.setattr(server, 'push_friend_message',
                        lambda *args: (pushed.append(args), True)[1], raising=False)

    msg = _send_ok(_client(a, a_name), b_name, '在吗')

    assert len(pushed) == 1, f'必须恰好推一次，实际 {len(pushed)} 次'
    to_uid, payload = pushed[0]
    assert str(to_uid) == str(b), '要推给**收件人**，不是发送者'

    assert PUSH_KEYS <= set(payload), f'socket payload 缺字段: {sorted(PUSH_KEYS - set(payload))}'
    assert payload['id'] == msg['id']
    assert payload['from_uid'] == a
    assert payload['from_username'] == a_name, '没打开会话的收件人要靠它弹提示'
    assert isinstance(payload['from_avatar'], str)
    assert payload['body'] == '在吗'
    assert payload['created_at'] == msg['created_at']
    assert payload['stamp'] == msg['stamp'], '推送与接口必须是同一个 stamp（同一份实现）'
    # ⚠️ 视角字段不许漏给收件人：`mine` 是**发送方**视角算的，对收件人是错的
    assert 'mine' not in payload, 'mine 是发送方视角的字段，推给收件人含义就是错的'


def test_send_still_returns_ok_when_the_recipient_is_offline(monkeypatch, make_user):
    """对方离线（推送返回 False）→ 接口**照样回 ok**。

    ⚠️ 与"邀战"不同：邀请必须是实时的（推不到就失败），私聊不是 ——
    消息已经落库，对方下次打开会话就拉到了。回 error 会让发送方以为没发出去、
    于是重发一遍（对方上线看到两条一模一样的）。
    """
    a, a_name = make_user()
    b, b_name = make_user()
    _be_friends(a, b)

    monkeypatch.setattr(server, 'push_friend_message', lambda *args: False, raising=False)

    resp = _send(_client(a, a_name), b_name, '在吗')
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body['status'] == 'ok', body
    # 真的落库了
    assert [m['body'] for m in db_module.list_friend_messages(a, b)] == ['在吗']


def test_send_never_pushes_when_the_body_is_rejected(monkeypatch, make_user):
    """被拒的消息（空/超长/限流）**一条都不许推**（推了就是"你收到了我没发出的东西"）。"""
    a, a_name = make_user()
    b, b_name = make_user()
    _be_friends(a, b)

    pushed = []
    monkeypatch.setattr(server, 'push_friend_message',
                        lambda *args: (pushed.append(args), True)[1], raising=False)
    ca = _client(a, a_name)

    assert _send(ca, b_name, '').status_code == 400
    assert _send(ca, b_name, '好' * 301).status_code == 400
    for i in range(dm.PER_MINUTE):
        _send_ok(ca, b_name, f'第{i}条')
    pushed.clear()
    assert _send(ca, b_name, '被限流').status_code == 429

    assert pushed == [], f'被拒的请求不许推送: {pushed}'


def test_push_friend_message_is_resolvable_by_name_from_the_injected_module():
    """接线守卫：`server.push_friend_message` 必须能被注入的模块**按名字取到**。

    ⚠️ 这条是**源码/接线级**的，不是行为级：pytest 里 server 就叫 `server`，
    一切正常；真跑起来是 `python server.py`（模块名 `__main__`），
    少注册一个能力只会让推送**静默失效**（接口照回 ok）。见
    `tests/test_friends_wiring.py` 的同款说明。
    """
    assert api._FRIEND_BACKEND_MODULE is server
    assert api._friend_backend('push_friend_message') is server.push_friend_message


def test_push_friend_message_event_name_and_shape(monkeypatch):
    """`server.push_friend_message` 发出的**事件名**是 `friend_message`，payload 逐字段。

    直接打桩 `_push_friend_event`（同一个文件里的发车口）来观察事件名 ——
    不碰 presence / socketio，因此与"对方在不在线"完全无关。
    """
    seen = []
    monkeypatch.setattr(server, '_push_friend_event',
                        lambda to_uid, name, payload: (seen.append((to_uid, name, payload)), True)[1])

    ok = server.push_friend_message('u-收件人', {
        'id': 13, 'from_uid': 'u-发件人', 'from_username': '小红', 'from_avatar': '',
        'body': '在吗', 'created_at': 1758273605, 'stamp': '09-19 15:40',
        # 接口那份 dict 上的视角字段**不许**漏给收件人
        'mine': True, 'to_uid': 'u-收件人',
    })
    assert ok is True
    assert len(seen) == 1
    to_uid, name, payload = seen[0]
    assert to_uid == 'u-收件人'
    assert name == 'friend_message', f'事件名冻结为 friend_message: {name}'
    assert set(payload) == PUSH_KEYS, f'payload 字段集漂移了: {sorted(payload)}'
    assert 'mine' not in payload, '视角字段 mine 是发送方视角的，不该推给收件人'
    assert 'to_uid' not in payload
    assert payload['id'] == 13 and payload['stamp'] == '09-19 15:40'


def test_push_friend_message_returns_false_for_offline_target(monkeypatch):
    """对方离线 → 返回 False，**不抛**（socket 静默丢弃，绝不能乐观地回 True）。"""
    monkeypatch.setattr(server, '_push_friend_event',
                        lambda to_uid, name, payload: False)
    assert server.push_friend_message('u-离线', {'id': 1, 'body': 'hi'}) is False


# ===========================================================================
# 9 · 契约守卫（形状冻结）
# ===========================================================================
def test_friends_payload_gained_exactly_unread_and_unread_total(make_user):
    """`GET /api/friends` 恰好多了两个键：friends 行的 `unread`、counts 的 `unread_total`。

    ⚠️ 用**集合相等**而不是 `in`：多出第三个键（比如顺手把消息内容也塞进来）
    同样算契约漂移，而其它的形状测试未必会发现。
    """
    a, a_name = make_user()
    b, b_name = make_user()
    _be_friends(a, b)
    ca = _client(a, a_name)
    _send_ok(ca, b_name, '在吗')

    payload = _friends(ca)
    assert set(payload) == PAYLOAD_KEYS, f'顶层键漂移: {sorted(payload)}'
    assert set(payload['counts']) == COUNT_KEYS, f'counts 键漂移: {sorted(payload["counts"])}'
    for row in payload['friends']:
        assert set(row) == FRIEND_KEYS, f'好友行键漂移: {sorted(row)}'
        assert isinstance(row['unread'], int), 'unread 必须是整数（前端当数字用）'


def test_get_and_post_shapes_are_frozen(make_user):
    """GET / POST 的响应形状逐字段冻结（契约 §4 的那两段 JSON）。"""
    a, a_name = make_user()
    b, b_name = make_user()
    _be_friends(a, b)
    ca = _client(a, a_name)

    msg = _send_ok(ca, b_name, '在吗')
    assert set(msg) == MESSAGE_KEYS, f'POST 的 message 形状漂移: {sorted(msg)}'
    assert msg['mine'] is True, 'A 自己发的 → mine=True'

    page = _history(ca, b_name)
    assert set(page) == {'status', 'has_more', 'messages'}, f'GET 顶层键漂移: {sorted(page)}'
    assert page['status'] == 'ok'
    assert isinstance(page['has_more'], bool)
    assert set(page['messages'][0]) == MESSAGE_KEYS

    # 已登录但关系不合法时，`status` 一律 'error' + 中文原因（契约的错误形状）
    resp = _send(_client(*make_user()), b_name, '在吗')
    assert resp.status_code == 403
    assert set(resp.get_json()) == {'status', 'error'}, resp.get_json()


def test_no_credentials_leak_in_message_responses(make_user):
    """任何响应里都不许出现凭证列（接口整行下发是本项目的硬教训）。"""
    a, a_name = make_user()
    b, b_name = make_user()
    _be_friends(a, b)
    ca = _client(a, a_name)
    _send_ok(ca, b_name, '在吗')

    raw = str(_history(ca, b_name)) + str(_friends(ca))
    for bad in ('password_hash', 'token', 'wins', 'losses'):
        assert bad not in raw, f'响应里泄露了 {bad}'
