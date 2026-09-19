# -*- coding: utf-8 -*-
r"""段位系统（段位批 A 票）回归测试：`ranks.py` 段位数学 + `db.py` 段位存取 + 名片开关。

分四块：
  1. `ranks.py` 的段位表 / 分数换算 / 视图文案（纯函数，不碰库）
  2. 大舰长晋升的三个条件（含"船长池不足 50 人不产生大舰长"这条护栏）
  3. `db.user_rank` 的读写：0 分封底、加减分、榜序、名次、船长池
  4. `profile_spec` 的 10 字段契约（多了 `show_rank`）与段位解锁的外观

⚠️ 跑测试必须重定向临时目录（本机 `%LOCALAPPDATA%\Temp\pytest-of-Administrator`
的 ACL 坏了，不重定向会有一批用例在 setup 阶段假红）：
    $env:TMP="$PWD\.tmp\pytemp"; $env:TEMP=$env:TMP; python -m pytest tests/ -q
"""
import json
import re
import uuid

import pytest

import api
import db as db_module
import profile_spec
import ranks


# ---------------------------------------------------------------------------
# 助手
# ---------------------------------------------------------------------------
def _uid():
    """建一个真账号（`user_rank` 只按 user_id 关联，但建号能让 join 类断言也能用）。"""
    username = 'rk' + uuid.uuid4().hex[:10]
    uid = db_module.create_user(username, 'x')
    assert uid, '建号失败'
    return uid, username


# ===========================================================================
# 1. 段位表与分数换算
# ===========================================================================
def test_tier_table_frozen():
    """段位表是契约：9 个段位、顺序、名字都不能改（前端图标按 id 取）。"""
    assert [t['name'] for t in ranks.TIERS] == [
        '二级水手', '一级水手', '水手长', '三副', '二副', '大副', '轮机长', '船长', '大舰长']
    assert [t['id'] for t in ranks.TIERS] == [
        'sailor2', 'sailor1', 'bosun', 'mate3', 'mate2', 'mate1', 'engineer',
        'captain', 'admiral']
    # index 必须严格递增 —— 段位高低全靠它
    assert [t['index'] for t in ranks.TIERS] == list(range(9))
    assert ranks.SUBS == ('Ⅰ', 'Ⅱ', 'Ⅲ')
    assert ranks.SUB_POINTS == 100
    assert ranks.CAPTAIN_FLOOR == 2100
    assert ranks.TOP_POINTS == 2400


@pytest.mark.parametrize('points,tier_name,sub,progress', [
    (0, '二级水手', 'Ⅰ', 0),
    (99, '二级水手', 'Ⅰ', 99),
    (100, '二级水手', 'Ⅱ', 0),
    (200, '二级水手', 'Ⅲ', 0),
    (300, '一级水手', 'Ⅰ', 0),
    (600, '水手长', 'Ⅰ', 0),
    (690, '水手长', 'Ⅰ', 90),
    (700, '水手长', 'Ⅱ', 0),
    (790, '水手长', 'Ⅱ', 90),      # 作者原话里的那个例子
    (800, '水手长', 'Ⅲ', 0),
    (1200, '二副', 'Ⅰ', 0),
    (2100, '船长', 'Ⅰ', 0),
    (2300, '船长', 'Ⅲ', 0),
])
def test_points_to_rank(points, tier_name, sub, progress):
    """分数 → 段位/小段位/进度。

    ⚠️ 一个段位 = 3 个小段位 = 300 分（作者："每个小段位提升需要100排位积分"）：
    水手长Ⅰ = 600~699、水手长Ⅱ = 700~799、水手长Ⅲ = 800~899。
    所以「水手长Ⅱ 90分」是**全局 790 分**，不是 690 —— label 显示的是
    "本小段位内已攒了多少分"，这个 90 与全局分差着两个小段位。
    """
    v = ranks.rank_view(points)
    assert v['tier_name'] == tier_name
    assert v['sub'] == sub
    assert v['progress'] == progress
    assert v['is_admiral'] is False


def test_points_above_captain_saturate_not_wrap():
    """⚠️ 船长Ⅲ 之后只累分，**不许回绕**。

    第一版用 `% 3` 算小段位，于是 2700 分变成船长Ⅱ、3000 分变成船长Ⅰ
    （分越高段位越低）—— 这条用例就是钉死那个 bug 的。
    """
    for p in (2399, 2400, 2700, 3000, 9900):
        v = ranks.rank_view(p)
        assert v['tier_name'] == '船长', (p, v)
        assert v['sub'] == 'Ⅲ', (p, v)
        assert v['saturated'] is True, (p, v)
        assert v['to_next'] is None, (p, v)
    # 进度是"从船长Ⅲ 起点（2300）起累加"的单调量，不是 0~99 回绕
    assert ranks.rank_view(2300)['progress'] == 0
    assert ranks.rank_view(2400)['progress'] == 100
    assert ranks.rank_view(2700)['progress'] == 400
    assert ranks.rank_view(3000)['progress'] > ranks.rank_view(2700)['progress']


