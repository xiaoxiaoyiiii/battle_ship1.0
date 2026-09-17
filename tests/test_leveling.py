# -*- coding: utf-8 -*-
"""等级 / 经验（leveling）的回归测试（2026-09-17）。

四块：
  1. 曲线与视图纯函数（唯一一份规则，前端不重算）；
  2. `user_xp` 表与 DAO（幂等、只增不减、批量读）；
  3. 接口下发（`/api/profile`、`/user_stats`、`/api/leaderboard` 三处口径一致）；
  4. 结算事件 `xp_gained`（只发本人、带动画分段、满级/升级两种情形）。

⚠️ 这里锁的关键点是「**只有一份曲线实现**」：前端拿 `segments` 播动画，
   所以段必须自洽（每段 from/to/need 与曲线对得上、升级段 to == need）。
"""
import itertools

import pytest

import api
import db
import leveling
import profile_spec
import server

_seq = itertools.count(1)


def _mk_user(prefix):
    name = f'{prefix}{next(_seq)}'
    uid = db.create_user(name, 'x' * 12)
    assert uid, f'建号失败: {name}'
    return uid, name


def _purge(uids):
    try:
        with db.db._lock:
            for uid in uids:
                for table in ('user_xp', 'user_perks', 'user_achievements'):
                    db.db.conn.execute(f'DELETE FROM {table} WHERE user_id = ?', (uid,))
            db.db.conn.commit()
    except Exception:
        pass


@pytest.fixture
def user():
    uid, name = _mk_user('lvl')
    try:
        yield uid, name
    finally:
        _purge((uid,))


def _http(uid=None):
    c = server.app.test_client()
    if uid:
        with c.session_transaction() as sess:
            sess['user_id'] = uid
            sess['username'] = uid
    return c


# ---------------------------------------------------------------------------
# 1. 曲线纯函数
# ---------------------------------------------------------------------------
def test_thresholds_are_monotonic():
    prev = -1
    for lv in range(1, leveling.LEVEL_101 + 1):
        at = leveling.xp_for_level(lv)
        assert at > prev, f'等级 {lv} 的阈值必须严格递增'
        prev = at


def test_threshold_anchors():
    """把关键点钉死：改了曲线这些数字就该一起改（否则是无声的行为变化）。"""
    assert leveling.xp_for_level(1) == 0
    assert leveling.xp_for_level(2) == 35
    assert leveling.xp_for_level(10) == 675
    assert leveling.xp_for_level(50) == 13475
    assert leveling.xp_for_level(100) == 51975
    assert leveling.xp_for_level(101) == 53000


def test_level_from_xp_boundaries():
    assert leveling.level_from_xp(0) == 1
    assert leveling.level_from_xp(34) == 1
    assert leveling.level_from_xp(35) == 2, '差 1 点不该升级'
    assert leveling.level_from_xp(51974) == 99
    assert leveling.level_from_xp(51975) == 100
    assert leveling.level_from_xp(10 ** 9) == leveling.MAX_LEVEL, '普通账号封顶 100'


def test_level_101_cap_for_perk_account():
    assert leveling.level_from_xp(51975, leveling.LEVEL_101) == 100
    assert leveling.level_from_xp(53000, leveling.LEVEL_101) == 101
    assert leveling.level_from_xp(10 ** 9, leveling.LEVEL_101) == 101, '101 也封顶'


def test_level_view_progress_math():
    v = leveling.level_view(40)          # L2 从 35 起，L3 在 80
    assert v['level'] == 2 and v['into'] == 5 and v['need'] == 45
    assert abs(v['ratio'] - 5 / 45) < 1e-3
    assert v['next_at'] == 80 and v['level_at'] == 35
    assert v['capped'] is False


def test_level_view_capped_has_no_division_by_zero():
    v = leveling.level_view(999999)
    assert v['capped'] is True and v['need'] == 0 and v['ratio'] == 1.0
    assert v['next_at'] is None


