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
_STREAK_CASES = []
for _win in (True, False):
    for _ws in (0, 1, 2, 3, 5, 9, 20):
        for _ls in (0, 1, 3, 4, 5, 12):
            for _broken in (0, 1, 2, 3, 4, 9):
                _STREAK_CASES.append((_win, _ws, _ls, _broken))

_SHAPE_CASES = []
for _win2 in (True, False):
    for _sec in (0, 30, 179, 180, 181, 900):
        for _rnd in (0, 1, 5, 6, 40):
            for _sunk in (0, 1, 5, 6, 10):
                for _lost in (0, 1, 6):
                    _SHAPE_CASES.append((_win2, _sec, _rnd, _sunk, _lost))


@pytest.mark.parametrize('win,win_streak,lose_streak,broken', _STREAK_CASES)
def test_breakdown_identity_streaks(win, win_streak, lose_streak, broken):
    """恒等式（连胜/连败/终止连败维度）。"""
    base, bonuses, total = ranks.points_breakdown(
        win, win_streak=win_streak, lose_streak=lose_streak, loss_streak_broken=broken)
    assert base + sum(b['value'] for b in bonuses) == total
    assert total == ranks.match_points(win, win_streak=win_streak,
                                       lose_streak=lose_streak,
                                       loss_streak_broken=broken)


@pytest.mark.parametrize('win,seconds,rounds,sunk,lost', _SHAPE_CASES)
def test_breakdown_identity_battle_shape(win, seconds, rounds, sunk, lost):
    """恒等式（用时/回合/击沉/被沉维度）。"""
    base, bonuses, total = ranks.points_breakdown(
        win, seconds=seconds, rounds=rounds, sunk=sunk, lost=lost)
    assert base + sum(b['value'] for b in bonuses) == total
    assert total == ranks.match_points(win, seconds=seconds, rounds=rounds,
                                       sunk=sunk, lost=lost)


def test_breakdown_identity_with_tiers():
    """恒等式（段位维度）+ 每一行的形状都是契约里那三个键。"""
    for win in (True, False):
        for my_tier in range(9):
            for opp_tier in range(9):
                base, bonuses, total = ranks.points_breakdown(
                    win, my_tier=my_tier, opp_tier=opp_tier)
                assert base + sum(b['value'] for b in bonuses) == total
                for row in bonuses:
                    assert set(row) == {'key', 'label', 'value'}, f'明细行的键集错了: {row}'
                    assert isinstance(row['label'], str) and row['label']
                    assert isinstance(row['value'], int)


def test_breakdown_identity_garbage_inputs():
    """脏输入（None / 负数 / 字符串）也不许抛、恒等式照样成立。"""
    for junk in (None, -5, '3', 2.7, ''):
        for win in (True, False):
            base, bonuses, total = ranks.points_breakdown(
                win, win_streak=junk, lose_streak=junk, loss_streak_broken=junk,
                seconds=junk, rounds=junk, sunk=junk, lost=junk,
                my_tier=junk, opp_tier=junk)
            assert base + sum(b['value'] for b in bonuses) == total
            assert isinstance(total, int)


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


def test_bare_call_is_just_the_base():
    """★ 回归守卫：**不带任何战况**的一局就是基础分，不许凭空多给加成。

    踩过两次，都是"不报错、只是分全错"的那种：
      ① `flawless` 写成"自己沉 0 艘就给"，而 `lost` 的默认值就是 0 → 白送 +8；
      ② `base` 既进了 `bonuses` 明细、又被当成求和的起点 → **基础分算了两遍**
         （赢一局变 +40）。所以这条既钉"干净局没有加成"，也钉"base 不在 bonuses 里"。
    """
    assert ranks.match_points(True) == _WIN_BASE == 20
    assert ranks.match_points(False) == _LOSE_BASE == -15
    base, bonuses, total = ranks.points_breakdown(True)
    assert base == 20 and bonuses == [] and total == 20, \
        f'干净的一局：base=20、bonuses=[]、total=20，实际 {(base, bonuses, total)}'
    assert ranks.match_points(True, lost=0) == _WIN_BASE, '对手一艘没沉时也没有零伤加成'
    assert [b['key'] for b in ranks.points_breakdown(False)[1]] == [], '干净的一局输也是空明细'


def test_base_is_not_a_bonus_row():
    """★ `base` 不许出现在 `bonuses` 里（它会和"起点"重复计一次）。"""
    for win in (True, False):
        base, bonuses, total = ranks.points_breakdown(
            win, win_streak=2, lose_streak=2, sunk=1, lost=1, seconds=200)
        assert 'base' not in {b['key'] for b in bonuses}, f'{bonuses}'
        assert base == (_WIN_BASE if win else _LOSE_BASE)
        assert base + sum(b['value'] for b in bonuses) == total


def test_plain_win_and_loss_are_the_base():
    """干净的一局：赢 +20 / 输 −15（与改造前的行为一致）。"""
    assert ranks.match_points(True) == _WIN_BASE
    assert ranks.match_points(False) == _LOSE_BASE
    base, bonuses, total = ranks.points_breakdown(True)
    assert base == _WIN_BASE and total == _WIN_BASE
    assert [b['key'] for b in bonuses] == [], 'clean 局没有加成项'
    # ⚠️ 首胜（win_streak=1）**不给**连胜加成
    assert _delta(win_streak=1) == 0