def test_captain_label_shows_sub_progress_and_server_rank():
    """船长及以上的文案 = 「船长Ⅲ 1000分 #60」——**同样是本小段位进度分**。

    ⚠️ 口径在 2026-09-18 由作者裁决统一：低段位一直显示"本小段位已攒的分"
    （水手长Ⅱ 90分），船长段**也照这条来**。第一版给船长段显示的是累计分，
    于是作者说「船长Ⅲ1200分」「船长Ⅲ1000分」时都对不上 —— 那两个数都小于
    船长Ⅲ 的起点 2300，"船长Ⅲ + 四位数"在累计口径下根本不成立。
    """
    # 2300 = 船长Ⅲ 起点 → 进度 0
    assert ranks.rank_view(2300, server_rank=60)['label'] == '船长Ⅲ 0分 #60'
    assert ranks.rank_view(2300)['label'] == '船长Ⅲ 0分'
    # 作者要的那个数：船长Ⅲ 小段位内 1000 分 = 累计 3300
    v = ranks.rank_view(3300, server_rank=12)
    assert v['label'] == '船长Ⅲ 1000分 #12', v
    assert v['points'] == 3300 and v['progress'] == 1000
    # 他最初举的例子：船长Ⅲ 1200分 = 累计 3500（现在也自洽了）
    assert ranks.rank_view(3500)['label'] == '船长Ⅲ 1200分'
    # 船长Ⅰ/Ⅱ 同理（也是进度分）
    assert ranks.rank_view(2119)['label'] == '船长Ⅰ 19分'
    assert ranks.rank_view(2400)['label'] == '船长Ⅲ 100分'
    # 船长以下仍是"进度分"，不带排名
    assert ranks.rank_view(790)['label'] == '水手长Ⅱ 90分'
    assert ranks.rank_view(790, server_rank=60)['label'] == '水手长Ⅱ 90分'
    # 累计分始终在 points 里（段位榜显示的就是它）
    assert ranks.rank_view(790)['points'] == 790


def test_admiral_label_has_no_points():
    """大舰长文案 = 「大舰长 #20」（作者明确：不带分数）。"""
    assert ranks.rank_view(3000, is_admiral=True, server_rank=20)['label'] == '大舰长 #20'
    assert ranks.rank_view(3000, is_admiral=True)['label'] == '大舰长'
    v = ranks.rank_view(3000, is_admiral=True)
    assert v['tier_index'] == 8 and v['sub'] == '' and v['is_admiral'] is True


def test_win_lose_delta_and_floor():
    """胜利 +20 / 失败 −15 / 0 分封底（封底时 `clamped=True` 告诉调用方"没真扣"）。"""
    assert ranks.WIN_POINTS == 20 and ranks.LOSE_POINTS == -15
    assert ranks.apply_delta(100, ranks.WIN_POINTS) == (120, False)
    assert ranks.apply_delta(100, ranks.LOSE_POINTS) == (85, False)
    assert ranks.apply_delta(10, ranks.LOSE_POINTS) == (0, True)
    assert ranks.apply_delta(0, ranks.LOSE_POINTS) == (0, True)
    assert ranks.apply_delta(0, ranks.WIN_POINTS) == (20, False)


def test_author_example_water_bosun_2_to_3():
    """作者原话：赢一局「水手长Ⅱ90分 → 水手长Ⅲ10分」。

    水手长Ⅱ = 700~799（进度 90 = 全局 790），+20 越界到水手长Ⅲ 的 10 分。
    """
    before = 790
    after, clamped = ranks.apply_delta(before, ranks.WIN_POINTS)
    assert (after, clamped) == (810, False)
    assert ranks.rank_view(before)['label'] == '水手长Ⅱ 90分'
    assert ranks.rank_view(after)['label'] == '水手长Ⅲ 10分'


def test_normalize_points_rejects_junk():
    """脏数据一律当 0，不抛（库里是 INTEGER，但接口/测试可能塞字符串）。"""
    assert ranks.normalize_points(None) == 0
    assert ranks.normalize_points('abc') == 0
    assert ranks.normalize_points(-50) == 0
    assert ranks.normalize_points('120') == 120
    assert ranks.normalize_points(True) == 1


def test_solve_delta_flags_promotion_and_demotion():
    """结算摘要：升/降小段位与升/降大段位要分开报（前端据此决定播什么动画）。"""
    up = ranks.solve_delta(85, 105)
    assert up['delta'] == 20 and up['promoted'] is True
    assert up['tier_up'] is False and up['demoted'] is False
    assert up['before']['sub'] == 'Ⅰ' and up['after']['sub'] == 'Ⅱ'

    cross = ranks.solve_delta(595, 615)
    assert cross['tier_up'] is True and cross['promoted'] is True
    assert cross['before']['tier_name'] == '一级水手'
    assert cross['after']['tier_name'] == '水手长'

    down = ranks.solve_delta(105, 85)       # 二级水手Ⅱ → 二级水手Ⅰ
    assert down['delta'] == -20 and down['demoted'] is True
    assert down['promoted'] is False and down['tier_down'] is False

    floor = ranks.solve_delta(5, 0)         # 0 分封底：掉的是分，不是小段位
    assert floor['delta'] == -5 and floor['points_after'] == 0
    assert floor['demoted'] is False, '同一个小段位内扣分不算掉段'

    flat = ranks.solve_delta(0, 0)
    assert flat['promoted'] is False and flat['demoted'] is False


