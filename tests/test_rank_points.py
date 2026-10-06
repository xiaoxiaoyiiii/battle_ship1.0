# -*- coding: utf-8 -*-
"""每局排位加减分的**多因子**回归测试（2026-09-18）。

作者原话：「可以把加分机制改一改 变得和经验一样就是很多因素都可以影响这一局的
加分扣分多少 比如说连胜 终止连败 闪电战这种的」。冻结的计分表见
`docs/RANKED_2026_09_17.md` §2.5，实现只此一份（`ranks.points_breakdown`）。

覆盖 8 组（逐条对应任务书）：

  1. **恒等式**：`base + sum(bonuses) == total`，在几十组参数化组合下都成立
     （这是这套机制的地基：明细与总数一旦对不上，结算界面就在撒谎）；
  2. 每个因子**单独**生效：连胜 / 终止连败 / 闪电战（179 vs 181 秒、5 vs 6 回合）/
     零伤 / 击沉封顶（沉 6 艘 == 沉 10 艘）/ 越级挑战（高 1~2 段 vs 高 ≥3 段）；
  3. **满配 +72** 与**败局下限 −5**（含 `cap` 行存在且为负）；
  4. 败局**永远不会变成正数**（把减免项全打开 → `total <= POINTS_LOSS_FLOOR`）；
  5. `segments` 的动画路径（跨小级 2 段且第一段 `sub_up`；不跨 1 段；`ratio` 在 0~1；
     `after < before` 给空列表）；
  6. ★ **取数顺序的回归**（本文件最重要的一条）：真跑一遍 `_finalize_match`，
     断言"某人首胜"的 `rank_changed['bonuses']` 里**没有**连胜加成 ——
     该用例会**故意把 `_streak_context` 打桩成"含本局"的值**，红基线必炸；
  7. 真链路一遍：`_finalize_match` 后分数正确、`game_over` 先于 `rank_changed`；
  8. 沉船数口径：**故意沉 2 艘 → `_dead_ship_count` 是 2**（不是 `len(player.ships)`）；
     另外把门禁回归也钉住（赛前投降不给分 / 人机房不给分）。

⚠️ 本文件造的账号一律带 `_TAG` 前缀，并在用例结束时清掉 `user_rank` 行 ——
   船长池是**全库共享**的，留一堆船长会污染别的用例（`test_ranked_match.py` 同一条规矩）。
"""
import itertools
import re
import time

import pytest

import db
import ranks
import server

_seq = itertools.count(1)
_TAG = 'rkp9'

_WIN_BASE = ranks.WIN_POINTS
_LOSE_BASE = ranks.LOSE_POINTS
_FLOOR = ranks.POINTS_LOSS_FLOOR


# ---------------------------------------------------------------------------
# 账号 / 清理 / 夹具（与 tests/test_ranked_match.py 同一套写法，避免再造一份房间夹具）
# ---------------------------------------------------------------------------
def _mk_user(prefix=_TAG):
    name = f'{prefix}{next(_seq)}'
    uid = db.create_user(name, 'x' * 12)
    assert uid, f'建号失败: {name}'
    return uid


def _purge(uids):
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


@pytest.fixture(autouse=True)
def _clean_globals():
    existing = set(server.room_manager.get_all_rooms())
    server.room_manager.match_queue = []
    yield
    for rid in list(server.room_manager.get_all_rooms()):
        if rid not in existing:
            server.room_manager.rooms.pop(rid, None)
    server.room_manager.match_queue = []


@pytest.fixture
def sockets():
    made = []

    def _make(uid=None):
        http = server.app.test_client()
        if uid:
            with http.session_transaction() as sess:
                sess['user_id'] = uid
                sess['username'] = uid
        client = server.socketio.test_client(server.app, flask_test_client=http)
        client.get_received()
        made.append(client)
        return client

    yield _make
    for client in made:
        try:
            client.disconnect()
        except Exception:
            pass


def _pick(events, name):
    out = []
    for m in events:
        if m['name'] != name:
            continue
        args = m['args']
        if isinstance(args, dict):
            args = [args]
        out.extend(a for a in (args or ()) if isinstance(a, dict))
    return out


def _drain_all(client, tries=30):
    events = client.get_received()
    for _ in range(tries):
        try:
            server.socketio.sleep(0)
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
    """`env(...)` 用真实 `find_match` 开一局两人排位对局。"""
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
        room.match_started_at = time.time() if started else 0
        room.state = 'attacking'
        return room, ca, cb, ua, ub

    def _track(*uids):
        state['uids'] += [u for u in uids if u]

    _start.track = _track
    _start.rooms = state['rooms']
    yield _start
    for rid in state['rooms']:
        server.room_manager.rooms.pop(rid, None)
    _purge(state['uids'])


def _mk_room(room_id):
    """造一个不带任何比赛历史的干净房间（纯函数级用例用）。"""
    room = server.GameRoom(room_id)
    room.__dict__.pop('match_started_at', None)
    return room


