# -*- coding: utf-8 -*-
r"""第 2 批 A 票：每局结算收口（`_finalize_match`）+ `user_counters` / `user_achievements`。

对应 `docs/BATCH_2_3_4_PLAN.md` §2.1 / §2.2 / §2.2.1。

覆盖四块：
  1. `user_counters` 的 DAO：默认值（不写库）、累加、`fastest_win_sec` 取最小非零、
     脏数据兜底、库异常不抛；
  2. `user_achievements` 的 DAO：只返回新增、重复授予幂等、首解时间不被刷新；
  3. `_finalize_match`：一次调用把「写战绩 + 累加统计 + 解锁徽章」三件事都做掉，
     以及人机 / 游客 / 玩家不在房间 / 库故障四种边界；
  4. 结构性断言：6 处结算调用点全部走收口，`server.py` 里只剩**一处**真正写库的调用。

⚠️ 跑测试必须重定向临时目录（本机 `%LOCALAPPDATA%\Temp\pytest-of-Administrator`
的 ACL 坏了，不重定向会有一批用例在 setup 阶段假红）：
    New-Item -ItemType Directory -Force .tmp\pytemp | Out-Null
    $env:TMP="$PWD\.tmp\pytemp"; $env:TEMP=$env:TMP; python -m pytest tests/ -q -p no:cacheprovider
"""
import os
import pathlib
import random
import re
import time
import uuid

import pytest

import achievements
import db as db_module
import server
from server import GameRoom, Player, PlayerShip, Position

REPO = pathlib.Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 夹具与助手
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _silence_emit(monkeypatch):
    """结算路径会 emit 播报；没有 socket 上下文时不该让它影响断言。"""
    monkeypatch.setattr(server, 'emit', lambda *a, **k: None)


@pytest.fixture
def make_user():
    """在（conftest 已隔离的）全局测试库上建账号，返回 (uid, username)。"""
    def _make(username=None):
        name = username or ('ach' + uuid.uuid4().hex[:10])
        uid = db_module.create_user(name, 'x')
        assert uid, '建号失败（用户名冲突？）'
        return uid, name

    return _make


def _ship(positions=((0, 0),), hits=(), sunk=False):
    """造一艘船；`sunk=True` 表示"每个格子都被打中"（= 已沉，未登记进沉船堆）。"""
    pos = [Position(x, y) for x, y in positions]
    if sunk:
        hit = [Position(x, y) for x, y in positions]
    else:
        hit = [Position(x, y) for x, y in hits]
    return PlayerShip(positions=pos, hits=hit)


def _player(uid, ships=None, sunken=None, name='p'):
    p = Player(name=name, ships=list(ships or []), attacks=[], remaining_ships=6,
               sid='sid-' + str(uid), user_id=uid)
    p.sunken_ships = list(sunken or [])
    return p


def _room(winner_player, loser_player, ai_room=False, started_ago=None, logs=None):
    """最小可用的房间桩。

    `started_ago` 给秒数时同时写 `match_started_at`（模拟"猜拳后真正开局"），
    不给就两个时间字段都不留 —— 用来验证「拿不到用时给 0，不编」。
    """
    room = GameRoom('ach-room-' + uuid.uuid4().hex[:6])
    room.is_ai_room = ai_room
    room.players = {'W': winner_player, 'L': loser_player}
    room.state = 'attacking'
    room.game_logs = logs if logs is not None else []
    if started_ago is not None:
        room.match_started_at = time.time() - started_ago
    return room


def _capture_record_match(monkeypatch):
    """把写库拦下来（与既有 `test_stats_display_fixes.py` 同一套做法）。"""
    calls = []
    monkeypatch.setattr(server.db, 'record_match',
                        lambda *a, **k: calls.append((a, k)) or True)
    return calls


def _counter_row(uid):
    """直接读库（绕过 DAO 的默认值），用于断言"到底写没写"。"""
    con = db_module.db
    with con._lock:
        row = con.cursor.execute(
            'SELECT sunk_total, matches_played, flawless_wins, fastest_win_sec '
            'FROM user_counters WHERE user_id = ?', (uid,)).fetchone()
    return dict(row) if row else None


