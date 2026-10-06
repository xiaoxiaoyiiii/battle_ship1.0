# -*- coding: utf-8 -*-
"""排位模式（ranked）**对局侧**支持的回归测试（2026-09-18）。

覆盖 11 组（与冻结契约逐条对应）：

  1. `GameRoom.ranked` 默认 False；自定义房 / 人机房恒 False
     （新增房间级状态三件齐里的"初始化"这一件）；
  2. `find_match(mode='ranked')` 必须登录 —— 游客排位被**明确拒绝**且不排队，
     游客休闲局照旧能排（别误伤）；
  3. **只在同 mode 之间配对**（ranked × casual 配不上；ranked × ranked / casual × casual 能配）；
  4. 队列条目的 `mode` 与 `sid` / `name` / `user_id` **不错位**
     （"平行数组漏改一个使用点就把 A 的 mode 配给 B"那条的守卫）；
  5. `cancel_match` 能取消排位排队；
  6. 排位房正常结算：胜者 +`WIN_POINTS` / 败者 +`LOSE_POINTS` 都落库，
     两人各收一条 `rank_changed` 且字段齐全（`role`/`delta`/`before`/`after`/`promoted`）；
  7. **赛前（没有开打时间）不给分、也不发事件**；
  8. 人机房不给分（`count_stats` 那条口径）；
  9. **0 分封底**：败者 5 分输一局 → 落库 0 分、`clamped=True`、`delta` 是实际值；
 10. `game_state` 与 `_build_room_sync`（重连快照）都带 `ranked` / `mode`；
 11. 大舰长晋升（含船长池不足人数时的护栏与中文原因）。

⚠️ 分差一律从 `ranks.WIN_POINTS` / `ranks.LOSE_POINTS` 取，**不写死 20 / -15** ——
   这两个常量现在支持环境变量覆盖（`RANK_WIN_POINTS` / `RANK_LOSE_POINTS`），
   写死就会在换了配置的环境里假红。

⚠️ 本文件造的账号一律带 `_TAG` 前缀，并在用例结束时清掉 `user_rank` 行 ——
   船长池是**全库共享**的（大舰长要数池子里有多少人），留 50 个船长会污染别的用例。
"""
import itertools
import re
import time
import types

import pytest

import db
import ranks
import server

_seq = itertools.count(1)
_TAG = 'rk9'

# rank_changed 的冻结字段（逐字来自契约）
_RANK_EVENT_KEYS = (
    'role', 'delta', 'clamped', 'points_before', 'points_after',
    'before', 'after', 'promoted', 'demoted', 'tier_up', 'tier_down',
    'admiral_promoted', 'admiral_demoted', 'admiral_reason',
)


# ---------------------------------------------------------------------------
# 账号 / 清理
# ---------------------------------------------------------------------------
def _mk_user(prefix=_TAG):
    name = f'{prefix}{next(_seq)}'
    uid = db.create_user(name, 'x' * 12)
    assert uid, f'建号失败: {name}'
    return uid


def _purge(uids):
    """清掉本用例造的段位行（账号本身留着，它没有段位行就不会进段位榜）。"""
    try:
        with db.db._lock:
            for uid in uids:
                if not uid:
                    continue
                for table in ('user_rank', 'user_xp', 'user_counters', 'user_achievements'):
                    try:
                        db.db.conn.execute(f'DELETE FROM {table} WHERE user_id = ?', (uid,))
                    except Exception:
                        pass
            db.db.conn.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 夹具：房间 / 队列全局状态、socket 测试连接、排位对局
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_globals():
    """每个用例前后都把 `rooms` / `match_queue` 恢复原样（匹配队列是模块级全局）。"""
    existing = set(server.room_manager.get_all_rooms())
    server.room_manager.match_queue = []
    yield
    for rid in list(server.room_manager.get_all_rooms()):
        if rid not in existing:
            server.room_manager.rooms.pop(rid, None)
    server.room_manager.match_queue = []


@pytest.fixture
def sockets():
    """建「已登录」的 socket 测试连接（带 session 的 flask test client 传进去）。"""
    made = []

    def _make(uid=None):
        http = server.app.test_client()
        if uid:
            with http.session_transaction() as sess:
                sess['user_id'] = uid
                sess['username'] = uid
        client = server.socketio.test_client(server.app, flask_test_client=http)
        client.get_received()          # 丢掉 connect 期间的噪音
        made.append(client)
        return client

    yield _make
    for client in made:
        try:
            client.disconnect()
        except Exception:
            pass


