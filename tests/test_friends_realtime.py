# -*- coding: utf-8 -*-
"""好友功能·实时侧（在线状态 / 事件推送 / 结算钩子）回归测试（2026-09-18 好友批）。

覆盖冻结契约里的 8 组：

  1. `presence` 计数口径：同一 uid 两次 `mark_online` 后**一次** `mark_offline`
     仍然在线，两次才离线；`sids_of` 返回全部 sid；`clear()` 有效；
  2. `presence` 对脏输入（None / 空串 / 不可哈希对象）**不抛异常**；
  3. `connect` 一个已登录的 socket → `presence.is_online(uid)` 为真；断开 → 为假
     （`presence` 按 **uid** 记账，与大厅那张 sid 表是两套口径 —— 合并大厅批时旧的
     裸 sid 集合 `online_users` 已被删除，这条只钉好友这一侧）；
  4. `push_friend_request`：对方在线能真的收到；对方离线返回 False 且不抛；
  5. `push_friend_invite` 同上，payload 字段齐全（`room_id`/`from_user_id`/`from_username`）；
  6. **结算钩子**：真跑一次 `_finalize_match` → 双方各收到一条 `recent_opponent`、
     字段齐全、`relation` 来自 `db.get_friend_relation`；**人机/游客局一条都不发**；
  7. ★ **降级**：把 `db.get_friend_relation` 换成会抛异常的桩 → 结算照常完成、
     该发的事件照发（缺一个 DAO 绝不许把结算搞崩）；
  8. 那条 `recent_opponent` **每人只发一次**（重复发会让结算面板弹两遍邀请）。

⚠️ 本文件只碰 `presence.py` / `server.py` 的**实时侧**；HTTP 侧的好友接口
   （`api.py`）由同批另一个智能体负责，别在这里造重复覆盖。
⚠️ 每个用例前后都 `presence.clear()`：presence 是**模块级内存全局**，不清就会串场
   （`is_online` 串味 → 用例顺序一变就假红/假绿）。
"""
import itertools
import time
import types

import pytest

import db
import presence
import server

_seq = itertools.count(1)
_TAG = 'fr9'

# `recent_opponent` 的冻结字段（逐字来自契约）
_OPPONENT_KEYS = {'user_id', 'username', 'avatar', 'relation'}


# ---------------------------------------------------------------------------
# 小工具（与 test_ranked_match.py 同一套写法：取干净一个客户端的事件队列）
# ---------------------------------------------------------------------------
def _mk_user(prefix=_TAG):
    name = f'{prefix}{next(_seq)}'
    uid = db.create_user(name, 'x' * 12)
    assert uid, f'建号失败: {name}'
    return uid


def _pick(events, name):
    """从**已经取回**的事件列表里挑出某类 payload（只留 args 是 dict 的）。"""
    out = []
    for m in events:
        if m['name'] != name:
            continue
        args = m['args']
        if isinstance(args, dict):
            args = [args]
        out.extend(a for a in (args or ()) if isinstance(a, dict))
    return out


def _drain(client, tries=30):
    """把客户端队列按到达顺序取干净。

    结算事件是从 socket 请求上下文里发的（`_push_friend_event` → `socketio.emit`），
    一次 `get_received()` 可能还没到 —— 让出几次执行权再取（与排位批同一套处理）。
    """
    events = client.get_received()
    for _ in range(tries):
        try:
            server.socketio.sleep(0)
        except Exception:
            break
        events += client.get_received()
    return events


def _recv(client, name):
    return _pick(_drain(client), name)


