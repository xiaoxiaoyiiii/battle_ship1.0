# -*- coding: utf-8 -*-
"""api.py 安全与数据校验回归测试。

背景：api.py 承载了登录、注册、改密、头像上传等鉴权/输入校验入口，但此前
整条链路零覆盖。这些路径一旦回归，后果是账号接管、任意文件上传、暴力破解
无门槛等严重安全事故。本文件按「最小可证明」原则补齐：
  * _rate_limited 限流器本身（窗口、上限、过期清理、作用域隔离）
  * 头像上传：扩展名 + 真实魔数 + 体积三重校验（防改扩展名上传恶意文件）
  * 改密：旧密码校验、新密码长度、限流
  * 注册：用户名/密码格式、重名、限流
  * 登录：凭据校验、空字段、限流
  * /user_stats 的 limit 未钳制（与 /api/leaderboard 对比，标记风险）

每个测试都清掉限流器的内存状态，保证可独立重跑。
"""
import io
import time

import pytest

import api
from api import app

PNG_MAGIC = b'\x89PNG\r\n\x1a\n'
JPEG_MAGIC = b'\xff\xd8\xff'
GIF_MAGIC = b'GIF89a'


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """每个测试前清空限流器内存字典，避免跨用例互相污染。"""
    api._login_attempts.clear()
    yield
    api._login_attempts.clear()


# ---------------------------------------------------------------------------
# 1. _rate_limited 限流器核心逻辑
# ---------------------------------------------------------------------------
def test_rate_limiter_allows_first_attempts():
    """窗口内前 _LOGIN_MAX_ATTEMPTS 次必须放行。"""
    with app.test_request_context():
        for _ in range(api._LOGIN_MAX_ATTEMPTS):
            assert api._rate_limited('login') is False


def test_rate_limiter_blocks_after_max_attempts():
    """超过上限后必须返回 True（拒绝）。"""
    with app.test_request_context():
        for _ in range(api._LOGIN_MAX_ATTEMPTS):
            api._rate_limited('login')
        assert api._rate_limited('login') is True


def test_rate_limiter_scopes_are_isolated():
    """不同 scope 互不影响：login 超限不该让 register 也被拒。"""
    with app.test_request_context():
        for _ in range(api._LOGIN_MAX_ATTEMPTS):
            api._rate_limited('login')
        assert api._rate_limited('login') is True
        assert api._rate_limited('register') is False


def test_rate_limiter_cleans_expired_keys(monkeypatch):
    """字典超过 5000 时清理过期项，避免内存无限增长。"""
    now = time.time()
    api._login_attempts.update({
        f'scope:ip{i}': [now - 120] for i in range(5001)  # 全部已过期
    })
    monkeypatch.setattr(api.time, 'time', lambda: now)
    with app.test_request_context():
        api._rate_limited('fresh')  # 触发清理分支
    # 清理后只剩当前 scope:ip 这一条（fresh）
    assert len(api._login_attempts) == 1


def test_rate_limiter_keeps_recent_keys_while_cleaning(monkeypatch):
    """清理时只清过期项，仍在窗口内的 key 必须保留。"""
    now = time.time()
    api._login_attempts['login:127.0.0.1'] = [now - 5]   # 仍在窗口内
    api._login_attempts.update({
        f'stale:ip{i}': [now - 120] for i in range(5000)  # 全部过期
    })
    monkeypatch.setattr(api.time, 'time', lambda: now)
    with app.test_request_context():
        api._rate_limited('other')  # 触发清理
    # login 那条仍在窗口内，必须保留
    assert 'login:127.0.0.1' in api._login_attempts


# ---------------------------------------------------------------------------
# 2. /api/profile/avatar 头像上传安全
# ---------------------------------------------------------------------------
def _avatar_payload(content: bytes, filename: str):
    return {'avatar': (io.BytesIO(content), filename)}