def test_win_streak_bonus():
    """连胜加成：+2 × N（含本局），N ≥ 2 才给，封顶 +10。"""
    # N 就是"本局是第几连胜"（含本局）→ 2 连胜给 2×2 = +4
    assert _delta(win_streak=1) == 0, '首胜不是"连胜"'
    assert _delta(win_streak=2) == 2 * ranks.POINTS_WIN_STREAK_STEP == 4
    assert _delta(win_streak=3) == 3 * ranks.POINTS_WIN_STREAK_STEP == 6
    assert _delta(win_streak=5) == 5 * ranks.POINTS_WIN_STREAK_STEP == 10
    assert _delta(win_streak=6) == ranks.POINTS_WIN_STREAK_CAP, '封顶 +10'
    assert _delta(win_streak=99) == ranks.POINTS_WIN_STREAK_CAP, '封顶 +10'
    rows = [b for b in ranks.points_breakdown(True, win_streak=3, lost=1)[1]
            if b['key'] == 'win_streak']
    assert rows and rows[0]['value'] == 6 and '3' in rows[0]['label']


@pytest.mark.parametrize('broken,expect', [
    (0, 0), (1, 0),                       # 没终结连败 / 只终结 1 连败 → 不给
    (2, ranks.POINTS_STREAK_BREAK_SHORT),
    (3, ranks.POINTS_STREAK_BREAK_SHORT),
    (4, ranks.POINTS_STREAK_BREAK_LONG),
    (9, ranks.POINTS_STREAK_BREAK_LONG),
])
def test_streak_break_bonus(broken, expect):
    """终止连败：终结 2~3 连败 +8 / ≥4 连败 +12。"""
    assert _delta(loss_streak_broken=broken) == expect


def test_blitz_by_seconds_and_rounds():
    """闪电战：≤180 秒 **或** ≤5 个大回合（任一达标即可）。"""
    b = ranks.POINTS_BLITZ
    assert _delta(seconds=179) == b
    assert _delta(seconds=180) == b
    assert _delta(seconds=181) == 0, '181 秒不算闪电战'
    assert _delta(rounds=5) == b
    assert _delta(rounds=6) == 0, '6 个大回合不算闪电战'
    assert _delta(seconds=500, rounds=20) == 0
    # 没有任何可信时间/回合数据（都是 0）时**不许**当成闪电战
    assert _delta(seconds=0, rounds=0) == 0
    assert _delta(seconds=181, rounds=5) == b, '回合数达标也给'


def test_flawless_needs_a_real_win():
    """零伤获胜 +8：必须**真的打沉过对方**（`sunk > 0`）且自己一艘没沉。"""
    assert _delta(sunk=1, lost=0) == ranks.POINTS_PER_SINK + ranks.POINTS_FLAWLESS
    assert _delta(sunk=6, lost=0) == ranks.POINTS_SINK_CAP + ranks.POINTS_FLAWLESS
    assert _delta(sunk=0, lost=0) == 0, '对手一艘没沉 → 谈不上"零伤获胜"'
    assert _delta(sunk=3, lost=1) == 3, '自己沉了 1 艘就没有零伤加成'
    rows = [b['key'] for b in ranks.points_breakdown(
        True, sunk=2, lost=0)[1]]
    assert rows == ['flawless', 'sinks'], f'明细顺序/内容: {rows}'


def test_sinks_bonus_and_cap():
    """击沉 +1/艘、封顶 +6（封顶后仍按真实击沉数进明细）。

    ⚠️ 这些断言一律带 `lost=1`（自己沉了 1 艘）—— 那才是"隔离击沉这一项"的基线，
    否则 `flawless` 会一起进来（+8），把数看串。
    ⚠️ 击沉的**最小值是 1**：`sunk=0` 表示"对手一艘都没沉"，那不叫打赢，
    也没有"零伤获胜"（见 `test_flawless_needs_a_real_win`）。
    """
    assert _delta(sunk=0) == 0, '没沉对方一艘就没有加成'
    assert _delta(sunk=1) == ranks.POINTS_PER_SINK == 1
    assert _delta(sunk=5) == 5 * ranks.POINTS_PER_SINK
    assert _delta(sunk=6) == ranks.POINTS_SINK_CAP == 6
    assert _delta(sunk=10) == _delta(sunk=6), '封顶：沉 6 艘 == 沉 10 艘'
    # 零伤时击沉与零伤**同时**给（互不吞并）
    assert _delta(sunk=3, lost=0) == 3 * ranks.POINTS_PER_SINK + ranks.POINTS_FLAWLESS
    rows = [b for b in ranks.points_breakdown(True, sunk=10, lost=1)[1] if b['key'] == 'sinks']
    assert rows and rows[0]['value'] == ranks.POINTS_SINK_CAP
    # ⚠️ 明细里的**艘数**是真实击沉数（10），不许被改小成 6 —— 那明细就在撒谎
    assert '10' in rows[0]['label']


def test_upset_bonus_by_tier_gap():
    """越级挑战：对手段位高 1~2 段 +6 / 高 ≥3 段 +10。"""
    assert _delta(my_tier=3, opp_tier=3) == 0, '同段位不给'
    assert _delta(my_tier=3, opp_tier=2) == 0, '打低段位不给'
    assert _delta(my_tier=0, opp_tier=1) == ranks.POINTS_UPSET_SMALL
    assert _delta(my_tier=0, opp_tier=2) == ranks.POINTS_UPSET_SMALL
    assert _delta(my_tier=0, opp_tier=3) == ranks.POINTS_UPSET
    assert _delta(my_tier=0, opp_tier=8) == ranks.POINTS_UPSET


