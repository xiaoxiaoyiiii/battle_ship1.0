# -*- coding: utf-8 -*-
r"""段位接口回归测试（段位批 C 票：`api.py` 的段位接口与名片字段）。

对应 `docs/RANKED_2026_09_17.md` §5（接口契约）与 §5.1（隐私的两条边界）。
规则本身在 `ranks.py`（`tests/test_ranks.py` 管），本文件只管**接口这一层**：
组装对不对、字段齐不齐、隐私拦没拦住。

覆盖 11 块：
  1. `api.rank_view_for`：没打过排位（不带 `#0`）/ 船长（累计分 + 全服名次）/ 大舰长
  2. `/api/ranked_leaderboard` 的形状：`leaderboard` / `total` / `constants`
  3. 榜序（按分倒序、`position` 从 1 连续、只含打过排位的账号、`username`/`avatar`
     来自 users 表**真值**）
  4. `limit` / `offset` 生效，且越界被夹住（`limit=9999` 不报错、`limit=0` 不空）
  5. 匿名可访问（200）
  6. `/api/profile` 带 `rank_info`（自己视角**恒有**，开关关掉也有）
  7. `/user_stats` 本人视角：`rank_info` 完整、`show_rank` 为 1
  8. ★ 隐私两侧断言：A 关掉 → **B（别人身份）读接口** 拿到 `rank_info is None`、
     且明细字段一个都不下发；同时 A 自己读自己仍然完整；改回 1 → B 又能看到
  9. 段位榜**不受 `show_rank` 影响**（关掉之后仍在榜上）
 10. `rank_info` 里没有 `password_hash` / `token`（沿用既有安全断言口径）
 11. 大舰长：船长池不足时**不晋升**（护栏）/ 池子填满且池内进前 50 才晋升

⚠️ **本文件里的用例顺序有意义**：第 11 块会把船长池填到 `ADMIRAL_MIN_CAPTAINS`
   之上，而前面几条"还不够船长段 / 池子太小"的断言依赖池子在此之前仍然很小
   （库是整个测试会话共用的）。所以"填满船长池"那条**必须留在文件最后**。

⚠️ **本文件造的数据会自己回收**（`make_user` 的 teardown → `_delete_rank_rows`），
   且有两条硬约束：
   1. 分数一律 **≤ 2400** —— `tests/test_ranks.py::test_captain_pool_and_count` 有一条
      `count_rank_at_least(2401) == 0`（"隔离库里没有账号超过 2400"）；
   2. 用例结束必须把 `user_rank` 行删掉 —— 大舰长那条要造满 50 个船长，
      留在表里会把 `test_ranks.py` 的 `ranked_leaderboard(limit=50)` 前 50 名占满，
      让那边"1800 分也在榜上"的断言假红（失败点还不在本文件里）。

跑测试必须重定向临时目录（本机 Temp 的 ACL 坏了）：
    New-Item -ItemType Directory -Force .tmp\pytemp | Out-Null
    $env:TMP="$PWD\.tmp\pytemp"; $env:TEMP=$env:TMP
    python -m pytest tests/ -q -p no:cacheprovider
"""
import uuid

import pytest

import api
import db as db_module
import ranks
import server

# `ranks.rank_view()` 返回的键就是接口要原样下发的字段（契约 §5.2）
RANK_VIEW_KEYS = {
    'tier_id', 'tier_name', 'tier_index', 'sub', 'progress', 'points', 'to_next',
    'sub_points', 'is_admiral', 'label', 'server_rank', 'captain_pool_rank',
}

# 段位榜每一行必须有的键（契约 §5.2：db 行 + users 的 username/avatar + rank_view）
BOARD_ENTRY_KEYS = {
    'user_id', 'username', 'avatar', 'points', 'is_admiral', 'ranked_wins',
    'ranked_losses', 'position',
} | RANK_VIEW_KEYS

# 未公开段位时**不许**出现在 /user_stats 里的明细字段
RANK_DETAIL_KEYS = ('points', 'server_rank', 'captain_pool_rank')


# ===========================================================================
# 夹具与助手
# ===========================================================================


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """清空按 IP 的限流计数（模块级字典，用例之间会互相顶成 429）。"""
    api._login_attempts.clear()
    yield
    api._login_attempts.clear()


