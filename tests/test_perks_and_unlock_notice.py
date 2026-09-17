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
def test_grant_and_has_perk(users):
    a, _ = users
    assert db.has_user_perk(a, profile_spec.PERK_RAINBOW_NAME) is False
    assert db.grant_user_perk(a, profile_spec.PERK_RAINBOW_NAME) is True
    assert db.has_user_perk(a, profile_spec.PERK_RAINBOW_NAME) is True
    assert profile_spec.PERK_RAINBOW_NAME in db.list_user_perks(a)


def test_grant_is_idempotent(users):
    """重复授予不报错、也不产生第二行（主键 + INSERT OR IGNORE）。"""
    a, _ = users
    for _ in range(3):
        assert db.grant_user_perk(a, profile_spec.PERK_UNLOCK_ALL) is True
    rows = db.db.conn.execute(
        'SELECT COUNT(*) AS n FROM user_perks WHERE user_id = ? AND perk = ?',
        (a, profile_spec.PERK_UNLOCK_ALL)).fetchone()
    assert rows['n'] == 1, '重复授予不该插出第二行'


def test_revoke_perk(users):
    a, _ = users
    db.grant_user_perk(a, profile_spec.PERK_UNLOCK_ALL)
    assert db.revoke_user_perk(a, profile_spec.PERK_UNLOCK_ALL) is True
    assert db.has_user_perk(a, profile_spec.PERK_UNLOCK_ALL) is False
    # 收回不存在的也返回 True（幂等），但不该抛
    assert db.revoke_user_perk(a, profile_spec.PERK_UNLOCK_ALL) is True


def test_perk_dao_is_safe_on_bad_input(users):
    """空 uid / 空 perk 一律安全返回，不抛（与其它 DAO 同一风格）。"""
    assert db.list_user_perks('') == set()
    assert db.has_user_perk('', 'x') is False
    assert db.grant_user_perk('', 'x') is False
    assert db.grant_user_perk('u', '') is False
    assert db.get_perks_map([]) == {}
    assert db.get_perks_map(None) == {}


def test_perks_map_batches_rows(users):
    a, b = users
    db.grant_user_perk(a, profile_spec.PERK_RAINBOW_NAME)
    db.grant_user_perk(a, profile_spec.PERK_UNLOCK_ALL)
    m = db.get_perks_map([a, b, 'nobody'])
    assert m.get(a) == {profile_spec.PERK_RAINBOW_NAME, profile_spec.PERK_UNLOCK_ALL}
    assert b not in m or not m[b]


# ---------------------------------------------------------------------------
# 2. 特权 → 外观全解锁（判据一处，两处调用必须一致）
# ---------------------------------------------------------------------------
def test_all_cosmetics_locked_without_perk():
    plain = {'wins': 0, 'losses': 0, 'longest_streak': 0, 'created_at': 0, 'card_uses_total': 0}
    assert profile_spec.unlocked_titles(plain) == {'rookie'}
    assert profile_spec.unlocked_frames(plain) == {'none', 'silver'}
    assert profile_spec.unlocked_card_bgs(plain) == {'deep', 'graphite'}


def test_all_cosmetics_unlocked_with_flag():
    """带标记时**整池**解锁（不只多一两项）。"""
    vip = {'wins': 0, 'losses': 0, 'longest_streak': 0, 'created_at': 0,
           'card_uses_total': 0, profile_spec.UNLOCK_ALL_FLAG: True}
    assert profile_spec.unlocked_titles(vip) == {t['id'] for t in profile_spec.TITLES}
    assert profile_spec.unlocked_frames(vip) == {f['id'] for f in profile_spec.FRAMES}
    assert profile_spec.unlocked_card_bgs(vip) == {b['id'] for b in profile_spec.CARD_BGS}


def test_unlock_stats_injects_flag_from_perk(users):
    """api 层的组装点：持有 perk 就注入标记（catalog 与保存校验共用这一处）。"""
    a, b = users
    db.grant_user_perk(a, profile_spec.PERK_UNLOCK_ALL)
    stats_a = api._profile_unlock_stats(a)
    stats_b = api._profile_unlock_stats(b)
    assert profile_spec.has_unlock_all(stats_a) is True
    assert profile_spec.has_unlock_all(stats_b) is False


