# -*- coding: utf-8 -*-
"""实时观战**第 5 批**：观战棋盘在「复活」与「棋盘重置」后必须跟着变。

## 作者实报的 4 个缺陷（本文件逐个钉住）

| # | 现象 | 根因（本批实测结论） |
| - | --- | --- |
| ① | 疗愈原地复活后，观战棋盘那一格仍然显示"沉" | 观众那块棋盘是**从 `attacks` 反推**的，而那份数据只在进席时来自快照；`board_attacks_updated` 在 `NOT_FOR_SPECTATORS` 里 ⇒ 永远不更新 |
| ② | 观战棋盘击沉格画「沉」、实战画 ✕ | `game.js` 全仓只有观战那一处写「沉」（实测 `grep` 只有 1 处），实战两处都是 `attack.hit ? '✕' : '○'` |
| ③ | 观战者看不到生效中的场地魔法 | 服务端 payload 是 `{'player_id','card':{…name…}}`，而观战 handler 读的是 `data.name` / `data.field_magic` ⇒ 恒 `undefined` ⇒ 被清成空串 |
| ④ | 回光返照 / 灵气复苏 / 败者食尘不重置观战棋盘 | 这三条都把 `player.attacks` 整批清空，但**没有任何一条事件到得了观众**（`reset_gameboard` / `board_attacks_updated` 都在 `NOT_FOR_SPECTATORS` 里） |

## ①②④是同一个根因，所以只有**一个**修法

**棋盘只从服务端的权威数据重新解算**，并把这份权威数据在棋盘变动的时刻推给观众
（`spectate_board` 帧）。**不给任何一张卡单独写"棋盘更新"** —— 那种按卡分支的写法
就是 CLAUDE.md 教训 #1 说的第二份实现，下一次加卡必然漂移。

帧里的字段与快照里给观众的那几块**同源**：
* 座位级 → `server._spectate_side_payload`（快照与帧共用同一个函数）；
* 格级   → `server._spectate_player_cells`（只有"已经轰过的格"）。

## 安全边界（本批最要紧的一条）

帧的数据源是 `Player.attacks`（**动作记录**），所以：
* **原地复活**（疗愈）会把那一格从历史里清掉 → 帧里那一格消失（与对手看到的一致）；
* **换位置重新部署**（增援 / 死者苏生 / 滥竽充数 / 神机妙算）的新位置**从来没挨过炮**
  → 在 `Player.attacks` 里根本不存在 → 帧里**一个字节都不会出现** ⇒ **新位置继续保密**。
  `test_redeploy_keeps_the_new_position_secret` 用"新位置最远那一格"把这个钉死。

## 形状守卫是**过滤**，不是断言

`spectate.canonical_frame_json` 按三级白名单（顶层 / 座位 / 格）**删掉**多余键 ——
所以以后有人往帧里塞 `ships` / `positions`，它也到不了观众手里。
`test_frame_shape_is_pinned_both_ways` 同时把服务端产出的键集合与那三张白名单
钉在一起（少一个键 = 前端静默退化成默认值，多一个 = 被静默丢掉）。
"""
import ast
import io
import json
import pathlib
import re
import uuid

import pytest

import db as db_module
import server
import spectate
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER_PY = REPO_ROOT / 'server.py'
GAME_JS = REPO_ROOT / 'static' / 'game.js'

SID_A, SID_B = 'spec5-sid-a', 'spec5-sid-b'
# 形状：`((船的格子…), (船的格子…), …)` —— 每艘船是"格子的元组"。
P1_SHIPS = tuple(((x, 0),) for x in range(6))
P2_SHIPS = tuple(((x, 5),) for x in range(6))
# 两格船：只有一格挨过炮，另一格是"未公开的船位"（与第 1 批 `BIG_SHIP_CELLS` 同用途）
BIG_SHIP_CELLS = ((3, 5), (4, 5))
PUBLIC_HIT_CELL = (3, 5)
HIDDEN_SHIP_CELL = (4, 5)


# ===========================================================================
# 房间 / 账号工厂（与第 2/4 批同一套约定）
# ===========================================================================
_ACCOUNTS = {}