@pytest.fixture
def make_user():
    """建一个真账号（走 db.create_user），可选直接给排位积分 / 头像。

    返回 `(uid, username)`。用例结束后**回收本用例造的排位行**（见 `_delete_rank_rows`）。
    """
    created = []

    def _make(points=None, avatar=None, password='x'):
        uid = None
        for _ in range(20):
            username = 'rk_' + uuid.uuid4().hex[:10]
            uid = db_module.create_user(username, password)
            if uid:
                break
        assert uid, '建号失败（用户名冲突？）'
        if avatar:
            assert db_module.update_user_avatar(uid, avatar), '头像写入失败'
        if points is not None:
            assert db_module.set_rank_points(uid, points), '排位积分写入失败'
        created.append(uid)
        return uid, username

    yield _make
    _delete_rank_rows(created)


def _delete_rank_rows(uids):
    """删掉本文件造出来的排位行（**只是测试卫生**，不是断言的一部分）。

    ⚠️ 为什么非要删：`user_rank` 是**整个测试会话共用**的一张表。
    大舰长那条用例必须造满 `ADMIRAL_MIN_CAPTAINS` 个船长（默认 50），
    这些行会把 `tests/test_ranks.py`（按文件名排在本文件**后面**跑）的
    `ranked_leaderboard(limit=50)` 前 50 名塞满 —— 那边一条"1800 分也在榜上"
    的断言当场假红，而失败点**不在本文件里**，排查起来很费劲（实测踩过一次）。
    用例一结束就把自己造的行收掉，两边都干净。

    删的是本用例自己建的 uid，不碰别人的数据（造什么回收什么）。
    """
    ids = [str(u) for u in (uids or []) if u]
    if not ids:
        return
    try:
        conn = db_module.db.conn
        marks = ','.join('?' for _ in ids)
        conn.execute(f'DELETE FROM user_rank WHERE user_id IN ({marks})', ids)
        conn.commit()
    except Exception as e:      # noqa: BLE001 —— 清理失败不该把用例判红
        print(f'[test] 回收 user_rank 失败（不影响断言）: {e}')


def _client(uid=None, username=None):
    """一个 test_client；给了 uid 就顺手登录。

    ⚠️ 每个 `test_client()` 各带各的 cookie jar —— 同一个用例里要**复用同一个
    client**，否则另起一个会丢 session（表现为"明明登录了却读到 401"）。
    """
    client = server.app.test_client()
    if uid:
        with client.session_transaction() as sess:
            sess['user_id'] = uid
            sess['username'] = username
    return client


def _board(client=None, **params):
    """请求段位榜（`client=None` = 匿名）。"""
    client = client or server.app.test_client()
    return client.get('/api/ranked_leaderboard', query_string=params)


def _board_json(**params):
    resp = _board(**params)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _stats_of(client, username):
    """读某人 `/user_stats` 的 `stats` 段（顺带断言 200）。"""
    resp = client.get('/user_stats', query_string={'username': username})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()['stats']


def _entry_of(payload, uid):
    for entry in payload['leaderboard']:
        if entry['user_id'] == uid:
            return entry
    return None


# ===========================================================================
# 1. rank_view_for：三种文案 + "没打过排位不带 #0"
# ===========================================================================
def test_rank_view_for_never_played_shows_sailor2_without_rank_suffix(make_user):
    """没打过排位 = `二级水手Ⅰ 0分`，`server_rank` 为 `None`（文案里不许出现 `#0`）。"""
    uid, _ = make_user()
    view = api.rank_view_for(uid)
    assert view['label'] == '二级水手Ⅰ 0分', view
    assert view['server_rank'] is None, '没打过排位不该带 #0'
    assert view['tier_id'] == 'sailor2' and view['tier_index'] == 0
    assert view['points'] == 0 and view['is_admiral'] is False
    assert view['captain_pool_rank'] is None
    assert set(view) >= RANK_VIEW_KEYS


def test_rank_view_for_unknown_uid_degrades_instead_of_raising():
    """uid 空 / 查无此人：给"没打过排位"的视图，不抛异常（接口不能因此 500）。"""
    for uid in ('', None, 'no-such-user-' + uuid.uuid4().hex[:8]):
        view = api.rank_view_for(uid)
        assert view['label'] == '二级水手Ⅰ 0分'
        assert view['server_rank'] is None


