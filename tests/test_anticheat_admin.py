# -*- coding: utf-8 -*-
"""反作弊管理后台 + 阶梯封禁的**端到端**测试（2026-09-20）。

纯函数层已在 `tests/test_suspicion.py`（28 条）。本文件验证**接线**：
  A. 管理员门禁 —— 非管理员**一律进不来**（这是安全边界，最重要）
  B. 干预写入/读取 —— 解封、加封、历史可审计
  C. ★ 封禁真的**生效** —— 走真实 socket handler，断言被拦
  D. 每局嫌疑度**按人落库**（累计的数据来源）
"""
import itertools

import pytest

import db
import server
import suspicion

_seq = itertools.count(1)
_TAG = 'adm9'


def _mk_user():
    name = f'{_TAG}{next(_seq)}'
    uid = db.create_user(name, 'x' * 12)
    assert uid, f'建号失败: {name}'
    return uid


def _purge(uids):
    try:
        with db.db._lock:
            for uid in uids:
                if not uid:
                    continue
                for table in ('user_rank', 'user_xp', 'user_counters',
                              'user_achievements'):
                    try:
                        db.db.conn.execute(f'DELETE FROM {table} WHERE user_id = ?', (uid,))
                    except Exception:
                        pass
                try:
                    db.db.conn.execute('DELETE FROM match_suspicion WHERE user_id = ?', (uid,))
                    db.db.conn.execute('DELETE FROM anticheat_overrides WHERE user_id = ?', (uid,))
                except Exception:
                    pass
            db.db.conn.commit()
    except Exception:
        pass


@pytest.fixture
def http():
    """一个未登录 / 可指定登录身份的 test_client 工厂。"""
    made = []

    def _make(uid=None):
        c = server.app.test_client()
        if uid:
            with c.session_transaction() as sess:
                sess['user_id'] = uid
                sess['username'] = uid
        made.append(c)
        return c

    yield _make


# ===========================================================================
# A. ★ 管理员门禁（安全边界）
# ===========================================================================
def test_admin_me_false_for_normal_user(http, monkeypatch):
    monkeypatch.setattr(server, 'DEBUG_ADMIN_USER_IDS', {'owner-1'})
    u = _mk_user()
    try:
        r = http(u).get('/api/admin/me')
        assert r.status_code == 200
        assert r.get_json()['is_admin'] is False
    finally:
        _purge([u])


def test_admin_me_true_for_admin(http, monkeypatch):
    monkeypatch.setattr(server, 'DEBUG_ADMIN_USER_IDS', {'owner-1'})
    try:
        r = http('owner-1').get('/api/admin/me')
        assert r.get_json()['is_admin'] is True
    finally:
        pass


def test_normal_user_cannot_list_suspicion(http, monkeypatch):
    """★ 普通玩家拉全服嫌疑度 → 403。"""
    monkeypatch.setattr(server, 'DEBUG_ADMIN_USER_IDS', {'owner-1'})
    u = _mk_user()
    try:
        r = http(u).get('/api/admin/suspicion')
        assert r.status_code == 403, '普通玩家不该能读全服嫌疑度'
    finally:
        _purge([u])


def test_normal_user_cannot_read_other_player(http, monkeypatch):
    """★ 普通玩家查别人 → 403（隐私）。"""
    monkeypatch.setattr(server, 'DEBUG_ADMIN_USER_IDS', {'owner-1'})
    target = _mk_user()
    u = _mk_user()
    try:
        r = http(u).get(f'/api/admin/player/{target}')
        assert r.status_code == 403
    finally:
        _purge([target, u])


def test_normal_user_cannot_override(http, monkeypatch):
    """★ 普通玩家给自己解封 → 403（最关键的一条）。"""
    monkeypatch.setattr(server, 'DEBUG_ADMIN_USER_IDS', {'owner-1'})
    u = _mk_user()
    try:
        r = http(u).post(f'/api/admin/player/{u}/override',
                         json={'cleared': True})
        assert r.status_code == 403, '普通玩家绝不能给自己解封'
        assert db.get_anticheat_override(u) is None
    finally:
        _purge([u])


def test_empty_allowlist_denies_everyone(http, monkeypatch):
    """★ 白名单为空 = **谁都不是管理员**（默认安全）。

    绝不能写成"空就放行" —— 那等于线上没配管理员时门户大开。
    """
    monkeypatch.setattr(server, 'DEBUG_ADMIN_USER_IDS', set())
    u = _mk_user()
    try:
        assert http(u).get('/api/admin/suspicion').status_code == 403
        assert http(u).post(f'/api/admin/player/{u}/override',
                            json={'cleared': True}).status_code == 403
    finally:
        _purge([u])


def test_anonymous_gets_401(http, monkeypatch):
    monkeypatch.setattr(server, 'DEBUG_ADMIN_USER_IDS', {'owner-1'})
    assert http().get('/api/admin/suspicion').status_code == 401