# ===========================================================================
# 2. 大舰长晋升
# ===========================================================================
def test_admiral_requires_captain_tier():
    ok, why = ranks.can_promote_to_admiral(2000, 1, 100)
    assert ok is False and '船长' in why


def test_admiral_requires_top50_in_captain_pool():
    ok, why = ranks.can_promote_to_admiral(2300, 51, 100)
    assert ok is False and '50' in why
    ok, why = ranks.can_promote_to_admiral(2300, 50, 100)
    assert ok is True and why == ''


def test_admiral_blocked_when_pool_too_small():
    """⚠️ 护栏：船长池不足 50 人时不产生大舰长。

    没有这条，今天这个玩家基数下**人人都是大舰长**（池子里就 3 个人，
    人人排名 ≤ 50）。作者要的是"最高段位"，不是"注册即送"。
    """
    ok, why = ranks.can_promote_to_admiral(2400, 1, ranks.ADMIRAL_MIN_CAPTAINS - 1)
    assert ok is False and '50' in why
    assert ranks.ADMIRAL_MIN_CAPTAINS == 50
    assert ranks.ADMIRAL_STICKY is False      # 默认动态：条件不满足会掉回船长


def test_admiral_is_dynamic_by_default():
    """动态判定：分数掉下船长段就不再是大舰长（`ADMIRAL_STICKY=False`）。"""
    row = {'points': 1000, 'is_admiral': 1}
    assert ranks.is_admiral(row, captain_pool_rank=1, captain_pool_size=100) is False
    row = {'points': 2300, 'is_admiral': 0}
    assert ranks.is_admiral(row, captain_pool_rank=3, captain_pool_size=100) is True


def test_env_int_knob_reads_and_falls_back():
    """赢分 / 输分 / 大舰长护栏三个数可以用环境变量调；**写错一律回默认值**。

    这条是给"上线后想微调一下"准备的：调参不该再走一次改代码 + 提交 + 部署。
    但配置写错（`abc` / 空串）绝不能把进程打崩 —— 所以非法值必须静默回默认。
    """
    import os
    key = 'RANK_TEST_KNOB'
    assert ranks._env_int(key, 7) == 7                    # 没设 → 默认
    os.environ[key] = '42'
    assert ranks._env_int(key, 7) == 42                    # 设了 → 生效
    os.environ[key] = 'abc'
    assert ranks._env_int(key, 7) == 7                     # 非法 → 默认
    os.environ[key] = '   '
    assert ranks._env_int(key, 7) == 7                     # 空白 → 默认
    os.environ[key] = '-15'
    assert ranks._env_int(key, 7) == -15                   # 负数是合法值（输分就是负的）
    del os.environ[key]
    # 默认值必须就是设计稿的值（服务器不配这几个变量时行为完全不变）
    assert ranks.WIN_POINTS == 20
    assert ranks.LOSE_POINTS == -15
    assert ranks.ADMIRAL_MIN_CAPTAINS == 50


def test_rank_view_has_one_shape():
    """⚠️ `rank_view` 的两条分支**键集必须完全一致**（只有 `sub` 是有意的差异）。

    大舰长那条分支第一版漏了 `saturated`，而普通分支里有 —— 同一个"段位视图"
    出现两种形状，调用方（前端 / 接口）就得对每个键写 `if key in view`。
    前端同事实测时正是被这条绊了一下。这里把"形状一致"钉死。
    """
    normal = ranks.rank_view(2300)
    admiral = ranks.rank_view(2300, is_admiral=True)
    assert set(normal) == set(admiral), (sorted(set(normal) - set(admiral)),
                                         sorted(set(admiral) - set(normal)))
    assert admiral['sub'] == '' and admiral['saturated'] is True
    assert isinstance(normal['saturated'], bool)
    # 两个视图返回的必须是**新 dict**（调用方会往里塞 server_rank 之外的东西）
    assert normal is not ranks.rank_view(2300)


def test_constants_snapshot_for_frontend():
    """接口下发的规则快照：前端画进度条不猜任何常数。"""
    c = ranks.constants()
    assert c['sub_points'] == 100 and c['subs'] == ['Ⅰ', 'Ⅱ', 'Ⅲ']
    assert c['win_points'] == 20 and c['lose_points'] == -15
    assert c['captain_floor'] == 2100 and c['top_points'] == 2400
    assert len(c['tiers']) == 9
    assert c['start_points_of_tier']['captain'] == 2100
    assert c['start_points_of_tier']['sailor2'] == 0


