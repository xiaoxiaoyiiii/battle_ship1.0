# -*- coding: utf-8 -*-
"""认证与账号安全流程回归测试（此前零覆盖的安全关键端点）。

覆盖七组此前完全没有测试的安全关键路径：
  1. `POST /api/profile/signature`   —— 签名修改（未登录拦截 / 空值清空 / 超长截断）
  2. `POST /api/profile/avatar`      —— 头像上传（未登录 / 无文件 / 扩展名白名单 /
                                       魔数校验防改扩展名 / 体积上限）
  3. `POST /api/change_password`     —— 改密（未登录 / 限流 / 原密码错 / 新密码过短 /
                                       正常改密后新密码可登录）
  4. `POST /api/login`               —— API 登录（限流 / 空凭据 / 用户不存在 / 密码错 /
                                       正常返回 token）
  5. `/register`                     —— 注册（限流 / 空值 / 用户名长度 / 非法字符 /
                                       密码过短 / 重名 / 正常注册写 session）
  6. `/login`                        —— 表单登录（限流 / 凭据错 / 正常写 session）
  7. `/logout`                       —— 退出（清 session）

为什么这些端点值得补测试：
  · 它们涉及**身份认证、密码哈希校验、暴力破解限流、文件上传魔数校验**——
    全部是「权限校验与数据验证」类的复杂逻辑，回归风险高；
  · 此前这 7 个端点在 tests/ 中 0 命中，任何改动都没有安全网；
  · 限流 `api._login_attempts` 是模块级全局状态，跨用例必须清（否则前一个用例
    的尝试会把后一个用例顶成 429，出现假红/假绿）。

实现准则：
  · 每个用例独立：用 uuid 生成唯一用户名，避免账号冲突；
  · 每个用例前后清空 `api._login_attempts`（autouse fixture）；
  · 断言用真实 HTTP 响应（状态码 + JSON body / 重定向 / session），不 monkeypatch
    内部函数——要测的就是「这条链路真的这么走」。
"""
import io
import uuid

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

import api
import db as db_module
import server

# ===========================================================================
# 夹具
# ===========================================================================


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """每个用例前后清空模块级限流计数（`_login_attempts` 按 IP 记窗口）。"""
    api._login_attempts.clear()
    yield
    api._login_attempts.clear()


def _mk_user(prefix='auth', password='Passw0rd!'):
    """建一个带真实密码哈希的账号，返回 (uid, username, raw_password)。"""
    for _ in range(50):
        username = f'{prefix}_{uuid.uuid4().hex[:10]}'
        uid = db_module.create_user(username, generate_password_hash(password))
        if uid:
            return uid, username, password
    raise AssertionError('建号失败')


def _client(uid=None, username=None):
    """一个 test_client；给了 uid 就顺手登录（写 session）。"""
    c = server.app.test_client()
    if uid:
        with c.session_transaction() as sess:
            sess['user_id'] = uid
            sess['username'] = username or uid
    return c


def _flashes(client):
    """取并清空当前 session 里的 flash 消息（register/login 用 flash + redirect）。"""
    with client.session_transaction() as sess:
        msgs = list(sess.get('_flashes') or [])
        sess['_flashes'] = []
    return [m for _, m in msgs]


# ===========================================================================
# 1. POST /api/profile/signature
# ===========================================================================

class TestUpdateSignature:
    def test_requires_login(self):
        """未登录直接 401，不许写库。"""
        c = _client()
        resp = c.post('/api/profile/signature', data={'signature': 'hello'})
        assert resp.status_code == 401

    def test_sets_signature(self):
        uid, name, _ = _mk_user()
        c = _client(uid, name)
        resp = c.post('/api/profile/signature', data={'signature': '甲板上的风'})
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True
        assert db_module.get_user(uid=uid)['signature'] == '甲板上的风'

    def test_empty_signature_clears(self):
        """空串应当把签名清空（而不是保留旧值）。"""
        uid, name, _ = _mk_user()
        db_module.update_user_signature(uid, '旧签名')
        c = _client(uid, name)
        resp = c.post('/api/profile/signature', data={'signature': ''})
        assert resp.get_json()['success'] is True
        assert db_module.get_user(uid=uid)['signature'] == ''

    def test_very_long_signature_is_truncated(self):
        """db 层把签名截断到 500 字：超长请求不该 500，也不该写进超长字符串。"""
        uid, name, _ = _mk_user()
        c = _client(uid, name)
        long_text = '长' * 1000
        resp = c.post('/api/profile/signature', data={'signature': long_text})
        assert resp.status_code == 200
        stored = db_module.get_user(uid=uid)['signature']
        assert len(stored) <= 500
        assert stored == long_text[:500]