def _account(key):
    if key not in _ACCOUNTS:
        uid = db_module.create_user('spec5-%s-%s' % (key, uuid.uuid4().hex[:10]), 'x' * 12)
        assert uid, '建测试账号失败'
        _ACCOUNTS[key] = uid
    return _ACCOUNTS[key]


def _ships(shape):
    return [PlayerShip(positions=[Position(x, y) for (x, y) in cells], hits=[])
            for cells in shape]


def _make_room(room_id=None, a_ships=P1_SHIPS, b_ships=P2_SHIPS):
    room_id = room_id or ('spec5-' + uuid.uuid4().hex[:6])
    room = GameRoom(room_id)
    room.players[SID_A] = Player(name='甲', ships=_ships(a_ships), attacks=[],
                                 remaining_ships=len(a_ships), sid=SID_A,
                                 user_id=_account('alpha'))
    room.players[SID_B] = Player(name='乙', ships=_ships(b_ships), attacks=[],
                                 remaining_ships=len(b_ships), sid=SID_B,
                                 user_id=_account('beta'))
    room.state = 'attacking'
    room.current_phase = 'battle'
    room.current_attacker = SID_A
    room.attack_order = [SID_A, SID_B]
    room.attacks_remaining = 5
    room.round = 3
    room.ranked = False
    room.game_logs = []
    room_manager.rooms[room.id] = room
    return room


@pytest.fixture
def room():
    r = _make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def _sid_of(client):
    return server.socketio.server.manager.sid_from_eio_sid(client.eio_sid, '/')


def _http(uid=None, username=None):
    http = server.app.test_client()
    if uid:
        with http.session_transaction() as sess:
            sess['user_id'] = uid
            sess['username'] = username or uid
    return http


@pytest.fixture
def socket_for(room):
    """真登录的 socket（与第 4 批同一套；`enter` 时同时进对局房间）。"""
    made = []

    def _make(uid, enter=None, username=None):
        client = server.socketio.test_client(server.app,
                                             flask_test_client=_http(uid, username))
        if enter:
            server.socketio.server.enter_room(_sid_of(client), enter)
        client.get_received()
        made.append(client)
        return client

    yield _make
    for client in made:
        try:
            client.disconnect()
        except Exception:                   # noqa: BLE001
            pass


def _drain(client):
    """收件队列按事件名归组（**一次取完**，避免多次 get_received 互相掏空）。

    ⚠️ `msg['args']` 不保证是 list：`connect` / 纯声明类事件的 args 可能是 dict
    （`{0: …}` 形式），拿 `args[0]` 直接取会抛 `KeyError: 0` —— 实测踩过。
    """
    out = {}
    for msg in client.get_received():
        args = msg.get('args')
        if isinstance(args, list):
            payload = args[0] if args else None
        elif isinstance(args, dict):
            payload = args.get(0)
        else:
            payload = None
        out.setdefault(msg.get('name'), []).append(payload)
    return out


def _join(client, room):
    return client.emit('spectate_join', {'room_id': room.id}, callback=True)


def _func_src(name):
    """按**函数名**取 `server.py` 里那个函数的源码（不按行号）。"""
    src = io.open(SERVER_PY, encoding='utf-8').read()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ''
    raise AssertionError('server.py 里找不到函数 %s（改名了？）' % name)


def _js():
    return io.open(GAME_JS, encoding='utf-8').read()


def _js_func(name):
    """按名字取 game.js 里 `function name(...) { … }` 的片段。

    ⚠️ 不能只数大括号：函数体里的**字符串字面量**可能带不配对的 `{` / `}`
    （模板串、中文文案），一数就错位，取到的片段会一路吃到文件尾 ——
    那种判据会"因为切片太大而永远通过"，是最难发现的一种假绿。
    所以这里走一个**认识字符串 / 注释 / 模板串 **的小扫描器。
    """
    src = _js()
    marker = 'function ' + name + '('
    start = src.index(marker)
    i = src.index('{', start)
    depth = 0
    j = i
    n = len(src)
    while j < n:
        ch = src[j]
        if ch == '/' and j + 1 < n and src[j + 1] == '/':
            j = src.index('\n', j)
            continue
        if ch == '/' and j + 1 < n and src[j + 1] == '*':
            j = src.index('*/', j) + 2
            continue
        if ch in ('"', "'", '`'):
            quote = ch
            j += 1
            while j < n and src[j] != quote:
                j += 2 if src[j] == '\\' else 1
            j += 1
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return src[start:j + 1]
        j += 1
    raise AssertionError('game.js 里找不到函数 %s 的结尾' % name)


