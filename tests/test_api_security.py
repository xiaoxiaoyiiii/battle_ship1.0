# -*- coding: utf-8 -*-
"""api.py 安全相关回归测试。

覆盖此前完全没有测试的高风险路径：
1. **头像上传魔数校验** —— 只信文件头不信扩展名，防止把任意文件（如脚本）
   改后缀后上传到 static/avatars 目录。这是一道明确的安全边界。
2. **改密流程** —— 旧密码必须对、新密码有长度下限、且受限流保护。
3. **限流逻辑** —— `_rate_limited` 是登录/注册/改密/API 登录共用的闸门，
   窗口内超过 10 次必须拒绝；内存字典超过 5000 条时要清理过期条目。
4. **/api/login** —— 密码对才发 token，错密码返回 401，同样受限流保护。
5. **/register** —— 用户名长度/字符集校验、密码长度、重名拒绝。

每个测试都用独立的 scope / IP，避免限流字典串台。
"""
import io
import time

import pytest
from werkzeug.security import generate_password_hash

import api
import server

PNG_HEAD = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
JPG_HEAD = b'\xff\xd8\xff\xe0' + b'\x00' * 64
GIF_HEAD = b'GIF89a' + b'\x00' * 64
TXT_HEAD = b'#!/bin/bash\nrm -rf /\n'


@pytest.fixture
def client():
    server.app.config['TESTING'] = True
    return server.app.test_client()


def _login(client, user_id='u1', username='tester'):
    """把 session 设成已登录，方便测需要登录态的接口。"""
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['username'] = username


# ===========================================================================
# 1. 头像上传：魔数校验（只信内容，不信扩展名）
# ===========================================================================
def test_avatar_requires_login(client):
    resp = client.post('/api/profile/avatar', data={})
    assert resp.status_code == 401


