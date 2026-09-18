# -*- coding: utf-8 -*-
r"""个人信息名片（第 1 批）回归测试 —— 对应 `docs/PROFILE_CARD_2026_09_17_PLAN.md` §4.2。

覆盖三块：
  1. `profile_spec.py` 的解锁规则与边界（纯函数，不碰库）
  2. `POST /api/profile/card` 的逐项校验（**服务端裁决**，前端灰掉不算数）
  3. `/user_stats` 的公开字段 + 隐私过滤 + 凭证不下发

⚠️ 跑测试必须重定向临时目录（本机 `%LOCALAPPDATA%\Temp\pytest-of-Administrator`
的 ACL 坏了，不重定向会有一批用例在 setup 阶段假红）：
    $env:TMP="$PWD\\.tmp\\pytemp"; $env:TEMP=$env:TMP; python -m pytest tests/ -q
"""
import json
import sqlite3
import time
import uuid

import pytest

import db as db_module
import profile_spec
import server
from db import Database


# ---------------------------------------------------------------------------
# 夹具与助手
# ---------------------------------------------------------------------------
@pytest.fixture
def make_user():
    """在（已由 conftest 隔离的）全局库上建账号。

    `create_user` 只写 id/username/password_hash/created_at，
    战绩字段要用 `update_user` 补；`created_at` 不在 update_user 的白名单里
    （它是注册时间，本来就不该被随便改），需要时直接改库。
    """
    def _make(wins=0, losses=0, longest_streak=0, current_streak=0,
              created_at=None, card_uses=None):
        username = 'pc' + uuid.uuid4().hex[:10]
        uid = db_module.create_user(username, 'x')
        assert uid, '建号失败（用户名冲突？）'
        assert db_module.update_user(uid, wins=wins, losses=losses,
                                     longest_streak=longest_streak,
                                     current_streak=current_streak), '更新战绩失败'
        if created_at is not None:
            con = db_module.db
            with con._lock:
                con.cursor.execute('UPDATE users SET created_at = ? WHERE id = ?',
                                   (int(created_at), uid))
                con.conn.commit()
        for name, uses in (card_uses or {}).items():
            db_module.record_user_card_use(uid, name, uses)
        return uid, username

    return _make


def _login(client, uid, username):
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['username'] = username
    return client


def _payload(**over):
    """一份合法的保存请求（**9 个字段**齐全）。

    第 3 批 D 票把 `show_guestbook`（留言板公开，默认 1）并进了同一条保存通道 ——
    它和另外三个 `show_*` 一样"必须全发"，所以这里的形状也跟着从 8 个变 9 个。
    契约来源：`docs/BATCH_2_3_4_PLAN.md` §3.4 + 主会话对写入通道的裁决。
    """
    body = {'title_id': 'rookie', 'tags': [], 'status_text': '', 'frame_id': 'none',
            'card_bg_id': 'deep', 'show_stats': 1, 'show_fav_cards': 1,
            'show_history': 0, 'show_guestbook': 1, 'show_rank': 1}
    body.update(over)
    return body


def _stats(**over):
    """解锁判定用的 stats（原始形状，和 api.py 组装的一致）。"""
    base = {'wins': 0, 'losses': 0, 'longest_streak': 0,
            'created_at': int(time.time()), 'card_uses_total': 0}
    base.update(over)
    return base


# ===========================================================================
# 0. 契约形状：池子条目与 catalog
# ===========================================================================
def test_pools_have_frozen_sizes_and_ids():
    """12 称号 / 12 标签 / 10 头像框 / 11 底色，id 是冻结契约（计划 §2.1）。

    ⚠️ 段位批给三个池子各加了 5 项**段位解锁**的外观（原 7/5/6 → 12/10/11）。
    新项排在池子末尾，所以下面"前 N 项 id 顺序"的断言保持不变 ——
    这是有意的：池子顺序 = 前端选项顺序，新东西追加在后面，老玩家的界面不变。
    """
    assert len(profile_spec.TITLES) == 12
    assert len(profile_spec.TAGS) == 12
    assert len(profile_spec.FRAMES) == 10
    assert len(profile_spec.CARD_BGS) == 11

    assert [t['id'] for t in profile_spec.TAGS] == [
        'aggressive', 'steady', 'fast', 'turtle', 'cardflow', 'chain',
        'rookie', 'pro', 'nightowl', 'needmate', 'serious', 'chatty']
    assert [t['id'] for t in profile_spec.TITLES][:7] == [
        'rookie', 'sailor', 'hunter', 'streak10', 'immortal', 'veteran', 'cardmaster']
    assert [f['id'] for f in profile_spec.FRAMES][:5] == [
        'none', 'silver', 'gold', 'aurora', 'crimson']
    assert [b['id'] for b in profile_spec.CARD_BGS][:6] == [
        'deep', 'graphite', 'cyber', 'lava', 'dusk', 'aurora']

    for pool in (profile_spec.TITLES, profile_spec.FRAMES, profile_spec.CARD_BGS):
        for item in pool:
            assert item['name'] and item['desc'] and item['requirement'], item
    # 标签的 id 与名称（计划 §2.1 逐个列出）
    names = {t['id']: t['name'] for t in profile_spec.TAGS}
    assert names['aggressive'] == '激进' and names['turtle'] == '蹲坑'
    assert names['serious'] == '不苟言笑' and names['chatty'] == '爱聊'