def test_rank_view_for_captain_carries_points_and_server_rank(make_user):
    """船长：`船长Ⅲ 0分 #N`（累计分 + 全服名次）。"""
    uid, _ = make_user(points=2300)
    pos = db_module.get_rank_position(uid)
    assert pos >= 1, '写过积分的账号必须有全服名次'

    # 前置：船长池还没满（大舰长那个用例在本文件最后，见文件头）
    assert db_module.count_rank_at_least(ranks.CAPTAIN_FLOOR) < ranks.ADMIRAL_MIN_CAPTAINS

    view = api.rank_view_for(uid)
    assert view['label'] == f'船长Ⅲ 0分 #{pos}', view
    assert view['server_rank'] == pos and view['server_rank'] is not None
    assert view['tier_id'] == 'captain' and view['tier_index'] == ranks.CAPTAIN['index']
    assert view['points'] == 2300 and view['is_admiral'] is False
    # 池子够不着 50 人 → 不晋升（护栏），但池内名次照样算得出来
    assert view['captain_pool_rank'] == 1, view


def test_rank_view_for_admiral_label_has_no_points(make_user):
    """大舰长：`大舰长 #N`（**不带分**）。显式传 `is_admiral` 时原样透传给 ranks。"""
    uid, _ = make_user(points=2400)
    view = api.rank_view_for(uid, server_rank=7, is_admiral=True)
    assert view['label'] == '大舰长 #7', view
    assert view['tier_id'] == 'admiral' and view['tier_index'] == ranks.ADMIRAL['index']
    assert view['sub'] == '' and view['to_next'] is None


# ===========================================================================
# 2. /api/ranked_leaderboard 的形状
# ===========================================================================
def test_ranked_leaderboard_shape_and_constants(make_user):
    make_user(points=2300)
    payload = _board_json()

    assert set(payload) == {'leaderboard', 'total', 'constants'}, payload.keys()
    assert isinstance(payload['leaderboard'], list) and payload['leaderboard']
    assert payload['total'] == db_module.count_rank_at_least(0)

    constants = payload['constants']
    for key in ('sub_points', 'tiers', 'win_points', 'lose_points', 'captain_floor'):
        assert key in constants, key
    assert constants['sub_points'] == ranks.SUB_POINTS
    assert constants['win_points'] == ranks.WIN_POINTS
    assert constants['lose_points'] == ranks.LOSE_POINTS
    assert constants['captain_floor'] == ranks.CAPTAIN_FLOOR
    assert [t['id'] for t in constants['tiers']] == [t['id'] for t in ranks.TIERS]


def test_ranked_leaderboard_entries_have_every_contracted_field(make_user):
    """entry 的字段逐字对齐冻结契约（前端与结算侧按这份写）。"""
    uid, username = make_user(points=2300, avatar='/static/avatars/rk_contract.png')
    payload = _board_json(limit=200)
    entry = _entry_of(payload, uid)
    assert entry is not None, '有排位记录的账号必须在榜上'
    missing = BOARD_ENTRY_KEYS - set(entry)
    assert not missing, f'段位榜 entry 缺字段: {sorted(missing)}'
    assert isinstance(entry['is_admiral'], bool)
    assert entry['username'] == username
    assert entry['avatar'] == '/static/avatars/rk_contract.png'


