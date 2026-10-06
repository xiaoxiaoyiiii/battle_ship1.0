# -*- coding: utf-8 -*-
"""个人信息接口 `/user_stats` 的回归测试（2026-09-17）。

作者要求「对局内看对手资料 / 排行榜点名字，都要能看到头像、个性签名、
排行榜名次」—— 接口必须把 `rank` 一起下发，且不能因为多查一次排名
而把敏感字段（password_hash / token）带出去。
"""
import pytest

import server


def _fake_stats():
    return {
        'id': 'u1', 'username': 'alice', 'wins': 4, 'losses': 2,
        'current_streak': 2, 'longest_streak': 3, 'created_at': 1700000000,
        'signature': '测试签名', 'avatar': '/static/avatars/x.png',
        # 以下字段绝不能出现在响应里
        'password_hash': 'pbkdf2:sha256:secret', 'token': 'session-token',
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server.db, 'get_user', lambda **kw: _fake_stats())
    monkeypatch.setattr(server.db, 'get_match_history', lambda uid, limit: [])
    monkeypatch.setattr(server.db, 'get_user_rank', lambda uid: 7)
    return server.app.test_client()