def test_catalog_shape_and_unlocked_flags():
    cat = profile_spec.catalog(_stats(wins=10, longest_streak=5, losses=10))
    assert set(cat) == {'titles', 'tags', 'frames', 'card_bgs'}
    assert {k: len(v) for k, v in cat.items()} == {
        'titles': 12, 'tags': 12, 'frames': 10, 'card_bgs': 11}

    for key in ('titles', 'frames', 'card_bgs'):
        for item in cat[key]:
            assert set(item) == {'id', 'name', 'desc', 'unlocked', 'requirement'}
            assert isinstance(item['unlocked'], bool)
    for item in cat['tags']:
        assert set(item) == {'id', 'name'}

    titles = {t['id']: t for t in cat['titles']}
    assert titles['hunter']['unlocked'] is False       # 胜场 10 < 30
    assert titles['hunter']['requirement'] == '胜场 ≥ 30'
    assert titles['rookie']['unlocked'] is True        # 无门槛
    bgs = {b['id']: b for b in cat['card_bgs']}
    assert bgs['cyber']['unlocked'] is True            # 胜场 10 ≥ 10
    assert bgs['aurora']['unlocked'] is False          # 胜场 10 < 50


# ===========================================================================
# 7. 解锁边界：差 1 场一律不解锁
# ===========================================================================
@pytest.mark.parametrize('wins,losses,streak,uses,expected_locked,expected_unlocked', [
    # 老水手：总场次 ≥ 20
    (10, 9, 0, 0, 'sailor', None),
    (10, 10, 0, 0, None, 'sailor'),
    # 深海猎手：胜场 ≥ 30
    (29, 0, 0, 0, 'hunter', None),
    (30, 0, 0, 0, None, 'hunter'),
    # 十连胜 / 不败神话：最高连胜 ≥ 10 / ≥ 15
    (0, 0, 9, 0, 'streak10', None),
    (0, 0, 10, 0, None, 'streak10'),
    (0, 0, 14, 0, 'immortal', None),
    (0, 0, 15, 0, None, 'immortal'),
    # 卡牌大师：累计出牌 ≥ 100
    (0, 0, 0, 99, 'cardmaster', None),
    (0, 0, 0, 100, None, 'cardmaster'),
])
def test_title_unlock_boundaries(wins, losses, streak, uses,
                                 expected_locked, expected_unlocked):
    got = profile_spec.unlocked_titles(
        _stats(wins=wins, losses=losses, longest_streak=streak, card_uses_total=uses))
    if expected_locked:
        assert expected_locked not in got, f'{expected_locked} 不该解锁：{got}'
    if expected_unlocked:
        assert expected_unlocked in got, f'{expected_unlocked} 该解锁：{got}'


def test_veteran_boundary_is_180_days():
    now = int(time.time())
    day = 24 * 3600
    # 差一小时不满 180 天
    locked = profile_spec.unlocked_titles(_stats(created_at=now - 180 * day + 3600))
    assert 'veteran' not in locked
    # 刚过 180 天
    unlocked = profile_spec.unlocked_titles(_stats(created_at=now - 180 * day - 3600))
    assert 'veteran' in unlocked
    # created_at 缺失（0）不能凭空送称号
    assert 'veteran' not in profile_spec.unlocked_titles(_stats(created_at=0))


@pytest.mark.parametrize('wins,losses,streak,fid,bid', [
    (0, 0, 9, 'gold', None),        # 金环：最高连胜 ≥ 10
    (0, 0, 10, None, None),
    (29, 0, 0, 'aurora', None),     # 极光框：胜场 ≥ 30
    (30, 0, 0, None, None),
    (25, 24, 0, 'crimson', None),   # 绯红：总场次 ≥ 50
    (25, 25, 0, None, None),
    (9, 0, 0, None, 'cyber'),       # 赛博底色：胜场 ≥ 10
    (10, 0, 0, None, None),
    (0, 0, 4, None, 'lava'),        # 熔岩：最高连胜 ≥ 5
    (0, 0, 5, None, None),
    (14, 15, 0, None, 'dusk'),      # 暮光：总场次 ≥ 30
    (15, 15, 0, None, None),
    (49, 0, 0, None, 'aurora'),     # 极光底色：胜场 ≥ 50
    (50, 0, 0, None, None),
])
def test_frame_and_bg_unlock_boundaries(wins, losses, streak, fid, bid):
    stats = _stats(wins=wins, losses=losses, longest_streak=streak)
    frames = profile_spec.unlocked_frames(stats)
    bgs = profile_spec.unlocked_card_bgs(stats)
    if fid:
        assert fid not in frames, f'{fid} 不该解锁：{frames}'
    if bid:
        assert bid not in bgs, f'{bid} 不该解锁：{bgs}'
    if not fid:
        # 免费项永远可用
        assert {'none', 'silver'} <= frames
    if not bid:
        assert {'deep', 'graphite'} <= bgs