# ===========================================================================
# 3. db.user_rank
# ===========================================================================
def test_rank_row_default_when_absent():
    """没打过排位 = 全 0 的默认行（**不是 None**）：段位要显示「二级水手Ⅰ 0分」。"""
    uid, _ = _uid()
    row = db_module.get_user_rank_row(uid)
    assert row == {'points': 0, 'is_admiral': 0, 'ranked_wins': 0,
                   'ranked_losses': 0, 'updated_at': 0}
    assert db_module.get_rank_position(uid) == 0


def test_add_rank_points_accumulates_and_records_wl():
    """加减分 + 排位胜负场次（只统计排位局）。"""
    uid, _ = _uid()
    row = db_module.add_rank_points(uid, ranks.WIN_POINTS)
    assert row['points'] == 20 and row['ranked_wins'] == 1 and row['ranked_losses'] == 0
    row = db_module.add_rank_points(uid, ranks.LOSE_POINTS)
    assert row['points'] == 5 and row['ranked_wins'] == 1 and row['ranked_losses'] == 1
    row = db_module.add_rank_points(uid, ranks.WIN_POINTS)
    assert row['points'] == 25 and row['ranked_wins'] == 2


def test_add_rank_points_never_goes_negative():
    """0 分封底。⚠️ 这条曾经真的坏过：SQL 里的 `excluded.points` 已被夹成 0，
    于是"减分"等于没减（只有胜负场次在涨）。用例钉死它。"""
    uid, _ = _uid()
    db_module.add_rank_points(uid, 20)
    row = db_module.add_rank_points(uid, -100)
    assert row['points'] == 0, row
    assert row['ranked_losses'] == 1, row
    row = db_module.add_rank_points(uid, -15)
    assert row['points'] == 0 and row['ranked_losses'] == 2


def test_add_rank_points_ignores_junk_delta():
    uid, _ = _uid()
    db_module.add_rank_points(uid, 50)
    assert db_module.add_rank_points(uid, 'oops')['points'] == 50
    assert db_module.add_rank_points(uid, None)['points'] == 50


def test_ranked_leaderboard_order_and_positions():
    """段位榜：按分倒序、名次从 1 连续、只列打过排位的账号。"""
    a, _ = _uid()
    b, _ = _uid()
    c, _ = _uid()
    nobody, _ = _uid()
    db_module.set_rank_points(c, 1800)
    db_module.set_rank_points(a, 2300)
    db_module.set_rank_points(b, 2150)

    board = db_module.ranked_leaderboard(limit=50)
    mine = [x for x in board if x['user_id'] in (a, b, c)]
    assert [(x['user_id'], x['points']) for x in mine] == [(a, 2300), (b, 2150), (c, 1800)]
    assert [x['position'] for x in mine] == sorted(x['position'] for x in mine)
    assert all(x['user_id'] != nobody for x in board), '没打过排位的账号不该在榜上'


def test_rank_position_matches_board_and_is_stable_on_ties():
    """同分时按 (updated_at, user_id) 稳定定序：两人名次相邻，且重复查询不变。

    ⚠️ 用"这一次的结果与下一次相同"来断言稳定性，而不是断言谁在前 ——
    "谁在前"取决于建号顺序，是巧合而不是契约；"再查一次不许变"才是契约。
    """
    a, _ = _uid()
    b, _ = _uid()
    db_module.set_rank_points(a, 1234)
    db_module.set_rank_points(b, 1234)
    first = (db_module.get_rank_position(a), db_module.get_rank_position(b))
    assert abs(first[0] - first[1]) == 1, first           # 同分两人紧邻
    assert min(first) >= 1 and max(first) <= db_module.count_rank_at_least(0), first
    again = (db_module.get_rank_position(a), db_module.get_rank_position(b))
    assert again == first, (first, again)
    # 与榜单里的 position 也一致
    board = {x['user_id']: x['position'] for x in db_module.ranked_leaderboard(limit=200)}
    assert (board[a], board[b]) == first, (board.get(a), board.get(b), first)


def test_rank_position_map_batches_and_skips_unknown():
    a, _ = _uid()
    ghost = 'nobody-' + uuid.uuid4().hex[:8]
    db_module.set_rank_points(a, 500)
    m = db_module.get_rank_position_map([a, ghost, ''])
    assert m == {a: db_module.get_rank_position(a)}, m
    assert db_module.get_rank_position_map([]) == {}
    assert db_module.get_rank_position_map(None) == {}