class _Frames:
    """把发往观战通道的 `spectate_board` 帧抓下来（其余 emit 也一并记账）。"""

    def __init__(self):
        self.frames = []
        self.other = []

    def install(self, monkeypatch):
        real = server.socketio.emit

        def spy(event, *a, **kw):
            payload = a[0] if a else None
            if event == 'spectate_board':
                self.frames.append((kw.get('room'), payload))
            else:
                self.other.append((event, kw.get('room')))
            return None

        monkeypatch.setattr(server.socketio, 'emit', spy)
        return real

    @property
    def last(self):
        assert self.frames, '一条 spectate_board 都没发出来'
        return self.frames[-1][1]


@pytest.fixture
def frames(monkeypatch):
    f = _Frames()
    f.install(monkeypatch)
    return f


def _seed_hit(room):
    """造出一艘"被击沉的两格船"：甲轰过 (3,5)，乙那艘船 hits 记一格 → 已沉。"""
    attacker = room.players[SID_A]
    defender = room.players[SID_B]
    attacker.attacks.append(Position(x=PUBLIC_HIT_CELL[0], y=PUBLIC_HIT_CELL[1],
                                     hit=True, ship_sunk=True))
    ship = next(s for s in defender.ships
                if any(p.x == PUBLIC_HIT_CELL[0] and p.y == PUBLIC_HIT_CELL[1]
                       for p in s.positions))
    ship.hits.append(Position(x=PUBLIC_HIT_CELL[0], y=PUBLIC_HIT_CELL[1], hit=True))
    defender.sunken_ships.append(ship)
    defender.remaining_ships -= 1
    return ship


# ===========================================================================
# 0. 帧的形状（这是"漏加一个键 = 透视"的机器守卫）
# ===========================================================================




def _all_keys(node, out=None):
    """递归收集 payload 里出现的全部字典键（**精确键名**，不是子串匹配）。

    ⚠️ 必须按精确键名断言：`'ships' in json.dumps(...)` 会被
    `remaining_ships` 这种**合法**字段命中，那种判据红的是它自己。
    """
    if out is None:
        out = set()
    if isinstance(node, dict):
        out.update(node.keys())
        for v in node.values():
            _all_keys(v, out)
    elif isinstance(node, list):
        for v in node:
            _all_keys(v, out)
    return out


def _all_coords(node, out=None):
    """递归收集 payload 里出现的全部坐标（`{'x':int,'y':int}` 形状）。"""
    if out is None:
        out = set()
    if isinstance(node, dict):
        if isinstance(node.get('x'), int) and isinstance(node.get('y'), int):
            out.add((node['x'], node['y']))
        for v in node.values():
            _all_coords(v, out)
    elif isinstance(node, list):
        for v in node:
            _all_coords(v, out)
    return out


def test_canonical_frame_strips_anything_outside_the_whitelist():
    """★ 白名单是**过滤**：塞进去的 `ships` / `positions` / 怪座位一律到不了观众手里。"""
    clean = spectate.canonical_frame_json({
        'room_id': 'r1',
        'seat_labels': {'sidA': 'p1', 'eve': 'p9'},
        'evil': 'x',
        'ships': [{'positions': [{'x': 0, 'y': 0}]}],
        'sides': {
            'p1': {'seat_id': 'sidA', 'name': '甲', 'remaining_ships': 6, 'hand_count': 2,
                   'attacks': [{'x': 1, 'y': 2, 'hit': True, 'ship_sunk': False,
                                'positions': [{'x': 9, 'y': 9}]}],
                   'ships': [{'positions': []}], 'magic_hand': ['x']},
            'p3': {'attacks': [{'x': 7, 'y': 7}]},
        },
    })
    keys = _all_keys(clean)
    assert set(clean) == set(spectate.SPECTATE_FRAME_KEYS)
    for forbidden in ('ships', 'positions', 'hits', 'sunk_positions',
                      'magic_hand', 'evil'):
        assert forbidden not in keys, '帧里漏出了 %r（keys=%s）' % (forbidden, sorted(keys))
    assert 'evil' not in clean
    assert set(clean['sides']) == {'p1'}                       # p3 不是座位标签 → 丢掉
    assert list(clean['sides']['p1']) == ['seat_id', 'name', 'remaining_ships',
                                          'hand_count', 'attacks']
    assert clean['sides']['p1']['attacks'] == [
        {'x': 1, 'y': 2, 'hit': True, 'ship_sunk': False}]
    assert _all_coords(clean) == {(1, 2)}, \
        '格里的多余字段（positions 里的 (9,9)）漏出来了：%s' % sorted(_all_coords(clean))