def _as_request(monkeypatch, sid, uid=None, username=None):
    """把 `request` / `session` / socketio 的 `join_room` 换成直调 handler 友好的假对象
    （与 `tests/test_ranked_match.py` 同一套写法）。

    ⚠️ `SocketIOTestClient.emit()` 的返回值**不保证**是 handler 的返回值
    （flask-socketio 的测试客户端只保证事件被投递），所以"要拿 room_id / 断言返回值"
    的用例一律直调 handler，别靠 socket 往返。
    """
    data = {'user_id': uid}
    if username is not None:
        data['username'] = username
    monkeypatch.setattr(server, 'request', types.SimpleNamespace(sid=sid))
    monkeypatch.setattr(server, 'session', data)
    # `join_room(room_id, sid)`（flask_socketio 的那个）在无请求上下文时会抛
    monkeypatch.setattr(server, 'join_room', lambda *a, **k: None)


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_globals():
    """presence 是模块级内存全局 + `rooms` / `match_queue` 也是 —— 前后都恢复原样。"""
    presence.clear()
    existing = set(server.room_manager.get_all_rooms())
    server.room_manager.match_queue = []
    yield
    presence.clear()
    for rid in list(server.room_manager.get_all_rooms()):
        if rid not in existing:
            server.room_manager.rooms.pop(rid, None)
    server.room_manager.match_queue = []


@pytest.fixture
def sockets():
    """建「已登录」的 socket 测试连接（session 里带 user_id，`connect` handler 才认）。"""
    made = []

    def _make(uid=None):
        http = server.app.test_client()
        if uid:
            with http.session_transaction() as sess:
                sess['user_id'] = uid
                sess['username'] = uid
        client = server.socketio.test_client(server.app, flask_test_client=http)
        client.get_received()          # 丢掉 connect 期间的噪音
        if uid:
            # connect handler 刚把这条连接的 sid 记进 presence，正是要找的那个
            sids = presence.sids_of(uid)
            if sids:
                _SID_BY_CLIENT[id(client)] = sids[-1]
        made.append(client)
        return client

    yield _make
    for client in made:
        _SID_BY_CLIENT.pop(id(client), None)
        try:
            client.disconnect()
        except Exception:
            pass


# `sockets(...)` 建连接时把服务端记下的 sid 存一份（key = 客户端对象），供 `_sid_of` 反查
_SID_BY_CLIENT = {}


def _sid_of(client):
    """测试客户端在**服务端**的 socket sid（= connect handler 里的 `request.sid`）。

    ⚠️ `SocketIOTestClient` **没有** `.sid`（flask-socketio 只给了 `eio_sid`，而
    `request.sid` 是 `sid_from_eio_sid(eio_sid, ...)` 现编出来的另一个 uuid），
    也没有公开的反查口子。所以从**服务端自己记下的** presence 登记表里取：
    这正好顺带断言了"connect 真的把这条连接记下来了"。
    """
    return _SID_BY_CLIENT.get(id(client))


@pytest.fixture
def party(sockets):
    """开一局**真结算**两人对局：`party()` → (room, ca, cb, ua, ub)。

    走真 `find_match`（和排位批同一个做法）：只有这样 `room.players` 才是"匹配房"
    那套约定（key = 入队时的 socket sid，真人 uid 在 `Player.user_id` 上）——
    结算钩子最容易在这里写错（拿 key 当 uid）。
    """
    state = {'uids': [], 'rooms': []}

    def _start():
        before = set(server.room_manager.get_all_rooms())
        ua, ub = _mk_user(), _mk_user()
        state['uids'] += [ua, ub]
        ca, cb = sockets(ua), sockets(ub)
        ca.emit('find_match', {'player_name': '甲', 'mode': 'casual'})
        cb.emit('find_match', {'player_name': '乙', 'mode': 'casual'})
        new = [r for r in server.room_manager.get_all_rooms().values() if r.id not in before]
        assert len(new) == 1, f'两个人应当被配成一局，实际新建 {len(new)} 个房'
        room = new[0]
        state['rooms'].append(room.id)
        room.state = 'attacking'
        room.match_started_at = time.time() - 400
        room.round = 6
        _drain(ca), _drain(cb)          # 丢掉 game_state 之类的配对噪音
        return room, ca, cb, ua, ub

    yield _start
    # 兜底：用例中途断言失败时 "_finalize_match 收尾 + 摘对局中标记" 也要发生，
    # 否则房间留在 rooms 里带着“对局中”标记，会串到后面的用例（假红最难查的一类）。
    for rid in state['rooms']:
        room = server.room_manager.get_room(rid)
        if room is not None:
            try:
                ids = list(room.players.keys())
                if len(ids) == 2:
                    server._finalize_match(room, ids[0], ids[1])
            except Exception:
                pass
        server.room_manager.rooms.pop(rid, None)
    presence.clear()


