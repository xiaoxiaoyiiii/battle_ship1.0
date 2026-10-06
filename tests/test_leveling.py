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






















# ---------------------------------------------------------------------------
# 2. 每局经验
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# 3. user_xp 表 / DAO
# ---------------------------------------------------------------------------










# ---------------------------------------------------------------------------
# 4. 接口下发（三处口径一致）
# ---------------------------------------------------------------------------








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