# ===========================================================================
# B. 干预：写入 / 读取 / 审计
# ===========================================================================
def test_admin_can_clear_ban(http, monkeypatch):
    monkeypatch.setattr(server, 'DEBUG_ADMIN_USER_IDS', {'owner-1'})
    u = _mk_user()
    try:
        r = http('owner-1').post(f'/api/admin/player/{u}/override',
                                 json={'cleared': True, 'reason': '误判'})
        assert r.status_code == 200
        assert r.get_json()['success'] is True
        ov = db.get_anticheat_override(u)
        assert ov is not None
        assert ov['cleared'] == 1
        assert ov['reason'] == '误判'
        assert ov['actor'] == 'owner-1', '必须记录是谁解的封（可审计）'
    finally:
        _purge([u])


def test_admin_can_set_level(http, monkeypatch):
    monkeypatch.setattr(server, 'DEBUG_ADMIN_USER_IDS', {'owner-1'})
    u = _mk_user()
    try:
        r = http('owner-1').post(f'/api/admin/player/{u}/override',
                                 json={'level': 2, 'reason': '确认刷分'})
        assert r.status_code == 200
        ov = db.get_anticheat_override(u)
        assert ov['level'] == 2 and ov['cleared'] == 0
    finally:
        _purge([u])


def test_override_rejects_bad_level(http, monkeypatch):
    monkeypatch.setattr(server, 'DEBUG_ADMIN_USER_IDS', {'owner-1'})
    u = _mk_user()
    try:
        c = http('owner-1')
        assert c.post(f'/api/admin/player/{u}/override', json={'level': 99}).status_code == 400
        assert c.post(f'/api/admin/player/{u}/override', json={'level': 'x'}).status_code == 400
        assert c.post(f'/api/admin/player/{u}/override', json={}).status_code == 400
        assert db.get_anticheat_override(u) is None, '非法请求不许写库'
    finally:
        _purge([u])


def test_override_history_is_append_only(http, monkeypatch):
    """★ 干预历史**只追加不覆盖** —— 否则无法审计。"""
    monkeypatch.setattr(server, 'DEBUG_ADMIN_USER_IDS', {'owner-1'})
    u = _mk_user()
    try:
        c = http('owner-1')
        c.post(f'/api/admin/player/{u}/override', json={'cleared': True, 'reason': 'A'})
        c.post(f'/api/admin/player/{u}/override', json={'level': 3, 'reason': 'B'})
        hist = db.get_anticheat_override_history(u)
        assert len(hist) == 2, '两次干预都要留痕'
        # 最新一条在前
        assert hist[0]['reason'] == 'B'
    finally:
        _purge([u])


def test_player_report_has_stats_and_flags(http, monkeypatch):
    """报告里必须同时有：战绩、嫌疑度、封禁等级、干预历史。"""
    monkeypatch.setattr(server, 'DEBUG_ADMIN_USER_IDS', {'owner-1'})
    u = _mk_user()
    try:
        r = http('owner-1').get(f'/api/admin/player/{u}')
        assert r.status_code == 200
        p = r.get_json()['player']
        for key in ('user_id', 'username', 'suspicion', 'level', 'level_name',
                    'blocked', 'stats', 'flagged_matches', 'override_history'):
            assert key in p, f'报告缺少 {key}'
        assert 'wins' in p['stats'] and 'rank_points' in p['stats']
    finally:
        _purge([u])


# ===========================================================================
# C. ★ 封禁真的生效（走真实 handler）
# ===========================================================================
def _as_request(monkeypatch, sid, uid=None):
    import types
    monkeypatch.setattr(server, 'request', types.SimpleNamespace(sid=sid))
    monkeypatch.setattr(
        server, 'session',
        types.SimpleNamespace(get=lambda k, d=None: uid if k == 'user_id' else d))
    monkeypatch.setattr(server, 'join_room', lambda *a, **k: None)


def _capture_emit(monkeypatch):
    sent = []
    monkeypatch.setattr(server, 'emit',
                        lambda event, data, to=None, room=None: sent.append(
                            {'name': event, 'data': data}))
    return sent


def test_banned_user_cannot_find_ranked_match(monkeypatch):
    """★ 1 级封禁（禁排位）→ 真实 find_match(ranked) 被拦。"""
    u = _mk_user()
    try:
        db.set_anticheat_override(u, level=1, reason='test', actor='t')
        _as_request(monkeypatch, 'sid-x', uid=u)
        sent = _capture_emit(monkeypatch)
        res = server.handle_find_match({'player_name': '甲', 'mode': 'ranked'})
        assert res['status'] == 'error', '被封排位的人不该进队列'
        assert any(e['name'] == 'error' for e in sent), '必须给玩家一个提示'
        assert not server.room_manager.has_player_in_match_queue('sid-x')
    finally:
        _purge([u])


