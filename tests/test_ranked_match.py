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
def test_game_room_ranked_defaults_false():
    """★ 新增房间级状态三件齐之一：`__init__` 必须初始化 `ranked`。"""
    room = server.GameRoom('rank-default')
    assert room.ranked is False


def test_custom_room_and_ai_room_are_not_ranked():
    """自定义房（create_room / join_room）与人机房一律 `ranked = False`（可以互刷分）。"""
    qm = server.room_manager

    rid = qm.create_room()
    room = qm.get_room(rid)
    assert room.ranked is False
    assert qm.join_room(rid, 'pid-x', '玩家X', 'sid-x') is True
    assert room.ranked is False, '自定义房不许被置成排位'

    ai_rid = qm.create_ai_room('sid-ai', '玩家甲', None)
    ai_room = qm.get_room(ai_rid)
    assert ai_room.is_ai_room is True
    assert ai_room.ranked is False, '人机房不许被置成排位'


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


def test_casual_guest_still_queues(monkeypatch):
    """游客休闲局不许被排位门禁误伤（默认 mode 就是 casual）。"""
    sent = _capture_emit(monkeypatch)
    _as_request(monkeypatch, sid='guest-b', uid=None)

    res = server.handle_find_match({'player_name': '游客'})

    assert res['status'] == 'success'
    assert server.room_manager.get_match_queue_size() == 1
    assert server.room_manager.match_queue[0]['mode'] == 'casual'
    assert not [e for e in sent if e['name'] == 'error']
    assert [e for e in sent if e['name'] == 'match_queued'], '入队要回 match_queued'


@pytest.mark.parametrize('bad', [None, '', 'RANKED', 'rank', 'casual', '1', 123])
def test_illegal_mode_falls_back_to_casual(monkeypatch, bad):
    """非法 mode 一律当休闲（只认逐字的 'ranked'）。"""
    sent = _capture_emit(monkeypatch)
    _as_request(monkeypatch, sid=f'guest-{bad}', uid=None)

    res = server.handle_find_match({'player_name': '游客', 'mode': bad})

    assert res['status'] == 'success'
    assert server.room_manager.match_queue[0]['mode'] == 'casual'
    assert not [e for e in sent if e['name'] == 'error']


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


def test_queue_head_blocked_by_other_mode_does_not_hold_back_same_mode_pair(monkeypatch):
    """队首是休闲、后面是两个排位时，那两个排位者仍然要能配上。

    （旧写法"拿队首找搭档、找不到就 break"在这里会让排位者一直干等，
      直到第三个休闲玩家入队 —— 是 mode 扩字段后新引入的坑。）
    """
    sent = _capture_emit(monkeypatch)
    _as_request(monkeypatch, sid='q-casual', uid='uid-qc')
    server.handle_find_match({'player_name': '休闲', 'mode': 'casual'})
    _as_request(monkeypatch, sid='q-r1', uid='uid-qr1')
    server.handle_find_match({'player_name': '排位甲', 'mode': 'ranked'})
    before = set(server.room_manager.get_all_rooms())
    _as_request(monkeypatch, sid='q-r2', uid='uid-qr2')
    server.handle_find_match({'player_name': '排位乙', 'mode': 'ranked'})

    new = [r for r in server.room_manager.get_all_rooms().values() if r.id not in before]
    assert len(new) == 1, '两个排位者必须配上（不许被队首的休闲者挡住）'
    assert set(new[0].players) == {'q-r1', 'q-r2'}
    assert new[0].ranked is True
    assert [e['sid'] for e in server.room_manager.match_queue] == ['q-casual']