# ===========================================================================
# 3. 榜序 / 名次 / 只含打过排位的账号 / users 表 join 真值
# ===========================================================================
def test_ranked_leaderboard_order_positions_and_users_join(make_user):
    a, a_name = make_user(points=2400, avatar='/static/avatars/rk_a.png')
    b, b_name = make_user(points=2200)
    c, c_name = make_user(points=2100)
    nobody, nobody_name = make_user()                 # 从没打过排位

    payload = _board_json(limit=200)
    board = payload['leaderboard']

    # 名次从 1 连续（不是每页从 1 重来，也不是跳号）
    assert [x['position'] for x in board] == list(range(1, len(board) + 1))
    # 按积分倒序
    pts = [x['points'] for x in board]
    assert pts == sorted(pts, reverse=True), pts
    assert len(board) == min(payload['total'], 200)

    ids = [x['user_id'] for x in board]
    # 只列**库里有排位记录**的账号 —— 没打过排位的不许以"二级水手Ⅰ 0分"占位
    assert nobody not in ids, '没打过排位的账号不该在榜上'
    assert set(db_module.get_rank_map(ids)) == set(ids), '榜上每一行都得有 user_rank 记录'
    assert set(ids) >= {a, b, c}

    # 三人的相对顺序 = 分数高低
    assert [x for x in ids if x in (a, b, c)] == [a, b, c]

    # username / avatar 是 users 表的真值（不是占位、也不是拿 id 顶）
    entry_a = _entry_of(payload, a)
    entry_b = _entry_of(payload, b)
    entry_c = _entry_of(payload, c)
    assert entry_a['username'] == a_name and entry_a['avatar'] == '/static/avatars/rk_a.png'
    assert entry_b['username'] == b_name and entry_b['avatar'] == ''
    assert entry_c['username'] == c_name
    assert nobody_name not in [x['username'] for x in board]

    # 段位字段由服务端算好（前端不重算曲线）
    # ⚠️ 船长段文案 2026-09-18 起统一成"本小段位进度分"（与低段位同口径）：
    #    2400 = 船长Ⅲ 起点 2300 + 100 → 「船长Ⅲ 100分」；2100 = 船长Ⅰ 起点 → 0 分。
    assert entry_a['label'] == f'船长Ⅲ 100分 #{entry_a["position"]}'
    assert entry_a['server_rank'] == entry_a['position']
    assert entry_a['tier_id'] == 'captain'
    assert entry_c['label'] == f'船长Ⅰ 0分 #{entry_c["position"]}'
    # 榜上没人够到大舰长（池子还没填，见文件头）
    assert all(x['is_admiral'] is False for x in board)


# ===========================================================================
# 4. limit / offset
# ===========================================================================
def test_limit_and_offset_are_applied(make_user):
    for points in (2400, 2300, 2200, 2100):
        make_user(points=points)

    full = _board_json(limit=200)['leaderboard']
    assert len(full) >= 4
    assert full[0]['position'] == 1

    page = _board_json(limit=2)['leaderboard']
    assert [x['user_id'] for x in page] == [x['user_id'] for x in full[:2]]
    assert [x['position'] for x in page] == [1, 2]

    page2 = _board_json(limit=2, offset=1)['leaderboard']
    assert [x['user_id'] for x in page2] == [x['user_id'] for x in full[1:3]]
    assert page2[0]['position'] == 2, '名次是**全服**名次，翻页不重置'


def test_limit_is_clamped_and_junk_never_breaks_the_endpoint(make_user):
    make_user(points=2300)

    # 上限被夹到 200（不报错、也不真去取 9999 行）
    resp = _board(limit=9999)
    assert resp.status_code == 200
    payload = resp.get_json()
    assert len(payload['leaderboard']) == min(200, payload['total'])
    # 下限被夹到 1（0 不能变成"空榜"）
    zero = _board(limit=0)
    assert zero.status_code == 200
    assert len(zero.get_json()['leaderboard']) == 1
    # 负数同理
    assert len(_board(limit=-5).get_json()['leaderboard']) == 1
    # 非法值退回默认值，不 500
    junk = _board(limit='abc', offset='xyz')
    assert junk.status_code == 200
    assert junk.get_json()['leaderboard']
    # offset 超出范围 → 空列表，仍然 200
    far = _board(offset=100000)
    assert far.status_code == 200 and far.get_json()['leaderboard'] == []


# ===========================================================================
# 5. 匿名可访问
# ===========================================================================
def test_ranked_leaderboard_is_public_without_login(make_user):
    uid, _ = make_user(points=2200)
    client = server.app.test_client()                 # 不登录、干净 cookie
    resp = client.get('/api/ranked_leaderboard')
    assert resp.status_code == 200, '段位榜是公开数据，匿名必须能看'
    assert _entry_of(resp.get_json(), uid) is not None


# ===========================================================================
# 6. /api/profile：自己视角恒有 rank_info
# ===========================================================================
def test_own_profile_always_carries_rank_info(make_user):
    uid, username = make_user(points=2300)
    profile = _client(uid, username).get('/api/profile').get_json()['profile']

    info = profile['rank_info']
    assert info is not None, '自己的名片必须有段位'
    assert set(info) >= RANK_VIEW_KEYS
    assert info['points'] == 2300
    assert info['label'].startswith('船长Ⅲ 0分 #')
    assert profile['show_rank'] == 1, '开关本身也要下发（编辑面初始化复选框）'

    # 关掉「段位公开」之后，**自己**的名片里仍然有段位
    # （那个开关管的是"别人能不能看"；连自己都被挡住的话「我的段位」就没了）
    assert db_module.set_show_rank(uid, 0)
    again = _client(uid, username).get('/api/profile').get_json()['profile']
    assert again['show_rank'] == 0
    assert again['rank_info']['points'] == 2300
    assert again['rank_info']['label'].startswith('船长Ⅲ 0分 #')


