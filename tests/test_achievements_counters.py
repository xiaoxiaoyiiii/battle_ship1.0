# -*- coding: utf-8 -*-
r"""第 2 批 A 票：每局结算收口（`_finalize_match`）+ `user_counters` / `user_achievements`。

对应 `docs/BATCH_2_3_4_PLAN.md` §2.1 / §2.2 / §2.2.1。

覆盖四块：
  1. `user_counters` 的 DAO：默认值（不写库）、累加、`fastest_win_sec` 取最小非零、
     脏数据兜底、库异常不抛；
  2. `user_achievements` 的 DAO：只返回新增、重复授予幂等、首解时间不被刷新；
  3. `_finalize_match`：一次调用把「写战绩 + 累加统计 + 解锁徽章」三件事都做掉，
     以及人机 / 游客 / 玩家不在房间 / 库故障四种边界；
  4. 结构性断言：6 处结算调用点全部走收口，`server.py` 里只剩**一处**真正写库的调用。

⚠️ 跑测试必须重定向临时目录（本机 `%LOCALAPPDATA%\Temp\pytest-of-Administrator`
的 ACL 坏了，不重定向会有一批用例在 setup 阶段假红）：
    New-Item -ItemType Directory -Force .tmp\pytemp | Out-Null
    $env:TMP="$PWD\.tmp\pytemp"; $env:TEMP=$env:TMP; python -m pytest tests/ -q -p no:cacheprovider
"""
import os
import pathlib
import random
import re
import time
import uuid

import pytest

import achievements
import db as db_module
import server
from server import GameRoom, Player, PlayerShip, Position

REPO = pathlib.Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 夹具与助手
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _silence_emit(monkeypatch):
    """结算路径会 emit 播报；没有 socket 上下文时不该让它影响断言。"""
    monkeypatch.setattr(server, 'emit', lambda *a, **k: None)


@pytest.fixture
def make_user():
    """在（conftest 已隔离的）全局测试库上建账号，返回 (uid, username)。"""
    def _make(username=None):
        name = username or ('ach' + uuid.uuid4().hex[:10])
        uid = db_module.create_user(name, 'x')
        assert uid, '建号失败（用户名冲突？）'
        return uid, name

    return _make


def _ship(positions=((0, 0),), hits=(), sunk=False):
    """造一艘船；`sunk=True` 表示"每个格子都被打中"（= 已沉，未登记进沉船堆）。"""
    pos = [Position(x, y) for x, y in positions]
    if sunk:
        hit = [Position(x, y) for x, y in positions]
    else:
        hit = [Position(x, y) for x, y in hits]
    return PlayerShip(positions=pos, hits=hit)


def _player(uid, ships=None, sunken=None, name='p'):
    p = Player(name=name, ships=list(ships or []), attacks=[], remaining_ships=6,
               sid='sid-' + str(uid), user_id=uid)
    p.sunken_ships = list(sunken or [])
    return p


def _room(winner_player, loser_player, ai_room=False, started_ago=None, logs=None):
    """最小可用的房间桩。

    `started_ago` 给秒数时同时写 `match_started_at`（模拟"猜拳后真正开局"），
    不给就两个时间字段都不留 —— 用来验证「拿不到用时给 0，不编」。
    """
    room = GameRoom('ach-room-' + uuid.uuid4().hex[:6])
    room.is_ai_room = ai_room
    room.players = {'W': winner_player, 'L': loser_player}
    room.state = 'attacking'
    room.game_logs = logs if logs is not None else []
    if started_ago is not None:
        room.match_started_at = time.time() - started_ago
    return room


def _capture_record_match(monkeypatch):
    """把写库拦下来（与既有 `test_stats_display_fixes.py` 同一套做法）。"""
    calls = []
    monkeypatch.setattr(server.db, 'record_match',
                        lambda *a, **k: calls.append((a, k)) or True)
    return calls


def _counter_row(uid):
    """直接读库（绕过 DAO 的默认值），用于断言"到底写没写"。"""
    con = db_module.db
    with con._lock:
        row = con.cursor.execute(
            'SELECT sunk_total, matches_played, flawless_wins, fastest_win_sec '
            'FROM user_counters WHERE user_id = ?', (uid,)).fetchone()
    return dict(row) if row else None


# ===========================================================================
# 1. user_counters 的 DAO
# ===========================================================================




















# ===========================================================================
# 2. user_achievements 的 DAO
# ===========================================================================














# ===========================================================================
# 3. 击沉口径（活船 / 沉船互补）
# ===========================================================================








# ===========================================================================
# 4. _finalize_match：三件事一次做掉
# ===========================================================================






def test_finalize_match_ai_room_does_not_touch_counters(make_user, monkeypatch):
    """上面那条的 db 层版本（不碰真库写入，直接看计数器）。"""
    _capture_record_match(monkeypatch)
    uid, _ = make_user()
    winner = _player(uid, ships=[_ship(hits=[])])
    ai = _player(None, ships=[], name='AI')
    room = _room(winner, ai, ai_room=True)

    server._finalize_match(room, 'W', 'L')

    assert _counter_row(uid) is None
    assert db_module.get_user_achievements(uid) == {}


















# ===========================================================================
# 5. 结构性断言：收口是否真的收住了
# ===========================================================================
def _read(rel):
    return (REPO / rel).read_text(encoding='utf-8')










# ===========================================================================
# 6. 建表 / 老库兼容
# ===========================================================================