def test_brave_and_underdog_and_fast_loss():
    """败局减免项各自单独生效。"""
    assert _delta(win=False, sunk=4) == 0, '击沉 4 艘还不够"虽败犹荣"'
    assert _delta(win=False, sunk=5) == ranks.POINTS_BRAVE
    assert _delta(win=False, sunk=6) == ranks.POINTS_BRAVE
    assert _delta(win=False, my_tier=0, opp_tier=1) == 0, '只高 1 段不算"输给高段位"'
    assert _delta(win=False, my_tier=0, opp_tier=2) == ranks.POINTS_UNDERDOG
    assert _delta(win=False, seconds=180) == ranks.POINTS_FAST_LOSS
    assert _delta(win=False, seconds=181) == 0
    assert _delta(win=False, seconds=0) == 0, '没有可信用时不减免'


@pytest.mark.parametrize('streak,expect', [
    (1, 0), (2, 0),
    (3, ranks.POINTS_PITY_SHORT), (4, ranks.POINTS_PITY_SHORT),
    (5, ranks.POINTS_PITY_LONG), (9, ranks.POINTS_PITY_LONG),
])
def test_pity_protection(streak, expect):
    """连败保护：本局是第 3~4 连败 +4 / ≥5 连败 +7。"""
    assert _delta(win=False, lose_streak=streak) == expect


def test_loss_side_ignores_win_only_factors():
    """败局不吃"胜利侧"的因子（零伤 / 连胜 / 越级 / 闪电战都不该出现在败局明细里）。"""
    _base, bonuses, _total = ranks.points_breakdown(
        False, win_streak=9, loss_streak_broken=9, seconds=100, rounds=2,
        sunk=0, lost=0, my_tier=0, opp_tier=8)
    keys = {b['key'] for b in bonuses}
    assert not keys & {'win_streak', 'streak_break', 'blitz', 'flawless', 'sinks', 'upset'}
    assert 'brave' not in keys, 'sunk=0 时不该有"虽败犹荣"'
    assert keys <= {'underdog', 'pity', 'fast_loss', 'cap'}
    # 越级 ≠ "输给高段位"：胜侧那个是 upset，败侧那个是 underdog
    assert 'upset' not in keys and 'underdog' in keys


# ===========================================================================
# 3. 满配 +72 / 败局下限 −5（含 cap 行）
# ===========================================================================
def test_perfect_win_is_72():
    """满配 = 20 + 10 + 12 + 6 + 8 + 6 + 10 = **+72**。"""
    total = ranks.match_points(True, win_streak=5, loss_streak_broken=4,
                               seconds=120, rounds=3, sunk=6, lost=0,
                               my_tier=0, opp_tier=3)
    assert total == _WIN_BASE + ranks.POINTS_WIN_STREAK_CAP \
        + ranks.POINTS_STREAK_BREAK_LONG + ranks.POINTS_BLITZ \
        + ranks.POINTS_FLAWLESS + ranks.POINTS_SINK_CAP + ranks.POINTS_UPSET
    base, bonuses, total = ranks.points_breakdown(
        True, win_streak=5, loss_streak_broken=4, seconds=120, rounds=3,
        sunk=6, lost=0, my_tier=0, opp_tier=3)
    assert base + sum(b['value'] for b in bonuses) == total
    assert [b['key'] for b in bonuses] == [
        'win_streak', 'streak_break', 'blitz', 'flawless', 'sinks', 'upset']


def test_worst_loss_is_floored_with_explicit_cap_row():
    """败局下限 −5：减免项**一个都不许被改小**，超出部分由一行显式的负值补平。"""
    base, bonuses, total = ranks.points_breakdown(
        False, lose_streak=5, seconds=100, sunk=6, lost=6, my_tier=0, opp_tier=3)
    assert total == _FLOOR
    by_key = {b['key']: b['value'] for b in bonuses}
    # 四个减免项都在，而且都是**计分表里的原值**（没被偷偷改小）
    assert by_key['brave'] == ranks.POINTS_BRAVE
    assert by_key['underdog'] == ranks.POINTS_UNDERDOG
    assert by_key['pity'] == ranks.POINTS_PITY_LONG
    assert by_key['fast_loss'] == ranks.POINTS_FAST_LOSS
    assert base == _LOSE_BASE
    # cap 那一行必须是**负的**（把被减免顶得太高的总分往下压回下限）
    assert 'cap' in by_key, 'cap 这一行不能省'
    assert by_key['cap'] < 0, f'cap 是把总分往下压的，实际 {by_key["cap"]}'
    assert base + sum(b['value'] for b in bonuses) == total == _FLOOR
    assert by_key['cap'] == _FLOOR - (_LOSE_BASE + ranks.POINTS_BRAVE
                                      + ranks.POINTS_UNDERDOG
                                      + ranks.POINTS_PITY_LONG + ranks.POINTS_FAST_LOSS)
    assert by_key['cap'] == -10, '−15 +20 顶到 +5 → 要补 −10 压回 −5'
    # 胜局永远不该出现 cap 行；没顶到下限的败局也不该有
    assert 'cap' not in {b['key'] for b in ranks.points_breakdown(True, sunk=6, lost=0)[1]}
    assert 'cap' not in {b['key'] for b in ranks.points_breakdown(False)[1]}, \
        '普通败局本来就在下限之下，不该有 cap（写反方向就会白送 +10）'


