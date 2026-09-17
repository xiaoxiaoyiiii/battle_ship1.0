# -*- coding: utf-8 -*-
r"""成就 / 徽章（第 2 批 B 票）回归测试 —— 对应 `docs/BATCH_2_3_4_PLAN.md` §2.2.2 / §2.3 / §2.4。

覆盖四块：
  1. `achievements.py` 的 12 枚判据与**边界**（差 1 就不解锁）+ 归一化兜底（纯函数，不碰库）
  2. 图鉴形状（全量 12 枚、未解锁项带 `requirement`、`unlocked_at` 语义）
  3. `GET /api/profile` / `GET /api/achievements` 自己视角 = 全量
  4. `GET /user_stats` **他人视角只下发已解锁**（未解锁的 id 与判据文案都不许出现）+ 凭据不下发

⚠️ 本票只改 `achievements.py` / `api.py` / 本文件。A 票的 5 个 DAO
（`get_user_counters` / `bump_user_counters` / `get_user_achievements` /
`grant_user_achievements` / `get_distinct_cards_used`）由 A 票落在 `db.py`：
接口层用例用 `monkeypatch` 打桩（不复制判据、也不改别人的文件），
另有两条分别钉住「DAO 缺失时接口不能 500」与「真实 DAO 的键名与判据上下文对得上」（跨票接缝）。

⚠️ 跑测试必须重定向临时目录（本机 `%LOCALAPPDATA%\Temp\pytest-of-Administrator`
的 ACL 坏了，不重定向会有一批用例在 setup 阶段假红）：
    New-Item -ItemType Directory -Force .tmp\pytemp | Out-Null
    $env:TMP="$PWD\.tmp\pytemp"; $env:TEMP=$env:TMP
    python -m pytest tests/ -q -p no:cacheprovider
"""
import json
import time
import uuid

import pytest

import achievements
import db as db_module
import server

# ===========================================================================
# 夹具与助手
# ===========================================================================


def _stats(**over):
    """一份「什么都没有」的判定输入（原始形状，与 api.py 组装的一致）。"""
    base = {'wins': 0, 'losses': 0, 'longest_streak': 0, 'created_at': int(time.time()),
            'matches_played': 0, 'sunk_total': 0, 'flawless_wins': 0,
            'fastest_win_sec': 0, 'card_uses_total': 0, 'distinct_cards': 0, 'rank': 0}
    base.update(over)
    return base


def _login(client, uid='u1', username='alice'):
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['username'] = username
    return client


def _install(monkeypatch, *, user=None, rank=0, counters=None, badges=None,
             distinct_cards=0, card_uses_total=0, history=None):
    """把 `/user_stats` 与 `/api/profile` 会用到的东西全部打桩。

    注意 `api.py` 与 `server.py` 里的 `db` 是**同一个模块对象**，
    所以 `monkeypatch.setattr(server.db, ...)` 对接口层同样生效。
    """
    user = user if user is not None else {
        'id': 'u1', 'username': 'alice', 'wins': 0, 'losses': 0,
        'current_streak': 0, 'longest_streak': 0, 'created_at': int(time.time()),
        'signature': '', 'avatar': '',
        # 以下字段绝不能出现在响应里
        'password_hash': 'pbkdf2:sha256:secret', 'token': 'session-token',
    }
    # `raising=False`：A 票的 DAO 是并行落地的，落地前这些属性还不存在。
    # 用 raising=False 让本文件在「A 票已落地」与「还没落地」两种状态下都能跑。
    monkeypatch.setattr(server.db, 'get_user', lambda **kw: user, raising=False)
    monkeypatch.setattr(server.db, 'get_user_rank', lambda uid: rank, raising=False)
    monkeypatch.setattr(server.db, 'get_user_counters',
                        lambda uid: dict(counters or {}), raising=False)
    monkeypatch.setattr(server.db, 'get_user_achievements',
                        lambda uid: dict(badges or {}), raising=False)
    monkeypatch.setattr(server.db, 'get_distinct_cards_used',
                        lambda uid: distinct_cards, raising=False)
    monkeypatch.setattr(server.db, 'get_user_card_uses_total',
                        lambda uid: card_uses_total, raising=False)
    monkeypatch.setattr(server.db, 'get_match_history',
                        lambda uid, limit: list(history or []), raising=False)
    return user


