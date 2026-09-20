# -*- coding: utf-8 -*-
"""外观回收：存储值必须按**当前**解锁状态过滤（2026-09-20 反作弊回收批）。

背景：靠刷分拿到高段位 → 解锁并戴上高段位外观（称号/头像框/名片底色）。
事后回滚了分数，但**外观没被收回** —— 因为：

  · 解锁判定只在**保存路径**跑（`validate_payload` → `_pick_owned`），
  · **读路径原样下发存储值**（`build_own_profile` / `public_stats`）。

一条规则一处校验、一处不校验，后果有两个：
  1. 被回滚的作弊者**奖励收不回来**（存储里那串 id 还在，前端照着渲染）；
  2. 正常玩家掉段后也自相矛盾 —— 不编辑名片就永久保留，一编辑就被拒。

修法：`profile_spec.effective_equipped()` 作为**唯一一份**读路径过滤，
两个视角（自己 / 别人）都走它。
"""
import pytest

import api
import db
import profile_spec
import ranks

_TAG = 'cos9'
_seq = [0]


def _mk_user():
    _seq[0] += 1
    name = f'{_TAG}{_seq[0]}'
    uid = db.create_user(name, 'x' * 12)
    assert uid
    return uid, name


def _purge(uids):
    try:
        with db.db._lock:
            for uid in uids:
                for table in ('user_rank', 'user_profile', 'user_xp'):
                    try:
                        db.db.conn.execute(
                            f'DELETE FROM {table} WHERE user_id = ?', (uid,))
                    except Exception:
                        pass
            db.db.conn.commit()
    except Exception:
        pass


# 段位下标：点数越高下标越大（见 ranks.points_tier_index）
def _tier_points(tier):
    """给一个"至少达到该段位下标"的点数。"""
    for pts in range(0, 6000, 10):
        if ranks.points_tier_index(pts) >= tier:
            return pts
    return 5500


# ===========================================================================
# A. 纯函数层：effective_equipped
# ===========================================================================
def test_high_tier_gear_kept_when_unlocked():
    """段位够 → 外观照常保留（不许误伤）。"""
    stats = {'rank_tier': 7}
    tid, fid, bid = profile_spec.effective_equipped(
        stats, 'unsinkable', 'golden_wheel', 'molten_gold')
    assert (tid, fid, bid) == ('unsinkable', 'golden_wheel', 'molten_gold')


def test_high_tier_gear_revoked_when_rank_lost():
    """★ 段位掉了 → 高段位外观被换成默认值。"""
    stats = {'rank_tier': 0}
    tid, fid, bid = profile_spec.effective_equipped(
        stats, 'unsinkable', 'golden_wheel', 'molten_gold')
    assert tid == '', f'称号应回落空串，实际 {tid!r}'
    assert fid == profile_spec.DEFAULT_FRAME_ID, f'头像框应回落默认，实际 {fid!r}'
    assert bid == profile_spec.DEFAULT_CARD_BG_ID, f'底色应回落默认，实际 {bid!r}'


def test_partial_revoke_only_affected_items():
    """★ 只收回**失效的那几项**，仍合法的不动。

    真实场景：`弱碱性` 当前段位下标 1，他的 `silver` 框与 `deep` 底
    都是合法持有的 —— 不能因为"他是作弊者"就一起清掉。
    """
    stats = {'rank_tier': 1}
    tid, fid, bid = profile_spec.effective_equipped(
        stats, '', 'silver', 'deep')
    assert fid == 'silver', '当前段位合法的头像框不该被收回'
    assert bid == 'deep', '当前段位合法的底色不该被收回'


def test_unlock_all_perk_keeps_everything():
    """反向守卫：`解锁全部外观` 特权账号不受影响。

    ⚠️ 标记键是 `profile_spec.UNLOCK_ALL_FLAG`（带下划线前缀的内部键），
       不是特权名 `PERK_UNLOCK_ALL` —— 两者容易混，直接引用常量最稳。
    """
    stats = {'rank_tier': 0, profile_spec.UNLOCK_ALL_FLAG: True}
    tid, fid, bid = profile_spec.effective_equipped(
        stats, 'unsinkable', 'golden_wheel', 'molten_gold')
    assert (tid, fid, bid) == ('unsinkable', 'golden_wheel', 'molten_gold'), \
        '特权账号应当保留全部外观'


def test_empty_values_fall_back_to_defaults():
    """空值（从没设置过）→ 默认值，不报错。"""
    tid, fid, bid = profile_spec.effective_equipped({}, '', '', '')
    assert tid == ''
    assert fid == profile_spec.DEFAULT_FRAME_ID
    assert bid == profile_spec.DEFAULT_CARD_BG_ID