# ===========================================================================
# 2. POST /api/profile/avatar
# ===========================================================================

class TestUploadAvatar:
    def test_requires_login(self):
        c = _client()
        resp = c.post('/api/profile/avatar')
        assert resp.status_code == 401

    def test_no_file_field(self):
        uid, name, _ = _mk_user()
        c = _client(uid, name)
        resp = c.post('/api/profile/avatar')
        assert resp.status_code == 400
        assert '未选择文件' in resp.get_json()['error']

    def test_empty_filename(self):
        uid, name, _ = _mk_user()
        c = _client(uid, name)
        resp = c.post('/api/profile/avatar',
                      data={'avatar': (io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'0' * 64), '')})
        assert resp.status_code == 400
        assert '文件类型不支持' in resp.get_json()['error']

    def test_disallowed_extension(self):
        uid, name, _ = _mk_user()
        c = _client(uid, name)
        # 扩展名 .exe 不在白名单
        resp = c.post('/api/profile/avatar',
                      data={'avatar': (io.BytesIO(b'MZ' + b'\x00' * 64), 'evil.exe')})
        assert resp.status_code == 400
        assert '文件类型不支持' in resp.get_json()['error']

    def test_extension_spoofing_blocked_by_magic(self):
        """★ 改扩展名绕过白名单：文件名 .png 但内容是文本 → 魔数校验必须拦下。

        这是头像上传最关键的安全点：只校验扩展名等于没校验，攻击者把 .txt 改名
        .png 就能上传任意内容。`AVATAR_MAGIC_PREFIXES` 必须真的起作用。
        """
        uid, name, _ = _mk_user()
        c = _client(uid, name)
        resp = c.post('/api/profile/avatar',
                      data={'avatar': (io.BytesIO(b'not an image at all'), 'fake.png')})
        assert resp.status_code == 400
        assert '不是有效的图片' in resp.get_json()['error']
        # 库也不该被写
        assert db_module.get_user(uid=uid)['avatar'] == ''

    def test_oversize_rejected(self):
        """超过 2MB 的请求应被拒（框架层 MAX_CONTENT_LENGTH 或兜底分支）。

        用略大于 2MB 的真实 PNG 头 + 填充字节。这里不依赖框架层的 413，
        而是断言「头像路径没被写入」——两条路（413/400）都算过。
        """
        uid, name, _ = _mk_user()
        c = _client(uid, name)
        payload = b'\x89PNG\r\n\x1a\n' + b'\x00' * (2 * 1024 * 1024 + 10)
        resp = c.post('/api/profile/avatar',
                      data={'avatar': (io.BytesIO(payload), 'big.png')})
        # 不写库是硬指标；状态码可能是 400（兜底）或 413（框架层）
        assert db_module.get_user(uid=uid)['avatar'] == ''
        assert resp.status_code in (400, 413)

    def test_valid_png_uploads(self, tmp_path):
        """合法 PNG（正确魔数 + 允许扩展名）应成功并写入 avatar 路径。"""
        uid, name, _ = _mk_user()
        c = _client(uid, name)
        png_bytes = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
        resp = c.post('/api/profile/avatar',
                      data={'avatar': (io.BytesIO(png_bytes), 'ok.png')})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True
        assert body['avatar'].startswith('/static/avatars/')
        assert db_module.get_user(uid=uid)['avatar'] == body['avatar']


# ===========================================================================
# 3. POST /api/change_password
# ===========================================================================