# ===========================================================================
# 0. 契约形状与「一处判据」
# ===========================================================================
def test_badges_are_exactly_the_twelve_from_the_plan():
    """12 枚、id 与顺序按计划 §2.3 冻结。"""
    assert achievements.BADGE_TOTAL == 12
    assert [b['id'] for b in achievements.BADGES] == [
        'first_win', 'veteran10', 'streak5', 'streak10', 'sunk50', 'sunk200',
        'flawless', 'flawless5', 'speedrun', 'cardmaster', 'allrounder', 'rank1']


def test_every_badge_has_a_rule_and_vice_versa():
    """池子与判据表一一对应 —— 防「加了徽章忘了写判据」（或反过来）。

    这里刻意读私有 `_RULES`：它就是「唯一一份判据」的载体，本用例是它的漂移守卫。
    """
    assert set(achievements._RULES) == {b['id'] for b in achievements.BADGES}


def test_badge_meta_is_complete():
    """每枚都有人话判据文案与分组（前端拿 `group` 直接分组显示，不能为空）。"""
    for badge in achievements.BADGES:
        assert badge['name'] and badge['desc'] and badge['requirement'] and badge['group']
    assert achievements.groups() == ['里程碑', '连胜', '击沉', '完美', '卡牌', '榜单']


# ===========================================================================
# 1. 12 枚判据的边界：达标解锁 / 差 1 不解锁
# ===========================================================================
# (badge_id, 上下文键, 门槛值) —— 门槛值处解锁，门槛 - 1 处不解锁
THRESHOLDS = [
    ('first_win', 'wins', 1),
    ('veteran10', 'matches_played', 10),
    ('streak5', 'longest_streak', 5),
    ('streak10', 'longest_streak', 10),
    ('sunk50', 'sunk_total', 50),
    ('sunk200', 'sunk_total', 200),
    ('flawless', 'flawless_wins', 1),
    ('flawless5', 'flawless_wins', 5),
    ('cardmaster', 'card_uses_total', 100),
    ('allrounder', 'distinct_cards', 20),
]


@pytest.mark.parametrize('badge_id,key,threshold', THRESHOLDS)
def test_threshold_unlocks_exactly_at_the_line(badge_id, key, threshold):
    """★ 差 1 就不解锁 —— 边界写错一位，玩家会觉得「明明达标了却不给」。"""
    assert badge_id in achievements.evaluate(_stats(**{key: threshold})), \
        f'{badge_id} 在 {key}={threshold} 时应当解锁'
    assert badge_id not in achievements.evaluate(_stats(**{key: threshold - 1})), \
        f'{badge_id} 在 {key}={threshold - 1} 时不该解锁'


@pytest.mark.parametrize('badge_id,key,threshold', THRESHOLDS)
def test_threshold_is_independent_of_other_keys(badge_id, key, threshold):
    """只满足别项不能解锁它（防止判据串台，例如把 sunk50 写成 longest_streak）。"""
    other = dict.fromkeys([k for _, k, _ in THRESHOLDS if k != key], 999)
    stats = _stats(**other)                     # 其它项全部拉满
    stats[key] = threshold - 1
    assert badge_id not in achievements.evaluate(stats)


def test_speedrun_needs_a_real_time_not_zero():
    """`fastest_win_sec = 0` 表示「还没有过胜局」，不能被当成 0 秒获胜。"""
    assert 'speedrun' in achievements.evaluate(_stats(fastest_win_sec=1))
    assert 'speedrun' in achievements.evaluate(_stats(fastest_win_sec=achievements.SPEEDRUN_SECONDS))
    assert 'speedrun' not in achievements.evaluate(
        _stats(fastest_win_sec=achievements.SPEEDRUN_SECONDS + 1))
    assert 'speedrun' not in achievements.evaluate(_stats(fastest_win_sec=0))