@pytest.mark.parametrize('sunk,lose_streak,seconds,opp_tier', [
    (6, 9, 30, 8), (5, 5, 100, 3), (6, 5, 179, 4),
    (5, 4, 180, 2), (6, 3, 5, 8), (5, 3, 60, 3),
])
def test_loss_never_becomes_positive(sunk, lose_streak, seconds, opp_tier):
    """★ 把减免项全打开：`total` 永远 `<= POINTS_LOSS_FLOOR`（输一局绝不可能加分）。"""
    total = ranks.match_points(False, lose_streak=lose_streak, seconds=seconds,
                               sunk=sunk, lost=6, my_tier=0, opp_tier=opp_tier)
    assert total <= _FLOOR, f'败局总量必须封在 {_FLOOR}，实际 {total}'
    assert total < 0, '败局的 delta 必须是负的'


def test_all_loss_factors_together_are_not_positive_anywhere():
    """穷举一遍减免组合（4 项 × 各档位）：没有一组能变成正数。

    ⚠️ 段位差只取 `(0, 1, 2, 8)` 四个代表值 —— 判据只看"差 ≥2"，再多取也是同一组结果。
    """
    for sunk in (0, 4, 5, 6, 10):
        for streak in (0, 1, 2, 3, 4, 5, 7):
            for sec in (0, 179, 180, 181, 600):
                for gap in (0, 1, 2, 8):
                    total = ranks.match_points(False, lose_streak=streak, seconds=sec,
                                               sunk=sunk, lost=3, my_tier=0, opp_tier=gap)
                    assert total <= _FLOOR, (sunk, streak, sec, gap, total)


# ===========================================================================
# 4. 规则快照 scoring_table() / constants()
# ===========================================================================
def test_scoring_table_shape_and_key_values():
    table = ranks.scoring_table()
    assert set(table['win'][0]) == {'key', 'label', 'value', 'condition'}
    assert set(table['lose'][0]) == {'key', 'label', 'value', 'condition'}
    assert [r['key'] for r in table['win']] == [
        'base', 'win_streak', 'streak_break', 'blitz', 'flawless', 'sinks', 'upset']
    assert [r['key'] for r in table['lose']] == [
        'base', 'brave', 'underdog', 'pity', 'fast_loss', 'cap']
    assert table['win'][0]['value'] == _WIN_BASE
    assert table['lose'][0]['value'] == _LOSE_BASE
    assert table['loss_floor'] == _FLOOR
    assert table['blitz_seconds'] == ranks.POINTS_BLITZ_SECONDS == 180
    assert table['blitz_rounds'] == ranks.POINTS_BLITZ_ROUNDS == 5
    assert table['win_streak_cap'] == 10
    assert table['sink_cap'] == 6
    assert table['upset_tiers'] == 3
    assert table['brave_sinks'] == 5
    assert table['underdog_tiers'] == 2


def test_constants_keep_old_keys_and_add_scoring():
    """★ 追加 `'scoring'`，**但既有的键一个都不许删**（接口与测试都在用）。"""
    c = ranks.constants()
    for key in ('sub_points', 'subs', 'tiers', 'top_points', 'captain_floor',
                'win_points', 'lose_points', 'min_points', 'admiral_rank_limit',
                'admiral_min_captains', 'admiral_sticky', 'start_points_of_tier'):
        assert key in c, f'constants() 少了既有键 {key}'
    assert c['win_points'] == _WIN_BASE and c['lose_points'] == _LOSE_BASE
    assert c['scoring'] == ranks.scoring_table()
    assert c['scoring']['loss_floor'] == _FLOOR


def test_env_override_still_wins_for_base_points(monkeypatch):
    """环境变量覆盖的既有机制不许被破坏（`_env_int` 读的是 import 期的值）。"""
    assert ranks._env_int('RANK_POINTS_TEST_NOT_SET', 7) == 7
    assert ranks._env_int('RANK_POINTS_TEST_NOT_SET', 7) == 7
    monkeypatch.setenv('RANK_POINTS_TEST_NOT_SET', '42')
    assert ranks._env_int('RANK_POINTS_TEST_NOT_SET', 7) == 42
    monkeypatch.setenv('RANK_POINTS_TEST_NOT_SET', 'garbage')
    assert ranks._env_int('RANK_POINTS_TEST_NOT_SET', 7) == 7, '非法值回默认值，不许抛'


# ===========================================================================
# 5. segments：进度条动画路径
# ===========================================================================
def test_segments_crossing_a_sub_tier_has_two_parts():
    """跨一个小级 → 2 段，且**第一段 `sub_up=True`**（前端在这里播"条子重置"）。"""
    segs = ranks.segments(790, 810)          # 水手长Ⅱ 90 → 水手长Ⅲ 10
    assert len(segs) == 2, segs
    assert segs[0]['sub_up'] is True
    assert segs[0]['from'] == 90 and segs[0]['to'] == 100 and segs[0]['need'] == 100
    assert segs[0]['ratio_from'] == 0.9 and segs[0]['ratio_to'] == 1.0
    assert segs[1]['sub_up'] is False
    assert segs[1]['from'] == 0 and segs[1]['to'] == 10
    assert segs[1]['ratio_to'] == 0.1
    assert segs[0]['tier_id'] == segs[1]['tier_id'] == 'bosun'
    assert segs[0]['sub'] == 'Ⅱ' and segs[1]['sub'] == 'Ⅲ'


def test_segments_within_a_sub_tier_is_one_part():
    segs = ranks.segments(100, 120)
    assert len(segs) == 1
    assert segs[0]['sub_up'] is False
    assert segs[0]['from'] == 0 and segs[0]['to'] == 20
    assert segs[0]['ratio_from'] == 0.0 and segs[0]['ratio_to'] == 0.2


