# -*- coding: utf-8 -*-
"""战绩展示与统计口径修复的回归测试（2026-09-13）。

线上账号 z1w6qn 的截图暴露了 6 个问题，本文件逐条盯住：

1. 历史战绩把 <button> 塞进 <table><tbody> —— 非法子元素，HTML 解析器会 foster
   parent 把按钮挪到表格之前，表头「时间 对手 结果 局内日志」孤立在列表最下方；
2. 胜负配色被通用 button 规则的 background-image 渐变盖掉，三行胜利记录全是蓝色；
3. .user-stats-table / .user-history 两个类在样式表里从未定义；
4. 人机对手显示成裸 ID（vs ai-4530c8）；
5. 点开胜局时「对局详情」的「对手」栏显示成自己；
6. 人机对局计入 users.wins / 连胜，而排行榜按 wins DESC 排序 —— 打电脑就能刷榜。
"""
import importlib.util
import os
import re
import sqlite3

import pytest

import server
from db import Database
from server import GameRoom, Player

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P1 = 'p1'


@pytest.fixture
def temp_db(tmp_path):
    """独立临时数据库（与 test_db_core 同一套写法）。"""
    instance = Database()
    instance.close()
    instance.db_path = tmp_path / 'test.db'
    instance.conn = sqlite3.connect(instance.db_path, check_same_thread=False)
    instance.conn.row_factory = sqlite3.Row
    instance.cursor = instance.conn.cursor()
    instance.init_db()
    return instance


def _make_user(db, username, password_hash='hash'):
    uid = db.create_user(username, password_hash)
    assert uid is not None
    return uid


def _read(rel_path):
    with open(os.path.join(ROOT, rel_path), 'r', encoding='utf-8') as f:
        return f.read()


# ---------------------------------------------------------------------------
# 1. db.record_match 的 count_stats 口径
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# 2. 人机对局的结算路径必须传 count_stats=False
# ---------------------------------------------------------------------------
def _make_room(ai_room):
    room = GameRoom('stats-room')
    room.is_ai_room = ai_room
    opponent_id = 'ai-stats-room' if ai_room else 'p2'
    room.players[P1] = Player(name='human', ships=[], attacks=[], remaining_ships=0,
                              sid='sid-p1', user_id='u1')
    room.players[opponent_id] = Player(name='AI' if ai_room else 'p2', ships=[], attacks=[],
                                       remaining_ships=0, sid='sid-p2',
                                       user_id=None if ai_room else 'u2')
    room.state = 'attacking'
    return room, opponent_id


@pytest.fixture(autouse=True)
def _silence_emit(monkeypatch):
    monkeypatch.setattr(server, 'emit', lambda *a, **k: None)


def _capture_record_match(monkeypatch):
    calls = []
    monkeypatch.setattr(server.db, 'record_match',
                        lambda *a, **k: calls.append((a, k)) or True)
    return calls










# ---------------------------------------------------------------------------
# 3. 前端：历史列表结构、唯一实现、样式
# ---------------------------------------------------------------------------










# ---------------------------------------------------------------------------
# 4. 历史数据重算工具
# ---------------------------------------------------------------------------
def _load_recompute_tool():
    path = os.path.join(ROOT, 'tools', 'recompute_ranked_stats.py')
    spec = importlib.util.spec_from_file_location('recompute_ranked_stats', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