def test_zero_stats_still_has_free_items():
    stats = _stats()
    assert profile_spec.unlocked_titles(stats) == {'rookie'}
    assert profile_spec.unlocked_frames(stats) == {'none', 'silver'}
    assert profile_spec.unlocked_card_bgs(stats) == {'deep', 'graphite'}


def test_unlock_context_normalizes_dirty_stats():
    """脏 stats（None / 字符串 / 负数）不能把解锁判定带飞。"""
    ctx = profile_spec.unlock_context(
        {'wins': '30', 'losses': None, 'longest_streak': -5,
         'created_at': 'x', 'card_uses_total': 100})
    assert ctx['wins'] == 30 and ctx['losses'] == 0
    assert ctx['matches'] == 30 and ctx['longest_streak'] == 0
    assert ctx['created_at'] == 0 and ctx['card_uses_total'] == 100
    # unlock_context 幂等：归一化后的上下文还能再喂给 unlocked_*
    again = profile_spec.unlock_context(ctx)
    assert again['matches'] == 30
    assert 'hunter' in profile_spec.unlocked_titles(ctx)


# ===========================================================================
# 1. 越权挂未解锁称号 → 400 且库里没被改
# ===========================================================================
def test_locked_title_rejected_and_nothing_written(make_user):
    uid, username = make_user(wins=0, losses=0)
    client = _login(server.app.test_client(), uid, username)

    # 先存一份合法内容（rookie 无门槛）
    ok = client.post('/api/profile/card', json=_payload(title_id='rookie',
                                                        status_text='原来的状态'))
    assert ok.status_code == 200 and ok.get_json()['success'] is True

    bad = client.post('/api/profile/card', json=_payload(title_id='immortal',
                                                         status_text='偷偷改掉'))
    assert bad.status_code == 400, bad.get_json()
    body = bad.get_json()
    assert body['success'] is False
    assert '未解锁的称号' in body['error'] and '不败神话' in body['error']

    # 整次保存被拒 → 连合法的 status_text 也不许落库
    stored = db_module.get_user_profile_extra(uid)
    assert stored['title_id'] == 'rookie', stored
    assert stored['status_text'] == '原来的状态', stored


def test_unknown_title_rejected(make_user):
    uid, username = make_user()
    client = _login(server.app.test_client(), uid, username)
    resp = client.post('/api/profile/card', json=_payload(title_id='<script>'))
    assert resp.status_code == 400
    assert '称号' in resp.get_json()['error']


def test_empty_title_means_hide_and_is_allowed(make_user):
    """库默认 title_id=''（不展示），所以空串必须允许，否则称号永远清不掉。"""
    uid, username = make_user()
    client = _login(server.app.test_client(), uid, username)
    assert client.post('/api/profile/card',
                       json=_payload(title_id='rookie')).status_code == 200
    resp = client.post('/api/profile/card', json=_payload(title_id=''))
    assert resp.status_code == 200
    assert db_module.get_user_profile_extra(uid)['title_id'] == ''


# ===========================================================================
# 2. 标签：4 个只存 3 个 / 池外 400
# ===========================================================================
def test_more_than_three_tags_keeps_first_three(make_user):
    uid, username = make_user()
    client = _login(server.app.test_client(), uid, username)
    resp = client.post('/api/profile/card',
                       json=_payload(tags=['pro', 'fast', 'chain', 'turtle']))
    assert resp.status_code == 200
    assert db_module.get_user_profile_extra(uid)['tags'] == ['pro', 'fast', 'chain']


def test_tags_are_deduplicated_and_trimmed(make_user):
    uid, username = make_user()
    client = _login(server.app.test_client(), uid, username)
    resp = client.post('/api/profile/card',
                       json=_payload(tags=[' pro ', 'pro', '', ' fast']))
    assert resp.status_code == 200
    assert db_module.get_user_profile_extra(uid)['tags'] == ['pro', 'fast']


def test_tag_outside_pool_rejected(make_user):
    uid, username = make_user()
    client = _login(server.app.test_client(), uid, username)
    assert client.post('/api/profile/card', json=_payload(tags=['pro'])).status_code == 200

    resp = client.post('/api/profile/card', json=_payload(tags=['pro', 'hacker']))
    assert resp.status_code == 400
    assert '未知的标签' in resp.get_json()['error']
    assert db_module.get_user_profile_extra(uid)['tags'] == ['pro'], '拒绝后不许落库'


def test_tags_must_be_a_list(make_user):
    uid, username = make_user()
    client = _login(server.app.test_client(), uid, username)
    resp = client.post('/api/profile/card', json=_payload(tags='pro'))
    assert resp.status_code == 400
    assert '数组' in resp.get_json()['error']


# ===========================================================================
# 3. 一句话状态：截断 + 清控制字符
# ===========================================================================
def test_status_truncated_to_30(make_user):
    uid, username = make_user()
    client = _login(server.app.test_client(), uid, username)
    resp = client.post('/api/profile/card', json=_payload(status_text='字' * 31))
    assert resp.status_code == 200, resp.get_json()
    stored = db_module.get_user_profile_extra(uid)['status_text']
    assert stored == '字' * 30 and len(stored) == 30