def test_captain_pool_and_count():
    """船长池 = 积分 ≥ 2100 的账号（大舰长晋升的两个输入都来自它）。

    ⚠️ 断言只钉"池内相对顺序"与"门槛内外"，不钉绝对 `pool_position` ——
    库是整个测试会话共用的，别的用例也会留下 2100+ 的账号。
    """
    a, _ = _uid()
    b, _ = _uid()
    low, _ = _uid()
    db_module.set_rank_points(a, 2400)
    db_module.set_rank_points(b, 2100)
    db_module.set_rank_points(low, 2099)
    pool = db_module.captains_ordered(limit=500)
    ids = [x['user_id'] for x in pool]
    assert low not in ids, '2099 分不算船长（边界）'
    assert a in ids and b in ids
    pos = {x['user_id']: x['pool_position'] for x in pool}
    assert pos[a] < pos[b], pos                 # 2400 排在 2100 前面
    assert pos[a] == ids.index(a) + 1           # pool_position 与池内下标一致
    assert db_module.count_rank_at_least(2100) >= 2
    assert db_module.count_rank_at_least(2401) == 0, '没有账号超过 2400（隔离库）'


def test_is_admiral_flag_readwrite():
    """`is_admiral` 三态：显式 1 / 显式 0 / None（不动这一列）。"""
    uid, _ = _uid()
    db_module.add_rank_points(uid, 2400, is_admiral=True)
    assert db_module.get_user_rank_row(uid)['is_admiral'] == 1
    db_module.add_rank_points(uid, 20)                       # None = 不动
    assert db_module.get_user_rank_row(uid)['is_admiral'] == 1
    db_module.add_rank_points(uid, 20, is_admiral=False)
    assert db_module.get_user_rank_row(uid)['is_admiral'] == 0


def test_rank_map_returns_only_existing_rows():
    """批量读**只给库里有行的账号** —— 调用方才能区分"真的 0 分"与"没打过排位"。"""
    a, _ = _uid()
    b, _ = _uid()
    db_module.set_rank_points(a, 0)
    assert set(db_module.get_rank_map([a, b])) == {a}
    assert db_module.get_rank_map([]) == {}


def test_set_rank_points_is_absolute_and_keeps_wl():
    uid, _ = _uid()
    db_module.add_rank_points(uid, 20)
    assert db_module.set_rank_points(uid, 2500) is True
    row = db_module.get_user_rank_row(uid)
    assert row['points'] == 2500 and row['ranked_wins'] == 1, row
    assert db_module.set_rank_points(uid, -5) and db_module.get_user_rank_row(uid)['points'] == 0
    assert db_module.set_rank_points('', 1) is False


def test_empty_uid_is_safe_everywhere():
    assert db_module.get_user_rank_row('')['points'] == 0
    assert db_module.add_rank_points('', 20)['points'] == 0
    assert db_module.get_rank_position('') == 0
    assert db_module.set_rank_points('', 1) is False


def test_user_rank_table_columns_and_show_rank_column_exist():
    """建表 / 加列都真的落地了（生产库是**已有数据**的老表，靠 ALTER 补列）。

    老库补列这条路坏了的表现是「线上 500」（SELECT 新列 no such column），
    而不是启动报错 —— 所以必须有一条用例在真库上 PRAGMA 一次。
    """
    cur = db_module.db.cursor
    rank_cols = [r[1] for r in cur.execute('PRAGMA table_info(user_rank)').fetchall()]
    assert rank_cols == ['user_id', 'points', 'is_admiral', 'ranked_wins',
                         'ranked_losses', 'updated_at'], rank_cols
    profile_cols = [r[1] for r in cur.execute('PRAGMA table_info(user_profile)').fetchall()]
    assert 'show_rank' in profile_cols, profile_cols