def test_segments_crossing_a_whole_tier_is_two_parts():
    """跨大段位（水手长Ⅲ → 三副Ⅰ）：走满 +8 分那一小级、再在新段位里涨 20。"""
    segs = ranks.segments(880, 920)
    assert len(segs) == 2, segs
    assert [s['sub_up'] for s in segs] == [True, False]
    assert [s['tier_id'] for s in segs] == ['bosun', 'mate3']
    assert (segs[0]['from'], segs[0]['to']) == (80, 100)
    assert (segs[1]['from'], segs[1]['to']) == (0, 20)


@pytest.mark.parametrize('before,after', [
    (0, 20), (5, 95), (95, 105), (790, 810), (880, 920),
    (0, 350), (2390, 2450), (2400, 2472), (2500, 2500),
])
def test_segments_ratios_are_always_inside_0_1(before, after):
    """每段的 `ratio_from` / `ratio_to` 一定在 0..1，`need` 恒为正。"""
    for seg in ranks.segments(before, after):
        assert seg['need'] > 0
        assert 0.0 <= seg['ratio_from'] <= 1.0, seg
        assert 0.0 <= seg['ratio_to'] <= 1.0, seg
        assert seg['from'] >= 0 and seg['to'] >= 0
        assert set(seg) == {'from', 'to', 'need', 'ratio_from', 'ratio_to',
                            'sub_up', 'tier_id', 'sub'}


def test_segments_ratio_delta_matches_points_delta():
    """段内 `(ratio_to - ratio_from)` 必须与真实分数增量成正比（路径不丢步）。"""
    for before, after in ((0, 20), (90, 110), (780, 830), (100, 100)):
        segs = ranks.segments(before, after)
        if not segs:
            continue
        delta = sum((s['ratio_to'] - s['ratio_from']) * s['need'] for s in segs)
        assert abs(delta - (after - before)) < 0.5, (before, after, segs, delta)


def test_segments_at_captain_iii_does_not_spin():
    """★ 船长Ⅲ 之上没有下一个小级：不许吐出成百上千条重复段（实测踩过一次）。"""
    segs = ranks.segments(2390, 2450)
    assert 1 <= len(segs) <= 3, f'饱和段位最多给几段，实际 {len(segs)}'
    assert all(s['tier_id'] == 'captain' for s in segs)
    # 路径必须"走到头"：各段长度之和 == 真实分数增量（`from`/`to` 的单位就是分）
    walked = sum(s['to'] - s['from'] for s in segs)
    assert walked == 60, f'路径没走完（2390→2450 应当走 60 分），实际 {walked}: {segs}'
    assert ranks.segments(2390, 2450)[0]['sub_up'] is True
    assert segs[-1]['sub_up'] is False, '饱和段位没有下一个小级可升'

    # 已经在 2400 之上（从"饱和区内部"起步）也必须只给一段、且长度正确
    segs2 = ranks.segments(2450, 2472)
    assert len(segs2) == 1, segs2
    assert segs2[0]['to'] - segs2[0]['from'] == 22, segs2


def test_segments_empty_when_points_do_not_rise():
    """★ 掉分（`after < before`）→ **空列表**。

    理由：进步条的"曲线"是"离下一个小级还差多少"，往回倒着播在两边都会是 bug 源；
    掉分的动画由前端按 `rank_changed` 的 `demoted` / `before` / `after` 自己演
    （文案与升降级摘要都是现成的）。这条口径写在这里，改它要先改这个用例。
    """
    assert ranks.segments(100, 85) == []
    assert ranks.segments(100, 100) == []
    assert ranks.segments(0, 0) == []
    # 掉分但被 0 分封底（normalize 后相等）也是空
    assert ranks.segments(5, -100) == []


def test_segments_single_step_matches_sub_tier_math():
    """单段路径的 `from` 必须等于"本小级内的进度"（与 `progress()` 同一口径）。"""
    for points in (0, 37, 99, 100, 237, 790, 2400, 2450):
        segs = ranks.segments(points, points)
        assert segs == [] or segs[0]['from'] == ranks.progress(points)
    segs = ranks.segments(237, 250)
    assert len(segs) == 1
    assert segs[0]['from'] == 37 and segs[0]['to'] == 50


# ===========================================================================
# 6. ★ 取数顺序的回归（**真跑一遍 _finalize_match**）
# ===========================================================================
def test_first_win_has_no_win_streak_bonus_via_real_finalize(env):
    """★ 本文件最重要的一条：**首胜不该有连胜加成**，而且真跑 `_finalize_match` 验。

    为什么必须走真链路：`_streak_context` 的结果只有 `_finalize_match` 会用，
    直接调 `ranks.match_points` 是测不到"读到含本局的值"这种 bug 的。

    做法：把 `_streak_context` **包一层**，在它被调用的那一刻快照胜者的
    `users.current_streak` 与 `matches` 行数 —— 正确的实现是在 `record_match`
    **之前**调它（那时库里还是赛前状态：连胜 0、本局那一行还不存在）。
    """
    room, ca, cb, ua, ub = env(points_a=100, points_b=100)
    assert db.get_user(uid=ua)['current_streak'] == 0, '新账号赛前连胜必须是 0'
    pid_a, pid_b = _pid_of(room, ua), _pid_of(room, ub)

    seen = {}
    real = server._streak_context

    def spy(winner, winner_user_id, loser, loser_user_id):
        ctx = real(winner, winner_user_id, loser, loser_user_id)
        row = db.get_user(uid=winner_user_id) if winner_user_id else None
        seen['streak_at_call'] = (row or {}).get('current_streak')
        seen['ctx'] = dict(ctx)
        return ctx

    server._streak_context = spy
    try:
        room.state = 'game_over'
        server._finalize_match(room, pid_a, pid_b)
    finally:
        server._streak_context = real

    assert seen.get('streak_at_call') == 0, \
        f'`_streak_context` 必须在本局写库**之前**跑（那时连胜还是 0），实际读到 {seen}'
    assert seen['ctx']['win_streak_before'] == 0

    won = _only(_recv_wait(ca, 'rank_changed'), 'rank_changed(胜者)')
    keys = [b['key'] for b in won['bonuses']]
    assert 'win_streak' not in keys, f'首胜不许有连胜加成，明细里却出现了: {keys}'
    assert won['base'] == _WIN_BASE
    assert won['breakdown_total'] == won['delta'], '这一局没有别的因子，理论值应当等于实际值'
    assert db.get_user_rank_row(ua)['points'] == 100 + won['delta']
    assert db.get_user(uid=ua)['current_streak'] == 1, '本局算完之后库里才是 1 连胜'


