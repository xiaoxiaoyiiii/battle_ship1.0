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








# ===========================================================================
# 2. /api/ranked_leaderboard 的形状
# ===========================================================================




# ===========================================================================
# 3. 榜序 / 名次 / 只含打过排位的账号 / users 表 join 真值
# ===========================================================================


# ===========================================================================
# 4. limit / offset
# ===========================================================================




# ===========================================================================
# 5. 匿名可访问
# ===========================================================================


# ===========================================================================
# 6. /api/profile：自己视角恒有 rank_info
# ===========================================================================


# ===========================================================================
# 7. /user_stats 本人视角
# ===========================================================================


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




# ===========================================================================
# 9. 段位榜不理会 show_rank
# ===========================================================================


# ===========================================================================
# 10. 不泄露凭证
# ===========================================================================


# ===========================================================================
# 11. 大舰长：池子不足不晋升 / 池子满了且进前 50 才晋升
#     ⚠️ 「池子填满」那条必须留在最后（见文件头）
# ===========================================================================