def test_rank_indexes_exist():
    """榜序与船长计数都要走索引（没有索引在玩家增长后退化成全表扫描）。"""
    names = {r[0] for r in db_module.db.cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='user_rank'").fetchall()}
    assert 'idx_user_rank_points' in names, names
    assert 'idx_user_rank_points_asc' in names, names


# ===========================================================================
# 4. profile_spec：11 字段契约 + 段位解锁外观
# ===========================================================================
def test_writable_fields_is_eleven_now():
    """⚠️ 段位批把保存载荷从 9 个字段加到 10 个（多了 `show_rank`）；
    好友批加到 **11** 个（多了 `friend_requests_open` —— 决策④的"设置里可关"）。

    这条是给未来的自己看的：任何"少发一个字段"的前端都会整次保存被拒。
    """
    assert len(profile_spec.WRITABLE_FIELDS) == 11
    assert 'show_rank' in profile_spec.WRITABLE_FIELDS
    assert 'friend_requests_open' in profile_spec.WRITABLE_FIELDS
    assert profile_spec._FLAG_KEYS == ('show_stats', 'show_fav_cards', 'show_history',
                                       'show_guestbook', 'show_rank',
                                       'friend_requests_open')
    assert profile_spec._FLAG_LABELS['show_rank'] == '段位公开'
    assert profile_spec._FLAG_LABELS['friend_requests_open'] == '允许他人加我好友'


def _full_payload(**over):
    body = {'title_id': 'rookie', 'tags': [], 'status_text': '', 'frame_id': 'none',
            'card_bg_id': 'deep', 'show_stats': 1, 'show_fav_cards': 1,
            'show_history': 0, 'show_guestbook': 1, 'show_rank': 1, 'friend_requests_open': 1}
    body.update(over)
    return body


def test_validate_requires_show_rank():
    """缺 `show_rank` 必须整次拒绝并点名 —— 不许"保持原值"（那是静默失败）。"""
    body = _full_payload()
    body.pop('show_rank')
    fields, errors = profile_spec.validate_payload(body, {'wins': 0})
    assert fields == {} and errors
    assert 'show_rank' in errors[0]


def test_validate_accepts_and_normalizes_show_rank():
    fields, errors = profile_spec.validate_payload(
        _full_payload(show_rank=0), {'wins': 0})
    assert errors == [] and fields['show_rank'] == 0
    fields, _ = profile_spec.validate_payload(_full_payload(show_rank=True), {'wins': 0})
    assert fields['show_rank'] == 1
    _, errors = profile_spec.validate_payload(_full_payload(show_rank=2), {'wins': 0})
    assert errors and '段位公开' in errors[0]


def test_validate_rejects_locked_rank_cosmetic():
    """段位没到就选不了 —— **服务端裁决**（前端灰掉不算数）。"""
    _, errors = profile_spec.validate_payload(
        _full_payload(title_id='sea_emperor'), {'wins': 0, 'rank_tier': 3})
    assert errors and '未解锁的称号' in errors[0]
    _, errors = profile_spec.validate_payload(
        _full_payload(frame_id='king_aura'), {'wins': 0, 'rank_tier': 7})
    assert errors and '未解锁的头像框' in errors[0]
    fields, errors = profile_spec.validate_payload(
        _full_payload(frame_id='king_aura'), {'wins': 0, 'rank_tier': 8})
    assert errors == [] and fields['frame_id'] == 'king_aura'


def test_rank_gated_pools_sizes_and_ids():
    """新增的 5+5+5 段位外观都在池子里，`requirement` 文案由 `rank_tier` 现算。"""
    titles = {t['id']: t for t in profile_spec.TITLES}
    frames = {f['id']: f for f in profile_spec.FRAMES}
    bgs = {b['id']: b for b in profile_spec.CARD_BGS}
    for pool, ids in ((titles, ['storm_helmsman', 'deep_navigator', 'iron_soul',
                                'unsinkable', 'sea_emperor']),
                      (frames, ['bronze_compass', 'silver_chain', 'golden_wheel',
                                'mithril_ring', 'king_aura']),
                      (bgs, ['shoal', 'storm', 'abyss', 'molten_gold', 'starfield'])):
        for pid in ids:
            assert pid in pool, pid
            assert pool[pid]['requirement'].startswith('段位达到 '), pool[pid]
            assert pool[pid].get('rank_tier') is not None, pool[pid]
    assert len(profile_spec.TITLES) == 12
    assert len(profile_spec.FRAMES) == 10
    assert len(profile_spec.CARD_BGS) == 11


def test_rank_requirement_text_matches_threshold():
    """⚠️ 文案与实际阈值必须来自同一个数：写着「船长」就必须是 `rank_tier >= 7`。

    这条正是"两处阈值会漂移"的守卫 —— 手写文案时，文案说船长、判定按大副
    不会报错，只会让玩家看着一个解不开的条件。
    """
    for item in profile_spec.TITLES + profile_spec.FRAMES + profile_spec.CARD_BGS:
        tier = item.get('rank_tier')
        if tier is None:
            continue
        assert item['requirement'] == '段位达到 ' + ranks.tier_of_index(tier)['name'], item['id']
        # 边界：差一个段位就不该解锁
        below = {'wins': 0, 'rank_tier': tier - 1}
        at = {'wins': 0, 'rank_tier': tier}
        pools = ((profile_spec.unlocked_titles, profile_spec.TITLES),
                 (profile_spec.unlocked_frames, profile_spec.FRAMES),
                 (profile_spec.unlocked_card_bgs, profile_spec.CARD_BGS))
        for fn, pool in pools:
            if any(x['id'] == item['id'] for x in pool):
                assert item['id'] not in fn(below), (item['id'], tier)
                assert item['id'] in fn(at), (item['id'], tier)


def test_rank_tier_defaults_to_zero_and_clamps():
    """没有段位数据 = 最低段位（不凭空送外观）；脏数据不许刷到海皇。"""
    assert profile_spec.unlock_context({})['rank_tier'] == 0
    assert profile_spec.unlock_context({'rank_tier': 999})['rank_tier'] == 8
    assert profile_spec.unlock_context({'rank_tier': 'x'})['rank_tier'] == 0
    assert profile_spec.unlock_context({'rank_tier': -3})['rank_tier'] == 0
    # 低段位账号不该解锁任何段位外观
    low = {'wins': 0}
    assert 'storm_helmsman' not in profile_spec.unlocked_titles(low)
    assert 'shoal' not in profile_spec.unlocked_card_bgs(low)


def test_unlock_all_perk_still_covers_rank_items():
    """外观全解锁特权要连新加的段位外观一起解锁（否则特权账号会看到灰位）。"""
    st = {'wins': 0, '_unlock_all_cosmetics': True}
    assert profile_spec.unlocked_titles(st) == {t['id'] for t in profile_spec.TITLES}
    assert profile_spec.unlocked_frames(st) == {f['id'] for f in profile_spec.FRAMES}
    assert profile_spec.unlocked_card_bgs(st) == {b['id'] for b in profile_spec.CARD_BGS}


def test_catalog_does_not_leak_internal_rank_tier_key():
    """`catalog` 的条目是**白名单展开**：内部的 `rank_tier` 不许漏给前端。"""
    cat = profile_spec.catalog({'wins': 10, 'rank_tier': 8})
    assert {k: len(v) for k, v in cat.items()} == {
        'titles': 12, 'tags': 12, 'frames': 10, 'card_bgs': 11}
    for key in ('titles', 'frames', 'card_bgs'):
        for item in cat[key]:
            assert set(item) == {'id', 'name', 'desc', 'requirement', 'unlocked'}, item
    em = [i for i in cat['titles'] if i['id'] == 'sea_emperor'][0]
    assert em['unlocked'] is True and em['requirement'] == '段位达到 大舰长'


# ===========================================================================
# 5. 前端契约：图标文件与脚本加载顺序
# ===========================================================================
def _static_text(name):
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, 'static', name), encoding='utf-8') as f:
        return f.read()