def test_rank1_needs_exactly_first_place():
    """榜首只在第 1 名解锁；榜外（None/0）不算。"""
    assert 'rank1' in achievements.evaluate(_stats(rank=1))
    assert 'rank1' not in achievements.evaluate(_stats(rank=2))
    assert 'rank1' not in achievements.evaluate(_stats(rank=0))
    assert 'rank1' not in achievements.evaluate(_stats(rank=None))


def test_everything_unlocks_for_a_maxed_out_account():
    """全满账号 12 枚全解锁（防止某条判据永远为假 = 死徽章）。"""
    assert achievements.evaluate(_stats(
        wins=99, matches_played=99, longest_streak=99, sunk_total=999,
        flawless_wins=99, fastest_win_sec=60, card_uses_total=999,
        distinct_cards=99, rank=1)) == {b['id'] for b in achievements.BADGES}


# ===========================================================================
# 2. 归一化兜底：脏数据不许抛异常
# ===========================================================================
def test_context_handles_none_missing_and_junk():
    """None / 缺字段 / 字符串数字 / 负数 / 布尔都要兜住。"""
    assert achievements.achievement_context(None) == dict.fromkeys(
        achievements.CONTEXT_KEYS, 0)
    assert achievements.achievement_context({}) == dict.fromkeys(
        achievements.CONTEXT_KEYS, 0)
    assert achievements.achievement_context('not-a-dict') == dict.fromkeys(
        achievements.CONTEXT_KEYS, 0)

    ctx = achievements.achievement_context({
        'wins': '3',            # 字符串数字（sqlite 有时会这么给）
        'sunk_total': -5,       # 负数夹到 0
        'flawless_wins': None,  # None → 0
        'fastest_win_sec': 'abc',   # 不可解析 → 0
        'rank': True,           # bool → 1
    })
    assert ctx['wins'] == 3
    assert ctx['sunk_total'] == 0
    assert ctx['flawless_wins'] == 0
    assert ctx['fastest_win_sec'] == 0
    assert ctx['rank'] == 1


def test_context_is_idempotent():
    """对已归一化的上下文再跑一次结果不变（evaluate 内部会调用它）。"""
    once = achievements.achievement_context(_stats(wins=3, sunk_total=60))
    assert achievements.achievement_context(once) == once


def test_evaluate_never_raises_on_junk():
    for junk in (None, {}, [], 'x', 0, {'wins': object()}):
        assert achievements.evaluate(junk) == set()


# ===========================================================================
# 3. 图鉴形状
# ===========================================================================
def test_catalog_shape_and_locked_entries_carry_requirement():
    items = achievements.catalog(_stats(wins=1), {})
    assert len(items) == achievements.BADGE_TOTAL
    assert sorted(items[0].keys()) == ['desc', 'group', 'id', 'name', 'requirement',
                                       'unlocked', 'unlocked_at']
    by_id = {i['id']: i for i in items}
    assert by_id['first_win']['unlocked'] is True
    assert by_id['streak10']['unlocked'] is False
    # 未解锁项也要有判据文案 —— 自己视角要能显示"还差什么"
    assert '≥ 10' in by_id['streak10']['requirement']
    assert by_id['streak10']['unlocked_at'] == 0


def test_catalog_unlocked_at_comes_from_the_db_rows():
    items = achievements.catalog(_stats(), {'first_win': 1789200000})
    by_id = {i['id']: i for i in items}
    assert by_id['first_win']['unlocked'] is True
    assert by_id['first_win']['unlocked_at'] == 1789200000
    # 库里没有、判据也不满足的仍是未解锁
    assert by_id['sunk50']['unlocked'] is False


def test_unlock_is_one_way():
    """解锁只进不退：库里记着解锁（哪怕 stats 后来变小）仍然算解锁。"""
    items = achievements.catalog(_stats(wins=0), {'first_win': 111})
    assert {i['id'] for i in items if i['unlocked']} == {'first_win'}
    assert achievements.evaluate(_stats(wins=0)) == set(), '判据本身仍应认为未达标'