class TestChangePassword:
    def test_requires_login(self):
        c = _client()
        resp = c.post('/api/change_password')
        assert resp.status_code == 401

    def test_empty_old_or_new(self):
        uid, name, pw = _mk_user()
        c = _client(uid, name)
        r1 = c.post('/api/change_password', data={'old_password': '', 'new_password': 'newpw'})
        r2 = c.post('/api/change_password', data={'old_password': pw, 'new_password': ''})
        for r in (r1, r2):
            assert r.status_code == 400
            assert '请填写原密码和新密码' in r.get_json()['msg']

    def test_wrong_old_password(self):
        uid, name, _ = _mk_user()
        c = _client(uid, name)
        resp = c.post('/api/change_password',
                      data={'old_password': 'wrong', 'new_password': 'newpass'})
        assert resp.status_code == 403
        assert '原密码错误' in resp.get_json()['msg']

    def test_new_password_too_short(self):
        uid, name, pw = _mk_user()
        c = _client(uid, name)
        resp = c.post('/api/change_password',
                      data={'old_password': pw, 'new_password': '12345'})
        assert resp.status_code == 400
        assert '至少6位' in resp.get_json()['msg']

    def test_rate_limit_after_10_attempts(self):
        """★ 改密走 `_rate_limited('change_password')`：第 11 次必须 429。

        暴力破解靠的就是「能无限试原密码」。限流是唯一防线，必须真的拦。
        """
        uid, name, pw = _mk_user()
        c = _client(uid, name)
        for i in range(10):
            r = c.post('/api/change_password',
                       data={'old_password': f'wrong{i}', 'new_password': 'newpass'})
            assert r.status_code == 403
        # 第 11 次：不管密码对不对，都该被限流挡
        resp = c.post('/api/change_password',
                      data={'old_password': pw, 'new_password': 'newpass'})
        assert resp.status_code == 429
        assert '频繁' in resp.get_json()['msg']

    def test_successful_change_allows_new_password(self):
        """★ 改密成功后，旧密码失效、新密码可用于 API 登录。

        这条用例把「改密 → 校验 → 写库 → 新密码可用」整条链路钉死。
        """
        uid, name, old_pw = _mk_user()
        c = _client(uid, name)
        new_pw = 'BrandNewPass1'
        resp = c.post('/api/change_password',
                      data={'old_password': old_pw, 'new_password': new_pw})
        assert resp.status_code == 200
        assert resp.get_json()['success'] is True

        # 库中哈希已更新
        stored = db_module.get_user(uid=uid)['password_hash']
        assert check_password_hash(stored, new_pw)
        assert not check_password_hash(stored, old_pw)

        # 新密码能登录、旧密码不能
        anon = _client()
        ok = anon.post('/api/login',
                       json={'username': name, 'password': new_pw})
        assert ok.status_code == 200 and 'token' in ok.get_json()
        bad = anon.post('/api/login',
                        json={'username': name, 'password': old_pw})
        assert bad.status_code == 401


# ===========================================================================
# 4. POST /api/login
# ===========================================================================

class TestApiLogin:
    def test_empty_credentials(self):
        c = _client()
        r1 = c.post('/api/login', json={'username': '', 'password': 'x'})
        r2 = c.post('/api/login', json={'username': 'x', 'password': ''})
        for r in (r1, r2):
            assert r.status_code == 400
            assert '不能为空' in r.get_json()['error']

    def test_unknown_user(self):
        c = _client()
        resp = c.post('/api/login',
                      json={'username': 'no_such_user_xyz', 'password': 'whatever'})
        assert resp.status_code == 401
        assert '用户名或密码错误' in resp.get_json()['error']

    def test_wrong_password(self):
        _, name, _ = _mk_user()
        c = _client()
        resp = c.post('/api/login',
                      json={'username': name, 'password': 'wrong_password'})
        assert resp.status_code == 401
        assert '用户名或密码错误' in resp.get_json()['error']

    def test_successful_login_returns_token(self):
        _, name, pw = _mk_user()
        c = _client()
        resp = c.post('/api/login',
                      json={'username': name, 'password': pw})
        assert resp.status_code == 200
        token = resp.get_json().get('token')
        assert isinstance(token, str) and token
        # token 真的写进库了
        assert db_module.get_user(username=name)['token'] == token

    def test_rate_limit_after_10_attempts(self):
        """★ API 登录同样走限流：连续 10 次失败后第 11 次必须 429，
        防止在线暴力破解。"""
        _, name, _ = _mk_user()
        c = _client()
        for _ in range(10):
            r = c.post('/api/login',
                       json={'username': name, 'password': 'wrong'})
            assert r.status_code == 401
        resp = c.post('/api/login',
                      json={'username': name, 'password': 'still_wrong'})
        assert resp.status_code == 429
        assert '频繁' in resp.get_json()['error']


# ===========================================================================
# 5. /register
# ===========================================================================