def test_status_control_chars_cleaned_without_error(make_user):
    uid, username = make_user()
    client = _login(server.app.test_client(), uid, username)
    resp = client.post('/api/profile/card',
                       json=_payload(status_text='  a\x00b\x07c\t  '))
    assert resp.status_code == 200, resp.get_json()
    stored = db_module.get_user_profile_extra(uid)['status_text']
    assert stored == 'abc', repr(stored)
    assert '\x00' not in stored


def test_status_normalizer_is_pure_and_bounded():
    assert profile_spec.normalize_status(None) == ''
    assert profile_spec.normalize_status('  hi  ') == 'hi'
    assert profile_spec.normalize_status('a\nb') == 'a b'
    assert len(profile_spec.normalize_status('x' * 100)) == profile_spec.MAX_STATUS_LEN


# ===========================================================================
# 4. 未解锁的头像框 / 名片底色 → 400
# ===========================================================================
def test_locked_frame_rejected(make_user):
    uid, username = make_user(wins=0, longest_streak=0)
    client = _login(server.app.test_client(), uid, username)
    resp = client.post('/api/profile/card', json=_payload(frame_id='gold'))
    assert resp.status_code == 400
    assert '未解锁的头像框' in resp.get_json()['error']
    assert db_module.get_user_profile_extra(uid)['frame_id'] == 'none'


def test_locked_card_bg_rejected(make_user):
    uid, username = make_user(wins=0, longest_streak=0)
    client = _login(server.app.test_client(), uid, username)
    resp = client.post('/api/profile/card', json=_payload(card_bg_id='aurora'))
    assert resp.status_code == 400
    assert '未解锁的名片底色' in resp.get_json()['error']
    assert db_module.get_user_profile_extra(uid)['card_bg_id'] == 'deep'


def test_unknown_frame_and_bg_rejected(make_user):
    uid, username = make_user()
    client = _login(server.app.test_client(), uid, username)
    assert client.post('/api/profile/card',
                       json=_payload(frame_id='rainbow')).status_code == 400
    assert client.post('/api/profile/card',
                       json=_payload(card_bg_id='matrix')).status_code == 400


def test_unlocked_frame_and_bg_accepted(make_user):
    """够条件就必须能存下来（防止"锁太死"把功能锁没）。"""
    uid, username = make_user(wins=30, losses=25, longest_streak=12)
    client = _login(server.app.test_client(), uid, username)
    resp = client.post('/api/profile/card', json=_payload(
        title_id='hunter', frame_id='gold', card_bg_id='cyber', tags=['pro']))
    assert resp.status_code == 200, resp.get_json()
    stored = db_module.get_user_profile_extra(uid)
    assert (stored['title_id'], stored['frame_id'], stored['card_bg_id']) == \
        ('hunter', 'gold', 'cyber')


def test_show_flags_normalized_to_0_or_1(make_user):
    uid, username = make_user()
    client = _login(server.app.test_client(), uid, username)
    resp = client.post('/api/profile/card', json=_payload(
        show_stats=True, show_fav_cards=0, show_history=1))
    assert resp.status_code == 200
    stored = db_module.get_user_profile_extra(uid)
    assert (stored['show_stats'], stored['show_fav_cards'], stored['show_history']) == (1, 0, 1)

    bad = client.post('/api/profile/card', json=_payload(show_stats='随便'))
    assert bad.status_code == 400
    assert '0 或 1' in bad.get_json()['error']


def test_missing_field_is_rejected_loudly(make_user):
    """缺字段必须报错点名，不能"保持原值"——那是"保存了没生效"的静默失败。"""
    uid, username = make_user()
    client = _login(server.app.test_client(), uid, username)
    resp = client.post('/api/profile/card', json={'title_id': 'rookie'})
    assert resp.status_code == 400
    assert '缺少字段' in resp.get_json()['error']


def test_validate_payload_returns_no_fields_on_error():
    fields, errors = profile_spec.validate_payload({'title_id': 'rookie'}, _stats())
    assert fields == {} and errors, (fields, errors)
    fields, errors = profile_spec.validate_payload(_payload(), _stats())
    assert errors == []
    assert set(fields) == set(profile_spec.WRITABLE_FIELDS)


# ===========================================================================
# 5. 隐私：show_history 两种视角
# ===========================================================================
def test_history_privacy_two_views(make_user):
    owner_uid, owner_name = make_user(wins=1, losses=0)
    other_uid, other_name = make_user(wins=1, losses=0)
    db_module.record_match(owner_uid, other_uid, count_stats=False)

    owner = _login(server.app.test_client(), owner_uid, owner_name)
    other = _login(server.app.test_client(), other_uid, other_name)
    anon = server.app.test_client()

    # 默认 show_history=0 → 只有本人看得到
    assert db_module.get_user_profile_extra(owner_uid)['show_history'] == 0
    assert len(owner.get(f'/user_stats?username={owner_name}').get_json()['history']) == 1
    assert other.get(f'/user_stats?username={owner_name}').get_json()['history'] == []
    assert anon.get(f'/user_stats?username={owner_name}').get_json()['history'] == []

    # 本人主动公开后，别人也能看到
    assert owner.post('/api/profile/card',
                      json=_payload(show_history=1)).status_code == 200
    assert len(other.get(f'/user_stats?username={owner_name}').get_json()['history']) == 1

    # 关回去：本人仍然完整（否则"我的对局记录"就废了）
    assert owner.post('/api/profile/card',
                      json=_payload(show_history=0)).status_code == 200
    assert len(owner.get(f'/user_stats?username={owner_name}').get_json()['history']) == 1
    assert other.get(f'/user_stats?username={owner_name}').get_json()['history'] == []