# ===========================================================================
# 1. user_counters 的 DAO
# ===========================================================================
def test_counters_defaults_are_zero_and_nothing_is_written(make_user):
    """没记录时返回全 0，且**不写库**（与 get_user_profile_extra 同一风格）。"""
    uid, _ = make_user()
    data = db_module.get_user_counters(uid)
    assert data['sunk_total'] == 0
    assert data['matches_played'] == 0
    assert data['flawless_wins'] == 0
    assert data['fastest_win_sec'] == 0
    assert data['updated_at'] == 0
    assert _counter_row(uid) is None, '只读不该建行'


def test_counters_defaults_for_empty_uid():
    data = db_module.get_user_counters('')
    assert data['sunk_total'] == 0 and data['updated_at'] == 0


def test_bump_accumulates(make_user):
    uid, _ = make_user()
    assert db_module.bump_user_counters(uid, sunk_total=3, matches_played=1,
                                        flawless_wins=1, fastest_win_sec=300) is True
    assert db_module.bump_user_counters(uid, sunk_total=2, matches_played=1) is True

    data = db_module.get_user_counters(uid)
    assert data['sunk_total'] == 5
    assert data['matches_played'] == 2
    assert data['flawless_wins'] == 1
    assert data['fastest_win_sec'] == 300


def test_bump_fastest_win_takes_min_nonzero(make_user):
    """`fastest_win_sec` 是"取最小非零"，0 表示"本次没有"、不许覆盖已有值。"""
    uid, _ = make_user()
    db_module.bump_user_counters(uid, fastest_win_sec=300)
    assert db_module.get_user_counters(uid)['fastest_win_sec'] == 300

    db_module.bump_user_counters(uid, fastest_win_sec=200)      # 更快 → 更新
    assert db_module.get_user_counters(uid)['fastest_win_sec'] == 200

    db_module.bump_user_counters(uid, fastest_win_sec=250)      # 更慢 → 不动
    assert db_module.get_user_counters(uid)['fastest_win_sec'] == 200

    db_module.bump_user_counters(uid, fastest_win_sec=0)        # 没有用时 → 不动
    assert db_module.get_user_counters(uid)['fastest_win_sec'] == 200


def test_bump_fastest_win_from_zero_row_gets_first_real_value(make_user):
    """先只累加场次（此时 fastest 落成 0），后面第一次真实用时必须能写进去。

    如果实现写成 `min(existing, candidate)`，0 会永远压死后面的真实值，
    「闪电战」就再也解不开了 —— 这条就是钉死那个坑。
    """
    uid, _ = make_user()
    db_module.bump_user_counters(uid, matches_played=1)
    assert db_module.get_user_counters(uid)['fastest_win_sec'] == 0
    db_module.bump_user_counters(uid, fastest_win_sec=120)
    assert db_module.get_user_counters(uid)['fastest_win_sec'] == 120


def test_bump_ignores_negative_garbage_and_unknown_keys(make_user):
    uid, _ = make_user()
    assert db_module.bump_user_counters(uid, sunk_total=-5) is True
    assert db_module.bump_user_counters(uid, matches_played='abc') is True
    assert db_module.bump_user_counters(uid, not_a_column=7) is True
    data = db_module.get_user_counters(uid)
    assert data['sunk_total'] == 0, '负数不许倒扣进度'
    assert data['matches_played'] == 0


def test_bump_with_no_usable_delta_is_noop_success(make_user):
    uid, _ = make_user()
    assert db_module.bump_user_counters(uid, matches_played=0) is True
    assert _counter_row(uid) is None, '没有可加的东西就不该建行'


def test_bump_empty_uid_returns_false():
    assert db_module.bump_user_counters('', sunk_total=1) is False


def test_bump_survives_db_error(make_user, monkeypatch):
    """库故障只记日志、返回 False，绝不抛（统计不许把结算搞崩）。"""
    uid, _ = make_user()

    class Boom:
        def execute(self, *a, **k):
            raise RuntimeError('库炸了')

    monkeypatch.setattr(db_module.db, 'cursor', Boom())
    assert db_module.bump_user_counters(uid, sunk_total=1) is False