# ===========================================================================
# 7. /user_stats 本人视角
# ===========================================================================
def test_user_stats_self_has_full_rank_info(make_user):
    uid, username = make_user(points=2300)
    client = _client(uid, username)

    # 不带 username = 当前登录用户
    stats = client.get('/user_stats').get_json()['stats']
    assert stats['id'] == uid
    assert stats['show_rank'] == 1
    info = stats['rank_info']
    assert info is not None
    assert set(info) >= RANK_VIEW_KEYS
    assert info['points'] == 2300
    assert info['label'].startswith('船长Ⅲ 0分 #')
    assert info['server_rank'] == db_module.get_rank_position(uid)
    assert info['sub'] == 'Ⅲ' and info['tier_id'] == 'captain'

    # 带 username 也是同一份
    same = _stats_of(client, username)
    assert same['rank_info'] == info


# ===========================================================================
# 8. ★ 隐私：两侧都要断言（只有服务端拦得住，前端断言会假绿）
# ===========================================================================
def test_rank_privacy_blocks_other_viewers_but_never_the_owner(make_user):
    a, a_name = make_user(points=2300)
    b, b_name = make_user(points=2200)
    outsider = _client(b, b_name)                     # B = 别人
    owner = _client(a, a_name)                        # A = 本人

    # ① 默认公开：别人看得到完整段位
    seen = _stats_of(outsider, a_name)
    assert seen['show_rank'] == 1
    assert seen['rank_info'] is not None and seen['rank_info']['points'] == 2300

    # ② A 关掉「段位公开」
    assert db_module.set_show_rank(a, 0)

    seen = _stats_of(outsider, a_name)
    assert seen['show_rank'] == 0, '开关本身必须下发 —— 前端靠它决定画不画'
    assert seen['rank_info'] is None, '别人 + 未公开 → None（不是空 dict，那会画出假段位）'
    for leaked in RANK_DETAIL_KEYS:
        assert leaked not in seen, f'{leaked} 不该在自己关掉之后还下发给别人'

    # ③ 本人读自己：仍然完整（"我的段位"不能因为隐私开关消失）
    mine = _stats_of(owner, a_name)
    assert mine['show_rank'] == 0
    assert mine['rank_info'] is not None
    assert mine['rank_info']['points'] == 2300
    assert mine['rank_info']['label'].startswith('船长Ⅲ 0分 #')
    assert mine['rank_info']['server_rank'] is not None

    # ④ 匿名访问 = 他人视角
    anon = _stats_of(server.app.test_client(), a_name)
    assert anon['show_rank'] == 0 and anon['rank_info'] is None
    for leaked in RANK_DETAIL_KEYS:
        assert leaked not in anon, leaked

    # ⑤ 改回公开 → 别人又能看到（开关是双向的，不是一次性的）
    assert db_module.set_show_rank(a, 1)
    seen = _stats_of(outsider, a_name)
    assert seen['show_rank'] == 1
    assert seen['rank_info']['points'] == 2300
    assert seen['rank_info']['label'].startswith('船长Ⅲ 0分 #')

    # ⑥ 只影响自己：B 的段位一直公开（别把过滤做成全局）
    b_seen = _stats_of(owner, b_name)
    assert b_seen['show_rank'] == 1 and b_seen['rank_info']['points'] == 2200


def test_rank_privacy_follows_save_user_profile_extra_too(make_user):
    """走整行写入（`POST /api/profile/card` 的落库通道）时过滤同样生效。

    两个入口（`set_show_rank` 单列 / `save_user_profile_extra` 整行）都可能被
    用来改这个开关，隐私判断必须只看**读出来的那一列**，与它怎么被写进去无关。
    """
    a, a_name = make_user(points=2300)
    b, b_name = make_user(points=2200)

    assert db_module.save_user_profile_extra(a, {'show_rank': 0})
    seen = _stats_of(_client(b, b_name), a_name)
    assert seen['show_rank'] == 0 and seen['rank_info'] is None

    assert db_module.save_user_profile_extra(a, {'show_rank': 1})
    seen = _stats_of(_client(b, b_name), a_name)
    assert seen['show_rank'] == 1 and seen['rank_info']['points'] == 2300