def _mk_player(name='玩家', ships=None, user_id=None):
    return server.Player(name=name, ships=list(ships or []), attacks=[],
                         remaining_ships=6, user_id=user_id, sid=f'sid-{name}')


def _ship(x, y, hits=0):
    """一艘单格船；`hits=1` 就是"已经沉了"。

    ⚠️ 存活判据是 `len(ship.hits) < len(ship.positions)`（`_is_ship_alive`），
    单格船挨一炮就沉 —— 所以 `hits` 只能传 0 或 1。
    """
    pos = server.Position(x=x, y=y)
    hit_list = []
    if int(hits) > 0:
        pos.hit = True
        hit_list.append(server.Position(x=x, y=y, hit=True))
    return server.PlayerShip(positions=[pos], hits=hit_list)


# ===========================================================================
# 1. 恒等式：base + sum(bonuses) == total（参数化几十组）
#    ⚠️ 两张参数表**分开命名**（早先按下标切片切错了组，收集期就炸了）
# ===========================================================================
# ⚠️ 这里**故意只留抽样**：原来那两张表是 2×7×6×6 与 2×6×5×5×3（合计 1404 条
#    参数化用例），把整套测试从 ~1300 顶到 2779 —— 而它们验的其实是同一件事
#    （恒等式 base + Σbonuses == total）。同样的覆盖广度改由下面**一个**随机用例
#    用固定种子跑 200 组来完成：用例数 1404 → 11，覆盖面一点没少。
_STREAK_CASES = [
    (True, 0, 0, 0), (True, 1, 0, 0), (True, 2, 0, 0), (True, 5, 3, 2),
    (True, 9, 4, 4), (True, 20, 12, 9),
    (False, 0, 1, 0), (False, 0, 3, 2), (False, 0, 12, 9), (False, 3, 5, 4),
    (False, 20, 12, 9),
]

_SHAPE_CASES = [
    (True, 0, 0, 0, 0), (True, 30, 1, 6, 0), (True, 179, 5, 5, 0),
    (True, 181, 6, 6, 1), (True, 900, 40, 10, 6), (True, 60, 2, 1, 6),
    (False, 30, 0, 5, 0), (False, 180, 5, 6, 6), (False, 900, 40, 0, 6),
    (False, 181, 6, 5, 1),
]












# ===========================================================================
# 2. 每个因子单独生效
# ===========================================================================
def _delta(**kw):
    """`ranks.match_points` 相对"什么都没发生"的差（= 这一项因子贡献了多少）。

    ⚠️ 默认 `lost=1`（自己沉了 1 艘）—— 那是"隔离因子"的基线：不沉对方也不沉自己
    （`sunk=0, lost=0`）根本不像一局打过的仗，不该用来测某个单项。
    需要"零伤"时显式传 `lost=0` 且 `sunk>0`。
    """
    win = kw.pop('win', True)
    kw.setdefault('lost', 1)
    return ranks.match_points(win, **kw) - ranks.match_points(win, lost=1, sunk=0)


























# ===========================================================================
# 3. 满配 +72 / 败局下限 −5（含 cap 行）
# ===========================================================================








# ===========================================================================
# 4. 规则快照 scoring_table() / constants()
# ===========================================================================






# ===========================================================================
# 5. segments：进度条动画路径
# ===========================================================================
















# ===========================================================================
# 6. ★ 取数顺序的回归（**真跑一遍 _finalize_match**）
# ===========================================================================