def test_catalog_ignores_unknown_badge_ids_from_db():
    """库里残留已下线的 badge_id 时不许把它带进图鉴（也不许报错）。"""
    items = achievements.catalog(_stats(), {'ghost_badge': 123, 'first_win': 1})
    assert {i['id'] for i in items} == {b['id'] for b in achievements.BADGES}


def test_catalog_accepts_set_as_unlocked():
    """`unlocked` 允许是集合（只给 id、没有时间）—— 时间给 0。"""
    items = achievements.catalog(_stats(), {'first_win'})
    by_id = {i['id']: i for i in items}
    assert by_id['first_win']['unlocked'] is True
    assert by_id['first_win']['unlocked_at'] == 0


def test_unlocked_only_and_count():
    items = achievements.catalog(_stats(wins=1, sunk_total=50), {})
    only = achievements.unlocked_only(items)
    assert {i['id'] for i in only} == {'first_win', 'sunk50'}
    # 过滤后 count 仍报真实总数（前端要显示 2 / 12）
    assert achievements.count_unlocked(only) == {'unlocked': 2, 'total': 12}
    assert achievements.count_unlocked(items) == {'unlocked': 2, 'total': 12}


def test_newly_unlocked_reports_only_the_delta_in_badge_order():
    stats = _stats(wins=1, sunk_total=50)
    assert achievements.newly_unlocked(stats, set()) == ['first_win', 'sunk50']
    assert achievements.newly_unlocked(stats, {'first_win'}) == ['sunk50']
    assert achievements.newly_unlocked(stats, {'first_win', 'sunk50'}) == []


def test_name_of_and_describe():
    assert achievements.name_of('streak10') == '十连胜'
    assert achievements.describe('streak10') == achievements.BADGES[3]['desc']
    assert achievements.name_of('nope') == '' and achievements.describe('nope') == ''


# ===========================================================================
# 4. 接口：自己视角 = 全量
# ===========================================================================
def test_profile_includes_all_badges_and_count(monkeypatch):
    _install(monkeypatch, user={
        'id': 'u1', 'username': 'alice', 'wins': 3, 'losses': 1, 'current_streak': 1,
        'longest_streak': 5, 'created_at': int(time.time()), 'signature': '', 'avatar': '',
    }, rank=4, counters={'matches_played': 12, 'sunk_total': 51}, distinct_cards=3)
    client = _login(server.app.test_client())
    resp = client.get('/api/profile')
    assert resp.status_code == 200
    profile = resp.get_json()['profile']

    assert isinstance(profile['achievements'], list)
    assert len(profile['achievements']) == 12, '自己视角要拿全量（含未解锁项，好画灰格）'
    assert profile['badge_count'] == {'unlocked': 4, 'total': 12}
    assert {i['id'] for i in profile['achievements'] if i['unlocked']} == {
        'first_win', 'veteran10', 'streak5', 'sunk50'}
    # 未解锁项也带判据文案
    locked = next(i for i in profile['achievements'] if i['id'] == 'streak10')
    assert locked['unlocked'] is False and locked['requirement']


def test_achievements_endpoint_requires_login():
    resp = server.app.test_client().get('/api/achievements')
    assert resp.status_code == 401
    assert 'achievements' not in resp.get_json()


def test_achievements_endpoint_returns_full_catalog(monkeypatch):
    _install(monkeypatch, user={
        'id': 'u1', 'username': 'alice', 'wins': 0, 'losses': 0, 'current_streak': 0,
        'longest_streak': 0, 'created_at': int(time.time()), 'signature': '', 'avatar': '',
    }, rank=None, badges={'first_win': 1789200000})
    client = _login(server.app.test_client())
    payload = client.get('/api/achievements').get_json()
    assert len(payload['achievements']) == 12
    assert payload['badge_count'] == {'unlocked': 1, 'total': 12}
    by_id = {i['id']: i for i in payload['achievements']}
    assert by_id['first_win']['unlocked_at'] == 1789200000