# ===========================================================================
# 4. 队列条目不错位（四个字段必须永远属于同一个 sid）
# ===========================================================================
def test_queue_entries_keep_their_own_mode(monkeypatch):
    sent = _capture_emit(monkeypatch)
    qm = server.room_manager
    spec = [
        ('s-a', 'A', 'u-a', 'casual'),
        ('s-b', 'B', 'u-b', 'ranked'),
        ('s-c', 'C', 'u-c', 'ranked'),
        ('s-d', 'D', 'u-d', 'casual'),
    ]

    for sid, name, uid, mode in spec:
        assert qm.add_to_match_queue(sid, name, uid, mode) is True

    # 入队后每个条目四个字段都要对得上（错位在这里就会露出来）
    assert [(e['sid'], e['name'], e['user_id'], e['mode']) for e in qm.match_queue] == spec

    # 再让一个排位者入队触发配对
    before = set(qm.get_all_rooms())
    _as_request(monkeypatch, sid='s-e', uid='u-e')
    server.handle_find_match({'player_name': 'E', 'mode': 'ranked'})

    rooms = [r for r in qm.get_all_rooms().values() if r.id not in before]
    assert len(rooms) == 2, '应当配出「两个休闲」+「两个排位」两局'
    by_players = {frozenset(r.players): r for r in rooms}
    casual_room = by_players[frozenset({'s-a', 's-d'})]
    ranked_room = by_players[frozenset({'s-b', 's-c'})]
    assert casual_room.ranked is False and ranked_room.ranked is True

    # name / user_id 必须还是各自入队时那一份（错位破坏的正是它们）
    for sid, name, uid, mode in spec:
        room = casual_room if sid in ('s-a', 's-d') else ranked_room
        assert room.players[sid].name == name, f'{sid} 的名字错位了'
        assert room.players[sid].user_id == uid, f'{sid} 的 user_id 错位了'

    # 落单的排位者仍在队列里，mode 也不能丢
    assert [(e['sid'], e['mode']) for e in qm.match_queue] == [('s-e', 'ranked')]


def test_find_match_queued_ack_carries_mode(monkeypatch):
    sent = _capture_emit(monkeypatch)
    _as_request(monkeypatch, sid='sid-ack', uid='uid-ack')
    server.handle_find_match({'player_name': '排位', 'mode': 'ranked'})
    queued = [e for e in sent if e['name'] == 'match_queued']
    assert queued and queued[-1]['data'].get('mode') == 'ranked'


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


def test_ranked_settlement_promotes_across_sub_tier(env):
    """跨小级进位：水手长Ⅱ 90 分 +20 → 水手长Ⅲ 10 分（`promoted` 必须为真）。"""
    room, ca, cb, ua, ub = env(points_a=790, points_b=100)
    server._finalize_match(room, _pid_of(room, ua), _pid_of(room, ub))

    pa = _only(_recv(ca, 'rank_changed'), 'rank_changed(胜者)')
    assert pa['points_before'] == 790 and pa['points_after'] == 790 + ranks.WIN_POINTS
    assert pa['promoted'] is True and pa['demoted'] is False
    assert pa['tier_up'] is False, '同一大段位内进位不算 tier_up'
    assert pa['after']['label'].startswith('水手长Ⅲ')
    assert db.get_user_rank_row(ua)['points'] == 790 + ranks.WIN_POINTS


def test_ranked_settlement_skips_guest_player(env):
    """房里可能有游客（`Player.user_id` 为空）→ 跳过，绝不写库。"""
    room, ca, cb, ua, ub = env(points_a=100, points_b=100)
    pid_a, pid_b = _pid_of(room, ua), _pid_of(room, ub)
    room.players[pid_b].user_id = None      # 对手变成游客

    server._finalize_match(room, pid_a, pid_b)

    assert db.get_user_rank_row(ua)['points'] == 100 + ranks.WIN_POINTS
    assert db.get_user_rank_row(ub)['points'] == 100, '游客那一份不许被写'
    assert len(_recv(ca, 'rank_changed')) == 1
    assert _recv(cb, 'rank_changed') == [], '游客不该收到段位事件'


def test_rank_settlement_has_a_single_call_site():
    """段位加减分也必须走结算收口（与战绩/统计/徽章/经验同一条规矩）。"""
    src = open('server.py', encoding='utf-8').read()
    assert src.count('def _settle_ranked_match(') == 1
    calls = re.findall(r'(?<!def )_settle_ranked_match\(room,', src)
    assert len(calls) == 1, f'只允许在 _finalize_match 里调用一次，实际 {len(calls)}'