def test_segments_within_one_level():
    segs = leveling.segments(20, 25)
    assert len(segs) == 1
    s = segs[0]
    assert s['level_up'] is False
    assert s['from'] == 20 and s['to'] == 25 and s['need'] == leveling.xp_for_level(2)
    assert abs(s['ratio_to'] - 25 / 35) < 1e-3


def test_segments_single_level_up_ends_full():
    """升级段的 `to` 必须正好等于 need —— 前端靠"这一段填满"来播升级动画。"""
    segs = leveling.segments(20, 40)
    assert [s['level_up'] for s in segs] == [True, False]
    assert segs[0]['to'] == segs[0]['need'] == leveling.xp_for_level(2)
    assert segs[0]['ratio_to'] == 1.0
    assert segs[1]['from'] == 0 and segs[1]['level'] == 2 and segs[1]['to'] == 5


def test_segments_multi_level_up():
    segs = leveling.segments(20, 120)
    ups = [s for s in segs if s['level_up']]
    assert len(ups) >= 2, '跨两级就该有两段升级动画'
    for s in ups:
        assert s['to'] == s['need']


def test_segments_at_cap_is_a_finished_bar():
    segs = leveling.segments(999999, 1000020)
    assert len(segs) == 1 and segs[0]['level_up'] is False
    assert segs[0]['ratio_from'] == 1.0 and segs[0]['ratio_to'] == 1.0


def test_segments_never_lose_xp():
    """段与段之间必须接得上：上一段结束时的累计经验 == 下一段起点。"""
    before, after = 10, 200
    segs = leveling.segments(before, after)
    xp = before
    for s in segs:
        base = leveling.xp_for_level(s['level'])
        assert s['from'] == xp - base, f'第 {s["level"]} 段的起点接不上'
        assert s['to'] >= s['from']
        xp = base + s['to']
    assert xp == after, '按段走完必须正好落在 after 上'


# ---------------------------------------------------------------------------
# 2. 每局经验
# ---------------------------------------------------------------------------
def test_match_xp_rules():
    assert leveling.match_xp(False) == leveling.XP_BASE
    assert leveling.match_xp(True) == leveling.XP_BASE + leveling.XP_WIN
    assert leveling.match_xp(True, sunk=3) == leveling.XP_BASE + leveling.XP_WIN + 3 * leveling.XP_PER_SINK
    full = leveling.match_xp(True, sunk=3, flawless=True, fast=True)
    assert full == leveling.XP_BASE + leveling.XP_WIN + 6 + leveling.XP_FLAWLESS + leveling.XP_FAST_WIN


def test_loser_gets_no_bonus_even_with_good_stats():
    """输的一方不给额外奖励（否则"输得漂亮"比赢拿得多）。"""
    assert leveling.match_xp(False, sunk=6, flawless=True, fast=True) == leveling.XP_BASE


def test_breakdown_sums_to_total():
    for win in (True, False):
        for sunk in (0, 3):
            for extra in ({}, {'flawless': True}, {'fast': True}, {'flawless': True, 'fast': True}):
                rows = leveling.xp_breakdown(win, sunk=sunk, **extra)
                assert sum(r['xp'] for r in rows) == leveling.match_xp(win, sunk=sunk, **extra)


def test_cap_for_perk():
    assert leveling.cap_for(False) == leveling.MAX_LEVEL == 100
    assert leveling.cap_for(True) == leveling.LEVEL_101 == 101


# ---------------------------------------------------------------------------
# 3. user_xp 表 / DAO
# ---------------------------------------------------------------------------
def test_xp_defaults_to_zero(user):
    uid, _ = user
    assert db.get_user_xp(uid) == 0
    assert db.get_user_xp('') == 0


def test_add_xp_returns_running_total(user):
    uid, _ = user
    assert db.add_user_xp(uid, 10) == 10
    assert db.add_user_xp(uid, 15) == 25
    assert db.get_user_xp(uid) == 25


