# -*- coding: utf-8 -*-
"""特权（user_perks）与「本局刚解锁」结算提示的回归测试（2026-09-17）。

三块：
  1. `user_perks` 表与 DAO（授予/查询/收回，幂等、绝不抛）；
  2. 特权对外观解锁的作用 —— 手上有 `unlock_all_cosmetics` 时，
     称号 / 头像框 / 名片底色**全池解锁**，且保存校验也放行（两处必须一致）；
  3. 名字样式 `name_style`：**必须下发给别人**（他人的 /user_stats 与 /api/leaderboard 里都要有），
     否则彩虹名字只有本人在自己名片里看得到；
  4. 结算事件 `achievements_unlocked`：只发给本人、带结构化徽章详情、对手收不到。

⚠️ 这些用例锁的是"**别人拿不到**"这件事：特权只能由运维在库里授予，
没有任何自助接口 —— 所以这里也顺带断言"接口不能给自己发特权"。
"""
import itertools

import pytest

import achievements
import api
import db
import profile_spec
import server

_seq = itertools.count(1)


def _mk_user(prefix):
    """每个用例都用**全新**用户名：同一个 pytest 会话共用一个临时库，
    固定用户名会在第二个用例里撞成"已存在"→ create_user 返回 None。"""
    name = f'{prefix}{next(_seq)}'
    uid = db.create_user(name, 'x' * 12)
    assert uid, f'建号失败: {name}'
    return uid, name


def _purge(uids):
    try:
        with db.db._lock:
            for uid in uids:
                for table in ('user_perks', 'user_achievements'):
                    db.db.conn.execute(f'DELETE FROM {table} WHERE user_id = ?', (uid,))
            db.db.conn.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
@pytest.fixture
def users():
    """建两个一次性账号，返回 (uid_a, uid_b)。"""
    a, _na = _mk_user('perk_a')
    b, _nb = _mk_user('perk_b')
    assert a and b and a != b
    try:
        yield a, b
    finally:
        _purge((a, b))


def _http(uid=None):
    c = server.app.test_client()
    if uid:
        with c.session_transaction() as sess:
            sess['user_id'] = uid
            sess['username'] = uid
    return c


# ---------------------------------------------------------------------------
# 1. user_perks 表与 DAO
# ---------------------------------------------------------------------------










# ---------------------------------------------------------------------------
# 2. 特权 → 外观全解锁（判据一处，两处调用必须一致）
# ---------------------------------------------------------------------------












def test_no_self_service_perk_endpoint(users):
    """**别人不能拥有**的保证：没有任何接口可以给自己发特权。"""
    a, _ = users
    c = _http(a)
    for path in ('/api/perk', '/api/perks', '/api/grant_perk', '/api/profile/perk'):
        r = c.post(path, json={'perk': profile_spec.PERK_RAINBOW_NAME})
        assert r.status_code == 404, f'{path} 不该存在（特权只能由运维在库里授予）'
    assert db.has_user_perk(a, profile_spec.PERK_RAINBOW_NAME) is False


# ---------------------------------------------------------------------------
# 3. 名字样式必须下发（本人 + 别人 + 排行榜）
# ---------------------------------------------------------------------------










# ---------------------------------------------------------------------------
# 4. 结算事件 achievements_unlocked
# ---------------------------------------------------------------------------




def _make_room(room_id, uid_a, uid_b):
    """照 test_quick_chat.py 的 `_make_room` 建房间（GameRoom 只吃 room_id，
    players 要自己塞）。玩家名字与 sid 都填上：结算播报要用 name，
    只发本人的那条事件要靠 sid。"""
    r = server.GameRoom(room_id)
    r.players['pa'] = server.Player(name='甲', ships=[], attacks=[], remaining_ships=6,
                                    sid='sid-a', user_id=uid_a)
    r.players['pb'] = server.Player(name='乙', ships=[], attacks=[], remaining_ships=6,
                                    sid='sid-b', user_id=uid_b)
    return r
