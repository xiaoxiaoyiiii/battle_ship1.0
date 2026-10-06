# -*- coding: utf-8 -*-
"""卡牌使用统计（图鉴「使用 N 次」）回归。

背景：图鉴此前只有卡面信息，没有任何"这张卡到底有多常用"的信号。
新增 `card_usage` 表 + `/api/card_usage` + 图鉴里的排序/角标。

⚠️ 这里特意覆盖了一条**曾经真实踩过的坑**：`server.py` / `api.py` 都是
`import db`（模块），而新方法最初只加在 Database 实例上 —— 调用会
AttributeError，被 server 里"统计失败不影响对局"的 try/except 吞掉，
表现为"对局正常、统计永远是 0"。所以下面既要测实例方法，也要测**模块级函数**。
"""
import io
import sqlite3
import pytest

import db as db_module
import server
from db import Database


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    # Database() 从环境变量取库路径（见 db.py __init__），用它做完全隔离
    monkeypatch.setenv('BATTLESHIP_DB_PATH', str(tmp_path / 'usage.db'))
    d = Database()
    yield d
    d.close()


# ---------------------------------------------------------------------------
# 1. 实例层
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# 2. 模块级函数（server.py / api.py 走的就是这条）
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# 3. 服务端出牌时会真的记账
# ---------------------------------------------------------------------------


def test_statistics_failure_never_breaks_the_game(monkeypatch):
    """统计炸了也不能影响出牌（这是"吞异常"设计的意义）。"""
    def boom(name, count=1):
        raise RuntimeError('disk full')

    monkeypatch.setattr(db_module, 'record_card_use', boom)
    server.record_card_use('冻结')      # 不应抛异常


# ---------------------------------------------------------------------------
# 4. 公开只读接口
# ---------------------------------------------------------------------------
