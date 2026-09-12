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
def test_count_stats_false_records_history_without_touching_stats(temp_db):
    winner = _make_user(temp_db, 'winner_u')
    loser = _make_user(temp_db, 'loser_u')

    assert temp_db.record_match(winner, loser, logs=[{'ts': 1, 'text': '一局人机'}],
                                count_stats=False) is True

    w = temp_db.get_user(uid=winner)
    l = temp_db.get_user(uid=loser)
    assert (w['wins'], w['current_streak'], w['longest_streak']) == (0, 0, 0), \
        '人机对局不能计入胜场/连胜'
    assert (l['losses'], l['current_streak']) == (0, 0), '人机对局不能计入负场'

    history = temp_db.get_match_history(winner)
    assert len(history) == 1, '人机对局仍要写进历史，供玩家回看'
    assert history[0]['loser_id'] == loser
    assert history[0]['logs'] == [{'ts': 1, 'text': '一局人机'}]


def test_count_stats_true_is_still_the_default(temp_db):
    winner = _make_user(temp_db, 'win_user')
    loser = _make_user(temp_db, 'lose_user')

    assert temp_db.record_match(winner, loser) is True

    w = temp_db.get_user(uid=winner)
    l = temp_db.get_user(uid=loser)
    assert (w['wins'], w['current_streak'], w['longest_streak']) == (1, 1, 1)
    assert (l['losses'], l['current_streak']) == (1, 0)


def test_count_stats_false_still_rejects_empty_ids(temp_db):
    assert temp_db.record_match('', 'loser', count_stats=False) is False
    assert temp_db.record_match('winner', '', count_stats=False) is False


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


def test_ai_room_settlement_does_not_count_stats(monkeypatch):
    calls = _capture_record_match(monkeypatch)
    room, ai_id = _make_room(ai_room=True)

    server._finish_game_win(room, room.id, P1, ai_id)

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == 'u1' and args[1] == ai_id
    assert kwargs.get('count_stats') is False, '人机对局不能计入战绩'


def test_human_room_settlement_counts_stats(monkeypatch):
    calls = _capture_record_match(monkeypatch)
    room, p2 = _make_room(ai_room=False)

    server._finish_game_win(room, room.id, P1, p2)

    assert len(calls) == 1
    assert calls[0][1].get('count_stats') is True, '真人对局仍要计入战绩'


def test_count_stats_helper_only_rejects_ai_rooms():
    ai_room, _ = _make_room(ai_room=True)
    human_room, _ = _make_room(ai_room=False)
    assert server._count_stats_for(ai_room) is False
    assert server._count_stats_for(human_room) is True


def test_every_record_match_call_site_passes_count_stats():
    """server.py 里任何一处 db.record_match 都必须显式给出 count_stats。"""
    source = _read('server.py')
    calls = re.findall(r'db\.record_match\((?:[^()]|\([^()]*\))*\)', source)
    assert calls, '没有找到任何 db.record_match 调用？'
    for call in calls:
        assert 'count_stats=' in call, '漏传 count_stats: ' + call


# ---------------------------------------------------------------------------
# 3. 前端：历史列表结构、唯一实现、样式
# ---------------------------------------------------------------------------
def test_history_rows_are_not_buttons_inside_tbody():
    js = _read(os.path.join('static', 'game.js'))
    assert '<tbody>' not in js, (
        '历史行不能再用 table/tbody 承载 <button>：解析器会 foster parent '
        '把它挪到表格外，表头会孤零零留在列表最下方')
    assert 'history-list' in js and 'history-head' in js


def test_stats_renderers_have_a_single_definition():
    js = _read(os.path.join('static', 'game.js'))
    assert js.count('function showUserStats(') == 1, 'showUserStats 只能有一份实现'
    assert js.count('function showMatchDetail(') == 1, 'showMatchDetail 只能有一份实现'
    assert 'window.renderUserStatsHTML' in js and 'window.renderMatchDetailHTML' in js


def test_stats_modal_no_longer_creates_duplicate_overlays():
    js = _read(os.path.join('static', 'game.js'))
    assert 'getStatsModalContent' in js
    assert "userStatsModal.innerHTML = '<div class=\"modal-content\">" not in js, \
        '头像入口不应再每次点击都 append 一个新的 #user-stats-modal'


def test_stylesheet_defines_stats_classes_and_kills_button_gradient():
    css = _read(os.path.join('static', 'style.css'))
    assert '.user-stats-table' in css and '.user-history' in css, \
        'JS 用到这两个类，样式表必须有定义'
    block = css[css.index('.match-history-btn {'):]
    block = block[:block.index('}')]
    assert 'background-image: none' in block, \
        '通用 button 规则的渐变会盖住胜负配色，必须显式关闭'
    assert '.match-history-btn.lose' in css and '.match-history-btn.win' in css


def test_ai_opponent_is_mapped_to_a_display_name():
    js = _read(os.path.join('static', 'game.js'))
    assert 'ai-' in js and "'电脑'" in js
    assert 'function opponentDisplayName(' in js
    assert 'matchData.winner_name || matchData.loser_name' not in js, \
        '赢的局 winner_name 就是自己，不能拿它当对手名'


# ---------------------------------------------------------------------------
# 4. 历史数据重算工具
# ---------------------------------------------------------------------------
def _load_recompute_tool():
    path = os.path.join(ROOT, 'tools', 'recompute_ranked_stats.py')
    spec = importlib.util.spec_from_file_location('recompute_ranked_stats', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_recompute_tool_drops_ai_matches_from_stats(temp_db):
    tool = _load_recompute_tool()
    winner = _make_user(temp_db, 'ranked_u')
    loser = _make_user(temp_db, 'ranked_l')
    # 手工制造旧口径下的脏数据：3 场人机胜 + 1 场真人胜
    for pid in ('ai-aaa111', 'ai-bbb222', 'ai-ccc333'):
        temp_db.conn.execute(
            'INSERT INTO matches (id, winner_id, loser_id, timestamp) VALUES (?,?,?,?)',
            ('m-' + pid, winner, pid, 1000))
    temp_db.conn.execute(
        'INSERT INTO matches (id, winner_id, loser_id, timestamp) VALUES (?,?,?,?)',
        ('m-human', winner, loser, 2000))
    temp_db.conn.execute('UPDATE users SET wins = 4, current_streak = 4, longest_streak = 4 WHERE id = ?', (winner,))
    temp_db.conn.commit()

    plan, info = tool.recompute(temp_db.conn)
    assert info['ai_matches'] == 3
    row = [p for p in plan if p['id'] == winner]
    assert row and row[0]['new']['wins'] == 1, plan
    assert row[0]['new']['current_streak'] == 1
    assert row[0]['new']['longest_streak'] == 1

    # 预演不写库
    assert temp_db.get_user(uid=winner)['wins'] == 4

    for item in plan:
        temp_db.conn.execute(
            'UPDATE users SET wins = ?, losses = ?, current_streak = ?, longest_streak = ? WHERE id = ?',
            (item['new']['wins'], item['new']['losses'], item['new']['current_streak'],
             item['new']['longest_streak'], item['id']))
    temp_db.conn.commit()
    assert temp_db.get_user(uid=winner)['wins'] == 1
    assert temp_db.get_user(uid=winner)['longest_streak'] == 1


def test_recompute_tool_is_idempotent(temp_db):
    tool = _load_recompute_tool()
    _make_user(temp_db, 'idem_u')
    plan, _ = tool.recompute(temp_db.conn)
    assert plan == [], '没有脏数据时不应产生任何变更'