# ===========================================================================
# 1. ★★ 帧里不许出现"没挨过炮的船位"（核心不变量 #1）
# ===========================================================================
def test_frame_never_carries_an_unhit_ship_cell(room):
    """★★ 船位已知、只轰过一格 → 帧里**只有那一格**，另一格一个字节都没有。

    这是本批最要紧的安全断言：帧是**新的事件**，必须证明它没有把
    "没挨过炮的船位"带出去（那才是透视）。
    """
    room.players[SID_B].ships = _ships((BIG_SHIP_CELLS, ((0, 5),), ((1, 5),),
                                        ((2, 5),), ((5, 5),), ((0, 0),)))
    room.players[SID_B].remaining_ships = 6
    room.players[SID_A].attacks.append(
        Position(x=PUBLIC_HIT_CELL[0], y=PUBLIC_HIT_CELL[1], hit=True, ship_sunk=False))

    frame = server._spectate_board_frame(room)
    clean = spectate.canonical_frame_json(frame)
    coords = _all_coords(clean)

    assert coords == {PUBLIC_HIT_CELL}, \
        '帧里出现了不是"已轰过"的格：%s（只允许 %s）' % (sorted(coords), PUBLIC_HIT_CELL)
    assert HIDDEN_SHIP_CELL not in coords, \
        '★ 两格船的**没挨过炮那一格**出现在帧里了 —— 这就是透视'
    # 反向校准：那一格**确实**是船位（否则上面那条是空转的）
    ship_cells = {(p.x, p.y) for s in room.players[SID_B].ships for p in s.positions}
    assert HIDDEN_SHIP_CELL in ship_cells, \
        '反向校准失效：样例里那一格本来就不在船位上，这条守卫是空转的'
    assert HIDDEN_SHIP_CELL != PUBLIC_HIT_CELL


def test_redeploy_keeps_the_new_position_secret(room, frames):
    """★★ 换位置重新部署（增援 / 死者苏生 / 滥竽充数 / 神机妙算）的新位置**必须继续保密**。

    做法：走 `_clear_attacks_on_cells`（这四张卡清格子的**唯一**入口），
    新位置选在棋盘另一头，断言帧里**一个字节**都不出现那个坐标。
    """
    attacker = room.players[SID_A]
    attacker.attacks.append(Position(x=1, y=5, hit=True, ship_sunk=False))
    attacker.attacks.append(Position(x=2, y=5, hit=False, ship_sunk=False))
    frames.frames.clear()

    # 乙的一艘船**重新部署**到 (5,5)（甲从没打过这里），同时把 (1,5) 那一格腾干净。
    # 走 `_clear_attacks_on_cells`：它正是那四张"换位置重新部署"的卡清格子的唯一入口。
    new_cell = (5, 5)
    server._clear_attacks_on_cells(room, [Position(x=1, y=5)], SID_B)

    assert new_cell != (1, 5) and new_cell != (2, 5)
    coords = _all_coords(frames.last)
    assert new_cell not in coords, '★ 重新部署的新位置泄漏到了观战帧里'
    assert coords == {(2, 5)}, \
        '帧里只该剩甲轰过、且没被清掉的那一格，实际 %s' % sorted(coords)