def test_streak_context_reads_before_the_win_is_recorded(env):
    """★ 二连胜那局必须拿到 +2：库里赛前 `current_streak=1` → 本局是第 2 连胜。"""
    room, ca, cb, ua, ub = env(points_a=100, points_b=100)
    # 赛前把甲的连胜计数造出来（等价于"上一局赢了、这一局还没打"）
    db.db.conn.execute('UPDATE users SET current_streak = 1 WHERE id = ?', (ua,))
    db.db.conn.commit()
    assert db.get_user(uid=ua)['current_streak'] == 1

    room.round = 9                      # 排掉闪电战，只看连胜这一项
    room.match_started_at = time.time() - 1000
    room.state = 'game_over'
    server._finalize_match(room, _pid_of(room, ua), _pid_of(room, ub))

    won = _only(_recv_wait(ca, 'rank_changed'), 'rank_changed(胜者)')
    by_key = {b['key']: b['value'] for b in won['bonuses']}
    assert by_key.get('win_streak') == 2 * ranks.POINTS_WIN_STREAK_STEP == 4, \
        f'赛前 current_streak=1 → 本局是第 2 连胜，应当 +4，实际明细 {won["bonuses"]}'
    assert db.get_user(uid=ua)['current_streak'] == 2, '库里也要真的涨到 2'


def test_loss_streak_counted_from_match_history_before_recording(env):
    """★ 连败要从 `matches` 表**赛前**数：败者先连败 2 场 → 本局是第 3 连败 → 有连败保护。"""
    room, ca, cb, ua, ub = env(points_a=100, points_b=300)
    pid_a, pid_b = _pid_of(room, ua), _pid_of(room, ub)
    room.round = 9                      # 排掉闪电战/速败减免，只看连败保护
    room.match_started_at = time.time() - 1000

    # 先造 2 场"乙输给丙"的历史（丙不在本局里，只用来往 matches 表里塞负场）。
    # ⚠️ 时间戳放得足够久（>180 秒）—— 否则本局会被算成"速败"而多一项减免，
    #    那样断言"delta 恰好等于 base + pity"就会假红。
    ghost = _mk_user()
    env.track(ghost)
    now = int(time.time())
    for i in range(2):
        db.db.conn.execute(
            'INSERT INTO matches (id, winner_id, loser_id, timestamp) VALUES (?,?,?,?)',
            (f'{_TAG}-hist-{next(_seq)}', ghost, ub, now - 600 + i))
    db.db.conn.commit()
    assert server._streak_context(None, None, room.players[pid_b], ub)['lose_streak_before'] == 2

    # 甲赢 → 本局是乙的第 3 连败 → pity +4（且这一局甲没有别的因子）
    room.state = 'game_over'
    server._finalize_match(room, pid_a, pid_b)

    lost = _only(_recv_wait(cb, 'rank_changed'), 'rank_changed(败者)')
    by_key = {b['key']: b['value'] for b in lost['bonuses']}
    assert by_key.get('pity') == ranks.POINTS_PITY_SHORT, \
        f'第 3 连败应当有 +4 连败保护，实际明细 {lost["bonuses"]}'
    assert lost['base'] == _LOSE_BASE
    assert lost['delta'] == _LOSE_BASE + ranks.POINTS_PITY_SHORT
    assert db.get_user_rank_row(ub)['points'] == 300 + lost['delta']

    # 而**本局**这一场也要能被下一局的 `_streak_context` 数到（赛前数到 3）
    assert server._streak_context(None, None, room.players[pid_b], ub)['lose_streak_before'] == 3


def test_streak_context_requires_login_and_ignores_none():
    """`_streak_context` 对游客（user_id 为 None）必须安静地给全 0。"""
    ctx = server._streak_context(_mk_player(), None, _mk_player(), None)
    # ⚠️ 键名在 2026-09-18 改过：`loss_streak_broken` → `winner_loss_streak_before`，
    #    因为"终结的连败数"指的是**胜者自己**的连败（原来那份取的是败者的，语义反了）。
    #    三个键分别是：胜者连胜 / 胜者连败（= 本局终结的连败数）/ 败者连败（连败保护）。
    assert ctx == {'win_streak_before': 0, 'winner_loss_streak_before': 0,
                   'lose_streak_before': 0}