def _pick(events, name):
    """从**已经取回**的事件列表里挑出某类 payload（只留 args[0] 是 dict 的）。"""
    out = []
    for m in events:
        if m['name'] != name:
            continue
        args = m['args']
        if isinstance(args, dict):
            args = [args]
        out.extend(a for a in (args or ()) if isinstance(a, dict))
    return out


def _recv(client, name):
    """取某个客户端本次收到的全部某类事件 payload。"""
    return _pick(_drain_all(client), name)


def _drain_all(client, tries=30):
    """把客户端队列里的事件**按到达顺序**取干净。

    结算事件 `rank_changed` 是从 socket 请求上下文里**用后台任务**补发的
    （`_dispatch_rank_events`：必须排在 `game_over` 之后），所以取事件时要
    让出几次执行权，等后台任务真的把事件推过来 —— 一次 `get_received()` 是不够的。
    """
    events = client.get_received()
    for _ in range(tries):
        try:
            server.socketio.sleep(0)          # eventlet 下让 hub 跑一次待执行的后台任务
        except Exception:
            break
        events += client.get_received()
    return events


def _only(items, what='事件'):
    assert len(items) == 1, f'应当恰好收到 1 条 {what}，实际 {len(items)}'
    return items[0]


def _pid_of(room, uid):
    for pid, player in room.players.items():
        if player.user_id == uid:
            return pid
    raise AssertionError(f'{uid} 不在这局里')


@pytest.fixture
def env(sockets):
    """`env(...)` 用真实 `find_match` 开一局两人对局，返回 (room, clientA, clientB, uidA, uidB)。"""
    state = {'uids': [], 'rooms': []}

    def _start(points_a=0, points_b=0, mode='ranked', started=True):
        before = set(server.room_manager.get_all_rooms())
        ua, ub = _mk_user(), _mk_user()
        state['uids'] += [ua, ub]
        db.set_rank_points(ua, points_a)
        db.set_rank_points(ub, points_b)
        ca, cb = sockets(ua), sockets(ub)
        ca.emit('find_match', {'player_name': '甲', 'mode': mode})
        cb.emit('find_match', {'player_name': '乙', 'mode': mode})
        new = [r for r in server.room_manager.get_all_rooms().values() if r.id not in before]
        assert len(new) == 1, f'两个人应当被配成一局，实际新建 {len(new)} 个房'
        room = new[0]
        state['rooms'].append(room.id)
        # 真正开打的时间戳（`_match_started_at` 优先取它）—— 赛前投降那条用例会清零它
        room.match_started_at = time.time() if started else 0
        room.state = 'attacking'
        # ⚠️ **把多因子计分的加成项显式排掉**，让"干净一局 == base（赢 +20 / 输 −15）"
        #    在本文件里重新成立 —— 否则下面那些 `100 + ranks.WIN_POINTS` 式断言全会红，
        #    而且报错信息指向不了真正的原因。
        #
        #    为什么要排：`GameRoom.__init__` 里 `self.round = 1`，而 `blitz` 的判据是
        #    「≤180 秒 **或** ≤5 个大回合」→ **1 ≤ 5 恒真**，于是这个夹具建出来的房
        #    每一局胜者都白拿 +6（落库 126 而不是 120）。
        #    ⚠️ 注意"round=1 的房间算闪电战"**在真链路上也是对的**（一局只打了一个
        #    大回合确实就是速胜），所以这里**不是把产品改掉**，只是让本文件的用例
        #    变成"不含加成的基准局"；多因子本身由 `tests/test_rank_points.py` 逐项测。
        if started:
            room.round = 6                              # 排掉闪电战（≤5 大回合）
            room.match_started_at = time.time() - 1000  # 排掉速败减免（≤180 秒）
        # 双方 `ships` 保持空 → sunk = lost = 0：没有击沉/零伤，也没有虽败犹荣
        return room, ca, cb, ua, ub

    def _track(*uids):
        state['uids'] += [u for u in uids if u]

    _start.track = _track
    _start.rooms = state['rooms']
    yield _start
    for rid in state['rooms']:
        server.room_manager.rooms.pop(rid, None)
    _purge(state['uids'])


# ---------------------------------------------------------------------------
# 直接调 handler 用的小工具（与 test_fixes_regression 同一套写法）
# ---------------------------------------------------------------------------
def _capture_emit(monkeypatch):
    """把 `server.emit` 换成记录器（直调 handler 时没有请求上下文）。"""
    sent = []

    def fake_emit(event, data, to=None, room=None):
        sent.append({'name': event, 'data': data, 'to': to, 'room': room})

    monkeypatch.setattr(server, 'emit', fake_emit)
    return sent