def test_rank_icons_cover_every_tier_and_stay_in_viewbox():
    r"""`static/rank_icons.js` 要有 9 个段位的图标，且所有坐标都落在 24×24 里。

    坐标越界不会报错，只会让图标被裁掉一角 —— 用数值断言兜住。
    """
    js = _static_text('rank_icons.js')
    for tier in ranks.TIERS:
        assert re.search(r'\b' + tier['id'] + r'\s*:', js), tier['id']
        assert tier['name'] in js, tier['name']
    # 所有 path 的坐标对 / cx / cy / r / x / y 都在 0..24
    for num in re.findall(r'(?:cx|cy|r)="([\d.]+)"', js):
        assert 0 <= float(num) <= 24, num
    for attr in ('x', 'y', 'width', 'height'):
        for num in re.findall(attr + r'="([\d.]+)"', js):
            assert 0 <= float(num) <= 24, (attr, num)


def _icon_primitive_counts():
    """数每个段位图标画了几个图形（把 STAR 变量展开后再数）。

    ⚠️ 不能只数字面量：三副~大副的星是一个 `STAR` 变量引用，
    直接正则会把"星 + 一道杠"数成 1 个图形，于是"越高级越复杂"这条
    会被误判成失败（第一版就是这么假的）。
    """
    js = _static_text('rank_icons.js')
    star = re.search(r"var STAR = '([^']+)'", js)
    assert star, '找不到 STAR 常量'
    body = js.split('var RANK_ICONS = {', 1)[1].split('\n    };', 1)[0]
    counts = {}
    for chunk in re.split(r'\n\s{8}(?=\w+:)', body):
        m = re.match(r'\s*(\w+):', chunk)
        if not m or m.group(1) not in [t['id'] for t in ranks.TIERS]:
            continue
        expanded = chunk.replace('STAR', star.group(1))
        counts[m.group(1)] = len(re.findall(r'<(?:path|circle|rect|g)\b', expanded))
    return counts


def test_rank_icons_all_present_and_unique():
    """9 个段位各一枚图标，互不相同（不许复制粘贴凑数）。"""
    counts = _icon_primitive_counts()
    assert set(counts) == {t['id'] for t in ranks.TIERS}, counts
    js = _static_text('rank_icons.js')
    body = js.split('var RANK_ICONS = {', 1)[1].split('\n    };', 1)[0]
    chunks = [c.strip() for c in re.split(r'\n\s{8}(?=\w+:)', body)
              if re.match(r'\s*\w+:', c)]
    assert len(set(chunks)) == len(chunks), '有段位图标内容重复'
    assert counts['sailor2'] == 1, '最低段位就该是最简的一道折线'