def test_streak_context_breaks_on_a_win():
    """连败只在"真的连着输"时累加：中间有一场胜仗就要断。"""
    ghost, uid = _mk_user(), _mk_user()
    now = int(time.time())
    rows = [(ghost, uid, now - 300), (uid, ghost, now - 200), (ghost, uid, now - 100)]
    for winner, loser, ts in rows:
        db.db.conn.execute(
            'INSERT INTO matches (id, winner_id, loser_id, timestamp) VALUES (?,?,?,?)',
            (f'{_TAG}-hist2-{next(_seq)}', winner, loser, ts))
    db.db.conn.commit()
    try:
        # 最近的顺序（倒着数）：输、赢 → 连败在"赢"那一场断掉 → 只数到 1
        assert server._streak_context(None, None, _mk_player(), uid)['lose_streak_before'] == 1
    finally:
        _purge([ghost, uid])
        try:
            with db.db._lock:
                db.db.conn.execute('DELETE FROM matches WHERE winner_id IN (?, ?) OR loser_id IN (?, ?)',
                                   (ghost, uid, ghost, uid))
                db.db.conn.commit()
        except Exception:
            pass


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


def test_settlement_uses_real_sunk_counts(env):
    """★ 沉船数口径：真沉对方的 2 艘 → 胜者明细里是"击沉 2 艘"（+2）。"""
    room, ca, cb, ua, ub = env(points_a=100, points_b=100)
    pid_a, pid_b = _pid_of(room, ua), _pid_of(room, ub)
    loser = room.players[pid_b]
    # 对手棋盘上真的沉 2 艘（`hits` 填满 → `_is_ship_alive` 假）
    loser.ships = [_ship(0, 0, hits=1), _ship(1, 0, hits=1),
                   _ship(2, 0), _ship(3, 0), _ship(4, 0), _ship(5, 0)]
    assert server._dead_ship_count(loser) == 2
    assert len(server._alive_ships(loser)) == 4
    # 胜者自己一艘没沉
    winner = room.players[pid_a]
    winner.ships = [_ship(i, 5) for i in range(6)]
    assert server._dead_ship_count(winner) == 0
    room.round = 9                     # 不是闪电战
    room.match_started_at = time.time() - 1000

    room.state = 'game_over'
    server._finalize_match(room, pid_a, pid_b)

    won = _only(_recv_wait(ca, 'rank_changed'), 'rank_changed(胜者)')
    by_key = {b['key']: b['value'] for b in won['bonuses']}
    assert by_key.get('sinks') == 2, f'沉了 2 艘就应当 +2，实际明细 {won["bonuses"]}'
    assert by_key.get('flawless') == ranks.POINTS_FLAWLESS, '自己 0 沉 → 零伤获胜'
    assert won['breakdown_total'] == _WIN_BASE + 2 + ranks.POINTS_FLAWLESS


def test_dead_ship_count_is_not_len_ships():
    """★ 口径守卫：`len(player.ships)` 会把"沉了 2 艘"数成 6（本项目沉船不移出列表）。"""
    player = _mk_player(ships=[_ship(0, 0, hits=1), _ship(1, 0, hits=1), _ship(2, 0)])
    assert server._dead_ship_count(player) == 2
    assert len(player.ships) == 3, '这就是"数列表长度"会错的原因'
    assert server._dead_ship_count(_mk_player()) == 0


def test_segments_in_payload_walk_the_real_path(env):
    """跨小级的那一局：`rank_changed['segments']` 必须是**两段**且第一段 `sub_up`。"""
    room, ca, cb, ua, ub = env(points_a=790, points_b=100)
    room.round = 9
    room.match_started_at = time.time() - 1000
    room.state = 'game_over'
    server._finalize_match(room, _pid_of(room, ua), _pid_of(room, ub))

    won = _only(_recv_wait(ca, 'rank_changed'), 'rank_changed(胜者)')
    segs = won['segments']
    assert len(segs) == 2, f'790 → 810 要跨一个小级: {segs}'
    assert segs[0]['sub_up'] is True and segs[1]['sub_up'] is False
    assert segs[0]['from'] == 90 and segs[1]['to'] == won['delta'] - 10
    # 全员一致：`segments` 与 `ranks.segments` 是同一个函数的结果（不许在 server 里再算一份）
    assert segs == ranks.segments(790, 790 + won['delta'])


def test_payload_keeps_every_old_field(env):
    """★ 追加不许删/改名：既有的 14 个键一个都不能少。"""
    old_keys = ('role', 'delta', 'clamped', 'points_before', 'points_after',
                'before', 'after', 'promoted', 'demoted', 'tier_up', 'tier_down',
                'admiral_promoted', 'admiral_demoted', 'admiral_reason')
    room, ca, cb, ua, ub = env(points_a=100, points_b=100)
    room.state = 'game_over'
    server._finalize_match(room, _pid_of(room, ua), _pid_of(room, ub))
    payload = _only(_recv_wait(ca, 'rank_changed'), 'rank_changed')
    for key in old_keys:
        assert key in payload, f'rank_changed 少了既有字段 {key}'
    for key in ('base', 'bonuses', 'breakdown_total', 'segments'):
        assert key in payload, f'rank_changed 少了新字段 {key}'


def test_clamped_delta_differs_from_breakdown_total(env):
    """★ 0 分封底时 `delta`（实际）与 `breakdown_total`（理论）**必须分开**。"""
    room, ca, cb, ua, ub = env(points_a=100, points_b=3)
    room.round = 9                                  # 排掉闪电战
    room.match_started_at = time.time() - 1000      # 排掉速败减免
    room.state = 'game_over'
    server._finalize_match(room, _pid_of(room, ua), _pid_of(room, ub))

    lost = _only(_recv_wait(cb, 'rank_changed'), 'rank_changed(败者)')
    assert lost['clamped'] is True
    assert lost['points_after'] == 0
    assert lost['delta'] == -3, '实际只掉了 3 分（封底）'
    assert lost['breakdown_total'] == _LOSE_BASE, '理论值仍是 −15'
    assert lost['delta'] != lost['breakdown_total']