def test_avatar_requires_login():
    client = app.test_client()
    resp = client.post('/api/profile/avatar',
                       data=_avatar_payload(PNG_MAGIC, 'x.png'),
                       content_type='multipart/form-data')
    assert resp.status_code == 401


def test_avatar_rejects_missing_file():
    client = app.test_client()
    with client.session_transaction() as s:
        s['user_id'] = 'u1'
    resp = client.post('/api/profile/avatar', data={},
                       content_type='multipart/form-data')
    assert resp.status_code == 400
    assert resp.get_json()['error'] == '未选择文件'


def test_avatar_rejects_empty_filename():
    client = app.test_client()
    with client.session_transaction() as s:
        s['user_id'] = 'u1'
    resp = client.post('/api/profile/avatar',
                       data=_avatar_payload(PNG_MAGIC, ''),
                       content_type='multipart/form-data')
    assert resp.status_code == 400


def test_avatar_rejects_unsupported_extension():
    client = app.test_client()
    with client.session_transaction() as s:
        s['user_id'] = 'u1'
    resp = client.post('/api/profile/avatar',
                       data=_avatar_payload(PNG_MAGIC, 'x.exe'),
                       content_type='multipart/form-data')
    assert resp.status_code == 400
    assert resp.get_json()['error'] == '文件类型不支持'


def test_avatar_rejects_fake_extension_with_wrong_magic():
    """扩展名是 .png 但内容不是 PNG 魔数 → 必须拒绝（防改扩展名上传）。"""
    client = app.test_client()
    with client.session_transaction() as s:
        s['user_id'] = 'u1'
    # 文本内容伪装成 .png
    resp = client.post('/api/profile/avatar',
                       data=_avatar_payload(b'#!/bin/sh\nrm -rf /', 'evil.png'),
                       content_type='multipart/form-data')
    assert resp.status_code == 400
    assert resp.get_json()['error'] == '文件内容不是有效的图片'


def test_avatar_accepts_valid_png(monkeypatch):
    client = app.test_client()
    with client.session_transaction() as s:
        s['user_id'] = 'u1'
    saved = []
    monkeypatch.setattr(api.db, 'update_user_avatar',
                        lambda uid, url: saved.append((uid, url)) or True)
    # 用一个临时目录做上传目标，避免污染 static/avatars
    monkeypatch.setattr(api, 'AVATAR_UPLOAD_FOLDER', '/tmp/battleship-avatar-test')
    import os
    os.makedirs(api.AVATAR_UPLOAD_FOLDER, exist_ok=True)
    resp = client.post('/api/profile/avatar',
                       data=_avatar_payload(PNG_MAGIC + b'\x00' * 100, 'ok.png'),
                       content_type='multipart/form-data')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    assert body['avatar'].endswith('.png')
    assert saved and saved[0][0] == 'u1'


def test_avatar_accepts_jpeg_and_gif_magic(monkeypatch):
    """JPEG / GIF 魔数必须放行（不仅限 PNG）。"""
    monkeypatch.setattr(api, 'AVATAR_UPLOAD_FOLDER', '/tmp/battleship-avatar-test')
    import os
    os.makedirs(api.AVATAR_UPLOAD_FOLDER, exist_ok=True)
    monkeypatch.setattr(api.db, 'update_user_avatar', lambda *a, **k: True)
    for magic, ext in ((JPEG_MAGIC, 'jpg'), (GIF_MAGIC, 'gif')):
        client = app.test_client()
        with client.session_transaction() as s:
            s['user_id'] = 'u1'
        resp = client.post('/api/profile/avatar',
                           data=_avatar_payload(magic + b'\x00' * 50, f'pic.{ext}'),
                           content_type='multipart/form-data')
        assert resp.status_code == 200, f'{ext} should be accepted'


