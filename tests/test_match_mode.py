# -*- coding: utf-8 -*-
"""战绩模式批 · `matches.mode`（后端）。

作者新提的需求：**战绩界面里看不出这一局是「排位赛 / 匹配 / 打人机」**。
那是数据缺口 —— `matches` 表原先只有 `id / winner_id / loser_id / timestamp`，
界面只能靠 `isAiOpponent(matchId)` **从 id 猜人机**（猜测，不是记录）。

## 取值表（唯一一份 = `server.MATCH_HISTORY_MODES`）

| 值 | 含义 | 判据 |
| --- | --- | --- |
| `'ai'` | 人机局 | `room.is_ai_room` |
| `'ranked'` | 排位赛 | `_room_match_mode(room) == 'ranked'`（**复用**，不重判） |
| `'custom'` | 自定义房 / 好友邀战 | `not room.matchmade` |
| `'casual'` | 匹配出来的休闲局 | 其余 |

优先级就是上表顺序：人机房恒 `ranked=False`，所以先判人机。

## 为什么加了个房间级布尔 `matchmade`

"这间房是匹配出来的"应该是**被记录的事实**，不是从 `room.players` 的 key 形状反推的判据
（CLAUDE.md §6：key 有两套约定，而且历史上漂移过一次；形状判据一旦漂移，症状是
"匹配局被静默标成自定义局"，**零报错**）。

全项目所有配对都汇到 `handle_find_match` 里那个消费 `match_queue` 的循环，
所以 `matchmade = True` **只有那一处**（源码级穷举守卫见下）。
形状判据降级成这里的**交叉校验**：将来谁改了 key 约定，是**测试先红**。

## 老数据

生产库那 342 行（其中 152 行两侧都是真实用户）的 `mode` 是 **NULL**。
NULL = "不知道"，**绝不许兜底成 `'casual'`**（教训 #21）。前后端都要能优雅处理。
"""
import ast
import io
import pathlib
import uuid

import pytest

import db as db_module
import server
from server import GameRoom, Player, room_manager

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER_PY = REPO_ROOT / 'server.py'
DB_PY = REPO_ROOT / 'db.py'


def _account():
    uid = db_module.create_user('mode-%s' % uuid.uuid4().hex[:10], 'x' * 12)
    assert uid
    return uid


@pytest.fixture
def room():
    """匹配房形状的房间（key = sid，真人 uid 在 `Player.user_id` 上）。"""
    r = GameRoom('mode-' + uuid.uuid4().hex[:6])
    r.players['mode-sid-a'] = Player(name='甲', ships=[], attacks=[], remaining_ships=0,
                                     sid='mode-sid-a', user_id=_account())
    r.players['mode-sid-b'] = Player(name='乙', ships=[], attacks=[], remaining_ships=0,
                                     sid='mode-sid-b', user_id=_account())
    r.game_logs = []
    room_manager.rooms[r.id] = r
    yield r
    room_manager.rooms.pop(r.id, None)


# ===========================================================================
# 取值表：四个格子逐个钉住
# ===========================================================================
def test_ai_room_is_ai(room):
    """★ 人机局 ⇒ `'ai'`（判据 `room.is_ai_room`，不是从 id 猜）。"""
    room.is_ai_room = True
    assert server._match_history_mode(room) == 'ai'


def test_ranked_room_is_ranked(room):
    """★ 排位局 ⇒ `'ranked'`。"""
    room.ranked = True
    assert server._match_history_mode(room) == 'ranked'












# ===========================================================================
# 与 `_room_match_mode` 永不矛盾（★ 教训 #1：同一判断不许两份实现）
# ===========================================================================
def test_history_mode_never_contradicts_game_state_mode(room):
    """★★★ `_match_history_mode` 说是排位 ⇔ `_room_match_mode` 说是排位。

    对局内 `game_state` 的 `mode` 字段走 `_room_match_mode`，战绩里的 `'ranked'`
    走本批新加的 `_match_history_mode` —— 两者必须是**同一个判断**的两个出口。
    不然会出现"结算屏写着排位赛、战绩里写着匹配"这种没人能复现的错。

    穷举四种标记组合 + 人机，两种口径逐一对齐。
    """
    combos = [
        {},
        {'ranked': True},
        {'matchmade': True},
        {'matchmade': True, 'ranked': True},
        {'is_ai_room': True},
        {'is_ai_room': True, 'matchmade': True},
        # ⚠️ `{'is_ai_room': True, 'ranked': True}` **故意不列**：那个组合在本项目里
        #    不可能出现（`create_ai_room` 显式 `room.ranked = False`），
        #    而"人机优先于排位"是本函数的**有意优先级**（见 `test_ai_wins_over_everything`）。
        #    把它列进来只会让这条守卫去断言一个不存在的状态。
    ]
    for combo in combos:
        room.ranked = False
        room.matchmade = False
        room.is_ai_room = False
        for k, v in combo.items():
            setattr(room, k, v)
        history = server._match_history_mode(room)
        game = server._room_match_mode(room)
        # **排位那个轴**两种口径必须一致（`custom`/`casual` 是战绩口径多出来的细分，
        # 它们在对局内都属于非排位 —— 这一点也在下面那条断言里钉住）。
        assert (history == 'ranked') == (game == 'ranked'), (
            '排位那个轴两种口径对不上：标记=%s，战绩=%s、对局内=%s' % (combo, history, game))
        if history != 'ai':
            assert history in (game, 'custom'), history
        else:
            # 人机局：战绩口径把人机排在排位**之前**（人机房恒 ranked=False，
            # 所以线上不会出现矛盾；这条只钉住优先级是写死的，不是碰巧）
            assert room.is_ai_room is True
    # 反向校准：非人机的那几种确实两种口径都算过（否则上面是空转）。
    # 这一间是**匹配出来的休闲房**（`matchmade=True`）⇒ 两种口径都是 casual。
    room.is_ai_room = room.ranked = False
    room.matchmade = True
    assert server._match_history_mode(room) == server._room_match_mode(room) == 'casual'
    # 自定义房只在**战绩口径**里细分出来，对局内一律 casual
    room.matchmade = False
    assert server._match_history_mode(room) == 'custom'
    assert server._room_match_mode(room) == 'casual'