def _pid_of(room, uid):
    for pid, player in room.players.items():
        if getattr(player, 'user_id', None) == uid:
            return pid
    raise AssertionError(f'{uid} 不在这局里')


# ===========================================================================
# 1 / 2 · presence 本体（纯内存，不碰 socket）
# ===========================================================================
def test_presence_multi_tab_counting():
    """同一 uid 多标签页：计数 +1；**一次 offline 仍在线**，两次才离线。"""
    presence.mark_online('u1')
    presence.mark_online('u1')
    assert presence.is_online('u1') is True

    presence.mark_offline('u1')
    assert presence.is_online('u1') is True, '还有一张标签页在线，不该被判离线'

    presence.mark_offline('u1')
    assert presence.is_online('u1') is False, '两张标签页都断了，应当离线'

    # 额外的 offline 不许把计数压成负数（否则下一次 mark_online 也只到 0 → 永远"离线"）
    presence.mark_offline('u1')
    assert presence.is_online('u1') is False
    presence.mark_online('u1')
    assert presence.is_online('u1') is True


def test_presence_online_uids_and_sids():
    """`online_uids` / `sids_of` 都是"全部"口径，且 `clear()` 能整表清空。"""
    presence.mark_online('u1')
    presence.mark_online('u2')
    presence.add_sid('u1', 's-a')
    presence.add_sid('u1', 's-b')
    presence.add_sid('u1', 's-a')          # 重复登记只留一份
    presence.add_sid('u2', 's-c')

    assert presence.online_uids() == {'u1', 'u2'}
    assert presence.sids_of('u1') == ['s-a', 's-b'], '多标签页必须全给出来（只发第一个会漏）'
    assert presence.sids_of('u2') == ['s-c']

    presence.remove_sid('u1', 's-a')
    assert presence.sids_of('u1') == ['s-b']
    presence.remove_sid('u1', 's-b')
    assert presence.sids_of('u1') == [], 'sid 清空后不留空壳'

    # `online_uids` 返回的是副本：调用方改它不许影响登记表
    snap = presence.online_uids()
    snap.add('u-fake')
    assert presence.online_uids() == {'u1', 'u2'}

    presence.set_in_game('u1', True)
    assert presence.is_in_game('u1') is True
    presence.set_in_game('u1', False)
    assert presence.is_in_game('u1') is False

    presence.clear()
    assert presence.online_uids() == set()
    assert presence.sids_of('u1') == []
    assert presence.is_online('u1') is False
    assert presence.is_in_game('u1') is False


def test_presence_dirty_input_never_raises():
    """脏数据（None / 空串 / 空白 / 不可哈希）一律当没发生，**绝不抛**。

    调用点全在 connect / disconnect / 结算这些主链路上：这里抛一下就是掉线逻辑
    或者整局结算被打断。
    """
    dirty = [None, '', b'bytes-not-hashable?', [], {}, object()]

    for bad in dirty:
        presence.mark_online(bad)
        presence.mark_offline(bad)
        presence.add_sid(bad, 's1')
        presence.add_sid('u1', bad)
        presence.remove_sid(bad, 's1')
        presence.remove_sid('u1', bad)
        presence.set_in_game(bad, True)
        presence.set_in_game('u1', bad)
        assert presence.is_online(bad) is False
        assert presence.is_in_game(bad) is False
        assert presence.sids_of(bad) == []

    # 脏输入不许把已经登记好的真状态带坏
    presence.mark_online('u1')
    presence.add_sid('u1', 's1')
    presence.mark_offline(None)
    presence.remove_sid('u1', None)
    assert presence.is_online('u1') is True
    assert presence.sids_of('u1') == ['s1']

    # 没登记过的 uid 直接 mark_offline：当没发生（不许压出负数）
    presence.mark_offline('never-seen')
    assert presence.is_online('never-seen') is False

    # 纯空白字符串是"脏 uid"：不许被当成一个真实用户登记（否则会凭空多一个在线账号）
    presence.mark_online('   ')
    assert presence.online_uids() == {'u1'}, '空白 uid 不许进在线表'


