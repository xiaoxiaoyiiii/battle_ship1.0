# -*- coding: utf-8 -*-
r"""成就 / 徽章（第 2 批 B 票）回归测试 —— 对应 `docs/BATCH_2_3_4_PLAN.md` §2.2.2 / §2.3 / §2.4。

覆盖四块：
  1. `achievements.py` 的 12 枚判据与**边界**（差 1 就不解锁）+ 归一化兜底（纯函数，不碰库）
  2. 图鉴形状（全量 12 枚、未解锁项带 `requirement`、`unlocked_at` 语义）
  3. `GET /api/profile` / `GET /api/achievements` 自己视角 = 全量
  4. `GET /user_stats` **他人视角只下发已解锁**（未解锁的 id 与判据文案都不许出现）+ 凭据不下发

⚠️ 本票只改 `achievements.py` / `api.py` / 本文件。A 票的 5 个 DAO
（`get_user_counters` / `bump_user_counters` / `get_user_achievements` /
`grant_user_achievements` / `get_distinct_cards_used`）由 A 票落在 `db.py`：
接口层用例用 `monkeypatch` 打桩（不复制判据、也不改别人的文件），
另有两条分别钉住「DAO 缺失时接口不能 500」与「真实 DAO 的键名与判据上下文对得上」（跨票接缝）。

⚠️ 跑测试必须重定向临时目录（本机 `%LOCALAPPDATA%\Temp\pytest-of-Administrator`
的 ACL 坏了，不重定向会有一批用例在 setup 阶段假红）：
    New-Item -ItemType Directory -Force .tmp\pytemp | Out-Null
    $env:TMP="$PWD\.tmp\pytemp"; $env:TEMP=$env:TMP
    python -m pytest tests/ -q -p no:cacheprovider
"""
import json
import time
import uuid

import pytest

import achievements
import db as db_module
import server

# ===========================================================================
# 夹具与助手
# ===========================================================================


def _stats(**over):
    """一份「什么都没有」的判定输入（原始形状，与 api.py 组装的一致）。"""
    base = {'wins': 0, 'losses': 0, 'longest_streak': 0, 'created_at': int(time.time()),
            'matches_played': 0, 'sunk_total': 0, 'flawless_wins': 0,
            'fastest_win_sec': 0, 'card_uses_total': 0, 'distinct_cards': 0, 'rank': 0}
    base.update(over)
    return base


def _login(client, uid='u1', username='alice'):
    with client.session_transaction() as sess:
        sess['user_id'] = uid
        sess['username'] = username
    return client


def _install(monkeypatch, *, user=None, rank=0, counters=None, badges=None,
             distinct_cards=0, card_uses_total=0, history=None):
    """把 `/user_stats` 与 `/api/profile` 会用到的东西全部打桩。

    注意 `api.py` 与 `server.py` 里的 `db` 是**同一个模块对象**，
    所以 `monkeypatch.setattr(server.db, ...)` 对接口层同样生效。
    """
    user = user if user is not None else {
        'id': 'u1', 'username': 'alice', 'wins': 0, 'losses': 0,
        'current_streak': 0, 'longest_streak': 0, 'created_at': int(time.time()),
        'signature': '', 'avatar': '',
        # 以下字段绝不能出现在响应里
        'password_hash': 'pbkdf2:sha256:secret', 'token': 'session-token',
    }
    # `raising=False`：A 票的 DAO 是并行落地的，落地前这些属性还不存在。
    # 用 raising=False 让本文件在「A 票已落地」与「还没落地」两种状态下都能跑。
    monkeypatch.setattr(server.db, 'get_user', lambda **kw: user, raising=False)
    monkeypatch.setattr(server.db, 'get_user_rank', lambda uid: rank, raising=False)
    monkeypatch.setattr(server.db, 'get_user_counters',
                        lambda uid: dict(counters or {}), raising=False)
    monkeypatch.setattr(server.db, 'get_user_achievements',
                        lambda uid: dict(badges or {}), raising=False)
    monkeypatch.setattr(server.db, 'get_distinct_cards_used',
                        lambda uid: distinct_cards, raising=False)
    monkeypatch.setattr(server.db, 'get_user_card_uses_total',
                        lambda uid: card_uses_total, raising=False)
    monkeypatch.setattr(server.db, 'get_match_history',
                        lambda uid, limit: list(history or []), raising=False)
    return user


# ===========================================================================
# 0. 契约形状与「一处判据」
# ===========================================================================






# ===========================================================================
# 1. 12 枚判据的边界：达标解锁 / 差 1 不解锁
# ===========================================================================
# (badge_id, 上下文键, 门槛值) —— 门槛值处解锁，门槛 - 1 处不解锁
THRESHOLDS = [
    ('first_win', 'wins', 1),
    ('veteran10', 'matches_played', 10),
    ('streak5', 'longest_streak', 5),
    ('streak10', 'longest_streak', 10),
    ('sunk50', 'sunk_total', 50),
    ('sunk200', 'sunk_total', 200),
    ('flawless', 'flawless_wins', 1),
    ('flawless5', 'flawless_wins', 5),
    ('cardmaster', 'card_uses_total', 100),
    ('allrounder', 'distinct_cards', 20),
]












# ===========================================================================
# 2. 归一化兜底：脏数据不许抛异常
# ===========================================================================






# ===========================================================================
# 3. 图鉴形状
# ===========================================================================
















# ===========================================================================
# 4. 接口：自己视角 = 全量
# ===========================================================================


def test_achievements_endpoint_requires_login():
    resp = server.app.test_client().get('/api/achievements')
    assert resp.status_code == 401
    assert 'achievements' not in resp.get_json()




# ===========================================================================
# 5. 接口：他人视角只下发已解锁的（不泄露进度）
# ===========================================================================




def test_user_stats_still_hides_credentials(monkeypatch):
    _install(monkeypatch, counters={'sunk_total': 50})
    data = server.app.test_client().get('/user_stats?username=alice').get_json()
    body = server.app.test_client().get('/user_stats?username=alice').get_data(as_text=True)
    assert 'password_hash' not in data['stats'] and 'token' not in data['stats']
    assert 'pbkdf2' not in body and 'session-token' not in body




# ===========================================================================
# 6. 兜底：统计读不到 / DAO 还没落地时，接口不许 500
# ===========================================================================




# ===========================================================================
# 7. 跨票接缝：A 票的真实 DAO → 本票的接口（不打桩）
# ===========================================================================