class TestRegister:
    def _post(self, client, username='', password=''):
        return client.post('/register',
                           data={'username': username, 'password': password})

    def test_empty_username(self):
        c = _client()
        self._post(c, password='secret')
        assert any('用户名和密码不能为空' in m for m in _flashes(c))

    def test_empty_password(self):
        c = _client()
        self._post(c, username='validuser')
        assert any('用户名和密码不能为空' in m for m in _flashes(c))

    def test_username_too_short(self):
        c = _client()
        self._post(c, username='ab', password='secret')
        assert any('至少 3 位' in m for m in _flashes(c))

    def test_username_invalid_chars(self):
        c = _client()
        self._post(c, username='bad name!', password='secret')
        assert any('只能包含字母' in m for m in _flashes(c))

    def test_password_too_short(self):
        c = _client()
        self._post(c, username='validuser', password='12345')
        assert any('至少 6 位' in m for m in _flashes(c))

    def test_duplicate_username(self):
        _, name, _ = _mk_user()
        c = _client()
        self._post(c, username=name, password='secret')
        assert any('用户名已存在' in m for m in _flashes(c))

    def test_successful_register_sets_session(self):
        """★ 正常注册：302 到首页，session 写入 user_id/username。"""
        c = _client()
        username = f'reg_{uuid.uuid4().hex[:10]}'
        resp = c.post('/register',
                      data={'username': username, 'password': 'secret123'})
        assert resp.status_code == 302
        with c.session_transaction() as sess:
            assert sess.get('user_id')
            assert sess.get('username') == username
        # 账号真的存在
        assert db_module.get_user(username=username) is not None

    def test_rate_limit_after_10(self):
        """注册也限流，防止批量建号刷榜。"""
        c = _client()
        for i in range(10):
            c.post('/register',
                   data={'username': f'rl_{i}_{uuid.uuid4().hex[:6]}', 'password': 'secret'})
        resp = c.post('/register',
                      data={'username': f'rl_extra_{uuid.uuid4().hex[:6]}', 'password': 'secret'})
        # 被限流时 flash 提示并 redirect
        assert any('频繁' in m for m in _flashes(c))


# ===========================================================================
# 6. /login (表单)
# ===========================================================================

class TestLoginForm:
    def test_wrong_credentials(self):
        _, name, _ = _mk_user()
        c = _client()
        c.post('/login', data={'username': name, 'password': 'wrong'})
        assert any('用户名或密码错误' in m for m in _flashes(c))
        with c.session_transaction() as sess:
            assert not sess.get('user_id')

    def test_successful_login_sets_session(self):
        uid, name, pw = _mk_user()
        c = _client()
        resp = c.post('/login', data={'username': name, 'password': pw})
        assert resp.status_code == 302
        with c.session_transaction() as sess:
            assert sess.get('user_id') == uid
            assert sess.get('username') == name

    def test_rate_limit_after_10(self):
        """允许 10 次，第 11 次触发限流（`_LOGIN_MAX_ATTEMPTS = 10`）。"""
        _, name, _ = _mk_user()
        c = _client()
        for _ in range(10):
            c.post('/login', data={'username': name, 'password': 'wrong'})
        # 第 11 次：不管密码对错，都该被限流挡下并 flash 提示
        c.post('/login', data={'username': name, 'password': 'still_wrong'})
        assert any('频繁' in m for m in _flashes(c))


# ===========================================================================
# 7. /logout
# ===========================================================================

class TestLogout:
    def test_clears_session(self):
        uid, name, _ = _mk_user()
        c = _client(uid, name)
        # 确认已登录
        with c.session_transaction() as sess:
            assert sess.get('user_id') == uid
        resp = c.get('/logout')
        assert resp.status_code == 302
        with c.session_transaction() as sess:
            assert not sess.get('user_id')
            assert not sess.get('username')


# ===========================================================================
# 跨用例不变量：限流是按 IP 记的，不区分接口
# ===========================================================================

class TestRateLimitIsolation:
    def test_login_and_register_share_ip_scope(self):
        """不同 scope（login / register）各自计数，不互相干扰。

        `_rate_limited(scope)` 的 key 是 `f"{scope}:{ip}"`。这条用例守住
        「登录 10 次不会把注册也封掉」—— 否则 scope 参数就名存实亡。
        """
        _, name, _ = _mk_user()
        c = _client()
        # 打满 login scope
        for _ in range(10):
            c.post('/login', data={'username': name, 'password': 'wrong'})
        # register scope 仍然可用（第 1 次不触发限流）
        reg_resp = c.post('/register',
                          data={'username': f'iso_{uuid.uuid4().hex[:8]}',
                                'password': 'secret'})
        assert not any('频繁' in m for m in _flashes(c)), \
            '登录限流不应波及注册'
        assert reg_resp.status_code == 302