# ===========================================================================
# 5. 接口：他人视角只下发已解锁的（不泄露进度）
# ===========================================================================
def test_user_stats_sends_only_unlocked_badges(monkeypatch):
    """★ 造一个「只解锁 2 枚、其余全锁」的账号：响应里只能出现那 2 枚。"""
    _install(monkeypatch, user={
        'id': 'u2', 'username': 'bravo', 'wins': 2, 'losses': 3, 'current_streak': 0,
        'longest_streak': 1, 'created_at': int(time.time()), 'signature': 'hi', 'avatar': '',
        'password_hash': 'pbkdf2:sha256:secret', 'token': 'session-token',
    }, rank=9, counters={'matches_played': 5, 'sunk_total': 0}, distinct_cards=1)
    resp = server.app.test_client().get('/user_stats?username=bravo')
    assert resp.status_code == 200
    payload = resp.get_json()
    stats = payload['stats']

    items = stats['achievements']
    assert [i['id'] for i in items] == ['first_win'], '只该有已解锁的那一枚'
    assert all(i['unlocked'] is True for i in items), '下发的必须都是已解锁的'
    # 总数照给（前端要显示 1 / 12），但**未解锁项的 id 与判据文案一个字都不能出现**
    assert stats['badge_count'] == {'unlocked': 1, 'total': 12}
    body = resp.get_data(as_text=True)
    for locked_id in ('streak10', 'sunk200', 'flawless5', 'speedrun', 'rank1', 'allrounder'):
        assert locked_id not in body, f'未解锁徽章 {locked_id} 的 id 泄露了'
    for requirement in ('最高连胜 ≥ 10', '零伤赢下 5 场', '最快获胜 ≤ 3 分钟'):
        assert requirement not in body, f'未解锁徽章的判据文案泄露了：{requirement}'


def test_user_stats_badge_count_total_is_always_twelve(monkeypatch):
    """一枚都没解锁时：列表为空，但总数仍是 12。"""
    _install(monkeypatch, user={
        'id': 'u3', 'username': 'carol', 'wins': 0, 'losses': 0, 'current_streak': 0,
        'longest_streak': 0, 'created_at': int(time.time()), 'signature': '', 'avatar': '',
    }, rank=0, counters={}, distinct_cards=0)
    stats = server.app.test_client().get('/user_stats?username=carol').get_json()['stats']
    assert stats['achievements'] == []
    assert stats['badge_count'] == {'unlocked': 0, 'total': 12}


def test_user_stats_still_hides_credentials(monkeypatch):
    _install(monkeypatch, counters={'sunk_total': 50})
    data = server.app.test_client().get('/user_stats?username=alice').get_json()
    body = server.app.test_client().get('/user_stats?username=alice').get_data(as_text=True)
    assert 'password_hash' not in data['stats'] and 'token' not in data['stats']
    assert 'pbkdf2' not in body and 'session-token' not in body


def test_user_stats_unknown_user_still_returns_empty_shape(monkeypatch):
    monkeypatch.setattr(server.db, 'get_user', lambda **kw: None)
    payload = server.app.test_client().get('/user_stats?username=ghost').get_json()
    assert payload == {'stats': None, 'history': []}


# ===========================================================================
# 6. 兜底：统计读不到 / DAO 还没落地时，接口不许 500
# ===========================================================================
def test_endpoints_survive_missing_daos(monkeypatch):
    """A 票的 DAO 缺失（AttributeError）时：徽章按空处理，页面照常。

    这条同时钉住两件事：① 并行开发期不会把整张名片打成 500；
    ② 「统计失败不影响展示」这个口径（与 `_card_speeds` 同一套处理）。
    """
    user = {'id': 'u9', 'username': 'dave', 'wins': 0, 'losses': 0, 'current_streak': 0,
            'longest_streak': 0, 'created_at': int(time.time()), 'signature': '', 'avatar': ''}
    monkeypatch.setattr(server.db, 'get_user', lambda **kw: user)
    monkeypatch.setattr(server.db, 'get_user_rank', lambda uid: None)
    monkeypatch.setattr(server.db, 'get_match_history', lambda uid, limit: [])
    for name in ('get_user_counters', 'get_user_achievements', 'get_distinct_cards_used'):
        monkeypatch.delattr(server.db, name, raising=False)

    resp = server.app.test_client().get('/user_stats?username=dave')
    assert resp.status_code == 200
    assert resp.get_json()['stats']['badge_count'] == {'unlocked': 0, 'total': 12}

    client = _login(server.app.test_client())
    resp = client.get('/api/profile')
    assert resp.status_code == 200
    assert len(resp.get_json()['profile']['achievements']) == 12