# ===========================================================================
# 2. ★★ 缺陷 ①：疗愈原地复活 → 观战棋盘必须跟着变
# ===========================================================================
def test_heal_revive_clears_the_sunk_mark_in_the_frame(room, frames):
    """★★ 击沉 → 疗愈复活：帧里那一格必须**消失**（与对手看到的一致）。

    改坏哪一行会红：`server._clear_attacks_on_cells` 里那句
    `_publish_spectate_board(room)` 一删，这条立刻红（帧压根不发）。
    """
    _seed_hit(room)
    before = server._spectate_board_frame(room)
    # ⚠️ 方向（第 6 批改）：帧里 `sides[label].attacks` = **label 自己打出去**的格，
    #    与快照同向。所以"落在乙棋盘上那一格"写在 **`sides.p1`**（甲打出去的）。
    assert before['sides']['p1']['attacks'] == [
        {'x': 3, 'y': 5, 'hit': True, 'ship_sunk': True}], '前置：那一格先是"击沉"'

    frames.frames.clear()
    revived = server._revive_sunken_ships(
        room, room.players[SID_B], 2, reveal_to=SID_A)
    assert revived == 1

    assert frames.frames, '疗愈之后一条 spectate_board 都没发 —— 观战棋盘会永远停在"沉"'
    after = frames.last
    assert after['sides']['p1']['attacks'] == [], \
        '疗愈复活后，观战帧里那一格仍然存在（%s）' % after['sides']['p1']['attacks']
    assert after['sides']['p2']['remaining_ships'] == 6, \
        '复活让剩余船数 +1（5→6），帧里的船数必须是复活后的真值（%s）' \
        % after['sides']['p2']['remaining_ships']
    assert room.players[SID_B].remaining_ships == 6


def test_heal_frame_reaches_a_real_spectator_and_not_the_players(room, socket_for):
    """★ 真 socket 两侧同时看：观众收得到 `spectate_board`，两个玩家一个字节都收不到。

    ⚠️ 对照腿不可少：只断言"玩家没收到"是**空转绿**（发送路径整个坏掉时照样通过）。
    这里的第一条对照腿是"**另一个观众**收到了"；第二条是"这两条玩家连接当时
    确实活着、而且在收事件"（靠给双方各发一条 `message` 来证明）。
    """
    spec = socket_for(_account('watcher'), username='watcher')
    spec2 = socket_for(_account('watcher2'), username='watcher2')
    player_a = socket_for(_account('alpha'), enter=room.id)
    player_b = socket_for(_account('beta'), enter=room.id)
    assert _join(spec, room)['status'] == 'success'
    assert _join(spec2, room)['status'] == 'success'
    for client in (spec, spec2, player_a, player_b):
        _drain(client)

    _seed_hit(room)
    server._revive_sunken_ships(room, room.players[SID_B], 2, reveal_to=SID_A)

    # ① 观众收得到（而且两个观众都收得到）
    for client, who in ((spec, '观众一'), (spec2, '观众二')):
        got = _drain(client)
        assert 'spectate_board' in got, '%s 没收到棋盘帧（收到的：%s）' % (who, sorted(got))
        frame = got['spectate_board'][-1]
        assert frame['sides']['p1']['attacks'] == [], '棋盘那一格没有跟着复活清掉'
        assert set(frame['sides']) == {'p1', 'p2'}
        assert {frame['sides']['p1']['seat_id'], frame['sides']['p2']['seat_id']} \
            == {SID_A, SID_B}, '帧里的座位对不上这两名玩家'

    # ② 隔离腿：两个玩家**一个字节都收不到**观战棋盘帧
    for client, who in ((player_a, '甲'), (player_b, '乙')):
        names = set(_drain(client))
        assert 'spectate_board' not in names, '%s 收到了观战棋盘帧' % who

    # ③ 对照腿（第二轮）：证明这两条玩家连接当时**活着而且在收事件** ——
    #    否则上面那条"没收到"可能只是因为连接早就断了（空转绿）。
    server.emit('message', {'message': 'batch5-leg-check', 'type': 'info'}, room=room.id)
    for client, who in ((player_a, '甲'), (player_b, '乙')):
        names = set(_drain(client))
        assert 'message' in names, '%s 这条连接根本没在收事件（对照腿失效）' % who






# ===========================================================================
# 3. ★★ 缺陷 ④：棋盘重置类卡牌
# ===========================================================================