# ===========================================================================
# `matchmade` 的置位点：源码级穷举 + 三条反例
# ===========================================================================
def _src():
    return io.open(SERVER_PY, encoding='utf-8').read()


def _pairing_loop_sources():
    """扫出所有**消费 `match_queue` 完成配对**的 while 循环（按缩进切块）。

    判据 = 代码里出现了 **两个** `match_queue.pop(` —— 配对要取**两个人**。
    （一个 pop 的是"出队"（`remove_from_match_queue` / `cancel_match`），不是配对；
    这条是实测校准出来的：第一版只用"出现 pop"当判据，把出队也扫进来了。）

    将来新增第二条匹配入口（比如按段位分池），它必然也要 pop 两个人，
    于是会被这条守卫扫到。
    """
    src = _src()
    lines = src.split('\n')
    blocks = []
    for i, line in enumerate(lines):
        if 'match_queue.pop(' not in line:
            continue
        indent = len(line) - len(line.lstrip())
        # 往上找那个 while（缩进更小的最近一行）
        start = i
        for j in range(i, -1, -1):
            stripped = lines[j].strip()
            if stripped.startswith('while ') and (len(lines[j]) - len(lines[j].lstrip())) < indent:
                start = j
                break
        # 往下找到缩进回到 while 那一层为止
        while_indent = len(lines[start]) - len(lines[start].lstrip())
        end = start + 1
        for k in range(start + 1, len(lines)):
            if not lines[k].strip():
                continue
            if (len(lines[k]) - len(lines[k].lstrip())) <= while_indent:
                break
            end = k
        block = '\n'.join(lines[start:end + 1])
        if block.count('match_queue.pop(') >= 2:      # 取两个人 = 配对
            blocks.append((start + 1, block))
    return blocks












# ===========================================================================
# 落库 / 读回 / NULL 老行（§8 的 ①②③）
# ===========================================================================
def _last_match_id():
    return db_module.db.cursor.execute(
        'SELECT id FROM matches ORDER BY rowid DESC LIMIT 1').fetchone()['id']










def test_mode_column_migration_is_idempotent_and_upgrades_old_databases(tmp_path):
    """★★★ §8-12 的姊妹条：`matches.mode` 老表加列**幂等**，且老库能升级。

    ⚠️ `CREATE TABLE IF NOT EXISTS` 对已存在的表是**空操作** —— 生产库那 342 行
       所在的 `matches` 表只有 `ALTER TABLE` 一条路（教训 #14）。
       写错的症状是**线上 500**（读端一 SELECT 这一列就 no such column）。
    """
    import sqlite3
    path = tmp_path / 'old_matches.db'
    conn = sqlite3.connect(path)
    conn.executescript('''
        CREATE TABLE matches (id TEXT PRIMARY KEY, winner_id TEXT, loser_id TEXT,
                              timestamp INTEGER);
        INSERT INTO matches (id, winner_id, loser_id, timestamp)
        VALUES ('old-1', 'u1', 'u2', 1700000000);
    ''')
    conn.commit()
    conn.close()

    instance = db_module.Database()
    instance.close()
    instance.db_path = path
    instance.conn = sqlite3.connect(path, check_same_thread=False)
    instance.conn.row_factory = sqlite3.Row
    instance.cursor = instance.conn.cursor()
    instance.init_db()

    cols = {r[1] for r in instance.cursor.execute('PRAGMA table_info(matches)')}
    assert 'mode' in cols, '老库升级之后必须有这一列，否则线上 500'
    row = instance.cursor.execute(
        'SELECT mode FROM matches WHERE id = ?', ('old-1',)).fetchone()
    assert row['mode'] is None, '老行的 mode 必须是 NULL（不是 casual）'
    for _ in range(3):
        instance.init_db()              # 幂等
    assert instance.get_match_history('u1', 5)[0]['mode'] is None