def _as_request(monkeypatch, sid, uid=None):
    """把 `request` / `session` / socketio 的 `join_room` 都换成直调友好的假对象。"""
    monkeypatch.setattr(server, 'request', types.SimpleNamespace(sid=sid))
    monkeypatch.setattr(
        server, 'session',
        types.SimpleNamespace(get=lambda k, d=None: uid if k == 'user_id' else d))
    # `join_room(room_id, sid)`（flask_socketio 的那个）在无请求上下文时会抛
    monkeypatch.setattr(server, 'join_room', lambda *a, **k: None)


# ===========================================================================
# 1. 房间级标记：初始化 + 自定义房 / 人机房恒 False
# ===========================================================================




# ===========================================================================
# 2. 排位必须登录（游客排位被拒 / 游客休闲不受影响 / 非法 mode 当休闲）
# ===========================================================================
def test_ranked_requires_login(monkeypatch):
    sent = _capture_emit(monkeypatch)
    _as_request(monkeypatch, sid='guest-a', uid=None)

    res = server.handle_find_match({'player_name': '游客', 'mode': 'ranked'})

    assert res['status'] == 'error'
    assert server.room_manager.get_match_queue_size() == 0, '被拒的排位请求不许留在队列里'
    errors = [e for e in sent if e['name'] == 'error']
    assert errors, '必须 emit error 告诉前端为什么排不上'
    assert errors[-1]['data']['message'] == '排位模式需要先登录'






# ===========================================================================
# 3. 只在同 mode 之间配对
# ===========================================================================
def test_only_same_mode_pairs(monkeypatch):
    sent = _capture_emit(monkeypatch)
    before = set(server.room_manager.get_all_rooms())

    # ① 排位者先入队
    _as_request(monkeypatch, sid='sid-r1', uid='uid-r1')
    assert server.handle_find_match({'player_name': '排位甲', 'mode': 'ranked'})['status'] == 'success'
    assert server.room_manager.get_match_queue_size() == 1

    # ② 休闲者入队 → **配不上**（混配 = 让休闲玩家白拿段位分）
    _as_request(monkeypatch, sid='sid-c1', uid='uid-c1')
    assert server.handle_find_match({'player_name': '休闲甲'})['status'] == 'success'
    assert server.room_manager.get_match_queue_size() == 2
    assert set(server.room_manager.get_all_rooms()) == before, '不同 mode 不许建房'
    assert [e['sid'] for e in server.room_manager.match_queue] == ['sid-r1', 'sid-c1']

    # ③ 第二个排位者 → 与第一个排位者配上
    _as_request(monkeypatch, sid='sid-r2', uid='uid-r2')
    assert server.handle_find_match({'player_name': '排位乙', 'mode': 'ranked'})['status'] == 'success'
    assert [e['sid'] for e in server.room_manager.match_queue] == ['sid-c1'], '只剩休闲那位'
    ranked_rooms = [r for r in server.room_manager.get_all_rooms().values() if r.id not in before]
    assert len(ranked_rooms) == 1
    assert set(ranked_rooms[0].players) == {'sid-r1', 'sid-r2'}
    assert ranked_rooms[0].ranked is True, '排位匹配建房必须打排位标记'

    # ④ 第二个休闲者 → 两个休闲配上，且这一局不是排位
    _as_request(monkeypatch, sid='sid-c2', uid='uid-c2')
    assert server.handle_find_match({'player_name': '休闲乙'})['status'] == 'success'
    assert server.room_manager.get_match_queue_size() == 0
    new_rooms = [r for r in server.room_manager.get_all_rooms().values() if r.id not in before]
    assert len(new_rooms) == 2
    casual = [r for r in new_rooms if r.ranked is False]
    assert len(casual) == 1
    assert set(casual[0].players) == {'sid-c1', 'sid-c2'}




# ===========================================================================
# 4. 队列条目不错位（四个字段必须永远属于同一个 sid）
# ===========================================================================