def test_ragged_counter_rows_do_not_break_the_endpoints(monkeypatch):
    """counters 里缺字段 / 值是垃圾时，判据按 0 处理，接口照常 200。"""
    _install(monkeypatch, counters={'sunk_total': 'not-a-number'}, distinct_cards=None)
    resp = server.app.test_client().get('/user_stats?username=alice')
    assert resp.status_code == 200
    assert resp.get_json()['stats']['badge_count'] == {'unlocked': 0, 'total': 12}


# ===========================================================================
# 7. 跨票接缝：A 票的真实 DAO → 本票的接口（不打桩）
# ===========================================================================
def test_real_daos_feed_the_badge_endpoints():
    """★ 用**真实**的 db DAO + 真实库跑一遍，验证两侧契约的键名对得上。

    这条的价值在于它守的是**跨票接缝**：A 票的 DAO 若把 `matches_played` 写成
    `match_count`、或 counters 少一列，判据会静默按 0 处理 ——
    界面上表现为「明明打了 12 场却没有十场老兵」，不报错、极难查。
    """
    username = 'bk' + uuid.uuid4().hex[:10]
    uid = db_module.create_user(username, 'x')
    assert uid, '建号失败（用户名冲突？）'
    assert db_module.update_user(uid, wins=1, losses=0, current_streak=1,
                                 longest_streak=5), '更新战绩失败'
    # A 票的累加式 DAO（每局结算用）
    assert db_module.bump_user_counters(uid, matches_played=12, sunk_total=51,
                                        flawless_wins=1, fastest_win_sec=120)
    # 真实解锁记录（只有首次解锁时间这一个事实）
    newly = db_module.grant_user_achievements(uid, ['first_win'])
    assert newly == ['first_win'], '首次授予应返回新增的 id'
    assert db_module.grant_user_achievements(uid, ['first_win', 'streak5']) == ['streak5'], \
        '已解锁的不能重复授予'

    client = _login(server.app.test_client(), uid, username)
    payload = client.get('/api/achievements').get_json()
    by_id = {i['id']: i for i in payload['achievements']}
    unlocked = {i for i, b in by_id.items() if b['unlocked']}
    # 判据：wins=1 / matches=12 / streak=5 / sunk=51 / flawless=1 / fastest=120s
    # ⚠️ 不写"等于某集合"：隔离库里这个新号 wins=1 往往就是**排行榜第 1 名**，
    #    `rank1` 会跟着解锁 —— 断言随别的用例留下的数据飘是假红的常见来源。
    assert {'first_win', 'veteran10', 'streak5', 'sunk50',
            'flawless', 'speedrun'} <= unlocked, f'判据与 counters 没对上：{sorted(unlocked)}'
    assert not ({'sunk200', 'flawless5', 'cardmaster', 'allrounder'} & unlocked), \
        f'这些还不该解锁：{sorted(unlocked)}'
    assert by_id['first_win']['unlocked_at'] > 0, '解锁时间应来自 user_achievements 表'
    assert by_id['streak5']['unlocked_at'] > 0, '已授予的也应有时间'
    assert by_id['veteran10']['unlocked_at'] == 0, '只靠判据达标、库还没记时间 → 给 0'

    # 他人视角（未登录）走真实库：只下发已解锁的
    body = server.app.test_client().get(f'/user_stats?username={username}').get_data(as_text=True)
    stats = json.loads(body)['stats']
    assert {i['id'] for i in stats['achievements']} == unlocked
    assert stats['badge_count'] == {'unlocked': len(unlocked), 'total': 12}
    assert 'sunk200' not in body and '累计击沉 ≥ 200' not in body