# ===========================================================================
# 3 · connect / disconnect 的在线登记
# ===========================================================================
def test_socket_login_marks_online_and_disconnect_clears(sockets):
    """登录用户连上 → 在线；断开 → 离线。游客（无 user_id）不进 presence。"""
    uid = _mk_user()
    client = sockets(uid)
    seat_sid = _sid_of(client)
    assert seat_sid, 'connect 必须把服务端分配的那条 sid 记进 presence'
    assert presence.is_online(uid) is True, 'connect 必须登记在线'
    assert seat_sid in presence.sids_of(uid), 'connect 必须记下这条 sid'

    client.disconnect()
    assert presence.is_online(uid) is False, 'disconnect 必须注销在线'
    assert presence.sids_of(uid) == [], 'disconnect 必须摘掉这条 sid'

    # 游客：不登记 presence（没有 uid 可登记），也不许报错
    guest = sockets(None)
    assert presence.online_uids() == set()
    guest.disconnect()


def test_connect_and_disconnect_keep_presence_by_uid(sockets):
    """`presence` 按 **uid** 记账，且**只**按 uid（与大厅那张 sid 表口径不同）。

    ⚠️ 这条原名叫 `..._keeps_legacy_online_users_semantics`，断言的是旧的那张裸 sid 集合
    `online_users`。**合并大厅批时那张表被整个删掉了**（大厅批统一读 `lobby_manager.presence`，
    见 CLAUDE.md 坑 #17"在线表只能有一份"），于是这条断言失去对象。
    现在改成只钉**好友这一侧**的契约：同一 uid 两张标签页 = 1 个人 2 条连接，
    断开一张仍在线、全断开才离线 —— 这正是好友面板要的"在线/对局中"语义。
    """
    uid = _mk_user()
    ca, cb = sockets(uid), sockets(uid)              # 同一 uid 两张标签页
    assert presence.is_online(uid) is True
    assert len(presence.sids_of(uid)) == 2, 'presence 按 uid 记两条 sid'

    ca.disconnect()
    assert presence.is_online(uid) is True, '还有一张标签页在线'
    cb.disconnect()
    assert presence.is_online(uid) is False


# ===========================================================================
# 4 / 5 · push_* 的发送端
# ===========================================================================
def test_push_friend_request_reaches_online_target(sockets):
    """对方在线：真的收到 `friend_request`，字段冻结。"""
    me, peer = _mk_user(), _mk_user()
    target = sockets(peer)

    ok = server.push_friend_request(peer, me, '申请人', '/static/avatar/1.png')
    assert ok is True, '对方在线时必须返回 True'

    got = _recv(target, 'friend_request')
    assert len(got) == 1, f'应当恰好收到 1 条 friend_request，实际 {len(got)}'
    assert got[0] == {
        'from_user_id': me,
        'from_username': '申请人',
        'from_avatar': '/static/avatar/1.png',
    }


def test_push_friend_request_offline_target_returns_false(sockets):
    """对方离线：返回 False、不发、**不抛**（申请本身已经落库，等他上线看列表）。"""
    me, peer = _mk_user(), _mk_user()
    # peer 没连 socket：完全离线
    assert server.push_friend_request(peer, me, '申请人', '') is False

    # 连过又断开：同样算离线（presence 里计数归零）
    client = sockets(peer)
    client.disconnect()
    assert server.push_friend_request(peer, me, '申请人', '') is False

    # 从来没连过的 uid / 空 uid：都不许抛
    assert server.push_friend_request('no-such-uid', me, '申请人', '') is False
    assert server.push_friend_request(None, me, '申请人', '') is False