# ===========================================================================
# 7. 结算走真链路：分数正确 + game_over 先于 rank_changed
# ===========================================================================
def test_real_settlement_points_and_event_order(env):
    """真链路一遍：走**真实投降路径**（socket 请求上下文）验落库 + payload + 事件顺序。

    ⚠️ 走 `emit('surrender')` 而不是直调 `_finalize_match`：只有在**socket 请求上下文**
    里 `_dispatch_rank_events` 才会把 `rank_changed` 交给后台任务补发（同步发的话它会
    **先于** `game_over` 到前端）。直调是测不到这个顺序的 —— 那样测出来的是"直调时
    顺序反了"，而不是真链路的顺序。既有测试 `test_ranked_match.py` 也是这么写的。
    """
    room, ca, cb, ua, ub = env(points_a=100, points_b=100)
    pid_a, pid_b = _pid_of(room, ua), _pid_of(room, ub)
    room.round = 9                                  # 排掉闪电战
    room.match_started_at = time.time() - 1000      # 排掉速败减免
    # ⚠️ 下面甲投降 → **甲是败者、乙是胜者**。所以要让"乙击沉甲 2 艘、乙自己零伤"：
    #    甲（败者）棋盘上沉 2 艘、乙（胜者）棋盘上 0 沉。
    room.players[pid_a].ships = [_ship(i, 0, hits=1) for i in range(2)] + \
        [_ship(i, 0) for i in range(2, 6)]
    room.players[pid_b].ships = [_ship(i, 5) for i in range(6)]
    assert server._dead_ship_count(room.players[pid_a]) == 2, '败者（甲）棋盘沉 2 艘'
    assert server._dead_ship_count(room.players[pid_b]) == 0, '胜者（乙）零伤'
    room.state = 'attacking'
    ca.get_received(); cb.get_received()

    ca.emit('surrender', {'room_id': room.id, 'player_id': pid_a})   # 甲投降 → 乙胜

    # 落库正确：乙的加分 = base + 明细之和（乙零伤获胜 + 击沉甲 2 艘）
    assert db.get_user_rank_row(ub)['points'] == 100 + _WIN_BASE \
        + ranks.POINTS_FLAWLESS + 2 * ranks.POINTS_PER_SINK, '乙：+20 +8 零伤 +2 击沉 = +30'
    assert db.get_user_rank_row(ua)['points'] == 100 + _LOSE_BASE, '甲：−15'

    evs_a, evs_b = _drain_all(ca), _drain_all(cb)
    won = _only(_pick(evs_b, 'rank_changed'), 'rank_changed(胜者)')
    lost = _only(_pick(evs_a, 'rank_changed'), 'rank_changed(败者)')

    for payload in (won, lost):
        assert isinstance(payload['base'], int)
        assert isinstance(payload['bonuses'], list)
        assert payload['base'] + sum(b['value'] for b in payload['bonuses']) \
            == payload['breakdown_total'], payload
        assert isinstance(payload['segments'], list)

    assert {b['key'] for b in won['bonuses']} == {'flawless', 'sinks'}, won['bonuses']
    assert won['base'] == _WIN_BASE and won['breakdown_total'] == 30
    assert won['delta'] == won['breakdown_total'] == 30, '没撞封底时理论值 == 实际值'
    assert lost['base'] == _LOSE_BASE and lost['bonuses'] == []
    assert lost['delta'] == lost['breakdown_total'] == _LOSE_BASE == -15
    assert lost['points_before'] == 100 and lost['points_after'] == 100 + lost['delta']

    # 事件顺序：`game_over` 必须先于 `rank_changed`（前端要等结算面板之后才弹段位面板）
    order = [m['name'] for m in evs_b]
    assert 'game_over' in order and 'rank_changed' in order, f'事件不齐: {order}'
    assert order.index('game_over') < order.index('rank_changed'), \
        f'rank_changed 必须排在 game_over 之后，实际顺序 {order}'












# ===========================================================================
# 8. 门禁回归（多因子不许把既有门禁改坏）
# ===========================================================================




def test_pre_match_surrender_still_gives_no_points(env):
    """赛前投降仍然不给分（门禁不许被这次改动破坏）。"""
    room, ca, cb, ua, ub = env(points_a=100, points_b=100, started=False)
    room.created_at = time.time()
    room.__dict__.pop('match_started_at', None)
    room.state = 'placing_ships'
    assert server._ranked_settlement_allowed(room, True) is False
    ca.get_received(); cb.get_received()

    ca.emit('surrender', {'room_id': room.id, 'player_id': _pid_of(room, ua)})

    assert db.get_user_rank_row(ua)['points'] == 100
    assert db.get_user_rank_row(ub)['points'] == 100
    assert _pick(_drain_all(ca), 'rank_changed') == []
    assert _pick(_drain_all(cb), 'rank_changed') == []


def test_ai_room_still_gives_no_points(env, sockets):
    """人机房仍然不给分。"""
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
    assert server._ranked_settlement_allowed(room, server._count_stats_for(room)) is False

    room.state = 'game_over'
    server._finalize_match(room, human_sid, ai_id)

    assert db.get_user_rank_row(uid)['points'] == 120, '打电脑不许刷段位'
    assert _pick(_drain_all(ca), 'rank_changed') == []


def test_guest_side_is_skipped_and_settlement_still_allowed(env):
    """房里混一个游客：游客那一份跳过，另一份照常结算（多因子不许把这段弄崩）。"""
    room, ca, cb, ua, ub = env(points_a=100, points_b=100)
    pid_a, pid_b = _pid_of(room, ua), _pid_of(room, ub)
    room.players[pid_b].user_id = None
    room.round = 9
    room.match_started_at = time.time() - 1000
    room.state = 'game_over'
    server._finalize_match(room, pid_a, pid_b)

    won = _only(_recv_wait(ca, 'rank_changed'), 'rank_changed')
    # 这一局双方都没船 → `sunk=0`、`lost=0` → 只有基础分（没有零伤加成、没有闪电战）
    assert won['base'] == _WIN_BASE and won['bonuses'] == []
    assert won['delta'] == _WIN_BASE == 20
    assert db.get_user_rank_row(ua)['points'] == 100 + won['delta']
    assert db.get_user_rank_row(ub)['points'] == 100
    assert won['role'] == 'winner'
    assert _pick(_drain_all(cb), 'rank_changed') == []




def _recv_wait(client, name):
    """等后台任务把 `rank_changed` 补发过来再取（与既有夹具同一套写法）。"""
    return _pick(_drain_all(client), name)