def test_get_counters_survives_db_error(make_user, monkeypatch):
    uid, _ = make_user()

    class Boom:
        def execute(self, *a, **k):
            raise RuntimeError('库炸了')

    monkeypatch.setattr(db_module.db, 'cursor', Boom())
    data = db_module.get_user_counters(uid)
    assert data['sunk_total'] == 0, '读失败要返回安全默认值'


# ===========================================================================
# 2. user_achievements 的 DAO
# ===========================================================================
def test_grant_returns_only_newly_granted(make_user):
    uid, _ = make_user()
    first = db_module.grant_user_achievements(uid, ['first_win', 'streak5'])
    assert sorted(first) == ['first_win', 'streak5']

    second = db_module.grant_user_achievements(uid, ['streak5', 'sunk50'])
    assert second == ['sunk50'], '已解锁的不该再报一次（播报会重复念）'

    assert db_module.grant_user_achievements(uid, ['sunk50']) == []


def test_grant_is_idempotent_and_keeps_first_time(make_user):
    """重复授予不重复插入，也**不刷新首解时间**（解锁是只进不退）。"""
    uid, _ = make_user()
    db_module.grant_user_achievements(uid, ['first_win'])
    first_at = db_module.get_user_achievements(uid)['first_win']

    con = db_module.db
    with con._lock:      # 把时间往回拨，验证第二次授予不会把它拉回来
        con.cursor.execute('UPDATE user_achievements SET unlocked_at = ? '
                           'WHERE user_id = ? AND badge_id = ?', (first_at - 1000, uid, 'first_win'))
        con.conn.commit()
    moved = db_module.get_user_achievements(uid)['first_win']

    assert db_module.grant_user_achievements(uid, ['first_win']) == []
    assert db_module.get_user_achievements(uid)['first_win'] == moved


def test_grant_dedupes_input_and_skips_empty(make_user):
    uid, _ = make_user()
    got = db_module.grant_user_achievements(uid, ['first_win', 'first_win', '', None, '  '])
    assert got == ['first_win']


def test_grant_from_empty_uid_or_bad_input(make_user):
    assert db_module.grant_user_achievements('', ['first_win']) == []
    uid, _ = make_user()
    assert db_module.grant_user_achievements(uid, 12345) == [], '不可迭代的输入不该抛'


def test_get_achievements_empty_uid_and_unknown_user():
    assert db_module.get_user_achievements('') == {}
    assert db_module.get_user_achievements('nobody-' + uuid.uuid4().hex[:8]) == {}


def test_grant_survives_db_error(make_user, monkeypatch):
    uid, _ = make_user()

    class Boom:
        def execute(self, *a, **k):
            raise RuntimeError('库炸了')

    monkeypatch.setattr(db_module.db, 'cursor', Boom())
    assert db_module.grant_user_achievements(uid, ['first_win']) == []


def test_get_distinct_cards_used_counts_distinct(make_user):
    uid, _ = make_user()
    db_module.record_user_card_use(uid, '失灵！', 5)
    db_module.record_user_card_use(uid, '神威！', 3)
    db_module.record_user_card_use(uid, '失灵！', 2)     # 同一张，重复使用
    assert db_module.get_distinct_cards_used(uid) == 2
    assert db_module.get_distinct_cards_used('') == 0
    assert db_module.get_distinct_cards_used('nobody-' + uuid.uuid4().hex[:8]) == 0


# ===========================================================================
# 3. 击沉口径（活船 / 沉船互补）
# ===========================================================================
def test_dead_ship_count_pairs_with_alive_ships():
    """`_dead_ship_count` 与 `_alive_ships` 是同一口径的两面，加起来才是全部船。

    这也是"不许写 len(player.ships)"的证明：6 艘船沉了 2 艘，
    `len(ships)` 永远是 6，只有这两个函数才分得清活/死。
    """
    ships = [_ship(positions=[(x, 0)]) for x in range(6)]
    ships[0].hits = [Position(0, 0)]
    ships[1].hits = [Position(1, 0)]
    p = _player('u', ships=ships, sunken=[ships[0], ships[1]])

    assert len(p.ships) == 6, 'ships 列表长度根本反映不出沉了几艘'
    assert len(server._alive_ships(p)) == 4
    assert server._dead_ship_count(p) == 2
    assert server._dead_ship_count(p) + len(server._alive_ships(p)) == 6