def test_avatar_rejects_oversized_file(monkeypatch):
    """超过 2MB 必须拒绝（MAX_CONTENT_LENGTH 在框架层拦截，这里测显式兜底）。"""
    client = app.test_client()
    with client.session_transaction() as s:
        s['user_id'] = 'u1'
    monkeypatch.setattr(api, 'AVATAR_UPLOAD_FOLDER', '/tmp/battleship-avatar-test')
    # 构造 2MB + 1 字节的 PNG
    big = PNG_MAGIC + b'\x00' * (2 * 1024 * 1024 + 1)
    resp = client.post('/api/profile/avatar',
                       data=_avatar_payload(big, 'big.png'),
                       content_type='multipart/form-data')
    # 框架层 MAX_CONTENT_LENGTH 会返回 413；若走到显式校验则是 400
    assert resp.status_code in (400, 413)


# ---------------------------------------------------------------------------
# 2b. /api/profile (GET) 与 /api/profile/signature (POST)
# ---------------------------------------------------------------------------
def test_profile_requires_login():
    client = app.test_client()
    resp = client.get('/api/profile')
    assert resp.status_code == 401


def test_profile_returns_public_fields_only(monkeypatch):
    monkeypatch.setattr(api.db, 'get_user_profile',
                        lambda uid: {'id': uid, 'username': 'x',
                                     'signature': 'hi', 'avatar': '/a.png'})
    client = app.test_client()
    with client.session_transaction() as s:
        s['user_id'] = 'u1'
    resp = client.get('/api/profile')
    assert resp.status_code == 200
    profile = resp.get_json()['profile']
    assert profile['username'] == 'x'
    assert profile['signature'] == 'hi'
    # get_user_profile 只查 4 个字段，这里确认不会额外泄露
    assert set(profile.keys()) <= {'id', 'username', 'signature', 'avatar'}


def test_update_signature_requires_login():
    client = app.test_client()
    resp = client.post('/api/profile/signature', data={'signature': 'hi'})
    assert resp.status_code == 401


def test_update_signature_success(monkeypatch):
    updated = []
    monkeypatch.setattr(api.db, 'update_user_signature',
                        lambda uid, sig: updated.append((uid, sig)) or True)
    client = app.test_client()
    with client.session_transaction() as s:
        s['user_id'] = 'u1'
    resp = client.post('/api/profile/signature', data={'signature': 'new sig'})
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True
    assert updated == [('u1', 'new sig')]


# ---------------------------------------------------------------------------
# 3. /api/change_password 改密
# ---------------------------------------------------------------------------
def test_change_password_requires_login():
    client = app.test_client()
    resp = client.post('/api/change_password',
                       data={'old_password': 'x', 'new_password': 'y'})
    assert resp.status_code == 401


def test_change_password_rejects_empty_fields():
    client = app.test_client()
    with client.session_transaction() as s:
        s['user_id'] = 'u1'
    resp = client.post('/api/change_password', data={})
    assert resp.status_code == 400
    assert resp.get_json()['msg'] == '请填写原密码和新密码'


def test_change_password_rejects_wrong_old_password(monkeypatch):
    from werkzeug.security import generate_password_hash
    monkeypatch.setattr(api.db, 'get_user',
                        lambda uid: {'id': uid, 'password_hash': generate_password_hash('correct')})
    client = app.test_client()
    with client.session_transaction() as s:
        s['user_id'] = 'u1'
    resp = client.post('/api/change_password',
                       data={'old_password': 'wrong', 'new_password': 'newpass123'})
    assert resp.status_code == 403
    assert resp.get_json()['msg'] == '原密码错误'


def test_change_password_rejects_short_new_password(monkeypatch):
    from werkzeug.security import generate_password_hash
    monkeypatch.setattr(api.db, 'get_user',
                        lambda uid: {'id': uid, 'password_hash': generate_password_hash('correct')})
    client = app.test_client()
    with client.session_transaction() as s:
        s['user_id'] = 'u1'
    resp = client.post('/api/change_password',
                       data={'old_password': 'correct', 'new_password': '12345'})
    assert resp.status_code == 400
    assert resp.get_json()['msg'] == '新密码长度至少6位'


