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
def test_record_and_read(temp_db):
    assert temp_db.record_card_use('冻结') is True
    assert temp_db.record_card_use('冻结') is True
    assert temp_db.record_card_use('无中生有') is True
    usage = temp_db.get_card_usage()
    assert usage['冻结'] == 2 and usage['无中生有'] == 1


def test_count_argument(temp_db):
    temp_db.record_card_use('神威！', 3)
    assert temp_db.get_card_usage()['神威！'] == 3


def test_empty_name_is_ignored(temp_db):
    assert temp_db.record_card_use('') is False
    assert temp_db.record_card_use(None) is False
    assert temp_db.get_card_usage() == {}


def test_usage_isolated_from_other_tables(temp_db):
    """卡牌统计不能污染战绩表。"""
    temp_db.record_card_use('冻结')
    rows = temp_db.conn.execute('SELECT COUNT(*) FROM matches').fetchone()[0]
    assert rows == 0


# ---------------------------------------------------------------------------
# 2. 模块级函数（server.py / api.py 走的就是这条）
# ---------------------------------------------------------------------------
def test_module_level_functions_exist():
    for name in ('record_card_use', 'get_card_usage'):
        assert hasattr(db_module, name), f'db 模块缺少 {name}（server/api 是 import db 调用的）'


def test_module_level_roundtrip():
    db_module.record_card_use('__pytest_probe__', 2)
    assert db_module.get_card_usage().get('__pytest_probe__') == 2


# ---------------------------------------------------------------------------
# 3. 服务端出牌时会真的记账
# ---------------------------------------------------------------------------
def test_playing_a_card_records_usage(monkeypatch):
    recorded = []
    monkeypatch.setattr(db_module, 'record_card_use',
                        lambda name, count=1: recorded.append((name, count)) or True)

    room = server.GameRoom('usage-room')
    card = server.MagicCard('无中生有')
    p1 = server.Player(name='p1', ships=[], attacks=[], remaining_ships=6, sid='s1', user_id='u1')
    p1.magic_hand = [card]          # 手牌在 __init__ 之后赋值（构造器不接受该参数）
    room.players['p1'] = p1
    room.players['p2'] = server.Player(name='p2', ships=[], attacks=[], remaining_ships=6,
                                       sid='s2', user_id='u2')
    room.state = 'attacking'
    room.current_attacker = 'p1'
    room.current_phase = 'battle'
    room.attack_order = ['p1', 'p2']
    server.room_manager.rooms[room.id] = room
    try:
        res = server.handle_use_magic_card({
            'room_id': room.id, 'player_id': 'p1',
            'card': {'name': card.name, 'speed': card.speed, 'type': card.type},
            'targets': [],
        })
        assert res['status'] == 'success', res
        assert recorded and recorded[0][0] == '无中生有', f'出牌必须记一次使用，实际 {recorded}'
    finally:
        server.room_manager.rooms.pop(room.id, None)


def test_statistics_failure_never_breaks_the_game(monkeypatch):
    """统计炸了也不能影响出牌（这是"吞异常"设计的意义）。"""
    def boom(name, count=1):
        raise RuntimeError('disk full')

    monkeypatch.setattr(db_module, 'record_card_use', boom)
    server.record_card_use('冻结')      # 不应抛异常


# ---------------------------------------------------------------------------
# 4. 公开只读接口
# ---------------------------------------------------------------------------
def test_api_returns_json_shape():
    import api
    client = api.app.test_client()
    resp = client.get('/api/card_usage')
    assert resp.status_code == 200, resp.status_code
    payload = resp.get_json()
    assert 'usage' in payload and 'total' in payload
    assert isinstance(payload['usage'], dict) and isinstance(payload['total'], int)