def test_privacy_filter_does_not_hide_title_or_tags(make_user):
    """设计稿 §7：称号/标签/状态/边框/底色属于「这个人是谁」，不受展示开关控制。"""
    uid, username = make_user(wins=30, losses=25, longest_streak=12)
    owner = _login(server.app.test_client(), uid, username)
    assert owner.post('/api/profile/card', json=_payload(
        title_id='hunter', tags=['pro'], status_text='找队友',
        frame_id='gold', card_bg_id='cyber', show_history=0)).status_code == 200

    stats = server.app.test_client().get(f'/user_stats?username={username}').get_json()['stats']
    assert stats['title_id'] == 'hunter' and stats['title_name'] == '深海猎手'
    assert stats['tags'] == ['pro'] and stats['status_text'] == '找队友'
    assert stats['frame_id'] == 'gold' and stats['card_bg_id'] == 'cyber'
    assert stats['show_history'] == 0


# --- 三个展示开关必须一起下发（2026-09-17 裁决补上 show_stats / show_fav_cards）---
def test_show_toggles_reach_the_other_viewer(make_user):
    """★ 关掉「战绩亮点 / 最爱用的卡」后，**他人视角**读到的必须是 0。

    第一版契约只下发 `show_history`：前端在「看别人」这条路径上读到 `undefined`
    → 按默认值当成"显示" → 玩家关掉的开关在别人眼里完全无效（假控件）。
    """
    uid, username = make_user(wins=3, losses=1, card_uses={'冻结': 2})
    owner = _login(server.app.test_client(), uid, username)
    other = _login(server.app.test_client(), *make_user(wins=1, losses=1))

    # 默认：战绩与最爱用的卡可见、对局历史不公开
    stats = other.get(f'/user_stats?username={username}').get_json()['stats']
    assert (stats['show_stats'], stats['show_fav_cards'], stats['show_history']) == (1, 1, 0)

    assert owner.post('/api/profile/card', json=_payload(
        show_stats=0, show_fav_cards=0, show_history=0)).status_code == 200
    stats = other.get(f'/user_stats?username={username}').get_json()['stats']
    assert (stats['show_stats'], stats['show_fav_cards'], stats['show_history']) == (0, 0, 0)

    assert owner.post('/api/profile/card', json=_payload(
        show_stats=1, show_fav_cards=1, show_history=1)).status_code == 200
    stats = other.get(f'/user_stats?username={username}').get_json()['stats']
    assert (stats['show_stats'], stats['show_fav_cards'], stats['show_history']) == (1, 1, 1)


def test_show_toggles_are_viewer_independent(make_user):
    """三个开关是**同一套语义**：0 = 对所有人隐藏（含自己），1 = 对所有人可见。

    不区分视角 —— 自己一套、别人一套必然漂移。这里把「本人 / 他人 / 未登录」
    三个视角与自己的 `/api/profile` 一起钉死，保证四个来源同一个值。
    """
    uid, username = make_user(wins=3, losses=1)
    owner = _login(server.app.test_client(), uid, username)
    other = _login(server.app.test_client(), *make_user(wins=1, losses=1))
    anon = server.app.test_client()
    assert owner.post('/api/profile/card', json=_payload(
        show_stats=0, show_fav_cards=0, show_history=1)).status_code == 200

    def flags(client):
        s = client.get(f'/user_stats?username={username}').get_json()['stats']
        return (s['show_stats'], s['show_fav_cards'], s['show_history'])

    assert flags(owner) == flags(other) == flags(anon) == (0, 0, 1)
    profile = owner.get('/api/profile').get_json()['profile']
    assert (profile['show_stats'], profile['show_fav_cards'],
            profile['show_history']) == (0, 0, 1)


def test_anonymous_viewer_gets_all_three_toggles(make_user):
    """未登录（无 session）请求他人 `/user_stats` 也要拿得到三个开关。

    缺字段时前端只能按默认值渲染，等于开关失效 —— 所以这里逐个断言"存在且为 0"。
    """
    uid, username = make_user()
    _login(server.app.test_client(), uid, username).post(
        '/api/profile/card',
        json=_payload(show_stats=0, show_fav_cards=0, show_history=0))

    stats = server.app.test_client().get(f'/user_stats?username={username}').get_json()['stats']
    for key in ('show_stats', 'show_fav_cards', 'show_history'):
        assert key in stats, f'未登录视角缺少 {key}'
        assert stats[key] == 0, f'{key} 该是 0，实际 {stats[key]}'
    # 数据本身照旧下发（隐藏与否由前端按同一个标志位判断）
    assert isinstance(stats['fav_cards'], list)