# ===========================================================================
# 7. 赛前（没有真开打）不给分、也不发事件
# ===========================================================================
def test_match_really_started_ignores_created_at():
    """★ 反向守卫：门禁必须看**显式开打打点**，不能用 `_match_started_at`。

    同一个房间（只设了 `created_at`）：
      · `_match_really_started(room)` → False；
      · `_match_started_at(room)` → **非 0** —— 因为它会退回 `created_at`，而
        `created_at` 是 `GameRoom.__init__` 无条件打的点，**真机上永远非 0**。
        所以拿 `_match_started_at(room) != 0` 当"开没开打"的判据等于没拦。
    设上 `match_started_at`（猜拳结束、真正进 attacking 时打的点）之后两者都为真。
    """
    room = server.GameRoom('rank-start-guard')
    room.ranked = True
    room.created_at = time.time()
    room.__dict__.pop('match_started_at', None)

    assert server._match_really_started(room) is False
    assert server._match_started_at(room) != 0, \
        '这正是老判据在真机上恒真、门禁形同虚设的原因'
    assert server._ranked_settlement_allowed(room, True) is False

    room.match_started_at = time.time()
    assert server._match_really_started(room) is True
    assert server._ranked_settlement_allowed(room, True) is True


def test_pre_match_surrender_gives_no_points(env):
    """★ 赛前投降不给分：匹配成功但**还没猜完拳**时投降 → 两人分数都不变、不发 rank_changed。

    走**真实投降路径**（`handle_surrender`，不是直调 `_finalize_match`）。
    ⚠️ `created_at` 显式设成真时间 —— 真实房间一定有它，这也正是
       `_match_started_at(room)` 恒非 0、只有"显式打点"这一条判据拦得住的地方。
    """
    room, ca, cb, ua, ub = env(points_a=100, points_b=100, started=False)
    room.created_at = time.time()
    room.__dict__.pop('match_started_at', None)
    room.state = 'placing_ships'           # 还没猜拳
    assert server._match_really_started(room) is False
    assert server._match_started_at(room) != 0
    ca.get_received(); cb.get_received()

    surrendering = _pid_of(room, ua)
    ca.emit('surrender', {'room_id': room.id, 'player_id': surrendering})

    assert room.state == 'game_over'
    assert db.get_user_rank_row(ua)['points'] == 100, '赛前投降不许给分'
    assert db.get_user_rank_row(ub)['points'] == 100
    assert _recv(ca, 'rank_changed') == []
    assert _recv(cb, 'rank_changed') == []


def test_surrender_after_match_started_settles(env):
    """★ 真开打之后投降**照常结算**（否则"打不过就投降"会变成免责），且事件在 game_over 之后。"""
    room, ca, cb, ua, ub = env(points_a=100, points_b=100)     # env 已打上开打时间戳
    assert server._match_really_started(room) is True
    room.state = 'attacking'
    ca.get_received(); cb.get_received()

    surrendering = _pid_of(room, ua)
    ca.emit('surrender', {'room_id': room.id, 'player_id': surrendering})

    assert db.get_user_rank_row(ua)['points'] == 100 + ranks.LOSE_POINTS
    assert db.get_user_rank_row(ub)['points'] == 100 + ranks.WIN_POINTS
    evs_a = _drain_all(ca)                 # 一次取干净，既验 payload 也验先后顺序
    evs_b = _drain_all(cb)
    lost = _only(_pick(evs_a, 'rank_changed'), 'rank_changed(投降方)')
    won = _only(_pick(evs_b, 'rank_changed'), 'rank_changed(胜者)')
    assert lost['role'] == 'loser' and won['role'] == 'winner'

    # 顺序：game_over 必须先于 rank_changed（前端要等结算面板之后才弹段位面板）。
    # 这条只能在这里验：`rank_changed` 是**从 socket 请求上下文里用后台任务补发**的。
    order = [m['name'] for m in evs_b]
    assert 'game_over' in order and 'rank_changed' in order, f'事件不齐: {order}'
    assert order.index('game_over') < order.index('rank_changed'), \
        f'rank_changed 必须排在 game_over 之后，实际顺序 {order}'


def test_no_points_when_finalize_without_start_marker(env):
    """直调 `_finalize_match` 的版本：没有开打打点时一律不给分、不发事件。"""
    room, ca, cb, ua, ub = env(points_a=100, points_b=100, started=False)
    room.created_at = time.time()
    room.__dict__.pop('match_started_at', None)
    room.ranked = True
    assert server._ranked_settlement_allowed(room, True) is False

    room.state = 'game_over'
    server._finalize_match(room, _pid_of(room, ua), _pid_of(room, ub))

    assert db.get_user_rank_row(ua)['points'] == 100, '没真开打就不许产分'
    assert db.get_user_rank_row(ub)['points'] == 100
    assert _recv(ca, 'rank_changed') == [] and _recv(cb, 'rank_changed') == []