def test_catalog_marks_everything_unlocked_for_perk_user(users):
    a, _ = users
    db.grant_user_perk(a, profile_spec.PERK_UNLOCK_ALL)
    cat = profile_spec.catalog(api._profile_unlock_stats(a))
    for key in ('titles', 'frames', 'card_bgs'):
        assert all(item['unlocked'] for item in cat[key]), f'{key} 里有未解锁项'


def test_validate_payload_accepts_every_pool_id_for_perk_user(users):
    """保存校验也必须放行 —— 否则"解锁了但选不上"（两处口径不一致的经典漂移）。"""
    a, _ = users
    db.grant_user_perk(a, profile_spec.PERK_UNLOCK_ALL)
    stats = api._profile_unlock_stats(a)
    payload = {
        'title_id': 'immortal', 'tags': [], 'status_text': '', 'frame_id': 'crimson',
        'card_bg_id': 'aurora', 'show_stats': 1, 'show_fav_cards': 1,
        'show_history': 0, 'show_guestbook': 1,
    }
    fields, errors = profile_spec.validate_payload(payload, stats)
    assert errors == [], errors
    assert fields['title_id'] == 'immortal' and fields['frame_id'] == 'crimson'


def test_validate_payload_still_rejects_for_normal_user(users):
    """对照：普通账号选未解锁的照样被拒（特权没有被顺手放开给所有人）。"""
    _, b = users
    stats = api._profile_unlock_stats(b)
    payload = {
        'title_id': 'immortal', 'tags': [], 'status_text': '', 'frame_id': 'crimson',
        'card_bg_id': 'aurora', 'show_stats': 1, 'show_fav_cards': 1,
        'show_history': 0, 'show_guestbook': 1,
    }
    fields, errors = profile_spec.validate_payload(payload, stats)
    assert errors, '普通账号选未解锁项必须被拒'


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
def test_name_style_empty_without_perk(users):
    _, b = users
    assert api._name_style(b) == ''


def test_name_style_rainbow_with_perk(users):
    a, _ = users
    db.grant_user_perk(a, profile_spec.PERK_RAINBOW_NAME)
    assert api._name_style(a) == 'rainbow'


def test_user_stats_carries_name_style_for_others(users):
    """★ 关键：**别人**查我的 /user_stats 也要拿到 name_style，否则彩虹名字别人看不到。"""
    a, b = users
    db.grant_user_perk(a, profile_spec.PERK_RAINBOW_NAME)
    user_a = db.get_user(uid=a)
    r = _http(b).get('/user_stats?username=' + user_a['username'])
    assert r.status_code == 200
    stats = r.get_json()['stats']
    assert stats.get('name_style') == 'rainbow'
    # 对照：没特权的 B 自己是空串
    user_b = db.get_user(uid=b)
    r2 = _http(a).get('/user_stats?username=' + user_b['username'])
    assert r2.get_json()['stats'].get('name_style') == ''


def test_own_profile_carries_name_style(users):
    a, _ = users
    db.grant_user_perk(a, profile_spec.PERK_RAINBOW_NAME)
    r = _http(a).get('/api/profile')
    assert r.status_code == 200
    assert r.get_json()['profile'].get('name_style') == 'rainbow'


def test_leaderboard_rows_carry_name_style(users):
    a, b = users
    db.grant_user_perk(a, profile_spec.PERK_RAINBOW_NAME)
    rows = _http(b).get('/api/leaderboard?limit=100').get_json()
    by_id = {str(r.get('id')): r for r in rows}
    if a in by_id:
        assert by_id[a].get('name_style') == 'rainbow'
    if b in by_id:
        assert by_id[b].get('name_style') == ''


# ---------------------------------------------------------------------------
# 4. 结算事件 achievements_unlocked
# ---------------------------------------------------------------------------
def test_badge_details_shape():
    d = achievements.details('first_win')
    assert d['id'] == 'first_win'
    assert d['name'] and d['desc'] and d['group'] and d['requirement']
    assert achievements.details('no_such_badge') == {}


def test_details_covers_every_badge():
    """每一枚都能组装出详情（结算提示不会出现空条目）。"""
    for b in achievements.BADGES:
        d = achievements.details(b['id'])
        assert d.get('name') == b['name']
        assert d.get('group') == b['group']


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