def test_level1_still_allows_casual(monkeypatch):
    """★ 反向守卫：1 级**只**禁排位，休闲仍然能玩（逐级收紧，不许一刀切）。"""
    u = _mk_user()
    try:
        db.set_anticheat_override(u, level=1, reason='test', actor='t')
        _as_request(monkeypatch, 'sid-c', uid=u)
        _capture_emit(monkeypatch)
        res = server.handle_find_match({'player_name': '甲', 'mode': 'casual'})
        assert res.get('status') != 'error', f'休闲不该被 1 级封禁拦住: {res}'
    finally:
        _purge([u])
        server.room_manager.remove_from_match_queue('sid-c')


def test_level2_blocks_casual_too(monkeypatch):
    """★ 2 级（禁匹配）→ 连休闲也拦。"""
    u = _mk_user()
    try:
        db.set_anticheat_override(u, level=2, reason='test', actor='t')
        _as_request(monkeypatch, 'sid-m', uid=u)
        _capture_emit(monkeypatch)
        res = server.handle_find_match({'player_name': '甲', 'mode': 'casual'})
        assert res['status'] == 'error', '2 级必须连休闲也拦'
    finally:
        _purge([u])


def test_level3_blocks_create_room(monkeypatch):
    """★ 3 级（禁房间）→ 建房被拦，且**不许先建出房来**。"""
    u = _mk_user()
    try:
        db.set_anticheat_override(u, level=3, reason='test', actor='t')
        _as_request(monkeypatch, 'sid-r', uid=u)
        sent = _capture_emit(monkeypatch)
        before = len(server.room_manager.get_all_rooms())
        res = server.handle_create_room({'player_name': '甲'})
        after = len(server.room_manager.get_all_rooms())
        assert res['status'] == 'error'
        assert after == before, '闸门必须在建房之前 —— 否则会挂出进不去的房'
        assert any(e['name'] == 'error' for e in sent)
    finally:
        _purge([u])


def test_level3_blocks_join_room(monkeypatch):
    """★ 3 级 → 进别人的房也被拦。"""
    u = _mk_user()
    try:
        db.set_anticheat_override(u, level=3, reason='test', actor='t')
        _as_request(monkeypatch, 'sid-j', uid=u)
        sent = _capture_emit(monkeypatch)
        res = server.handle_join_room({'room_id': 'whatever'})
        assert res['status'] == 'error'
        assert any(e['name'] == 'error' for e in sent)
    finally:
        _purge([u])


def test_clean_user_not_blocked(monkeypatch):
    """★ 反向守卫：没被封的人一切照常（封禁不许误伤）。"""
    u = _mk_user()
    try:
        _as_request(monkeypatch, 'sid-ok', uid=u)
        _capture_emit(monkeypatch)
        assert server.handle_find_match(
            {'player_name': '甲', 'mode': 'ranked'}).get('status') != 'error'
    finally:
        _purge([u])
        server.room_manager.remove_from_match_queue('sid-ok')


def test_enforcement_fails_open(monkeypatch):
    """★ 封禁判定炸了 → **放行**（失败开放）。

    宁可漏拦一个作弊者，也不能因为判据故障把正常玩家挡在门外。
    """
    u = _mk_user()
    try:
        def _boom(*a, **k):
            raise RuntimeError('判定崩了')
        monkeypatch.setattr(server, '_suspicion_level', _boom)
        _as_request(monkeypatch, 'sid-f', uid=u)
        _capture_emit(monkeypatch)
        assert server.handle_find_match(
            {'player_name': '甲', 'mode': 'ranked'}).get('status') != 'error'
    finally:
        _purge([u])
        server.room_manager.remove_from_match_queue('sid-f')


# ===========================================================================
# D. 每局按人落库（累计的数据来源）
# ===========================================================================
def test_match_suspicion_recorded_for_both_sides():
    """一局的嫌疑度要**双方各记一条**（靶子也要记 —— 他自己可能就是小号）。"""
    from server import GameRoom, Player, PlayerShip, Position
    room = GameRoom('susp-room')
    pa = Player('甲', [PlayerShip([Position(0, 0)], [])], [], 1, user_id='u-a')
    pb = Player('乙', [PlayerShip([Position(1, 0)], [])], [], 1, user_id='u-b')
    room.players = {'pa': pa, 'pb': pb}
    try:
        server._record_match_suspicion_for(room, {'score': 40, 'level': 'record'})
        a = db.get_match_suspicion('u-a')
        b = db.get_match_suspicion('u-b')
        assert any(str(r['match_id']).startswith('susp-room') for r in a)
        assert any(str(r['match_id']).startswith('susp-room') for r in b)
        assert a[0]['score'] == 40
    finally:
        _purge(['u-a', 'u-b'])


def test_recording_never_raises():
    """落库失败绝不许把对局结算搞崩。"""
    server._record_match_suspicion_for(None, None)
    server._record_match_suspicion_for(object(), {'score': 'abc'})
