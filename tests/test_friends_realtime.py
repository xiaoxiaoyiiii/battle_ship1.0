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






# ===========================================================================
# 3 · connect / disconnect 的在线登记
# ===========================================================================




# ===========================================================================
# 4 / 5 · push_* 的发送端
# ===========================================================================












# ===========================================================================
# 6 · 结算钩子：recent_opponent
# ===========================================================================








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




# ===========================================================================
# 7 · ★ 降级：DAO 缺失 / 抛异常都不许把结算搞崩
# ===========================================================================






# ===========================================================================
# 3' · "对局中"状态的挂点（进房 / 结算）
# ===========================================================================