# ===========================================================================
# 6. /user_stats 字段白名单：绝不下发凭证
# ===========================================================================
def test_user_stats_never_leaks_credentials(make_user):
    uid, username = make_user(wins=3, losses=1, card_uses={'冻结': 4})
    db_module.update_user(uid, token='tok-must-not-leak', signature='签名')
    stats = server.app.test_client().get(f'/user_stats?username={username}').get_json()['stats']
    assert 'password_hash' not in stats and 'token' not in stats
    raw = server.app.test_client().get(f'/user_stats?username={username}').get_data(as_text=True)
    assert 'tok-must-not-leak' not in raw
    # 新增的名片字段确实在（三个展示开关必须**同进同出**：只下发 show_history 时，
    # 「看别人」这条路径拿不到另外两个 → 前端按默认值当成"显示"→ 开关变成假控件）
    for key in ('title_id', 'title_name', 'tags', 'status_text', 'frame_id',
                'card_bg_id', 'fav_cards',
                'show_stats', 'show_fav_cards', 'show_history'):
        assert key in stats, f'/user_stats 缺少 {key}'


def test_user_stats_includes_fav_cards_with_speed(make_user):
    uid, username = make_user(card_uses={'冻结': 5, '无中生有': 2})
    stats = server.app.test_client().get(f'/user_stats?username={username}').get_json()['stats']
    assert [c['name'] for c in stats['fav_cards']] == ['冻结', '无中生有']
    assert stats['fav_cards'][0]['uses'] == 5
    assert isinstance(stats['fav_cards'][0]['speed'], int)


def test_profile_endpoint_shape(make_user):
    uid, username = make_user(wins=30, losses=25, longest_streak=12, card_uses={'失灵！': 41})
    client = _login(server.app.test_client(), uid, username)
    resp = client.get('/api/profile')
    assert resp.status_code == 200
    profile = resp.get_json()['profile']
    for key in ('id', 'username', 'signature', 'avatar', 'wins', 'losses',
                'current_streak', 'longest_streak', 'created_at', 'rank',
                'title_id', 'tags', 'status_text', 'frame_id', 'card_bg_id',
                'show_stats', 'show_fav_cards', 'show_history', 'show_guestbook',
                'show_rank', 'fav_cards', 'catalog'):
        assert key in profile, f'/api/profile 缺少 {key}'
    assert profile['fav_cards'][0] == {'name': '失灵！', 'speed': 3, 'uses': 41}
    assert {k: len(v) for k, v in profile['catalog'].items()} == {
        'titles': 12, 'tags': 12, 'frames': 10, 'card_bgs': 11}
    assert 'password_hash' not in profile and 'token' not in profile


def test_save_response_has_same_shape_as_get(make_user):
    uid, username = make_user()
    client = _login(server.app.test_client(), uid, username)
    saved = client.post('/api/profile/card', json=_payload(status_text='你好')).get_json()
    got = client.get('/api/profile').get_json()
    assert set(saved['profile']) == set(got['profile'])
    assert saved['profile']['status_text'] == '你好' == got['profile']['status_text']


# ===========================================================================
# 8. user_card_usage：累加 / Top3 排序 / 合计
# ===========================================================================
@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv('BATTLESHIP_DB_PATH', str(tmp_path / 'profile.db'))
    d = Database()
    yield d
    d.close()


def test_user_card_usage_accumulates(temp_db):
    assert temp_db.record_user_card_use('u1', '冻结') is True
    assert temp_db.record_user_card_use('u1', '冻结') is True
    assert temp_db.record_user_card_use('u1', '无中生有', 3) is True
    usage = {row['name']: row['uses'] for row in temp_db.get_user_card_usage('u1')}
    assert usage == {'冻结': 2, '无中生有': 3}
    assert temp_db.get_user_card_uses_total('u1') == 5


def test_user_card_usage_top3_and_total(temp_db):
    for name, uses in (('失灵！', 41), ('冻结', 12), ('无中生有', 7), ('桃园结义', 1)):
        temp_db.record_user_card_use('u1', name, uses)
    top = temp_db.get_user_card_usage('u1', 3)
    assert [r['name'] for r in top] == ['失灵！', '冻结', '无中生有']
    assert temp_db.get_user_card_uses_total('u1') == 61
    # 并列时按卡名稳定排序（否则每次刷新顺序都会跳）
    temp_db.record_user_card_use('u2', 'bbb', 2)
    temp_db.record_user_card_use('u2', 'aaa', 2)
    assert [r['name'] for r in temp_db.get_user_card_usage('u2')] == ['aaa', 'bbb']


def test_user_card_usage_isolated_per_user(temp_db):
    temp_db.record_user_card_use('u1', '冻结', 5)
    temp_db.record_user_card_use('u2', '冻结', 2)
    assert temp_db.get_user_card_usage('u1')[0]['uses'] == 5
    assert temp_db.get_user_card_usage('u2')[0]['uses'] == 2
    assert temp_db.get_user_card_uses_total('u2') == 2


