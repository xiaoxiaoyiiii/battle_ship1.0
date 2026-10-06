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