def test_dead_ship_count_covers_ships_removed_from_list():
    """被轰炸/牺牲移出 `ships` 的船只剩在沉船堆里，也要算进击沉数。"""
    gone = _ship(positions=[(0, 0)])
    gone.hits = [Position(0, 0)]
    p = _player('u', ships=[_ship(positions=[(1, 0)])], sunken=[gone])
    assert server._dead_ship_count(p) == 1


def test_dead_ship_count_does_not_count_revived_ship():
    """复活过的船：沉船堆里被 pop 掉、hits 也清空了 → 两边都不算它。"""
    revived = _ship(positions=[(0, 0)])          # hits 为空 = 活着
    p = _player('u', ships=[revived], sunken=[])
    assert server._dead_ship_count(p) == 0
    assert len(server._alive_ships(p)) == 1


def test_took_any_damage_only_counts_real_hits():
    """被盾挡下的一炮不进 `hits`（2026-09-14 的口径）→ 不算受伤。"""
    clean = _player('u', ships=[_ship(hits=[])])
    assert server._took_any_damage(clean) is False

    scratched = _player('u', ships=[_ship(positions=[(0, 0), (0, 1)], hits=[(0, 0)])])
    assert server._took_any_damage(scratched) is True


# ===========================================================================
# 4. _finalize_match：三件事一次做掉
# ===========================================================================
def test_finalize_match_writes_record_counters_and_badges(make_user):
    """核心用例：一次调用后战绩、计数、徽章三件事都发生。"""
    winner_uid, _ = make_user()
    loser_uid, _ = make_user()

    winner = _player(winner_uid, ships=[_ship(hits=[])], name='win')
    # 输家沉了 3 艘（2 艘还在 ships 里、1 艘被移出列表只剩登记表）
    alive_loser = _ship(positions=[(3, 0)])
    sunk_a = _ship(positions=[(0, 0)]); sunk_a.hits = [Position(0, 0)]
    sunk_b = _ship(positions=[(1, 0)]); sunk_b.hits = [Position(1, 0)]
    removed = _ship(positions=[(2, 0)]); removed.hits = [Position(2, 0)]
    loser = _player(loser_uid, ships=[alive_loser, sunk_a, sunk_b],
                    sunken=[sunk_a, sunk_b, removed], name='lose')

    room = _room(winner, loser, started_ago=90)
    newly = server._finalize_match(room, 'W', 'L')

    # ① 战绩：真人对局 → record_match 计数（走真实库，赢得 1 场）
    assert db_module.get_user(uid=winner_uid)['wins'] == 1
    assert db_module.get_user(uid=loser_uid)['losses'] == 1

    # ② 每局统计
    w = db_module.get_user_counters(winner_uid)
    l = db_module.get_user_counters(loser_uid)
    assert w['sunk_total'] == 3, '击沉数 = 对方的沉船数（含被移出列表的那艘）'
    assert w['matches_played'] == 1 and l['matches_played'] == 1
    assert w['flawless_wins'] == 1, '赢家全场没被打中过'
    assert 0 < w['fastest_win_sec'] <= 90
    assert l['sunk_total'] == 0 and l['flawless_wins'] == 0, '输家不该拿完美/用时'
    assert l['fastest_win_sec'] == 0

    # ③ 徽章：首胜（wins=1）+ 零伤获胜 + 闪电战（90 秒 ≤ 180）
    granted = dict(newly)
    assert winner_uid in granted
    assert set(granted[winner_uid]) >= {'first_win', 'flawless', 'speedrun'}
    stored = db_module.get_user_achievements(winner_uid)
    for badge_id in ('first_win', 'flawless', 'speedrun'):
        assert badge_id in stored, f'{badge_id} 应已写入 user_achievements'
    assert 'first_win' not in db_module.get_user_achievements(loser_uid), '输家解不出首胜'