# ===========================================================================
# 9. 段位榜不理会 show_rank
# ===========================================================================
def test_ranked_leaderboard_ignores_show_rank(make_user):
    a, a_name = make_user(points=2400)
    b, _ = make_user(points=2200)
    assert db_module.set_show_rank(a, 0)

    # 别人视角（B 登录）读榜
    payload = _board_json()
    entry = _entry_of(payload, a)
    assert entry is not None, '关掉「段位公开」**不影响**段位榜（榜是公共竞技数据）'
    assert entry['points'] == 2400 and entry['username'] == a_name
    assert entry['label'].startswith('船长Ⅲ 100分 #')
    # 匿名视角同样在榜
    assert _entry_of(_board().get_json(), a) is not None
    # 榜上不下发任何名片隐私字段（榜与名片是两码事）
    for leaked in ('show_rank', 'show_stats', 'show_history', 'signature'):
        assert leaked not in entry, leaked
    assert _entry_of(payload, b) is not None


# ===========================================================================
# 10. 不泄露凭证
# ===========================================================================
def test_rank_info_and_endpoints_never_leak_credentials(make_user):
    # ⚠️ 用一段**可辨识**的假哈希：`create_user` 是原样入库的，若拿默认的那
    # 一个字符 `'x'` 去断言"响应里不含它"，任何 JSON 都能让断言假绿
    # （实测就踩过：`'x'` 出现在 `"index"` 里）。
    secret = 'pbkdf2:sha256:rank-batch-deadbeef'
    uid, username = make_user(points=2300, password=secret)
    row = db_module.get_user(uid=uid)
    assert row['password_hash'] == secret, '前置：假哈希要原样入库'
    token = row.get('token') or 'no-such-token'

    info = api.rank_view_for(uid)
    assert 'password_hash' not in info and 'token' not in info

    for url, segment in (('/api/ranked_leaderboard', 'leaderboard'),
                         ('/user_stats', 'stats'),
                         ('/api/profile', 'profile')):
        resp = _client(uid, username).get(url)
        assert resp.status_code == 200, url
        body = resp.get_data(as_text=True)
        assert secret not in body, f'{url} 泄露了 password_hash'
        assert token not in body, f'{url} 泄露了 token'
        payload = resp.get_json()
        inner = payload[segment]
        if isinstance(inner, dict):
            assert 'password_hash' not in inner and 'token' not in inner
            if isinstance(inner.get('rank_info'), dict):
                assert 'password_hash' not in inner['rank_info']
                assert 'token' not in inner['rank_info']


# ===========================================================================
# 11. 大舰长：池子不足不晋升 / 池子满了且进前 50 才晋升
#     ⚠️ 「池子填满」那条必须留在最后（见文件头）
# ===========================================================================
def test_endpoints_survive_broken_rank_daos(monkeypatch, make_user):
    """段位表读不出来时：接口降级（段位按"没打过排位"渲染），**绝不 500**。

    段位是展示层，一次读库失败不该把整张名片/整张榜打成 500 ——
    与 `_card_speeds` / `_safe_read` 同一套处理（`tests/test_achievements.py`
    的 `test_endpoints_survive_missing_daos` 钉的是同一件事）。
    """
    uid, username = make_user(points=2300)

    def _boom(*args, **kwargs):
        raise RuntimeError('段位表炸了')

    for name in ('get_user_rank_row', 'get_rank_position', 'captains_ordered',
                 'count_rank_at_least', 'ranked_leaderboard'):
        monkeypatch.setattr(db_module, name, _boom, raising=False)

    resp = _client(uid, username).get('/user_stats')
    assert resp.status_code == 200, resp.get_data(as_text=True)
    info = resp.get_json()['stats']['rank_info']
    assert info['label'] == '二级水手Ⅰ 0分' and info['server_rank'] is None
    assert info['is_admiral'] is False

    assert _client(uid, username).get('/api/profile').status_code == 200

    board = _board()
    assert board.status_code == 200, board.get_data(as_text=True)
    payload = board.get_json()
    assert payload['leaderboard'] == [] and payload['total'] == 0
    assert payload['constants']['sub_points'] == ranks.SUB_POINTS, '规则快照不该跟着一起丢'