def test_user_card_usage_safe_defaults(temp_db):
    assert temp_db.record_user_card_use('', '冻结') is False
    assert temp_db.record_user_card_use('u1', '') is False
    assert temp_db.get_user_card_usage('', 3) == []
    assert temp_db.get_user_card_usage('nobody') == []
    assert temp_db.get_user_card_uses_total('') == 0
    assert temp_db.get_user_card_uses_total('nobody') == 0


def test_profile_extra_safe_defaults_and_upsert(temp_db):
    default = temp_db.get_user_profile_extra('nobody')
    assert default['title_id'] == '' and default['tags'] == []
    assert default['frame_id'] == 'none' and default['card_bg_id'] == 'deep'
    assert default['show_stats'] == 1 and default['show_fav_cards'] == 1
    assert default['show_history'] == 0, '隐私默认：对局历史不公开'
    # 读默认值不该偷偷写库
    row = temp_db.conn.execute('SELECT COUNT(*) FROM user_profile').fetchone()[0]
    assert row == 0

    assert temp_db.save_user_profile_extra('u1', {'title_id': 'rookie'}) is True
    assert temp_db.save_user_profile_extra('u1', {'title_id': 'hunter',
                                                  'tags': ['pro']}) is True
    stored = temp_db.get_user_profile_extra('u1')
    assert stored['title_id'] == 'hunter' and stored['tags'] == ['pro']
    assert temp_db.save_user_profile_extra('', {}) is False


def test_profile_extra_ignores_unknown_columns(temp_db):
    """传了表里没有的键也不能拼进 SQL（白名单）。"""
    assert temp_db.save_user_profile_extra('u1', {'nope': 1, 'is_admin': 1}) is True
    cols = {r[1] for r in temp_db.conn.execute('PRAGMA table_info(user_profile)')}
    assert 'nope' not in cols and 'is_admin' not in cols


def test_profile_extra_survives_dirty_tags(temp_db):
    temp_db.save_user_profile_extra('u1', {'tags': ['pro']})
    with temp_db._lock:
        temp_db.cursor.execute("UPDATE user_profile SET tags = ? WHERE user_id = ?",
                               ('{不是 JSON', 'u1'))
        temp_db.conn.commit()
    assert temp_db.get_user_profile_extra('u1')['tags'] == [], '脏 tags 必须兜成空数组'


def test_card_usage_module_level_wrappers():
    """server.py / api.py 都是 `import db` 调模块级函数 —— 少一个就是 AttributeError
    （会被"统计失败不影响对局"的 try/except 吞掉，表现为功能永远不生效）。"""
    for name in ('get_user_profile_extra', 'save_user_profile_extra',
                 'record_user_card_use', 'get_user_card_usage',
                 'get_user_card_uses_total'):
        assert hasattr(db_module, name), f'db 模块缺少 {name}'


def test_module_level_user_card_usage_roundtrip(make_user):
    uid, _ = make_user()
    assert db_module.record_user_card_use(uid, '__pytest_probe__', 2) is True
    assert db_module.get_user_card_usage(uid)[0] == {'name': '__pytest_probe__', 'uses': 2}
    assert db_module.get_user_card_uses_total(uid) == 2


# ===========================================================================
# server.py：出牌时同时写全局表与个人表
# ===========================================================================
def test_record_card_use_writes_both_tables(make_user):
    uid, _ = make_user()
    before_global = db_module.get_card_usage().get('冻结', 0)
    server.record_card_use(server.MagicCard('冻结'), user_id=uid)
    assert db_module.get_card_usage().get('冻结', 0) == before_global + 1
    assert db_module.get_user_card_usage(uid)[0] == {'name': '冻结', 'uses': 1}


def test_record_card_use_without_user_id_only_writes_global(make_user):
    """游客没有 user_id → 只写全局表，不往个人表里塞脏 key。"""
    uid, _ = make_user()
    before_global = db_module.get_card_usage().get('冻结', 0)
    server.record_card_use(server.MagicCard('冻结'))
    server.record_card_use(server.MagicCard('冻结'), user_id=None)
    assert db_module.get_card_usage().get('冻结', 0) == before_global + 2
    assert db_module.get_user_card_usage(uid) == []


def test_playing_a_card_records_personal_use(make_user):
    """真链路：handle_use_magic_card 必须把施法者的 Player.user_id 传下去。"""
    uid, _ = make_user()
    room = server.GameRoom('profile-usage-room')
    card = server.MagicCard('无中生有')
    p1 = server.Player(name='p1', ships=[], attacks=[], remaining_ships=6,
                       sid='s1', user_id=uid)
    p1.magic_hand = [card]
    room.players['p1'] = p1
    room.players['p2'] = server.Player(name='p2', ships=[], attacks=[],
                                       remaining_ships=6, sid='s2', user_id=None)
    room.state = 'attacking'
    room.current_attacker = 'p1'
    room.current_phase = 'battle'
    room.attack_order = ['p1', 'p2']
    server.room_manager.rooms[room.id] = room
    try:
        res = server.handle_use_magic_card({
            'room_id': room.id, 'player_id': 'p1',
            'card': {'name': card.name, 'speed': card.speed, 'type': card.type},
            'targets': [],
        })
        assert res['status'] == 'success', res
        top = db_module.get_user_card_usage(uid)
        assert top and top[0]['name'] == '无中生有', f'个人统计没记上: {top}'
    finally:
        server.room_manager.rooms.pop(room.id, None)