def test_push_friend_accepted_reaches_online_target(sockets):
    """`friend_accepted`：字段是**同意方**（= 新好友）的资料。"""
    requester, accepter = _mk_user(), _mk_user()
    target = sockets(requester)

    assert server.push_friend_accepted(requester, accepter, '同意者', '/a.png') is True
    got = _recv(target, 'friend_accepted')
    assert len(got) == 1
    assert got[0] == {'user_id': accepter, 'username': '同意者', 'avatar': '/a.png'}

    assert server.push_friend_accepted('no-such-uid', accepter, '同意者', '') is False


def test_push_friend_invite_reaches_online_target(sockets):
    """`friend_invite`：payload 三个字段齐全（`room_id`/`from_user_id`/`from_username`）。"""
    inviter, invitee = _mk_user(), _mk_user()
    target = sockets(invitee)

    assert server.push_friend_invite(invitee, 'room-abc', inviter, '邀请人') is True
    got = _recv(target, 'friend_invite')
    assert len(got) == 1, f'应当恰好收到 1 条 friend_invite，实际 {len(got)}'
    payload = got[0]
    assert set(payload.keys()) == {'room_id', 'from_user_id', 'from_username'}
    assert payload['room_id'] == 'room-abc'
    assert payload['from_user_id'] == inviter
    assert payload['from_username'] == '邀请人'


def test_push_friend_invite_offline_target_returns_false(sockets):
    """对方离线：返回 False 且不抛（邀请只对在线好友有意义）。"""
    inviter, invitee = _mk_user(), _mk_user()
    client = sockets(invitee)
    client.disconnect()

    assert server.push_friend_invite(invitee, 'room-abc', inviter, '邀请人') is False
    assert server.push_friend_invite(None, 'room-abc', inviter, '邀请人') is False


def test_push_friend_event_reaches_every_tab(sockets):
    """同一个人的**每张**标签页都要收到（只发第一张 = 另一张静默丢事件）。"""
    peer = _mk_user()
    tab1, tab2 = sockets(peer), sockets(peer)

    assert server.push_friend_invite(peer, 'room-xyz', 'u-inviter', '邀请人') is True
    assert len(_recv(tab1, 'friend_invite')) == 1
    assert len(_recv(tab2, 'friend_invite')) == 1


# ===========================================================================
# 6 · 结算钩子：recent_opponent
# ===========================================================================
@pytest.mark.parametrize('relation', ['none', 'pending_out', 'pending_in', 'friends'])
def test_finalize_match_pushes_recent_opponent_to_both(party, monkeypatch, relation):
    """真跑一次结算：**双方各一条** `recent_opponent`，字段齐全、relation 来自 DAO。"""
    room, ca, cb, ua, ub = party()

    calls = []

    def fake_relation(a, b):
        calls.append((a, b))
        return relation

    monkeypatch.setattr(db, 'get_friend_relation', fake_relation, raising=False)

    pid_a, pid_b = _pid_of(room, ua), _pid_of(room, ub)
    server._finalize_match(room, pid_a, pid_b)       # pid_a 胜

    got_a = _recv(ca, 'recent_opponent')
    got_b = _recv(cb, 'recent_opponent')
    assert len(got_a) == 1, f'胜者应当恰好收到 1 条 recent_opponent，实际 {len(got_a)}'
    assert len(got_b) == 1, f'败者应当恰好收到 1 条 recent_opponent，实际 {len(got_b)}'

    assert set(got_a[0].keys()) == _OPPONENT_KEYS
    assert set(got_b[0].keys()) == _OPPONENT_KEYS

    # 一人一条、方向各自正确：我收到的那条 `user_id` 必须是**对手**的
    assert got_a[0]['user_id'] == ub
    assert got_b[0]['user_id'] == ua
    assert got_a[0]['relation'] == relation
    assert got_b[0]['relation'] == relation
    assert got_a[0]['username'] == '乙'
    assert got_b[0]['username'] == '甲'

    # relation 必须是**按自己视角**问的 DAO，不能拿一份 payload 发两次
    assert (ua, ub) in calls and (ub, ua) in calls