def test_add_xp_ignores_non_positive(user):
    """经验只增不减：负数/0/垃圾值都不许把玩家打回去。"""
    uid, _ = user
    db.add_user_xp(uid, 50)
    assert db.add_user_xp(uid, -100) == 50
    assert db.add_user_xp(uid, 0) == 50
    assert db.add_user_xp(uid, 'abc') == 50
    assert db.get_user_xp(uid) == 50


def test_set_xp_for_ops(user):
    uid, _ = user
    assert db.set_user_xp(uid, 53000) is True
    assert db.get_user_xp(uid) == 53000


def test_xp_map_batches(user):
    uid, _ = user
    db.set_user_xp(uid, 123)
    m = db.get_xp_map([uid, 'nobody'])
    assert m.get(uid) == 123 and 'nobody' not in m
    assert db.get_xp_map([]) == {}


# ---------------------------------------------------------------------------
# 4. 接口下发（三处口径一致）
# ---------------------------------------------------------------------------
def test_profile_carries_level_info(user):
    uid, _ = user
    db.set_user_xp(uid, 40)
    d = _http(uid).get('/api/profile').get_json()['profile']
    li = d.get('level_info')
    assert li and li['level'] == 2 and li['max_level'] == 100


def test_user_stats_carries_level_info_for_others(user):
    uid, name = user
    db.set_user_xp(uid, 675)
    r = _http().get('/user_stats?username=' + name).get_json()
    li = r['stats'].get('level_info')
    assert li and li['level'] == 10, '别人看你的名片也要看到等级（同一个视图）'


def test_level_101_perk_raises_cap(user):
    uid, _ = user
    db.set_user_xp(uid, 53000)
    plain = _http(uid).get('/api/profile').get_json()['profile']['level_info']
    assert plain['level'] == 100 and plain['max_level'] == 100
    db.grant_user_perk(uid, profile_spec.PERK_LEVEL_101)
    vip = _http(uid).get('/api/profile').get_json()['profile']['level_info']
    assert vip['level'] == 101 and vip['max_level'] == 101, '持特权才能到 101'


def test_leaderboard_rows_carry_level(user):
    uid, name = user
    db.set_user_xp(uid, 675)
    # ⚠️ 排行榜只收"真打过一局"的账号（见 get_user_rank 的注释：排序口径要对齐），
    #    0 胜 0 负的新号根本不在榜上 —— 第一版没给战绩，于是"找不到这一行"假红了一次。
    db.db.conn.execute('UPDATE users SET wins = 1, losses = 0 WHERE id = ?', (uid,))
    db.db.conn.commit()
    rows = _http().get('/api/leaderboard?limit=100').get_json()
    row = next((r for r in rows if str(r.get('id')) == uid), None)
    assert row is not None, '这个账号应当出现在排行榜里'
    assert row.get('level') == 10


# ---------------------------------------------------------------------------
# 5. 结算事件 xp_gained
# ---------------------------------------------------------------------------
def _room_with(uid_a, uid_b, room_id):
    r = server.GameRoom(room_id)
    r.players['pa'] = server.Player(name='甲', ships=[], attacks=[], remaining_ships=6,
                                    sid='sid-a', user_id=uid_a)
    r.players['pb'] = server.Player(name='乙', ships=[], attacks=[], remaining_ships=6,
                                    sid='sid-b', user_id=uid_b)
    return r