# ===========================================================================
# 9. 老库兼容：重复 init_db() 不报错、老数据还在
# ===========================================================================
_OLD_SCHEMA = '''
CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT,
    wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0, current_streak INTEGER DEFAULT 0,
    longest_streak INTEGER DEFAULT 0, created_at INTEGER, signature TEXT DEFAULT '',
    avatar TEXT DEFAULT '', token TEXT DEFAULT '');
CREATE TABLE matches (id TEXT PRIMARY KEY, winner_id TEXT, loser_id TEXT, timestamp INTEGER);
CREATE TABLE match_logs (match_id TEXT PRIMARY KEY, logs TEXT);
CREATE TABLE chat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT,
    username TEXT, content TEXT, timestamp INTEGER);
CREATE TABLE active_games (user_id TEXT PRIMARY KEY, room_id TEXT, updated_at INTEGER);
CREATE TABLE card_usage (card_name TEXT PRIMARY KEY, uses INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER);
'''


def test_init_db_is_idempotent_on_old_db(tmp_path, monkeypatch):
    """老库（只有第 1 批之前的表）升级路径：加表不报错、老数据一条不少。"""
    path = tmp_path / 'old.db'
    con = sqlite3.connect(path)
    con.executescript(_OLD_SCHEMA)
    con.execute("INSERT INTO users (id, username, password_hash, wins, losses, "
                "longest_streak, created_at, signature) VALUES (?,?,?,?,?,?,?,?)",
                ('old-1', 'olduser', 'hash', 12, 5, 7, 1600000000, '老签名'))
    con.execute("INSERT INTO matches (id, winner_id, loser_id, timestamp) "
                "VALUES ('m1', 'old-1', 'old-2', 1600000001)")
    con.execute("INSERT INTO card_usage (card_name, uses, updated_at) VALUES ('冻结', 9, 0)")
    con.commit()
    con.close()

    monkeypatch.setenv('BATTLESHIP_DB_PATH', str(path))
    d = Database()          # __init__ 里就会跑一次 init_db
    try:
        # 再跑两次：CREATE TABLE IF NOT EXISTS 必须幂等
        d.init_db()
        d.init_db()

        tables = {r[0] for r in d.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {'user_profile', 'user_card_usage'} <= tables, tables

        old = d.get_user(uid='old-1')
        assert old and old['username'] == 'olduser' and old['wins'] == 12
        assert old['signature'] == '老签名'
        assert d.get_match_history('old-1'), '老对局记录不能丢'
        assert d.get_card_usage()['冻结'] == 9

        # 新表在"老库"上直接可用
        assert d.get_user_profile_extra('old-1')['frame_id'] == 'none'
        assert d.save_user_profile_extra('old-1', {'title_id': 'rookie'}) is True
        assert d.record_user_card_use('old-1', '冻结') is True
        assert d.get_user_card_uses_total('old-1') == 1
    finally:
        d.close()


def test_init_db_does_not_touch_users_columns(tmp_path, monkeypatch):
    """本项目没有 ALTER 迁移机制：新表以外的 users 列一个都不许动。"""
    path = tmp_path / 'cols.db'
    monkeypatch.setenv('BATTLESHIP_DB_PATH', str(path))
    d = Database()
    try:
        cols = {r[1] for r in d.conn.execute('PRAGMA table_info(users)')}
        assert cols == {'id', 'username', 'password_hash', 'wins', 'losses',
                        'current_streak', 'longest_streak', 'created_at',
                        'signature', 'avatar', 'token'}, cols
    finally:
        d.close()


# ===========================================================================
# 10. 未登录 → 401
# ===========================================================================
def test_anonymous_cannot_save_or_read_own_card():
    anon = server.app.test_client()
    resp = anon.post('/api/profile/card', json=_payload())
    assert resp.status_code == 401
    assert resp.get_json()['success'] is False
    assert resp.get_json()['error'] == '未登录'
    assert anon.get('/api/profile').status_code == 401


def test_anonymous_cannot_save_even_legal_values(make_user):
    """参数完全合法也没用：先判登录，再判内容。"""
    uid, _ = make_user(wins=100, losses=0, longest_streak=30)
    anon = server.app.test_client()
    resp = anon.post('/api/profile/card', json=_payload(
        title_id='immortal', frame_id='aurora', card_bg_id='aurora'))
    assert resp.status_code == 401
    assert db_module.get_user_profile_extra(uid)['title_id'] == '', '匿名请求不许写别人的库'


def test_non_json_body_rejected(make_user):
    uid, username = make_user()
    client = _login(server.app.test_client(), uid, username)
    resp = client.post('/api/profile/card', data='not json',
                       content_type='text/plain')
    assert resp.status_code == 400
    assert resp.get_json()['success'] is False