# ===========================================================================
# 8. 人机房不给分
# ===========================================================================
def test_ai_room_gives_no_rank_points(env, sockets):
    uid = _mk_user()
    env.track(uid)
    db.set_rank_points(uid, 120)

    room_id = server.room_manager.create_ai_room('sid-human', '玩家甲', uid)
    room = server.room_manager.get_room(room_id)
    env.rooms.append(room_id)
    room.match_started_at = time.time()
    ca = sockets(uid)
    human_sid = server.socketio.server.manager.sid_from_eio_sid(ca.eio_sid, '/')
    room.players[human_sid] = server.Player(name='玩家甲', ships=[], attacks=[],
                                            remaining_ships=6, user_id=uid, sid=human_sid)
    ca.get_received()
    ai_id = server._ai_player_id(room)

    assert room.ranked is False
    assert server._count_stats_for(room) is False
    assert server._ranked_settlement_allowed(room, server._count_stats_for(room)) is False

    room.state = 'game_over'
    server._finalize_match(room, human_sid, ai_id)     # 真人打赢电脑

    assert db.get_user_rank_row(uid)['points'] == 120, '打电脑不许刷段位'
    assert _recv(ca, 'rank_changed') == []


# ===========================================================================
# 9. 0 分封底
# ===========================================================================
def test_zero_point_floor_clamps_loser(env):
    lose = ranks.LOSE_POINTS
    assert lose < 0, '这个用例的前提是"输一局会扣分"'
    start = max(1, abs(lose) - 10)          # 保证 start + lose < 0（会撞到 0 分封底）
    assert start + lose < 0

    room, ca, cb, ua, ub = env(points_a=100, points_b=start)
    server._finalize_match(room, _pid_of(room, ua), _pid_of(room, ub))

    assert db.get_user_rank_row(ub)['points'] == 0, '0 分封底：不许出现负分'
    pb = _only(_recv(cb, 'rank_changed'), 'rank_changed(败者)')
    assert pb['points_before'] == start and pb['points_after'] == 0
    assert pb['clamped'] is True
    assert pb['delta'] == -start, 'delta 必须是**实际**变化量（不是请求的 -15）'
    assert pb['delta'] > lose, '被夹住时实际扣得比请求的少'


# ===========================================================================
# 10. game_state / 重连快照带 ranked / mode
# ===========================================================================
def test_game_state_and_room_sync_carry_ranked(env):
    room, ca, cb, ua, ub = env(mode='ranked')
    gs = _recv(ca, 'game_state')
    assert gs, '匹配成功必须下发 game_state'
    assert gs[-1]['ranked'] is True and gs[-1]['mode'] == 'ranked'
    snap = server._build_room_sync(room, _pid_of(room, ua))
    assert snap['ranked'] is True, '重连快照不带 ranked，重连后前端会以为是休闲局'
    assert snap['mode'] == 'ranked'


def test_game_state_and_room_sync_carry_casual(env):
    room, ca, cb, ua, ub = env(mode='casual')
    gs = _recv(ca, 'game_state')
    assert gs[-1]['ranked'] is False and gs[-1]['mode'] == 'casual'
    snap = server._build_room_sync(room, _pid_of(room, ua))
    assert snap['ranked'] is False and snap['mode'] == 'casual'


def test_room_sync_without_created_at_does_not_crash():
    """老房间 / 手工构造的房没有 `created_at` 也不能 AttributeError（新字段一律 getattr）。"""
    room = server.GameRoom('rank-sync')
    room.players['p1'] = server.Player(name='甲', ships=[], attacks=[],
                                       remaining_ships=6, user_id='u1', sid='s1')
    if hasattr(room, 'created_at'):
        del room.created_at
    if hasattr(room, 'ranked'):
        del room.ranked
    snap = server._build_room_sync(room, 'p1')
    assert snap['ranked'] is False and snap['mode'] == 'casual'