def test_change_password_success(monkeypatch):
    from werkzeug.security import generate_password_hash
    monkeypatch.setattr(api.db, 'get_user',
                        lambda uid: {'id': uid, 'password_hash': generate_password_hash('correct')})
    updated = []
    monkeypatch.setattr(api.db, 'update_user_password',
                        lambda uid, h: updated.append((uid, h)) or True)
    client = app.test_client()
    with client.session_transaction() as s:
        s['user_id'] = 'u1'
    resp = client.post('/api/change_password',
                       data={'old_password': 'correct', 'new_password': 'newpass123'})
    assert resp.status_code == 200
    assert resp.get_json()['success'] is True
    assert updated and updated[0][0] == 'u1'


def test_change_password_rate_limited(monkeypatch):
    """超限后直接 429，不再校验密码。"""
    monkeypatch.setattr(api.db, 'get_user', lambda uid: {'id': uid, 'password_hash': 'x'})
    client = app.test_client()
    with client.session_transaction() as s:
        s['user_id'] = 'u1'
    for _ in range(api._LOGIN_MAX_ATTEMPTS + 1):
        client.post('/api/change_password',
                    data={'old_password': 'x', 'new_password': 'y'})
    resp = client.post('/api/change_password',
                       data={'old_password': 'x', 'new_password': 'y'})
    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# 4. /register 注册
# ---------------------------------------------------------------------------
def test_register_rejects_empty_username():
    client = app.test_client()
    resp = client.post('/register', data={'username': '', 'password': 'pass123'})
    # 重定向到 register（flash 提示），不应该创建用户
    assert resp.status_code in (301, 302)


def test_register_rejects_short_username(monkeypatch):
    created = []
    monkeypatch.setattr(api.db, 'create_user', lambda *a: created.append(a) or 'uid')
    monkeypatch.setattr(api.db, 'get_user', lambda **kw: None)
    client = app.test_client()
    resp = client.post('/register', data={'username': 'ab', 'password': 'pass123'})
    assert resp.status_code in (301, 302)
    assert created == [], '用户名 < 3 位不得调用 create_user'


def test_register_rejects_invalid_username_chars(monkeypatch):
    created = []
    monkeypatch.setattr(api.db, 'create_user', lambda *a: created.append(a) or 'uid')
    monkeypatch.setattr(api.db, 'get_user', lambda **kw: None)
    client = app.test_client()
    resp = client.post('/register', data={'username': 'bad name', 'password': 'pass123'})
    assert resp.status_code in (301, 302)
    assert created == []


def test_register_rejects_short_password(monkeypatch):
    created = []
    monkeypatch.setattr(api.db, 'create_user', lambda *a: created.append(a) or 'uid')
    monkeypatch.setattr(api.db, 'get_user', lambda **kw: None)
    client = app.test_client()
    resp = client.post('/register', data={'username': 'valid', 'password': '12345'})
    assert resp.status_code in (301, 302)
    assert created == [], '密码 < 6 位不得调用 create_user'


def test_register_rejects_duplicate_username(monkeypatch):
    monkeypatch.setattr(api.db, 'get_user', lambda **kw: {'id': 'exists'})
    created = []
    monkeypatch.setattr(api.db, 'create_user', lambda *a: created.append(a) or 'uid')
    client = app.test_client()
    resp = client.post('/register', data={'username': 'taken', 'password': 'pass123'})
    assert resp.status_code in (301, 302)
    assert created == [], '重名用户不得重复创建'


def test_register_success_sets_session(monkeypatch):
    from werkzeug.security import check_password_hash
    created = []

    def fake_create_user(username, pw_hash):
        created.append((username, pw_hash))
        return 'new-uid'

    monkeypatch.setattr(api.db, 'create_user', fake_create_user)
    monkeypatch.setattr(api.db, 'get_user', lambda **kw: None)
    client = app.test_client()
    resp = client.post('/register', data={'username': 'gooduser', 'password': 'pass123'})
    assert resp.status_code in (301, 302)
    assert created and created[0][0] == 'gooduser'
    # 密码必须以哈希形式存储，不能明文
    assert not check_password_hash(created[0][1], 'wrong')
    assert check_password_hash(created[0][1], 'pass123')