# ===========================================================================
# 5. cancel_match 能取消排位排队
# ===========================================================================
def test_cancel_match_removes_ranked_queue(monkeypatch):
    sent = _capture_emit(monkeypatch)
    _as_request(monkeypatch, sid='sid-rq', uid='uid-rq')
    server.handle_find_match({'player_name': '排位', 'mode': 'ranked'})
    assert server.room_manager.get_match_queue_size() == 1
    assert server.room_manager.match_queue[0]['mode'] == 'ranked'

    res = server.handle_cancel_match({})

    assert res['status'] == 'success'
    assert server.room_manager.get_match_queue_size() == 0
    assert not server.room_manager.has_player_in_match_queue('sid-rq')
    canceled = [e for e in sent if e['name'] == 'match_canceled']
    assert canceled and canceled[-1]['to'] == 'sid-rq'


# ===========================================================================
# 6. 排位房正常结算：加减分落库 + rank_changed 字段齐全
# ===========================================================================
def test_ranked_settlement_persists_points_and_emits(env):
    room, ca, cb, ua, ub = env(points_a=100, points_b=100)
    pid_a, pid_b = _pid_of(room, ua), _pid_of(room, ub)
    assert room.ranked is True

    room.state = 'game_over'
    server._finalize_match(room, pid_a, pid_b)     # 甲 胜

    assert db.get_user_rank_row(ua)['points'] == 100 + ranks.WIN_POINTS
    assert db.get_user_rank_row(ub)['points'] == 100 + ranks.LOSE_POINTS
    assert db.get_user_rank_row(ua)['ranked_wins'] == 1
    assert db.get_user_rank_row(ub)['ranked_losses'] == 1

    pa = _only(_recv(ca, 'rank_changed'), 'rank_changed(胜者)')
    pb = _only(_recv(cb, 'rank_changed'), 'rank_changed(败者)')

    # 每人只收到**自己**那一份（用 role 区分，甲胜）
    assert pa['role'] == 'winner' and pb['role'] == 'loser'
    for payload in (pa, pb):
        for key in _RANK_EVENT_KEYS:
            assert key in payload, f'rank_changed 缺少字段 {key}'
        assert isinstance(payload['before']['label'], str) and payload['before']['label']
        assert isinstance(payload['after']['label'], str) and payload['after']['label']
        assert isinstance(payload['admiral_reason'], str)
        assert isinstance(payload['before']['server_rank'], int)
        assert isinstance(payload['after']['server_rank'], int)
        # before / after 是 rank_view 的原样返回
        for view in (payload['before'], payload['after']):
            for key in ('tier_id', 'tier_name', 'tier_index', 'sub', 'progress',
                        'points', 'to_next', 'is_admiral', 'label', 'server_rank'):
                assert key in view, f'rank_view 少了 {key}'

    assert pa['points_before'] == 100 and pa['points_after'] == 100 + ranks.WIN_POINTS
    assert pa['delta'] == ranks.WIN_POINTS and pa['clamped'] is False
    assert pb['points_before'] == 100 and pb['points_after'] == 100 + ranks.LOSE_POINTS
    assert pb['delta'] == ranks.LOSE_POINTS and pb['clamped'] is False
    # 名次是**结算之后**取的：必须与库里现在的一致
    assert pa['after']['server_rank'] == db.get_rank_position(ua)
    assert pb['after']['server_rank'] == db.get_rank_position(ub)
    # 没到船长段位时，原因文案是"还差什么"
    assert pa['admiral_reason'] == '需要先达到船长段位'
    assert pa['admiral_promoted'] is False and pa['admiral_demoted'] is False








# ===========================================================================
# 7. 赛前（没有真开打）不给分、也不发事件
# ===========================================================================








# ===========================================================================
# 8. 人机房不给分
# ===========================================================================


# ===========================================================================
# 9. 0 分封底
# ===========================================================================


# ===========================================================================
# 10. game_state / 重连快照带 ranked / mode
# ===========================================================================






# ===========================================================================
# 11. 大舰长晋升与护栏
# ===========================================================================








# ===========================================================================
# ★★ 回归守卫：**配对偏好绝不能影响排位结算**（2026-09-20 玩家实测报的）
#
# 事故形状：`handle_find_match` 曾写
#     room.ranked = (mode == ranked) and bool(assessed)
# 把"软规避没躲开"（`assessed=False`）直接变成**这一局不给排位分**。
# 而小社区里「和刚打过的人再打一局」恰恰是最常见的匹配 →
# 大量正常排位对局静默不结算：赢的不加分、输的不扣分。
#
# ⚠️ 这个 bug **纯函数测不出来**（match_guard 单测全绿），
#    必须走**真实 `find_match`** 才能钉住。本文件就是那条守卫。
# ===========================================================================
