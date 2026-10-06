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


def test_high_tier_gear_revoked_when_rank_lost():
    """★ 段位掉了 → 高段位外观被换成默认值。"""
    stats = {'rank_tier': 0}
    tid, fid, bid = profile_spec.effective_equipped(
        stats, 'unsinkable', 'golden_wheel', 'molten_gold')
    assert tid == '', f'称号应回落空串，实际 {tid!r}'
    assert fid == profile_spec.DEFAULT_FRAME_ID, f'头像框应回落默认，实际 {fid!r}'
    assert bid == profile_spec.DEFAULT_CARD_BG_ID, f'底色应回落默认，实际 {bid!r}'












# ===========================================================================
# B. 接口层：自己视角 / 别人视角都要过滤
# ===========================================================================
@pytest.fixture
def client():
    return api.app.test_client()