def test_finalize_match_returns_only_new_badges_on_repeat(make_user):
    """重复结算时，**已经解锁过的徽章不该被再报一遍**（播报不会念重复的名字）。

    ⚠️ 不能写成"第二次必须返回空列表"：第二次结算会真的再写一场战绩，
    于是 `rank1`（当前排行榜第 1）这类**依赖当前状态**的徽章可能就在这时才达标 ——
    那是正确行为。所以断言的是"第一次拿到的那几枚不再出现"，
    这样与库里其它测试留下的排名状态无关（写死成空列表会变成顺序相关的假红）。
    """
    winner_uid, _ = make_user()
    loser_uid, _ = make_user()
    winner = _player(winner_uid, ships=[_ship(hits=[])])
    loser = _player(loser_uid, ships=[_ship()], sunken=[_ship(positions=[(0, 0)])])

    first = dict(server._finalize_match(_room(winner, loser), 'W', 'L'))
    assert first.get(winner_uid), '第一次应解锁首胜'
    first_ids = set(first[winner_uid])
    assert 'first_win' in first_ids

    second = dict(server._finalize_match(_room(winner, loser), 'W', 'L'))
    repeated = first_ids & set(second.get(winner_uid, []))
    assert repeated == set(), f'已解锁的徽章被重复播报：{repeated}'
    assert 'first_win' not in set(second.get(winner_uid, []))


def test_finalize_match_ai_room_writes_history_but_no_stats(make_user, monkeypatch):
    """人机对局：写历史（count_stats=False），但不累计计数、不发徽章。"""
    calls = _capture_record_match(monkeypatch)
    winner_uid, _ = make_user()
    winner = _player(winner_uid, ships=[_ship(hits=[])])
    ai = _player(None, ships=[_ship()], sunken=[_ship(positions=[(0, 0)])], name='AI')

    room = _room(winner, ai, ai_room=True, started_ago=30)
    newly = server._finalize_match(room, 'W', 'L')

    assert len(calls) == 1
    assert calls[0][1].get('count_stats') is False, '人机不计战绩'
    assert newly == [], '打电脑刷不出徽章'
    assert _counter_row(winner_uid) is None, '人机不该累加计数'


def test_finalize_match_ai_room_does_not_touch_counters(make_user, monkeypatch):
    """上面那条的 db 层版本（不碰真库写入，直接看计数器）。"""
    _capture_record_match(monkeypatch)
    uid, _ = make_user()
    winner = _player(uid, ships=[_ship(hits=[])])
    ai = _player(None, ships=[], name='AI')
    room = _room(winner, ai, ai_room=True)

    server._finalize_match(room, 'W', 'L')

    assert _counter_row(uid) is None
    assert db_module.get_user_achievements(uid) == {}


def test_finalize_match_guests_only_writes_nothing(monkeypatch):
    """双方都是游客：不写战绩、不累计（与改动前「至少一个登录用户才记录」一致）。"""
    calls = _capture_record_match(monkeypatch)
    room = _room(_player(None, ships=[]), _player(None, ships=[]))
    assert server._finalize_match(room, 'W', 'L') == []
    assert calls == [], '没有登录用户时不该写 matches'


def test_finalize_match_missing_player_is_noop(monkeypatch):
    """玩家不在房间里 → 整段不做（沿用原来 try 包住一切的行为）。"""
    calls = _capture_record_match(monkeypatch)
    room = GameRoom('ach-broken')
    room.players = {}
    assert server._finalize_match(room, 'W', 'L') == []
    assert calls == []