def test_huiguang_reset_clears_only_the_casters_board_in_the_frame(room, frames):
    """★★ 回光返照：只清**施法者**那块棋盘，对手那块一格都不能动。

    ⚠️ 这条是本批最容易被"顺手多清一块"的地方：服务端只清 `opponent.attacks`
    （对方打在施法者棋盘上的记录），帧必须与它同口径。
    """
    room.current_attacker = SID_A          # 回光返照要求自己先手
    room.players[SID_A].attacks.append(Position(x=1, y=5, hit=True, ship_sunk=False))
    room.players[SID_B].attacks.append(Position(x=2, y=0, hit=False, ship_sunk=False))

    frames.frames.clear()
    res = server.apply_magic_effect(room, SID_A, MagicCard('回光返照'), {})
    assert res.success is not False, res.message

    assert frames.frames, '回光返照之后一条 spectate_board 都没发'
    # ⚠️ 方向（第 6 批改）：帧里 `sides[label].attacks` = **label 自己打出去**的格。
    #    回光返照清的是"对方（乙）打在甲那块棋盘上的记录" ⇒ 乙的 `attacks` 清空
    #    ⇒ 帧里 **`sides.p2`** 清空；甲自己打在乙棋盘上的那些格与本次重摆无关
    #    ⇒ 帧里 **`sides.p1`** 一格都不许动。
    assert frames.last['sides']['p2']['attacks'] == [], \
        '被清掉的那一位（乙）在帧里必须清空（实际 %s）' % frames.last['sides']['p2']['attacks']
    assert frames.last['sides']['p1']['attacks'] == [
        {'x': 1, 'y': 5, 'hit': True, 'ship_sunk': False}], \
        '施法者自己打出去的格与本次重摆无关，一格都不该动（实际 %s）' \
        % frames.last['sides']['p1']['attacks']






# ===========================================================================
# 4. ★ 缺陷 ③：观战者看不到生效中的场地魔法
# ===========================================================================










# ===========================================================================
# 5. ★ 缺陷 ②：字形统一（源码级）
# ===========================================================================






# ===========================================================================
# 6. ★ 通道隔离：这条新事件**只**发观战通道
# ===========================================================================
def test_frame_goes_only_to_the_spectate_channel():
    """★★ 源码级：`_publish_spectate_board` 只许用观战通道名。

    一旦有人顺手改成 `room=room.id`（"顺便让玩家也看到"），玩家当场多收一条
    毫无意义的大 payload —— 而且**运行时毫无症状**。
    """
    body = _func_src('_publish_spectate_board')
    rooms = []
    for node in ast.walk(ast.parse(body)):
        if isinstance(node, ast.Call):
            fname = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, 'attr', None)
            if fname not in ('emit', 'semit'):
                continue
            for kw in node.keywords:
                if kw.arg == 'room':
                    rooms.append(ast.unparse(kw.value).replace(' ', ''))
    assert rooms, '没扫到 room= 参数 —— 这条守卫自己失效了'
    for room_kw in rooms:
        assert 'spectate.spectate_room_id(' in room_kw, \
            '棋盘帧发到了非观战通道：room=%s' % room_kw


def test_frame_is_not_forwarded_by_the_emit_third_leg(room, frames):
    """★ 棋盘帧走的是 `socketio.emit` 直发，**不经** `emit` 的第三条腿。

    所以它不会因为"有人在别处 emit 同名事件"而重复发、也不会拐回对局 room。
    """
    frames.frames.clear()
    server.emit('attack_result', {'attacker': SID_A, 'x': 0, 'y': 0, 'hit': False},
                room=room.id)
    assert not frames.frames, '`emit` 的第三条腿把 spectate_board 也发了一份（会重复）'


# ===========================================================================
# 7. ★ 前端接线（id / 事件名 / 形状）
# ===========================================================================




def _strip_js_comments(src):
    """剔掉 `//` 行注释与 `/* */` 块注释（保留字符串字面量）。"""
    out = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == '/' and i + 1 < n and src[i + 1] == '/':
            i = src.index('\n', i)
            continue
        if ch == '/' and i + 1 < n and src[i + 1] == '*':
            i = src.index('*/', i) + 2
            continue
        if ch in ('"', "'", '`'):
            quote = ch
            out.append(ch)
            i += 1
            while i < n and src[i] != quote:
                if src[i] == '\\':
                    out.append(src[i])
                    i += 1
                if i < n:
                    out.append(src[i])
                    i += 1
            if i < n:
                out.append(src[i])
                i += 1
            continue
        out.append(ch)
        i += 1
    return ''.join(out)