# ===========================================================================
# 11. 大舰长晋升与护栏
# ===========================================================================
def test_admiral_promotion_when_captain_pool_is_full(env):
    """★ 船长段 + 池内前 50 + 池子 ≥ 50 人 → 升大舰长，且 `is_admiral` 落库为 1。"""
    min_captains = ranks.ADMIRAL_MIN_CAPTAINS
    assert min_captains <= 200, f'护栏 {min_captains} 太大，这个用例不方便造数据'
    assert ranks.WIN_POINTS >= 3, '这条用例要求"赢一局恰好跨进船长段"，分差太小时不成立'
    pool_uids = [_mk_user() for _ in range(min_captains)]
    env.track(*pool_uids)
    # 池里的人全都在目标分数之下（这样目标晋升后池内名次靠前）
    target_after = ranks.CAPTAIN_FLOOR - 1 + ranks.WIN_POINTS
    span = max(1, ranks.WIN_POINTS - 2)
    for i, uid in enumerate(pool_uids):
        db.set_rank_points(uid, ranks.CAPTAIN_FLOOR + 1 + (i % span))
    assert db.count_rank_at_least(ranks.CAPTAIN_FLOOR) >= min_captains
    assert ranks.CAPTAIN_FLOOR + span < target_after, '造数据的前提：池里的人分数更低'
    # 别的用例可能也在共享库里留下过船长段账号；只要高过目标的不满 50 个就还能构造出
    # "池内前 50"（满了就没法构造，明确跳过而不是假红）。
    above = sum(1 for it in db.captains_ordered(limit=500) if it['points'] > target_after)
    if above >= ranks.ADMIRAL_RANK_LIMIT:
        pytest.skip(f'库里已有 {above} 个比目标分高的船长账号，无法构造"池内前 50"')

    room, ca, cb, ua, ub = env(points_a=ranks.CAPTAIN_FLOOR - 1, points_b=100)
    server._finalize_match(room, _pid_of(room, ua), _pid_of(room, ub))

    row = db.get_user_rank_row(ua)
    assert row['points'] == target_after, '这一局要正好把人推进船长段'
    assert row['is_admiral'] == 1, '晋升必须落库（is_admiral=1）'
    pa = _only(_recv(ca, 'rank_changed'), 'rank_changed(胜者)')
    assert pa['admiral_promoted'] is True
    assert pa['admiral_demoted'] is False
    assert pa['after']['is_admiral'] is True
    assert pa['after']['label'].startswith('大舰长')
    assert pa['after']['captain_pool_rank'] is not None
    assert pa['after']['captain_pool_rank'] <= ranks.ADMIRAL_RANK_LIMIT
    assert db.get_user_rank_row(ub)['is_admiral'] == 0


def test_admiral_not_promoted_when_pool_too_small(env, monkeypatch):
    """★ 护栏：船长池不足 `ADMIRAL_MIN_CAPTAINS` 人时不晋升，且给中文原因。"""
    pool_now = db.count_rank_at_least(ranks.CAPTAIN_FLOOR)
    monkeypatch.setattr(ranks, 'ADMIRAL_MIN_CAPTAINS', pool_now + 100)   # 池子恒不足

    room, ca, cb, ua, ub = env(points_a=ranks.CAPTAIN_FLOOR, points_b=100)
    server._finalize_match(room, _pid_of(room, ua), _pid_of(room, ub))

    row = db.get_user_rank_row(ua)
    assert row['points'] == ranks.CAPTAIN_FLOOR + ranks.WIN_POINTS, '分照加'
    assert row['is_admiral'] == 0, '池子不够人数时不许产生大舰长'
    pa = _only(_recv(ca, 'rank_changed'), 'rank_changed(胜者)')
    assert pa['admiral_promoted'] is False
    assert pa['after']['is_admiral'] is False
    reason = pa['admiral_reason']
    assert reason and re.search(r'[\u4e00-\u9fff]', reason), f'必须给中文原因，实际 {reason!r}'
    assert str(pool_now + 100) in reason, f'原因要说清"还差多少人"，实际 {reason!r}'


def test_admiral_reason_when_below_captain(env):
    """没到船长段位时，`admiral_reason` 也要是给人看的中文说明。"""
    room, ca, cb, ua, ub = env(points_a=10, points_b=10)
    server._finalize_match(room, _pid_of(room, ua), _pid_of(room, ub))

    pa = _only(_recv(ca, 'rank_changed'), 'rank_changed(胜者)')
    assert pa['admiral_promoted'] is False
    assert pa['admiral_reason'] == '需要先达到船长段位'