def test_admiral_not_promoted_when_captain_pool_is_too_small(make_user, monkeypatch):
    """护栏：池子人数 < `ADMIRAL_MIN_CAPTAINS` 时，池内排第 1 也不晋升。

    这里用打桩把池子钉成"比门槛少一人" —— 人少时"人人排名 ≤ 50"，
    不拦的话注册即大舰长。（门槛可用 `RANK_ADMIRAL_MIN_CAPTAINS` 覆盖，
    所以断言一律引用常量，不写死 50。）
    """
    uid, _ = make_user(points=2400)
    pool_small = max(0, ranks.ADMIRAL_MIN_CAPTAINS - 1)     # 差一人 = 不满足护栏
    ok, reason = ranks.can_promote_to_admiral(2400, 1, pool_small)
    assert ok is False, (ok, reason)                        # 前置：规则本身就要求拦
    assert str(ranks.ADMIRAL_MIN_CAPTAINS) in reason, (ok, reason)

    monkeypatch.setattr(db_module, 'captains_ordered',
                        lambda limit=60: [{'user_id': uid, 'pool_position': 1}],
                        raising=False)
    monkeypatch.setattr(db_module, 'count_rank_at_least', lambda points: pool_small,
                        raising=False)

    view = api.rank_view_for(uid)
    assert view['captain_pool_rank'] == 1
    assert view['is_admiral'] is False, \
        f'船长池不满 {ranks.ADMIRAL_MIN_CAPTAINS} 人时不该产生大舰长'
    assert view['label'] == f'船长Ⅲ 100分 #{view["server_rank"]}', view


def test_admiral_promoted_once_pool_is_full_and_rank_is_top(make_user):
    """★ 真数据：把船长池填到 ≥ `ADMIRAL_MIN_CAPTAINS`，本人池内第 1 → 大舰长。

    走的是真实的 `db.set_rank_points` / `db.captains_ordered` / `count_rank_at_least`，
    不打工 —— 大舰长是"池内名次 + 池子人数"两个输入共同决定的，
    打桩会把最容易错的那一环（口径对不对）绕过去。
    """
    uid, username = make_user(points=2400)          # 本批最高分（≤2400，见文件头）
    need = ranks.ADMIRAL_MIN_CAPTAINS - db_module.count_rank_at_least(ranks.CAPTAIN_FLOOR)
    for _ in range(max(0, need)):
        make_user(points=2100)                      # 刚够船长段，垫在池子尾部

    pool_size = db_module.count_rank_at_least(ranks.CAPTAIN_FLOOR)
    assert pool_size >= ranks.ADMIRAL_MIN_CAPTAINS, pool_size
    pool = db_module.captains_ordered(limit=500)
    pos = next(x['pool_position'] for x in pool if x['user_id'] == uid)
    assert pos <= ranks.ADMIRAL_RANK_LIMIT, f'池内第 {pos} 名，进不了前 50'

    view = api.rank_view_for(uid)
    assert view['is_admiral'] is True, view
    assert view['tier_id'] == 'admiral'
    assert view['tier_index'] == ranks.ADMIRAL['index']
    assert view['sub'] == '' and view['to_next'] is None
    assert view['label'].startswith('大舰长 #'), view['label']
    assert view['captain_pool_rank'] == pos

    # 接口三条路径都跟着变（名片 / 他人视角 / 榜单）
    stats = _stats_of(_client(uid, username), username)
    assert stats['rank_info']['is_admiral'] is True
    assert stats['rank_info']['label'].startswith('大舰长 #')

    entry = _entry_of(_board_json(limit=200), uid)
    assert entry is not None
    assert entry['is_admiral'] is True
    assert entry['label'].startswith('大舰长 #')
    assert entry['captain_pool_rank'] == pos

    # 接口只读不写库：算完之后 `is_admiral` 那一列**不许**被接口改掉
    # （落库是结算侧的事；接口写一次，"动态晋升"就变成"看谁访问得多"了）
    assert db_module.get_user_rank_row(uid)['is_admiral'] == 0