def test_newly_granted_emits_to_player_only(users):
    """★ 结算时：本人收到 achievements_unlocked，对手**收不到**。

    用真实 test_client 两端 + 真实房间，直接调 `_grant_match_achievements`
    （它就是 `_finalize_match` 里负责授予与播报的那一步）。
    """
    a, b = users
    room = _make_room('perk-room', a, b)
    sa = server.socketio.test_client(server.app, flask_test_client=_http(a))
    sb = server.socketio.test_client(server.app, flask_test_client=_http(b))
    try:
        pa = room.players['pa']
        pb = room.players['pb']
        # ⚠️ 两件事都要做，否则断言会假红/假绿：
        #   ① `player.sid` 要设成**真实测试连接**的 sid —— `achievements_unlocked`
        #      是按 sid 单发给本人的，sid 不对就谁都收不到；
        #   ② 还要 `enter_room(sid, room.id)` —— 房间广播那句 message 是发到
        #      flask_socketio 的**房间**里的，连接没进房间就收不到（test_quick_chat.py
        #      的 fixture 也是这么做的）。
        for client, player in ((sa, pa), (sb, pb)):
            sid = server.socketio.server.manager.sid_from_eio_sid(client.eio_sid, '/')
            player.sid = sid
            server.socketio.server.enter_room(sid, room.id)
        sa.get_received(); sb.get_received()

        # 让 A 直接满足"首胜"（wins ≥ 1）
        db.db.conn.execute('UPDATE users SET wins = 1 WHERE id = ?', (a,))
        db.db.conn.commit()

        newly = server._grant_match_achievements(room, ((pa, a), (pb, b)))
        # ⚠️ `get_received()` 会**清空**队列 —— 只取一次再在本地过滤，
        # 否则第二次取就是空列表（这里第一次写成两次 get_received，白红了一条）。
        recv_a = sa.get_received()
        recv_b = sb.get_received()
        got_a = [e for e in recv_a if e['name'] == 'achievements_unlocked']
        got_b = [e for e in recv_b if e['name'] == 'achievements_unlocked']
        assert isinstance(newly, list)
        assert len(got_a) == 1, f'本人应当收到一条结算提示，实际 {len(got_a)}'
        payload = got_a[0]['args'][0]
        assert payload['count'] == len(payload['items']) >= 1
        ids = [i['id'] for i in payload['items']]
        assert 'first_win' in ids
        item = payload['items'][ids.index('first_win')]
        assert item['name'] == '首胜' and item['group']
        assert got_b == [], '对手不该收到本人的结算提示'
        # 房间广播那句（「XX 解锁了新徽章：…」）是**改动前就有的**行为，这里只确认它没被我改坏。
        # ⚠️ `get_received()` 里同一条事件的 `args` **可能是 dict 也可能是 tuple**
        #    （本机实测是 dict）—— 当成 tuple 去迭代会拿到键名，断言就变成"文案不对: []"
        #    这种看着像产品问题、其实是取形状取错的假红。两种都兜住。
        texts = []
        for ev in recv_a:
            if ev.get('name') != 'message':
                continue
            args = ev.get('args')
            if isinstance(args, dict):
                args = [args]
            for arg in (args or ()):
                if isinstance(arg, dict) and arg.get('text'):
                    texts.append(str(arg['text']))
        assert any('解锁了新徽章' in t for t in texts), f'房间广播文案不对: {texts}'
    finally:
        try:
            sa.disconnect(); sb.disconnect()
        except Exception:
            pass


def test_no_event_when_nothing_new(users):
    """没解锁新徽章时不发事件（否则每局都弹一次"刚解锁"）。"""
    a, b = users
    room = _make_room('perk-room2', a, b)
    sa = server.socketio.test_client(server.app, flask_test_client=_http(a))
    try:
        pa = room.players['pa']
        pa.sid = server.socketio.server.manager.sid_from_eio_sid(sa.eio_sid, '/')
        sa.get_received()
        # 0 胜 0 负：一枚都不达标
        db.db.conn.execute('UPDATE users SET wins = 0, losses = 0, longest_streak = 0 WHERE id = ?', (a,))
        db.db.conn.commit()
        server._grant_match_achievements(room, ((pa, a),))
        got = [e for e in sa.get_received() if e['name'] == 'achievements_unlocked']
        assert got == []
    finally:
        try:
            sa.disconnect()
        except Exception:
            pass