def test_recent_opponent_relation_reflects_each_side(party, monkeypatch):
    """relation 是"我 → 对手"，两边可以不同（A 发出申请、B 收到申请）。"""
    room, ca, cb, ua, ub = party()

    def fake_relation(a, b):
        return 'pending_out' if a == ua else 'pending_in'

    monkeypatch.setattr(db, 'get_friend_relation', fake_relation, raising=False)
    pid_a, pid_b = _pid_of(room, ua), _pid_of(room, ub)
    server._finalize_match(room, pid_a, pid_b)

    assert _recv(ca, 'recent_opponent')[0]['relation'] == 'pending_out'
    assert _recv(cb, 'recent_opponent')[0]['relation'] == 'pending_in'


def test_recent_opponent_sent_exactly_once_per_player(party, monkeypatch):
    """★ 每人**只发一次**（重复发会让结算面板弹两遍好友提示）。"""
    room, ca, cb, ua, ub = party()
    monkeypatch.setattr(db, 'get_friend_relation', lambda a, b: 'none', raising=False)

    pid_a, pid_b = _pid_of(room, ua), _pid_of(room, ub)
    server._finalize_match(room, pid_a, pid_b)

    assert len(_recv(ca, 'recent_opponent')) == 1
    assert len(_recv(cb, 'recent_opponent')) == 1

    # 再结算一次（同一条路径被重复调用，比如掉线判胜叠加投降）：每人再多一条 ——
    # 也就是"一次结算 = 一条"，不会因为内部循环/双发而翻倍。
    server._finalize_match(room, pid_a, pid_b)
    assert len(_recv(ca, 'recent_opponent')) == 1, '第二次结算只该再来一条，不许翻倍'
    assert len(_recv(cb, 'recent_opponent')) == 1


def test_ai_room_settlement_sends_no_recent_opponent(monkeypatch, sockets):
    """人机房：结算照常走（写历史），但 `recent_opponent` 一条都不发。"""
    uid = _mk_user()
    client = sockets(uid)
    seat_sid = _sid_of(client)
    room_id = server.room_manager.create_ai_room(seat_sid, '玩家', uid, 'normal')
    room = server.room_manager.get_room(room_id)
    room.players[uid] = server.Player(name='玩家', ships=[], attacks=[],
                                      remaining_ships=0, user_id=uid, sid=seat_sid)
    room.state = 'attacking'
    room.match_started_at = time.time() - 100

    monkeypatch.setattr(db, 'get_friend_relation', lambda a, b: 'friends', raising=False)
    ai_id = 'ai-' + room_id
    server._finalize_match(room, ai_id, uid)          # AI 胜

    assert _recv(client, 'recent_opponent') == [], '人机局不该发 recent_opponent'
    server.room_manager.rooms.pop(room_id, None)


def test_guest_with_seat_sid_gets_no_recent_opponent(party, monkeypatch):
    """★ 自定义房里**游客**的 `Player.user_id` 是入座时的 sid：一条都不许发。

    ⚠️ 这条守的是一个真实缺陷（端到端钉出来的）：判据写成"user_id 非空"的话，
    登录玩家打完之后结算屏上会出现一个**可点的「加好友」**，而对手是游客 ——
    点下去必然 404「账号不存在」。判据必须是"这个 uid 真的查得到账号"。
    """
    room, ca, cb, ua, ub = party()
    monkeypatch.setattr(db, 'get_friend_relation', lambda a, b: 'none', raising=False)
    ids = list(room.players.keys())
    # 真正的产品代码就是这么写的：游客的 user_id = 入座时的 socket sid
    room.players[ids[1]].user_id = 'GuestSeatSid12345'
    room.players[ids[1]].name = '路边游客'

    server._finalize_match(room, ids[0], ids[1])

    assert _recv(ca, 'recent_opponent') == [], '对手是游客时不该推 recent_opponent（按钮点了必然 404）'
    assert _recv(cb, 'recent_opponent') == []