def test_finalize_match_without_start_time_records_zero_duration(make_user, monkeypatch):
    """拿不到开局时间 → 用时记 0（= "没有可信用时"），不能编成"0 秒获胜"。

    否则第一次写入的 0 会让「闪电战」（`0 < fastest_win_sec <= 180`）永远判不出来。
    """
    _capture_record_match(monkeypatch)
    uid, _ = make_user()
    room = _room(_player(uid, ships=[_ship()]), _player(None, ships=[]))
    room.__dict__.pop('created_at', None)
    assert server._match_started_at(room) == 0
    assert server._match_duration_sec(room) == 0

    db_module.bump_user_counters(uid, fastest_win_sec=server._match_duration_sec(room))
    assert db_module.get_user_counters(uid)['fastest_win_sec'] == 0
    assert 'speedrun' not in achievements.evaluate(
        {'fastest_win_sec': db_module.get_user_counters(uid)['fastest_win_sec']})


def test_finalize_match_does_not_raise_when_db_write_fails(make_user, monkeypatch):
    """统计写失败不许影响结算（收口内部必须吞掉异常）。"""
    _capture_record_match(monkeypatch)
    uid, _ = make_user()
    room = _room(_player(uid, ships=[_ship()]), _player(None, ships=[]))

    def boom(*a, **k):
        raise RuntimeError('计数器炸了')

    monkeypatch.setattr(server.db, 'bump_user_counters', boom)
    assert server._finalize_match(room, 'W', 'L') == []      # 不该抛


def test_finalize_match_survives_achievement_evaluation_failure(make_user, monkeypatch):
    _capture_record_match(monkeypatch)
    uid, _ = make_user()
    room = _room(_player(uid, ships=[_ship()]), _player(None, ships=[]))
    monkeypatch.setattr(server.achievements, 'evaluate',
                        lambda stats: (_ for _ in ()).throw(RuntimeError('判据炸了')))
    assert server._finalize_match(room, 'W', 'L') == []


def test_finalize_match_speedrun_needs_real_duration(make_user, monkeypatch):
    """4 分钟的一局不该解锁闪电战（边界：> 180 秒）。"""
    _capture_record_match(monkeypatch)
    uid, _ = make_user()
    room = _room(_player(uid, ships=[_ship()]), _player(None, ships=[_ship()]),
                 started_ago=240)
    server._finalize_match(room, 'W', 'L')
    counters = db_module.get_user_counters(uid)
    assert counters['fastest_win_sec'] >= 180
    assert 'speedrun' not in db_module.get_user_achievements(uid)


def test_finalize_match_ignores_loser_for_fastest_time(make_user, monkeypatch):
    """输家不该产生"最快获胜用时"候选值。"""
    _capture_record_match(monkeypatch)
    winner_uid, _ = make_user()
    loser_uid, _ = make_user()
    room = _room(_player(winner_uid, ships=[_ship()]), _player(loser_uid, ships=[_ship()]),
                 started_ago=45)
    server._finalize_match(room, 'W', 'L')
    assert db_module.get_user_counters(winner_uid)['fastest_win_sec'] > 0
    assert db_module.get_user_counters(loser_uid)['fastest_win_sec'] == 0


def test_achievement_stats_shape_matches_module_contract(make_user):
    """`_achievement_stats` 必须给全 `achievements.CONTEXT_KEYS` 的输入。

    少一个键 → `achievement_context` 把它按 0 → 徽章静默不解锁且不报错，
    所以这里直接对着模块声明的键集合比对。
    """
    uid, _ = make_user()
    stats = server._achievement_stats(uid)
    missing = [k for k in achievements.CONTEXT_KEYS if k not in stats]
    assert missing == [], f'stats 缺字段会让对应判据永远为假: {missing}'


# ===========================================================================
# 5. 结构性断言：收口是否真的收住了
# ===========================================================================
def _read(rel):
    return (REPO / rel).read_text(encoding='utf-8')