def test_register_rate_limited(monkeypatch):
    """注册接口同样受限流保护。"""
    monkeypatch.setattr(api.db, 'get_user', lambda **kw: None)
    client = app.test_client()
    for _ in range(api._LOGIN_MAX_ATTEMPTS + 1):
        client.post('/register', data={'username': 'x', 'password': 'pass123'})
    # 被限流时重定向回 register，且不创建用户
    created = []
    monkeypatch.setattr(api.db, 'create_user', lambda *a: created.append(a) or 'uid')
    resp = client.post('/register', data={'username': 'y', 'password': 'pass123'})
    assert resp.status_code in (301, 302)
    assert created == []


# ---------------------------------------------------------------------------
# 5. /api/login 登录
# ---------------------------------------------------------------------------
def test_api_login_rejects_empty_credentials():
    client = app.test_client()
    resp = client.post('/api/login', json={})
    assert resp.status_code == 400
    assert resp.get_json()['error'] == '用户名或密码不能为空'


def test_api_login_rejects_wrong_credentials(monkeypatch):
    monkeypatch.setattr(api.db, 'get_user',
                        lambda **kw: {'id': 'u1', 'password_hash': 'hash'})
    monkeypatch.setattr(api.db, 'get_token_by_password', lambda *a: None)
    client = app.test_client()
    resp = client.post('/api/login', json={'username': 'x', 'password': 'wrong'})
    assert resp.status_code == 401
    assert resp.get_json()['error'] == '用户名或密码错误'


def test_api_login_success_returns_token(monkeypatch):
    from werkzeug.security import generate_password_hash
    monkeypatch.setattr(api.db, 'get_user',
                        lambda **kw: {'id': 'u1', 'password_hash': generate_password_hash('secret')})
    monkeypatch.setattr(api.db, 'get_token_by_password', lambda u, p: 'fake-token')
    client = app.test_client()
    resp = client.post('/api/login', json={'username': 'x', 'password': 'secret'})
    assert resp.status_code == 200
    assert resp.get_json()['token'] == 'fake-token'


def test_api_login_rate_limited(monkeypatch):
    """登录暴力破解必须被限流。"""
    monkeypatch.setattr(api.db, 'get_user', lambda **kw: None)
    client = app.test_client()
    for _ in range(api._LOGIN_MAX_ATTEMPTS + 1):
        client.post('/api/login', json={'username': 'x', 'password': 'y'})
    resp = client.post('/api/login', json={'username': 'x', 'password': 'y'})
    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# 6. /user_stats 的 limit 未钳制（与 leaderboard 对比）
# ---------------------------------------------------------------------------
def test_user_stats_limit_not_clamped(monkeypatch):
    """⚠️ 风险标记：/user_stats 的 limit 不像 /api/leaderboard 那样钳制到 1-100。

    传 limit=999999 会原样透传给 db.get_match_history，虽然后者内部会钳制，
    但这是依赖下游的偶然行为，接口层没有显式防护。本测试锁死当前行为，
    提醒维护者：若未来 get_match_history 去掉钳制，这里会变成 DoS 面。
    """
    monkeypatch.setattr(api.db, 'get_user',
                        lambda **kw: {'id': 'u1', 'username': 'x', 'wins': 0,
                                      'losses': 0, 'current_streak': 0,
                                      'longest_streak': 0, 'created_at': 0,
                                      'signature': '', 'avatar': ''})
    received = []
    monkeypatch.setattr(api.db, 'get_match_history',
                        lambda uid, limit=20: received.append(limit) or [])
    client = app.test_client()
    client.get('/user_stats?username=x&limit=999999')
    # 当前行为：原样透传超大值（下游 db.get_match_history 才钳制）
    assert received == [999999], (
        '若此断言失败，说明接口层已加上钳制 —— 这是好事，'
        '请把本测试改为断言 limit 被钳到 100。')