def test_guest_only_match_sends_no_recent_opponent(party, monkeypatch):
    """双方都是游客（`user_id` 为 None）：同样一条都不发。"""
    room, ca, cb, ua, ub = party()
    monkeypatch.setattr(db, 'get_friend_relation', lambda a, b: 'friends', raising=False)
    for player in room.players.values():
        player.user_id = None

    ids = list(room.players.keys())
    server._finalize_match(room, ids[0], ids[1])
    assert _recv(ca, 'recent_opponent') == []
    assert _recv(cb, 'recent_opponent') == []


# ===========================================================================
# 7 · ★ 降级：DAO 缺失 / 抛异常都不许把结算搞崩
# ===========================================================================
def test_finalize_match_survives_raising_relation_dao(party, monkeypatch):
    """★ `db.get_friend_relation` 抛异常 → 结算照常完成，事件照发（relation 降级 none）。"""
    room, ca, cb, ua, ub = party()
    boosted = {'n': 0}

    def boom(a, b):
        boosted['n'] += 1
        raise RuntimeError('db.get_friend_relation 还没落地 / 临时出错')

    monkeypatch.setattr(db, 'get_friend_relation', boom, raising=False)

    pid_a, pid_b = _pid_of(room, ua), _pid_of(room, ub)
    result = server._finalize_match(room, pid_a, pid_b)     # 不许抛

    assert boosted['n'] >= 2, '两个人各问一次关系'
    assert isinstance(result, list), '返回值口径没变（本局新解锁的徽章列表）'

    got_a = _recv(ca, 'recent_opponent')
    got_b = _recv(cb, 'recent_opponent')
    assert len(got_a) == 1 and len(got_b) == 1, '关系取不到也要把事件发出去（降级 none）'
    assert got_a[0]['relation'] == 'none'
    assert got_b[0]['relation'] == 'none'

    # 别的结算收尾没被吞掉：战绩落库了
    history_a = db.get_match_history(ua, limit=5)
    assert history_a, '结算必须照常写战绩（缺一个 DAO 不许影响它）'


def test_finalize_match_survives_missing_relation_dao(party, monkeypatch):
    """DAO 整个不存在（另一个智能体还没落地）→ 一样不崩、照发 `none`。"""
    room, ca, cb, ua, ub = party()
    monkeypatch.delattr(db, 'get_friend_relation', raising=False)

    pid_a, pid_b = _pid_of(room, ua), _pid_of(room, ub)
    server._finalize_match(room, pid_a, pid_b)

    assert [p['relation'] for p in _recv(ca, 'recent_opponent')] == ['none']
    assert [p['relation'] for p in _recv(cb, 'recent_opponent')] == ['none']


def test_relation_safe_helper_degrades_quietly(monkeypatch):
    """`_friend_relation_safe` 的兜底口径：脏值 / 未知取值一律 `none`；self 自己判。"""
    monkeypatch.setattr(db, 'get_friend_relation', lambda a, b: 'weird-unknown', raising=False)
    assert server._friend_relation_safe('a', 'b') == 'none', '未知取值降级成 none'
    assert server._friend_relation_safe('a', 'a') == 'self'
    assert server._friend_relation_safe(None, 'b') == 'none'
    assert server._friend_relation_safe('a', None) == 'none'

    monkeypatch.setattr(db, 'get_friend_relation', lambda a, b: None, raising=False)
    assert server._friend_relation_safe('a', 'b') == 'none'

    monkeypatch.setattr(db, 'get_friend_relation', lambda a, b: 'blocked_by_me', raising=False)
    assert server._friend_relation_safe('a', 'b') == 'blocked_by_me', \
        'db 会返回 blocked_*，不该被压成 none（前端要按"不能加好友"渲染）'