# ===========================================================================
# 8. 门禁回归（多因子不许把既有门禁改坏）
# ===========================================================================
def test_streak_break_is_the_winners_own_losing_streak(env):
    """★「终止连败」看的是**胜者自己**之前连败了几场，不是败者的连败数。

    这条守的是一个**语义写反**的真 bug：第一版把 `loss_streak_broken` 直接等于
    **败者**赛前的连败数，于是

      · 打赢一个正在连败的人 → 胜者白拿「终止连败」；
      · 真正"自己止住连败"的那个人 → 一分没有。

    两个方向都错，而且**不报错**（恒等式照样成立）。实测是拿真实 socket 连打三局
    抓到的：B 连败两场后赢下第三局，明细里没有 `streak_break`。
    """
    room, ca, cb, ua, ub = env(points_a=100, points_b=100)
    # 造出"**败者**（乙 ub… 等下是败者）"不对 —— 这里要造的是**胜者甲**自己连败两场。
    # 直接把两场"甲输给丙"写进 matches（只影响连败统计；points 不受影响）。
    third = _mk_user()
    now = int(time.time())
    with db.db._lock:
        for i in range(2):
            db.db.conn.execute(
                'INSERT INTO matches (id, winner_id, loser_id, timestamp) VALUES (?,?,?,?)',
                (f'rp-streakbreak-{ua[:8]}-{i}', third, ua, now - 10 + i))
        db.db.conn.commit()

    seen = {}
    real = server._streak_context

    def spy(winner, winner_user_id, loser, loser_user_id):
        ctx = real(winner, winner_user_id, loser, loser_user_id)
        seen.update(ctx)
        return ctx

    server._streak_context = spy
    try:
        room.round = 9                                  # 排掉闪电战，只看连败这一项
        room.match_started_at = time.time() - 1000      # 排掉速败减免
        room.state = 'game_over'
        server._finalize_match(room, _pid_of(room, ua), _pid_of(room, ub))
    finally:
        server._streak_context = real

    assert seen.get('winner_loss_streak_before') == 2, \
        f"胜者赛前连败数应当是 2（它自己连败两场），实际 {seen}"
    assert seen.get('lose_streak_before') == 0, \
        f"败者赛前没连败过，实际 {seen}"

    won = _only(_recv_wait(ca, 'rank_changed'), 'rank_changed(胜者)')
    keys = [b['key'] for b in won['bonuses']]
    assert 'streak_break' in keys, f'胜者自己终结了 2 连败，明细里该有 streak_break: {keys}'
    brk = [b for b in won['bonuses'] if b['key'] == 'streak_break'][0]
    assert brk['value'] == 8, f'终结 2 连败应当是 +8，实际 {brk}'
    # 败者一侧：它自己没连败过 → 没有连败保护，也没有"终结连败"这种东西
    lost = _only(_recv_wait(cb, 'rank_changed'), 'rank_changed(败者)')
    assert [b['key'] for b in lost['bonuses']] == [], \
        f'败者这边不该有任何加成，实际 {lost["bonuses"]}'


def test_beating_a_losing_player_gives_the_winner_no_streak_break(env):
    """★ 反向守卫：**打赢一个正在连败的人**不会让胜者拿到「终止连败」。"""
    room, ca, cb, ua, ub = env(points_a=100, points_b=100)
    third = _mk_user()
    now = int(time.time())
    with db.db._lock:
        for i in range(3):
            db.db.conn.execute(
                'INSERT INTO matches (id, winner_id, loser_id, timestamp) VALUES (?,?,?,?)',
                (f'rp-opploss-{ub[:8]}-{i}', third, ub, now - 10 + i))
        db.db.conn.commit()

    room.round = 9
    room.match_started_at = time.time() - 1000
    room.state = 'game_over'
    server._finalize_match(room, _pid_of(room, ua), _pid_of(room, ub))

    won = _only(_recv_wait(ca, 'rank_changed'), 'rank_changed(胜者)')
    keys = [b['key'] for b in won['bonuses']]
    assert 'streak_break' not in keys, \
        f'胜者自己没有连败过，不该有终止连败（对手连败与胜者无关）: {keys}'
    assert won['breakdown_total'] == _WIN_BASE, f'这一局应当只有基础分，实际 {won}'


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


def test_settlement_is_still_single_call_site():
    """结算仍然只有一个调用点（本批只是给它多加了一个参数）。

    ⚠️ 正则写法与 `tests/test_ranked_match.py::test_rank_settlement_has_a_single_call_site`
       逐字一致（否定后顾排除 `def `）—— 这两个文件里有**我自己写的说明文字**
       提到了这个函数名，`str.count` 会把说明也算进去（既有文件里那条同源注释
       早就警告过这件事）。
    """
    src = open('server.py', encoding='utf-8').read()
    assert src.count('def _settle_ranked_match(') == 1
    calls = re.findall(r'(?<!def )_settle_ranked_match\(room,', src)
    assert len(calls) == 1, f'_settle_ranked_match 只允许在 _finalize_match 里调用一次，实际 {len(calls)}'
    assert len(re.findall(r'(?<!def )_streak_context\(', src)) == 1, \
        '`_streak_context` 只允许有一处调用（就是 `_finalize_match` 开头那段）'
    assert src.count('_finalize_match(room, winner_id, loser_id, streak_ctx)') == 0, \
        'streak_ctx 是内部变量，不该在调用点里手写'


def _recv_wait(client, name):
    """等后台任务把 `rank_changed` 补发过来再取（与既有夹具同一套写法）。"""
    return _pick(_drain_all(client), name)