def test_avatar_accepts_valid_png(client, monkeypatch):
    called = {}

    def fake_update(uid, avatar):
        called['uid'] = uid
        called['avatar'] = avatar
        return True

    monkeypatch.setattr(server.db, 'update_user_avatar', fake_update)
    _login(client)
    data = {'avatar': (io.BytesIO(PNG_HEAD), 'me.png')}
    resp = client.post('/api/profile/avatar', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True
    assert called['avatar'].endswith('.png')


def test_avatar_accepts_valid_jpg_and_gif(client, monkeypatch):
    monkeypatch.setattr(server.db, 'update_user_avatar', lambda uid, a: True)
    _login(client)
    for head, name in ((JPG_HEAD, 'a.jpg'), (GIF_HEAD, 'b.gif')):
        data = {'avatar': (io.BytesIO(head), name)}
        resp = client.post('/api/profile/avatar', data=data, content_type='multipart/form-data')
        assert resp.status_code == 200, resp.get_json()


def test_avatar_rejects_wrong_magic_bytes(client, monkeypatch):
    """扩展名是 .png 但内容是脚本 → 必须拒绝（防改后缀上传任意文件）。"""
    monkeypatch.setattr(server.db, 'update_user_avatar', lambda *a, **k: (_ for _ in ()).throw(AssertionError('不该走到保存')))
    _login(client)
    data = {'avatar': (io.BytesIO(TXT_HEAD), 'evil.png')}
    resp = client.post('/api/profile/avatar', data=data, content_type='multipart/form-data')
    assert resp.status_code == 400
    assert '图片' in resp.get_json()['error']


def test_avatar_rejects_non_image_extension(client, monkeypatch):
    monkeypatch.setattr(server.db, 'update_user_avatar', lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    _login(client)
    data = {'avatar': (io.BytesIO(PNG_HEAD), 'doc.exe')}
    resp = client.post('/api/profile/avatar', data=data, content_type='multipart/form-data')
    assert resp.status_code == 400


def test_avatar_rejects_empty_filename(client, monkeypatch):
    monkeypatch.setattr(server.db, 'update_user_avatar', lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    _login(client)
    data = {'avatar': (io.BytesIO(PNG_HEAD), '')}
    resp = client.post('/api/profile/avatar', data=data, content_type='multipart/form-data')
    assert resp.status_code == 400


def test_avatar_rejects_missing_file_field(client):
    _login(client)
    resp = client.post('/api/profile/avatar', data={})
    assert resp.status_code == 400


def test_avatar_rejects_oversized_file(client, monkeypatch):
    """超过 2MB 的图片应被拒（MAX_CONTENT_LENGTH 在框架层拦，这里兜底层）。"""
    monkeypatch.setattr(server.db, 'update_user_avatar', lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    _login(client)
    big = PNG_HEAD + b'\x00' * (3 * 1024 * 1024)
    data = {'avatar': (io.BytesIO(big), 'big.png')}
    resp = client.post('/api/profile/avatar', data=data, content_type='multipart/form-data')
    # 框架层 MAX_CONTENT_LENGTH 会返回 413；若走到兜底层则是 400
    assert resp.status_code in (400, 413)


# ===========================================================================
# 2. 改密：旧密码校验 + 长度下限 + 限流
# ===========================================================================
def test_change_password_requires_login(client):
    resp = client.post('/api/change_password', data={})
    assert resp.status_code == 401


def test_change_password_wrong_old_password(client, monkeypatch):
    fake_user = {'id': 'u1', 'password_hash': generate_password_hash('correct')}
    monkeypatch.setattr(server.db, 'get_user', lambda **kw: dict(fake_user))
    monkeypatch.setattr(server.db, 'update_user_password', lambda *a, **k: (_ for _ in ()).throw(AssertionError('不该改密')))
    _login(client)
    resp = client.post('/api/change_password', data={'old_password': 'wrong', 'new_password': 'newpass'})
    assert resp.status_code == 403
    assert '原密码错误' in resp.get_json()['msg']


def test_change_password_short_new_password(client, monkeypatch):
    fake_user = {'id': 'u1', 'password_hash': generate_password_hash('correct')}
    monkeypatch.setattr(server.db, 'get_user', lambda **kw: dict(fake_user))
    monkeypatch.setattr(server.db, 'update_user_password', lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    _login(client)
    resp = client.post('/api/change_password', data={'old_password': 'correct', 'new_password': '12345'})
    assert resp.status_code == 400
    assert '6' in resp.get_json()['msg']


def test_change_password_success(client, monkeypatch):
    fake_user = {'id': 'u1', 'password_hash': generate_password_hash('correct')}
    updated = {}

    def fake_update(uid, pw_hash):
        updated['uid'] = uid
        updated['hash'] = pw_hash
        return True

    monkeypatch.setattr(server.db, 'get_user', lambda **kw: dict(fake_user))
    monkeypatch.setattr(server.db, 'update_user_password', fake_update)
    _login(client)
    resp = client.post('/api/change_password', data={'old_password': 'correct', 'new_password': 'newpass123'})
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True
    assert updated['uid'] == 'u1'


def test_change_password_empty_fields(client, monkeypatch):
    monkeypatch.setattr(server.db, 'get_user', lambda **kw: {'id': 'u1', 'password_hash': 'x'})
    _login(client)
    resp = client.post('/api/change_password', data={})
    assert resp.status_code == 400


# ===========================================================================
# 3. 限流逻辑
# ===========================================================================
@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """每个测试前清空调流字典，避免跨测试串台。"""
    api._login_attempts.clear()
    yield
    api._login_attempts.clear()


def test_rate_limit_blocks_after_threshold(monkeypatch):
    """同一 scope+IP 在窗口期内超过 10 次必须返回 True（被限流）。"""
    # 模拟请求上下文：_rate_limited 读 request.remote_addr
    with server.app.test_request_context('/'):
        monkeypatch.setattr(api, 'request', type('R', (), {'remote_addr': '1.2.3.4'})())
        for i in range(10):
            assert api._rate_limited('test_scope') is False
        # 第 11 次开始被拒
        assert api._rate_limited('test_scope') is True


def test_rate_limit_distinct_scopes_are_independent(monkeypatch):
    """不同 scope 的计数互不影响。"""
    with server.app.test_request_context('/'):
        monkeypatch.setattr(api, 'request', type('R', (), {'remote_addr': '9.9.9.9'})())
        for _ in range(10):
            api._rate_limited('scope_a')
        assert api._rate_limited('scope_a') is True
        assert api._rate_limited('scope_b') is False  # 另一个 scope 还没满


def test_rate_limit_distinct_ips_are_independent(monkeypatch):
    with server.app.test_request_context('/'):
        for _ in range(10):
            monkeypatch.setattr(api, 'request', type('R', (), {'remote_addr': '10.0.0.1'})())
            api._rate_limited('s')
        monkeypatch.setattr(api, 'request', type('R', (), {'remote_addr': '10.0.0.2'})())
        assert api._rate_limited('s') is False


def test_rate_limit_cleans_expired_entries(monkeypatch):
    """字典超过 5000 条时应清理过期 key，避免内存无限增长。"""
    old = time.time() - 120  # 远超 60s 窗口
    with server.app.test_request_context('/'):
        monkeypatch.setattr(api, 'request', type('R', (), {'remote_addr': '127.0.0.1'})())
        # 塞满 5001 个过期 key
        for i in range(5001):
            api._login_attempts[f'old:{i}'] = [old]
        # 触发清理：下一次调用不应抛异常，且过期条目被清掉
        assert api._rate_limited('cleanup_scope') is False
        assert len(api._login_attempts) < 5001


def test_rate_limit_integrates_with_api_login(client, monkeypatch):
    """连续 11 次错误登录后，第 11 次返回 429 而非 401。"""
    monkeypatch.setattr(server.db, 'get_user', lambda **kw: None)
    for i in range(10):
        resp = client.post('/api/login', json={'username': 'x', 'password': 'y'})
        assert resp.status_code == 401
    resp = client.post('/api/login', json={'username': 'x', 'password': 'y'})
    assert resp.status_code == 429


# ===========================================================================
# 4. /api/login：token 发放
# ===========================================================================
def test_api_login_returns_token_on_success(client, monkeypatch):
    fake_user = {'id': 'u1', 'password_hash': generate_password_hash('secret')}
    monkeypatch.setattr(server.db, 'get_user', lambda **kw: dict(fake_user))
    monkeypatch.setattr(server.db, 'get_token_by_password', lambda u, p: 'tok-123' if p == 'secret' else None)
    resp = client.post('/api/login', json={'username': 'alice', 'password': 'secret'})
    assert resp.status_code == 200
    assert resp.get_json()['token'] == 'tok-123'


def test_api_login_rejects_wrong_password(client, monkeypatch):
    fake_user = {'id': 'u1', 'password_hash': generate_password_hash('secret')}
    monkeypatch.setattr(server.db, 'get_user', lambda **kw: dict(fake_user))
    resp = client.post('/api/login', json={'username': 'alice', 'password': 'wrong'})
    assert resp.status_code == 401


def test_api_login_rejects_empty_credentials(client):
    resp = client.post('/api/login', json={})
    assert resp.status_code == 400


# ===========================================================================
# 5. /register：校验与重名
# ===========================================================================
def test_register_rejects_short_username(client, monkeypatch):
    monkeypatch.setattr(server.db, 'get_user', lambda **kw: None)
    monkeypatch.setattr(server.db, 'create_user', lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    resp = client.post('/register', data={'username': 'ab', 'password': '123456'})
    assert resp.status_code == 302  # redirect 回注册页
    assert 'register' in resp.headers['Location']


def test_register_rejects_invalid_username_chars(client, monkeypatch):
    monkeypatch.setattr(server.db, 'get_user', lambda **kw: None)
    monkeypatch.setattr(server.db, 'create_user', lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    resp = client.post('/register', data={'username': 'bad name!', 'password': '123456'})
    assert resp.status_code == 302


def test_register_rejects_short_password(client, monkeypatch):
    monkeypatch.setattr(server.db, 'get_user', lambda **kw: None)
    monkeypatch.setattr(server.db, 'create_user', lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    resp = client.post('/register', data={'username': 'validuser', 'password': '123'})
    assert resp.status_code == 302


def test_register_rejects_duplicate_username(client, monkeypatch):
    monkeypatch.setattr(server.db, 'get_user', lambda **kw: {'id': 'exists'})
    monkeypatch.setattr(server.db, 'create_user', lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    resp = client.post('/register', data={'username': 'taken', 'password': '123456'})
    assert resp.status_code == 302


def test_register_success_creates_session(client, monkeypatch):
    monkeypatch.setattr(server.db, 'get_user', lambda **kw: None)
    monkeypatch.setattr(server.db, 'create_user', lambda u, h: 'new-uid')
    resp = client.post('/register', data={'username': 'newuser', 'password': '123456'})
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/')  # 跳到首页
    with client.session_transaction() as sess:
        assert sess.get('user_id') == 'new-uid'
        assert sess.get('username') == 'newuser'


# ===========================================================================
# 6. /api/profile 与签名更新
# ===========================================================================
def test_profile_requires_login(client):
    resp = client.get('/api/profile')
    assert resp.status_code == 401


def test_profile_returns_public_fields(client, monkeypatch):
    monkeypatch.setattr(server.db, 'get_user_profile', lambda uid: {
        'id': uid, 'username': 'alice', 'signature': 'hi', 'avatar': '/a.png',
    })
    _login(client)
    resp = client.get('/api/profile')
    assert resp.status_code == 200
    profile = resp.get_json()['profile']
    assert profile['username'] == 'alice'
    assert profile['signature'] == 'hi'


def test_update_signature_requires_login(client):
    resp = client.post('/api/profile/signature', data={'signature': 'x'})
    assert resp.status_code == 401


def test_update_signature_success(client, monkeypatch):
    updated = {}

    def fake_update(uid, sig):
        updated['sig'] = sig
        return True

    monkeypatch.setattr(server.db, 'update_user_signature', fake_update)
    _login(client)
    resp = client.post('/api/profile/signature', data={'signature': 'hello world'})
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True
    assert updated['sig'] == 'hello world'


# ===========================================================================
# 7. asset_v 上下文处理器：静态资源缓存版本号
# ===========================================================================
def test_asset_v_returns_mtime_for_existing_file():
    """存在的静态文件返回 mtime（字符串化的 int），用于 ?v= 缓存破除。"""
    with server.app.test_request_context('/'):
        ctx = api._inject_asset_version()
        v = ctx['asset_v']('game.js')
        assert v.isdigit() and int(v) > 0


def test_asset_v_returns_zero_for_missing_file():
    """不存在的文件返回 '0' 而非抛异常（模板不应因为一个坏链接崩掉）。"""
    with server.app.test_request_context('/'):
        ctx = api._inject_asset_version()
        assert ctx['asset_v']('definitely-not-here.js') == '0'