def test_only_one_real_record_match_call_and_it_is_in_finalize_match():
    """选了「grep 级断言」：`server.py` 里真正写库的调用**只能有一处**。

    它同时满足既有守卫 `test_every_record_match_call_site_passes_count_stats`
    （那一条要求每一处调用都带 `count_stats=`）—— 注意它扫的是**全文含注释**，
    所以注释里也不能出现带括号的调用形式。
    """
    source = _read('server.py')
    calls = re.findall(r'db\.record_match\((?:[^()]|\([^()]*\))*\)', source)
    assert len(calls) == 1, (
        '对局结算必须只有一处写库调用（收口失效了）：'
        + repr([c[:60] for c in calls]))
    assert 'count_stats=' in calls[0], '这一处必须显式传 count_stats'

    # 它必须落在 _finalize_match 的函数体里
    body_start = source.index('def _finalize_match(')
    body_end = source.index('\ndef ', body_start + 1)
    assert source.index(calls[0]) > body_start and source.index(calls[0]) < body_end, \
        '唯一那处写库调用必须在 _finalize_match 里'


def test_six_settlement_call_sites_go_through_finalize_match():
    """6 处对局结束全部改调 `_finalize_match`（计划 §2.1）。

    如果你**有意**新增了第 7 条结算路径，把这里的数字一起改掉 —— 这个断言存在的
    意义就是"新增结算路径时必须想起来统计与徽章也要跟上"。
    """
    source = _read('server.py')
    # `(?<!def )` 排除函数定义本身（`def _finalize_match(room, ...)` 也是这个形状）
    calls = re.findall(r'(?<!def )_finalize_match\(room,\s*([^)]*)\)', source)
    assert len(calls) == 6, f'结算收口调用点数量变了（现在 {len(calls)} 处）：{calls}'
    args = {a.strip() for a in calls}
    assert args == {'attacker_id, defender_id', 'winner_id, loser_id',
                    'other, player_id', 'caster_id, opponent_id',
                    'opponent_id, player_id'}, f'调用点的实参看着不对：{args}'


def test_finalize_match_is_defined_once():
    source = _read('server.py')
    assert source.count('def _finalize_match(') == 1
    assert source.count('def _bump_match_counters(') == 1
    assert source.count('def _grant_match_achievements(') == 1
    assert source.count('def _dead_ship_count(') == 1
    assert source.count('def _achievement_stats(') == 1


def test_match_started_at_set_once_in_rps_path():
    """开局打点：猜拳结束进入 attacking 时记一次，且只在不存在的写。"""
    source = _read('server.py')
    assert 'room.match_started_at = time.time()' in source
    assert "if not getattr(room, 'match_started_at', None):" in source


# ===========================================================================
# 6. 建表 / 老库兼容
# ===========================================================================
def test_new_tables_exist_with_frozen_columns():
    con = db_module.db
    with con._lock:
        cols = {r[1] for r in con.cursor.execute('PRAGMA table_info(user_counters)')}
        ach = {r[1] for r in con.cursor.execute('PRAGMA table_info(user_achievements)')}
    assert cols == {'user_id', 'sunk_total', 'matches_played', 'flawless_wins',
                    'fastest_win_sec', 'updated_at'}, f'user_counters 列不符：{cols}'
    assert ach == {'user_id', 'badge_id', 'unlocked_at'}, f'user_achievements 列不符：{ach}'


def test_init_db_is_repeatable_on_existing_db(make_user):
    """老库兼容：没有 ALTER 迁移机制，建表必须靠 IF NOT EXISTS 反复执行不报错。"""
    uid, _ = make_user()
    db_module.bump_user_counters(uid, sunk_total=7, matches_played=2)
    db_module.grant_user_achievements(uid, ['first_win'])

    before = db_module.get_user_counters(uid)
    db_module.db.init_db()          # 再跑一次（模拟服务重启）
    db_module.db.init_db()

    assert db_module.get_user_counters(uid) == before, '重跑 init_db 不该动数据'
    assert 'first_win' in db_module.get_user_achievements(uid)


def test_users_table_columns_untouched():
    """本批只加新表：`users` 的列一个都不许动（没有迁移机制）。"""
    con = db_module.db
    with con._lock:
        cols = {r[1] for r in con.cursor.execute('PRAGMA table_info(users)')}
    assert cols == {'id', 'username', 'password_hash', 'wins', 'losses',
                    'current_streak', 'longest_streak', 'created_at',
                    'signature', 'avatar', 'token'}, f'users 列被改了：{cols}'