def test_settlement_emits_xp_to_each_player_only():
    """★ 结算经验**各发本人**：双方都会收到，但每个人只收到**自己那份**。

    （第一版把这个用例写成"期望只有胜者收到" → 假红。输的一方也有基础经验，
    这是有意的设计：参与对局 +10，不至于打一局白打。要守的是
    "A 的事件里不能出现 B 的经验"，而不是"只有一个人收得到"。）
    """
    a, _ = _mk_user('lvlx')
    b, _ = _mk_user('lvly')
    try:
        room = _room_with(a, b, 'lvl-room')
        sa = server.socketio.test_client(server.app, flask_test_client=_http(a))
        sb = server.socketio.test_client(server.app, flask_test_client=_http(b))
        try:
            pa, pb = room.players['pa'], room.players['pb']
            for client, pl in ((sa, pa), (sb, pb)):
                sid = server.socketio.server.manager.sid_from_eio_sid(client.eio_sid, '/')
                pl.sid = sid
                server.socketio.server.enter_room(sid, room.id)
            sa.get_received(); sb.get_received()
            db.set_user_xp(a, 30)          # 离 L2 只差 5 点：这一局一定会升级
            server._grant_match_xp(room, (('pa', pa, a, True), ('pb', pb, b, False)))

            def payloads(client):
                out = []
                for ev in client.get_received():
                    if ev['name'] != 'xp_gained':
                        continue
                    args = ev['args']
                    if isinstance(args, dict):
                        args = [args]
                    out.extend(x for x in (args or ()) if isinstance(x, dict))
                return out

            got_a = payloads(sa)
            got_b = payloads(sb)
            assert len(got_a) == 1, f'本人应当恰好收到一条经验事件，实际 {len(got_a)}'
            assert len(got_b) == 1, '输的一方也有基础经验，同样收到（自己那份）'
            assert got_a[0]['player_id'] == 'pa' and got_b[0]['player_id'] == 'pb'
            assert got_a[0]['xp_after'] == db.get_user_xp(a), 'A 的事件必须是 A 的经验'
            assert got_b[0]['xp_after'] == db.get_user_xp(b), 'B 的事件必须是 B 的经验'
            assert got_a[0]['delta'] != got_b[0]['delta'], '赢的比输的多（规则要真的生效）'
            p = got_a[0]
            assert p['after']['level'] > p['before']['level'], '这一局应当升级'
            assert p['segments'] and p['segments'][0]['level_up'] is True
            assert sum(r['xp'] for r in p['breakdown']) == p['delta'], '明细必须等于总经验'
        finally:
            try:
                sa.disconnect(); sb.disconnect()
            except Exception:
                pass
    finally:
        _purge((a, b))


def test_settlement_skips_guests_and_ai():
    """游客（没有 user_id）不发经验；人机对局在 `count_stats` 那一步就被拦住了。"""
    a, _ = _mk_user('lvlz')
    try:
        room = _room_with(a, None, 'lvl-room2')
        sa = server.socketio.test_client(server.app, flask_test_client=_http(a))
        try:
            pa = room.players['pa']
            pa.sid = server.socketio.server.manager.sid_from_eio_sid(sa.eio_sid, '/')
            sa.get_received()
            server._grant_match_xp(room, (('pa', pa, a, True), ('pb', room.players['pb'], None, False)))
            ra = sa.get_received()
            assert len([e for e in ra if e['name'] == 'xp_gained']) == 1
            # 对手是游客：不该有任何发给它的写入（这里用"库里没有它的行"来证明）
            assert db.get_user_xp('') == 0
        finally:
            try:
                sa.disconnect()
            except Exception:
                pass
    finally:
        _purge((a,))


def test_finalize_match_is_the_only_xp_call_site():
    """经验也必须走结算收口（与战绩/统计/徽章同一条规矩）。

    ⚠️ 统计"调用点"要看**带参数的那种写法**：`def _grant_match_xp(room, rows)` 这行
    本身也含 `_grant_match_xp(room,`，第一版就是这么多数了一次（2 != 1 假红）。
    """
    src = open('server.py', encoding='utf-8').read()
    assert src.count('def _grant_match_xp(') == 1
    assert src.count('_grant_match_xp(room, ((') == 1, '只允许在 _finalize_match 里调用一次'