def test_rank_icons_get_more_detailed_towards_the_top():
    """「段位越高越精致」要可测 —— 但**不能用一个数字硬套全 9 级**。

    ⚠️ 第一版这条是大舰长那一串"图形数单调递增"，结果自己假红：
    船长是一枚舵轮（2 圆 + 2 条多段路径 = 4 个图形），轮机长是"齿轮 + 三道杠"
    （6 个图形）—— 论图形数船长反而更少，可它明显更精致（一个舵轮要 16 段线）。
    换成"数路径段数"也一样假红（齿轮只用一条虚线圆就画出来了）。
    **任何单一数字代理都会冤枉某一种画法**，所以这里只钉真正成立的三条。

    三条断言：
      · 折线梯（二级水手 → 一级水手 → 水手长）图形数严格递增；
      · 条纹梯（三副 → 二副 → 大副）横杠数严格递增 1 → 2 → 3；
      · 大舰长是 9 枚里图形数**唯一最大**的一枚。
    """
    counts = _icon_primitive_counts()
    chevron = [counts[t] for t in ('sailor2', 'sailor1', 'bosun')]
    assert chevron[0] < chevron[1] < chevron[2], chevron

    js = _static_text('rank_icons.js')
    body = js.split('var RANK_ICONS = {', 1)[1].split('\n    };', 1)[0]
    chunks = {}
    for chunk in re.split(r'\n\s{8}(?=\w+:)', body):
        m = re.match(r'\s*(\w+):', chunk)
        if m:
            chunks[m.group(1)] = chunk
    bars = [len(re.findall(r'<rect\b', chunks[t])) for t in ('mate3', 'mate2', 'mate1')]
    assert bars == [1, 2, 3], bars

    assert counts['admiral'] == max(counts.values()), counts
    assert list(counts.values()).count(counts['admiral']) == 1, counts


def test_index_html_loads_rank_icons_before_game_js():
    """`rank_icons.js` 必须在 `game.js` 之前加载（game.js 直接取全局）。"""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, 'templates', 'index.html'), encoding='utf-8') as f:
        html = f.read()
    assert '/static/rank_icons.js' in html
    assert html.index('rank_icons.js') < html.index('/static/game.js')


# ===========================================================================
# 6. 段位奖励的"实装"守卫（2026-09-18 补：这两条各自对应一个真 bug）
# ===========================================================================
def test_rank_cosmetics_unlock_through_api_stats():
    """★ 到段位就该解锁 —— 而且必须走**接口那条路**（`api._profile_unlock_stats`）。

    为什么单独一条：`profile_spec.unlock_context` 对缺失的 `rank_tier` 一律按 0 算，
    而 `api._profile_unlock_stats` 曾经**压根没注入 `rank_tier`** —— 于是段位外观
    **一件都解不开**，而接口、前端、纯函数测试**全都不报错**。
    只测 `profile_spec.unlocked_*`（纯函数）是**测不到**这个 bug 的：
    那些用例自己传 `rank_tier`，永远绿。
    """
    uid, _ = _uid()
    # 0 段位：一件段位外观都不该解锁
    st0 = api._profile_unlock_stats(uid)
    assert st0['rank_tier'] == 0, st0
    assert not [t for t in profile_spec.unlocked_titles(st0)
                if profile_spec._BY_ID['titles'][t].get('rank_tier')], '还没打排位就解锁了段位外观'

    # 推到船长段（2100）：解锁门槛 ≤ 船长的那些
    db_module.set_rank_points(uid, ranks.CAPTAIN_FLOOR)
    st1 = api._profile_unlock_stats(uid)
    assert st1['rank_tier'] == 7, st1
    for pool, unlocked in ((profile_spec.TITLES, profile_spec.unlocked_titles(st1)),
                           (profile_spec.FRAMES, profile_spec.unlocked_frames(st1)),
                           (profile_spec.CARD_BGS, profile_spec.unlocked_card_bgs(st1))):
        for item in pool:
            if item.get('rank_tier') is not None and item['rank_tier'] <= 7:
                assert item['id'] in unlocked, f"船长段应当解锁 {item['id']}"

    # 大舰长段位（8）再往上：海皇 / 海皇光环 / 星海
    db_module.set_rank_points(uid, 3000)
    st2 = api._profile_unlock_stats(uid)
    assert st2['rank_tier'] == 7, '分数到不了大舰长（它是晋升制），rank_tier 仍应是 7'
    assert 'sea_emperor' not in profile_spec.unlocked_titles(st2), \
        '大舰长是晋升制，光有分数不该直接给海皇'


def test_every_cosmetic_has_css():
    """★ 池子里每一件外观都必须有样式规则 —— 否则"解锁了"等于"看不见"。

    这条对应另一个真 bug：5 个头像框 + 5 个名片底色在 `profile_spec.py` 里存在、
    能解锁、能保存，但 `style.css` 里**一行规则都没有** → 玩家选了完全看不出差别，
    表现就是「我拿到段位奖励了但看不到」。

    判据按既有约定（别改）：头像框看 `.pf-avatar[data-frame="X"]`，
    名片底色看 `.pf-cover[data-bg="X"]`。
    """
    css = _static_text('style.css')
    missing = []
    for frame in profile_spec.FRAMES:
        if f'[data-frame="{frame["id"]}"]' not in css:
            missing.append('frame:' + frame['id'])
    for bg in profile_spec.CARD_BGS:
        if f'[data-bg="{bg["id"]}"]' not in css:
            missing.append('bg:' + bg['id'])
    assert not missing, f'这些外观在池子里但没有样式（选了看不见）: {missing}'