def test_admiral_demoted_when_condition_no_longer_met(env, monkeypatch):
    """动态称号（`ADMIRAL_STICKY is False`）：条件不再满足要从大舰长掉回船长。"""
    if ranks.ADMIRAL_STICKY:
        pytest.skip('粘性开启时不会掉回船长，这条用例不适用')
    pool_now = db.count_rank_at_least(ranks.CAPTAIN_FLOOR)
    monkeypatch.setattr(ranks, 'ADMIRAL_MIN_CAPTAINS', pool_now + 100)

    room, ca, cb, ua, ub = env(points_a=ranks.CAPTAIN_FLOOR + 50, points_b=100)
    # 曾经是大舰长（库里带着 is_admiral=1），但这一局的条件已经不满足
    db.set_rank_points(ua, ranks.CAPTAIN_FLOOR + 50, is_admiral=1)
    assert db.get_user_rank_row(ua)['is_admiral'] == 1

    server._finalize_match(room, _pid_of(room, ua), _pid_of(room, ub))

    assert db.get_user_rank_row(ua)['is_admiral'] == 0, '条件不满足要掉回船长'
    pa = _only(_recv(ca, 'rank_changed'), 'rank_changed(胜者)')
    assert pa['admiral_demoted'] is True
    assert pa['admiral_promoted'] is False
    assert pa['after']['is_admiral'] is False
    assert pa['before']['is_admiral'] is True


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
def test_rematch_pairing_still_settles_ranked(sockets):
    """★ 和「最近刚打过的人」再次匹配上时，`room.ranked` 仍必须是 True。

    这正是玩家报的场景：两人反复匹配（小号社区里很常见），
    结果排位分不加也不扣。
    """
    ua, ub = _mk_user(), _mk_user()
    try:
        db.set_rank_points(ua, 100)
        db.set_rank_points(ub, 100)
        # 先让他们"刚打过一局" → 互为 recent_foes（触发软规避扣分）
        db.record_match(ua, ub, None, count_stats=False)
        assert ub in server._recent_foes(ua), '前置条件：应互为最近对手'

        ca, cb = sockets(ua), sockets(ub)
        before = set(server.room_manager.get_all_rooms())
        ca.emit('find_match', {'player_name': '甲', 'mode': 'ranked'})
        cb.emit('find_match', {'player_name': '乙', 'mode': 'ranked'})
        new = [r for r in server.room_manager.get_all_rooms().values() if r.id not in before]
        assert len(new) == 1, f'两人应当被配成一局，实际新建 {len(new)} 个房'

        room = new[0]
        assert room.ranked is True, (
            '★ 和最近打过的人再匹配，排位**仍然要结算** —— '
            '配对偏好（assessed）不是结算判据；给不给分由 anticheat 按对局内容决定'
        )
    finally:
        for client in (locals().get('ca'), locals().get('cb')):
            try:
                client and client.disconnect()
            except Exception:
                pass


def test_rematch_pairing_actually_awards_points(sockets):
    """★ 更进一步：这种"重复匹配"的一局**真的把分加上去了**。

    上面那条只验标记；这条走完整结算，验分数确实变了。
    """
    ua, ub = _mk_user(), _mk_user()
    ca = cb = None
    try:
        db.set_rank_points(ua, 100)
        db.set_rank_points(ub, 100)
        db.record_match(ua, ub, None, count_stats=False)   # 互为最近对手

        ca, cb = sockets(ua), sockets(ub)
        before = set(server.room_manager.get_all_rooms())
        ca.emit('find_match', {'player_name': '甲', 'mode': 'ranked'})
        cb.emit('find_match', {'player_name': '乙', 'mode': 'ranked'})
        new = [r for r in server.room_manager.get_all_rooms().values() if r.id not in before]
        assert len(new) == 1
        room = new[0]

        # 让这一局"真开打"（否则赛前投降不给分是既有正确行为）
        room.match_started_at = time.time()
        room.state = 'attacking'
        room.round = 6

        server._finalize_match(room, _pid_of(room, ua), _pid_of(room, ub))

        assert db.get_user_rank_row(ua)['points'] > 100, '赢的一方必须加分'
        assert db.get_user_rank_row(ub)['points'] < 100, '输的一方必须扣分'
    finally:
        for client in (ca, cb):
            try:
                client and client.disconnect()
            except Exception:
                pass