def test_garbage_tolerated():
    """脏数据不许抛（失败开放）。"""
    profile_spec.effective_equipped({}, None, None, None)
    profile_spec.effective_equipped({}, 123, [], {})
    profile_spec.effective_equipped('not-a-dict', 'x', 'y', 'z')


def test_unknown_id_falls_back():
    """不存在的 id（脏数据）→ 默认值。"""
    stats = {'rank_tier': 7}
    tid, fid, bid = profile_spec.effective_equipped(
        stats, 'no_such_title', 'no_such_frame', 'no_such_bg')
    assert tid == ''
    assert fid == profile_spec.DEFAULT_FRAME_ID
    assert bid == profile_spec.DEFAULT_CARD_BG_ID


# ===========================================================================
# B. 接口层：自己视角 / 别人视角都要过滤
# ===========================================================================
@pytest.fixture
def client():
    return api.app.test_client()


def test_own_profile_filters_revoked_cosmetics(client):
    """★ `GET /api/profile` 必须把失效外观换成默认值。"""
    uid, name = _mk_user()
    try:
        # 先给高段位 + 戴上顶级外观
        db.set_rank_points(uid, _tier_points(7))
        db.save_user_profile_extra(uid, {
            'title_id': 'unsinkable', 'frame_id': 'golden_wheel',
            'card_bg_id': 'molten_gold',
        })
        # 再把分收回（模拟反作弊回滚）
        db.set_rank_points(uid, 0)

        with client.session_transaction() as sess:
            sess['user_id'] = uid
            sess['username'] = name
        p = client.get('/api/profile').get_json()['profile']
        assert p['title_id'] == '', f"称号该被收回，实际 {p['title_id']!r}"
        assert p['frame_id'] == profile_spec.DEFAULT_FRAME_ID, \
            f"头像框该被收回，实际 {p['frame_id']!r}"
        assert p['card_bg_id'] == profile_spec.DEFAULT_CARD_BG_ID, \
            f"底色该被收回，实际 {p['card_bg_id']!r}"
    finally:
        _purge([uid])


def test_public_stats_filters_revoked_cosmetics(client):
    """★ 别人视角（`/user_stats`）同样要过滤 —— 这是公开可见的，漏了更糟。"""
    uid, name = _mk_user()
    try:
        db.set_rank_points(uid, _tier_points(7))
        db.save_user_profile_extra(uid, {
            'title_id': 'unsinkable', 'frame_id': 'golden_wheel',
            'card_bg_id': 'molten_gold',
        })
        db.set_rank_points(uid, 0)

        r = client.get(f'/user_stats?username={name}')
        s = r.get_json()['stats']
        assert s['title_id'] == '', '别人视角也不该看到失效称号'
        assert s['frame_id'] == profile_spec.DEFAULT_FRAME_ID, \
            '别人视角也不该看到失效头像框'
        assert s['card_bg_id'] == profile_spec.DEFAULT_CARD_BG_ID, \
            '别人视角也不该看到失效底色'
    finally:
        _purge([uid])


def test_legit_high_tier_player_not_affected(client):
    """★ 反向守卫：**合法**的高段位玩家外观照常显示（不许误伤）。"""
    uid, name = _mk_user()
    try:
        db.set_rank_points(uid, _tier_points(7))
        db.save_user_profile_extra(uid, {
            'title_id': 'unsinkable', 'frame_id': 'golden_wheel',
            'card_bg_id': 'molten_gold',
        })
        with client.session_transaction() as sess:
            sess['user_id'] = uid
            sess['username'] = name
        p = client.get('/api/profile').get_json()['profile']
        assert p['title_id'] == 'unsinkable'
        assert p['frame_id'] == 'golden_wheel'
        assert p['card_bg_id'] == 'molten_gold'
    finally:
        _purge([uid])


def test_saving_revoked_cosmetic_is_rejected():
    """★ 反向守卫：保存路径**仍然**拒绝失效外观（这条是既有行为，不许弄坏）。"""
    uid, name = _mk_user()
    try:
        db.set_rank_points(uid, 0)
        stats = {'rank_tier': 0}
        fields, errors = profile_spec.validate_payload({
            'title_id': '', 'tags': [], 'status_text': '',
            'frame_id': 'golden_wheel', 'card_bg_id': 'deep',
            'show_stats': 1, 'show_fav_cards': 1, 'show_history': 0,
            'show_guestbook': 1, 'show_rank': 1,
        }, stats)
        assert errors, '未解锁的头像框必须被保存路径拒绝'
        assert 'frame_id' not in fields
    finally:
        _purge([uid])