# ===========================================================================
# 3' · "对局中"状态的挂点（进房 / 结算）
# ===========================================================================
def test_in_game_flag_follows_room_lifecycle(party, monkeypatch):
    """配对成功 → 双方"对局中"；结算 → 双方摘掉（`is_in_game` 的消费点）。"""
    room, ca, cb, ua, ub = party()
    assert presence.is_in_game(ua) is True, '匹配成功就该标成对局中'
    assert presence.is_in_game(ub) is True

    monkeypatch.setattr(db, 'get_friend_relation', lambda a, b: 'none', raising=False)
    pid_a, pid_b = _pid_of(room, ua), _pid_of(room, ub)
    server._finalize_match(room, pid_a, pid_b)

    assert presence.is_in_game(ua) is False, '结算后必须摘掉对局中标记'
    assert presence.is_in_game(ub) is False


def test_in_game_flag_on_custom_room_join(monkeypatch):
    """自定义房：建房 / 加入都要标"对局中"（key 就是 uid 的那套约定）。"""
    ua, ub = _mk_user(), _mk_user()

    _as_request(monkeypatch, sid='sid-a', uid=ua, username='甲')
    res = server.handle_create_room({'player_name': '甲'})
    assert res['status'] == 'success'
    room_id = res['room_id']
    assert presence.is_in_game(ua) is True, '房主建房即对局中'
    assert presence.is_in_game(ub) is False

    _as_request(monkeypatch, sid='sid-b', uid=ub, username='乙')
    res = server.handle_join_room({'room_id': room_id, 'player_name': '乙'})
    assert res['status'] == 'success'
    assert presence.is_in_game(ub) is True, '入座者同样要对局中'
    assert presence.is_in_game(ua) is True

    room = server.room_manager.get_room(room_id)
    ids = list(room.players.keys())
    server._finalize_match(room, ids[0], ids[1])
    assert presence.is_in_game(ua) is False, '结算后必须摘掉'
    assert presence.is_in_game(ub) is False
    server.room_manager.rooms.pop(room_id, None)


def test_in_game_flag_on_socket_create_room(sockets):
    """走**真 socket** 建房：connect → `create_room` → 该 uid 立刻是"对局中"。

    （与上面那条直调用例互补：这条验的是"挂在 handler 上的收尾位真的会被执行"，
    那条验的是"房主/入座者两个座位都标上、结算后都摘掉"。）
    """
    uid = _mk_user()
    client = sockets(uid)
    assert presence.is_in_game(uid) is False, '只是连上、还没入座'

    client.emit('create_room', {'player_name': '甲'})
    assert presence.is_in_game(uid) is True, '建房即对局中'

    room_id = None
    for rid, room in server.room_manager.get_all_rooms().items():
        if uid in room.players:
            room_id = rid
    assert room_id, 'create_room 必须建出一个自己已入座的房'
    server.room_manager.rooms.pop(room_id, None)


def test_disconnect_clears_online_and_in_game(monkeypatch):
    """掉线：在线登记注销 + "对局中"摘掉（**纯内存**，disconnect 里不许 emit）。"""
    uid = _mk_user()

    # 先造出"标了在线 + 座位在房里"的状态（直调 handler，不依赖 socket 往返）
    _as_request(monkeypatch, sid='sid-d', uid=uid, username='甲')
    res = server.handle_create_room({'player_name': '甲'})
    room_id = res['room_id']
    presence.mark_online(uid)
    presence.add_sid(uid, 'sid-d')
    assert presence.is_online(uid) is True
    assert presence.is_in_game(uid) is True

    # 掉线（真 handler：它会去排 `_start_disconnect_grace` 后台任务，测试环境下没人
    # 调 `eventlet.sleep` → 那个任务不会真跑 30 秒宽限，用例秒回）
    _as_request(monkeypatch, sid='sid-d', uid=uid, username='甲')
    server.handle_disconnect()

    assert presence.is_online(uid) is False
    assert presence.sids_of(uid) == []
    assert presence.is_in_game(uid) is False
    server.room_manager.rooms.pop(room_id, None)
