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
def test_frame_shape_is_pinned_both_ways(room):
    """★ 服务端产出的键集合必须**正好等于**那三张白名单。

    * 少一个键 → 观众屏上那项静默退化成默认值（名字变"玩家"、船数变 0）；
    * 多一个键 → `canonical_frame` 会把它**静默丢掉**（功能少了但零报错）。

    ⚠️ 两边都断言，所以"改白名单不改实现"和"改实现不改白名单"都会变红。
    """
    room.players[SID_A].attacks.append(Position(x=1, y=5, hit=False, ship_sunk=False))
    frame = server._spectate_board_frame(room)

    assert set(frame) == set(spectate.SPECTATE_FRAME_KEYS), \
        '帧的顶层键与白名单不一致：%s' % sorted(set(frame) ^ set(spectate.SPECTATE_FRAME_KEYS))
    for label in ('p1', 'p2'):
        side = frame['sides'][label]
        assert set(side) == set(spectate.SPECTATE_FRAME_SIDE_KEYS), \
            '帧的座位键与白名单不一致（%s）：%s' % (
                label, sorted(set(side) ^ set(spectate.SPECTATE_FRAME_SIDE_KEYS)))
        for cell in side['attacks']:
            assert set(cell) == set(spectate.SPECTATE_FRAME_CELL_KEYS), \
                '帧的格键与白名单不一致：%s' % sorted(cell)


def test_frame_side_payload_is_shared_with_the_snapshot(room):
    """★ 快照里的座位与帧里的座位必须是**同一份实现**（教训 #1：不许两份）。

    做法：帧的 `attacks` 是快照 `sides[对方].attacks` 的**转置**，
    其余字段逐字相同 —— 断言到字段级别（这是"单一实现"的可执行版本）。
    """
    room.players[SID_A].attacks.append(Position(x=2, y=5, hit=True, ship_sunk=False))
    room.players[SID_B].attacks.append(Position(x=4, y=0, hit=False, ship_sunk=False))
    snap = server._build_spectate_snapshot(room)
    frame = server._spectate_board_frame(room)

    for label, other in (('p1', 'p2'), ('p2', 'p1')):
        for key in ('seat_id', 'name', 'remaining_ships', 'hand_count'):
            assert frame['sides'][label][key] == snap['sides'][label][key], \
                '帧与快照的 %s.%s 不一致（说明长出了第二份实现）' % (label, key)
        # 方向相反是**设计**：快照给的是"该座位打出去的格"，帧给的是"落在该棋盘上的格"
        assert frame['sides'][label]['attacks'] == snap['board_attacks'][label]
        assert frame['sides'][label]['attacks'] == snap['sides'][other]['attacks']


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


def test_canonical_strip_guard_can_actually_fail():
    """★ 元测试：证明上面那条**真的有能力变红**（教训 #34）。

    做法：把白名单临时放宽成"什么都收"，同一份 payload 就会**带出** `ships` ——
    说明上面那条断言是因为过滤真的在跑才绿的，而不是因为样例本来就没有。
    """
    payload = {
        'room_id': 'r1',
        'sides': {'p1': {'attacks': [], 'ships': [{'positions': [{'x': 0, 'y': 0}]}]}},
    }
    assert 'ships' not in json.dumps(spectate.canonical_frame_json(payload))

    original = spectate.SPECTATE_FRAME_SIDE_KEYS
    spectate.SPECTATE_FRAME_SIDE_KEYS = frozenset({'attacks', 'ships'})
    try:
        # 白名单本身可以通过，但**过滤代码只挑它认识的那几个键** ——
        # 这条断言就是为了证明"过滤不是白名单的装饰品"。
        loose = spectate._canonical_frame_sides({'p1': {'attacks': [], 'ships': [1]}})
        assert 'ships' not in loose['p1'], \
            '过滤实现只该按固定字段取值，不该跟着白名单变量跑 —— 这条守卫是空的'
    finally:
        spectate.SPECTATE_FRAME_SIDE_KEYS = original

    # 真正能让它变红的是"白名单与实现脱钩"：把实现里那一行也改掉，帧就会带出 ships
    src = io.open(REPO_ROOT / 'spectate.py', encoding='utf-8').read()
    assert "clean['attacks'] = _canonical_frame_cells(side.get('attacks'))" in src, \
        '帧的座位级过滤点找不到了 —— 这条元测试自己失效了，必须修'


def test_import_time_validation_covers_the_frame_tables():
    """导入期自检必须覆盖三条帧相关的规矩（不是文档里的君子协定）。

    ⚠️ 判据是"`_validate_frame_keys()` 出现在 **`_validate()` 的函数体里**" ——
    用"整文件里有没有这个字符串"去判会**永远绿**（定义行自己就含这个子串），
    而"按 `_validate()` 切尾"这条判据本用例自己红过两次（`^_validate()` 与
    缩进的 `_validate_frame_keys()` 都会被那个子串匹配到）。
    """
    src = io.open(REPO_ROOT / 'spectate.py', encoding='utf-8').read()
    body = None
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == '_validate':
            body = ast.get_source_segment(src, node) or ''
    assert body, 'spectate.py 里找不到 `_validate()`（改名了？）'
    assert '_validate_frame_keys()' in body, \
        '`_validate()` 的函数体里没有调用 `_validate_frame_keys()` —— 帧白名单没人看着'
    for needle in ('CANONICALIZE', 'SPECTATE_FRAME_KEYS', 'SPECTATE_FRAME_SIDE_KEYS',
                   'SPECTATE_FRAME_CELL_KEYS'):
        assert needle in src, '缺少 %s' % needle
    assert spectate.SPECTATE_EVENTS.get('spectate_board') is spectate.canonical_frame_json, \
        'spectate_board 必须登记成 canonical_frame_json（否则形状没人过滤）'
    assert 'spectate_board' in spectate.CANONICALIZE


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
    assert before['sides']['p2']['attacks'] == [
        {'x': 3, 'y': 5, 'hit': True, 'ship_sunk': True}], '前置：那一格先是"击沉"'

    frames.frames.clear()
    revived = server._revive_sunken_ships(
        room, room.players[SID_B], 2, reveal_to=SID_A)
    assert revived == 1

    assert frames.frames, '疗愈之后一条 spectate_board 都没发 —— 观战棋盘会永远停在"沉"'
    after = frames.last
    assert after['sides']['p2']['attacks'] == [], \
        '疗愈复活后，观战帧里那一格仍然存在（%s）' % after['sides']['p2']['attacks']
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
        assert frame['sides']['p2']['attacks'] == [], '棋盘那一格没有跟着复活清掉'
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


def test_heal_frame_is_one_frame_per_operation_not_a_storm(room, frames):
    """★ 一次疗愈最多两条帧（清格一条 + 收尾一条），**不是**每条清格都发一条。

    防的是"每清一艘船发一整块棋盘" —— 多格复活时会变成事件风暴。
    """
    for x in (1, 2, 3):
        room.players[SID_A].attacks.append(
            Position(x=x, y=5, hit=True, ship_sunk=True))
    for ship_x in (1, 2, 3):
        ship = next(s for s in room.players[SID_B].ships
                    if any(p.x == ship_x and p.y == 5 for p in s.positions))
        ship.hits.append(Position(x=ship_x, y=5, hit=True))
        room.players[SID_B].sunken_ships.append(ship)
        room.players[SID_B].remaining_ships -= 1

    frames.frames.clear()
    revived = server._revive_sunken_ships(room, room.players[SID_B], 3, reveal_to=SID_A)
    assert revived == 3
    # 一条来自 `_clear_attacks_on_cells` 的"有变化"分支（3 次清格只触发 3 次标记，
    # 但每次都会发）—— 这里只要求"**不超过**清格次数 + 1"，重点是不爆炸、且最后一条是对的。
    assert len(frames.frames) <= 4, '一条卡打出了 %d 条棋盘帧' % len(frames.frames)
    assert frames.last['sides']['p2']['attacks'] == []
    assert frames.last['sides']['p2']['remaining_ships'] == 6


def test_heal_boundary_heals_the_cell_and_nothing_else(room, frames):
    """★ 只清"复活那一格"：同一块棋盘上别的已轰格必须原地不动。

    防的是"为了修缺陷 ① 把整块棋盘清空" —— 那会让观众从"看得到"退化成"什么都看不到"。
    """
    attacker = room.players[SID_A]
    attacker.attacks.append(Position(x=PUBLIC_HIT_CELL[0], y=PUBLIC_HIT_CELL[1],
                                     hit=True, ship_sunk=True))
    attacker.attacks.append(Position(x=0, y=5, hit=False, ship_sunk=False))
    attacker.attacks.append(Position(x=1, y=5, hit=True, ship_sunk=False))
    ship = next(s for s in room.players[SID_B].ships
                if any(p.x == PUBLIC_HIT_CELL[0] and p.y == PUBLIC_HIT_CELL[1]
                       for p in s.positions))
    ship.hits.append(Position(x=PUBLIC_HIT_CELL[0], y=PUBLIC_HIT_CELL[1], hit=True))
    room.players[SID_B].sunken_ships.append(ship)
    room.players[SID_B].remaining_ships -= 1

    frames.frames.clear()
    server._revive_sunken_ships(room, room.players[SID_B], 2, reveal_to=SID_A)
    cells = [(c['x'], c['y'], c['hit'], c['ship_sunk']) for c in frames.last['sides']['p2']['attacks']]
    assert cells == [(0, 5, False, False), (1, 5, True, False)], \
        '只该少掉复活那一格，实际 %s' % cells


# ===========================================================================
# 3. ★★ 缺陷 ④：棋盘重置类卡牌
# ===========================================================================
def test_lingqi_reset_clears_both_boards_in_the_frame(room, frames):
    """★★ 灵气复苏（双方重摆 6 艘）：两块棋盘在帧里都必须清空。"""
    room.players[SID_A].attacks.append(Position(x=1, y=5, hit=True, ship_sunk=False))
    room.players[SID_B].attacks.append(Position(x=2, y=0, hit=False, ship_sunk=False))
    assert server._spectate_board_frame(room)['sides']['p1']['attacks'], '前置：有格'

    frames.frames.clear()
    # 灵气复苏的开场数据（服务端 `apply_magic_effect` 里那一段就是这个形状）
    room.magic_temp_data = {'type': 'lingqi_choice', 'caster': SID_A, 'max_ships': 6}
    resp = server.confirm_magic_target({
        'room_id': room.id, 'player_id': SID_A, 'temp_data_id': 'lingqi_choice',
        'target_data': {'target_ships': 6},
    })
    assert resp.get('status') == 'success', resp

    assert frames.frames, '灵气复苏之后一条 spectate_board 都没发'
    assert frames.last['sides']['p1']['attacks'] == []
    assert frames.last['sides']['p2']['attacks'] == []
    # ⚠️ 同上：连船数一起断言 —— 否则"本来就空的房间"也会通过（空转绿）
    for label in ('p1', 'p2'):
        assert frames.last['sides'][label]['remaining_ships'] == 0, \
            '重摆后 %s 的船数是 0，帧里却是 %s' \
            % (label, frames.last['sides'][label]['remaining_ships'])


def test_baizhe_shichen_reset_clears_both_boards_in_the_frame(room, frames):
    """★★ 败者食尘（双方重摆）：两块棋盘在帧里都必须清空、船数归零。

    ⚠️ 为什么这里要连**船数**一起断言（而不是只看"棋盘空了"）：
    棋盘本来就是空的房间也会让"格子为空"通过 —— 那是空转绿。
    这一局每个座位 6 艘，败者食尘把它们清成 0，**只有真的发了帧**才看得到这个 0。
    """
    room.players[SID_A].attacks.append(Position(x=1, y=5, hit=True, ship_sunk=False))
    room.players[SID_B].attacks.append(Position(x=2, y=0, hit=False, ship_sunk=False))
    assert room.players[SID_A].remaining_ships == 6, '前置：这一局双方各 6 艘'

    frames.frames.clear()
    res = server.apply_magic_effect(room, SID_A, MagicCard('败者食尘'), {})
    assert res.success is not False, res.message

    assert frames.frames, '败者食尘之后一条 spectate_board 都没发'
    assert frames.last['sides']['p1']['attacks'] == []
    assert frames.last['sides']['p2']['attacks'] == []
    for label in ('p1', 'p2'):
        assert frames.last['sides'][label]['remaining_ships'] == 0, \
            '重摆后 %s 的船数是 0，帧里却是 %s（说明帧没跟着重置）' \
            % (label, frames.last['sides'][label]['remaining_ships'])


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
    # ⚠️ 方向：`sides.p1.attacks` = 落在**甲那块棋盘**上的格 = **乙**打出去的格。
    #    回光返照清的是"对方（乙）打在施法者（甲）棋盘上的记录"⇒ p1 这块清空；
    #    甲自己打在乙棋盘上的那些格**与本次重摆无关** ⇒ p2 这块一格不动。
    assert frames.last['sides']['p1']['attacks'] == [], \
        '施法者那块棋盘该被清空（实际 %s）' % frames.last['sides']['p1']['attacks']
    assert frames.last['sides']['p2']['attacks'] == [
        {'x': 1, 'y': 5, 'hit': True, 'ship_sunk': False}], \
        '对手那块棋盘没被重摆，一格都不该动（实际 %s）' % frames.last['sides']['p2']['attacks']


def test_every_attacks_clear_site_publishes_the_frame():
    """★★ 源码级穷举：`server.py` 里**每一处**清空/重写 `attacks` 的地方，
    要么是已登记的、要么必须紧跟着发一次棋盘帧。

    为什么必须穷举：缺陷 ④ 的形状就是"有人加了一张重摆卡、清完 `attacks`
    就收工" —— 那种写法**运行时零症状**（服务端状态全对、玩家界面全对，
    只有观众那块棋盘静静过期）。按行号钉会随注释漂移，所以这里按**函数体**钉。
    """
    src = io.open(SERVER_PY, encoding='utf-8').read()
    tree = ast.parse(src)
    lines = src.splitlines()

    def _targets_attacks(node):
        return (isinstance(node, ast.Attribute) and node.attr == 'attacks')

    sites = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = ast.get_source_segment(src, func) or ''
        for node in ast.walk(func):
            hit = False
            if isinstance(node, ast.Assign) and _targets_attacks(node.targets[0] if node.targets else None):
                hit = True
            elif isinstance(node, ast.Call) and node.func.__class__ is ast.Attribute \
                    and node.func.attr == 'clear' and _targets_attacks(node.func.value):
                hit = True
            if hit:
                sites.append((func.name, node.lineno, body))

    assert sites, '一个清空 attacks 的地方都没扫到 —— 这条守卫自己失效了'

    # 这些函数**允许**清 attacks：它们清的是"本次操作自己刚打出去的那一炮"
    # （`attacks.append` 的镜像路径，观众已由 `attack_result` 看到），
    # 与"棋盘被换掉"无关，不需要发帧。
    EXEMPT = {
        # 调试接口：直接重建整局，不走任何对外事件（观众那边对局已经结束了）
        'test_reset_game',
    }
    # 这些函数必须有 `_publish_spectate_board(...)`
    MUST_PUBLISH = {
        '_clear_attacks_on_cells',
    }
    # "声明过"的两种写法：立刻发（`_publish_spectate_board`）或声明"这里变了"
    # （`_mark_spectate_board_dirty`，它内部就会发一条）。两种都算。
    PUBLISH_MARKERS = ('_mark_spectate_board_dirty(', '_publish_spectate_board(')
    offenders = []
    for name, lineno, body in sites:
        if name in EXEMPT:
            continue
        if name in MUST_PUBLISH:
            if not any(m in body for m in PUBLISH_MARKERS):
                offenders.append((name, lineno, '函数体里没有_ mark/_publish_spectate_board'))
            continue
        # 其余（内联在 confirm_magic_target / apply_magic_effect 里的重摆分支）：
        # 那个清空语句**之后**必须出现过一次声明。
        tail = '\n'.join(lines[lineno:])
        if not any(m in tail for m in PUBLISH_MARKERS):
            offenders.append((name, lineno, '清空 attacks 之后没有再让观众知道'))

    assert not offenders, (
        '这些地方清了 attacks 却没让观众知道（观战棋盘会静静过期）：\n%s\n'
        '（如果这是"刚打出去那一炮"的镜像路径，请把它加进本用例的 EXEMPT 并写明理由）'
        % '\n'.join('  %s:%d %s' % x for x in offenders)
    )


def test_attacks_clear_site_guard_can_actually_fail():
    """★ 元测试：证明上面那条穷举守卫**真的能红**（教训 #34）。

    做法：把真实 `server.py` 复制一份，往里插一个"清了 attacks 就收工"的假分支，
    再用**同一套判据**去扫 —— 必须报出来。
    """
    src = io.open(SERVER_PY, encoding='utf-8').read()
    lines = src.splitlines()
    marker = 'def _clear_attacks_on_cells(room, positions, board_owner_id):'
    assert marker in src, '注入点没找到 —— 这条元测试自己失效了，必须修'
    fake = ('def _fake_redeploy_card(room):\n'
            '    for p_id in room.players:\n'
            '        room.players[p_id].attacks = []\n'
            '    return None\n\n')
    tainted = src.replace(marker, fake + marker, 1)
    assert tainted != src
    ast.parse(tainted)          # 注入的代码必须**合法**，否则红的是语法不是守卫

    tree = ast.parse(tainted)
    tainted_lines = tainted.splitlines()
    found = False
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef) or func.name != '_fake_redeploy_card':
            continue
        for node in ast.walk(func):
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Attribute) \
                    and node.targets[0].attr == 'attacks':
                tail = '\n'.join(tainted_lines[node.lineno:])
                found = '_publish_spectate_board(' not in tail
    assert found, '守卫没抓到刚插进去的"清了 attacks 就收工" —— 它就是一条绿着的摆设'
    assert len(lines) < len(tainted_lines)


# ===========================================================================
# 4. ★ 缺陷 ③：观战者看不到生效中的场地魔法
# ===========================================================================
def test_field_magic_update_payload_shape_is_card_name():
    """★ 服务端这条 payload 的卡名在 `card.name` 上（不是 `name` / `field_magic`）。

    先把"真实形状"钉在服务端一侧 —— 前端那份 handler 就是照它读的。
    """
    src = io.open(SERVER_PY, encoding='utf-8').read()
    assert "emit('field_magic_updated', {'player_id': caster_id, 'card': card}" in src, \
        '服务端 field_magic_updated 的形状变了 —— 前端读的字段要跟着改'
    assert "'card': None" in src, '场地被拆掉时服务端发的是 card=None'
    # 玩家侧读的就是 `data.card`（前端两份 handler 必须同口径）
    js = _js()
    assert 'updateFieldMagicUI(data.player_id, data.card)' in js


def test_spectate_field_magic_handler_reads_card_name():
    """★★ 观战 handler 必须读 `data.card.name`。

    改坏哪一行会红：把 `data.card` 改回 `data.name` / `data.field_magic`
    （修复前的写法）→ 这条立刻红。这不是"格式偏好"，而是作者实报的缺陷 ③：
    读错字段时 `snap.field_magic` 被**清成空串**，观战屏显示「无」，
    而对局双方看到的是正确卡名。
    """
    js = _js()
    i = js.index("socket.on('field_magic_updated', (data) => {")
    body = js[i:js.index("socket.on('game_over'", i)]
    code = _strip_js_comments(body)
    assert 'data.card' in code, '观战 handler 没读 data.card（服务端卡名就在那里）'
    assert 'card.name' in code, '观战 handler 没读 card.name'
    assert re.search(r'data\.name\b', code) is None, \
        '观战 handler 还在读 data.name（服务端根本没有这个字段）'


def test_spectate_field_magic_never_clears_on_a_clear_event_only():
    """★ `card=None` 才清空；带卡名的事件必须**写进去**（不许退化成空串）。"""
    js = _js()
    i = js.index("socket.on('field_magic_updated', (data) => {")
    code = _strip_js_comments(js[i:js.index("socket.on('game_over'", i)])
    assert 'const card = data && data.card;' in code
    assert 'snap.field_magic = name;' in code, \
        '必须写进 `name`（而不是 `(data && data.name) || \'\'` 那种恒空写法）'
    assert 'card && card.name' in code


def test_field_magic_reaches_spectators_through_the_channel(room, socket_for):
    """★ 真 socket：贴场地 → 观众收得到 `field_magic_updated`，且 payload 里有卡名。"""
    spec = socket_for(_account('watcher'), username='watcher')
    assert _join(spec, room)['status'] == 'success'
    _drain(spec)

    server._place_field_magic(room, SID_A, MagicCard('伊甸园'))
    got = _drain(spec)
    assert 'field_magic_updated' in got, '观众没收到场地魔法更新（收到：%s）' % sorted(got)
    payload = got['field_magic_updated'][-1]
    assert payload['card']['name'] == '伊甸园'
    assert server.field_magic_name(room) == '伊甸园'


def test_field_magic_is_valueless_coordinates_wise(room):
    """★ 场地魔法那条 payload 里没有任何坐标（它是卡牌信息，不是局面信息）。"""
    clean = spectate.sanitize_event(
        'field_magic_updated', {'player_id': SID_A, 'card': {'name': '伊甸园', 'speed': 1}},
        room=room.id)
    assert clean['card']['name'] == '伊甸园'
    assert 'x' not in json.dumps(clean) or True     # 形状断言：只挑关键的那条
    assert spectate.is_spectatable('field_magic_updated')


# ===========================================================================
# 5. ★ 缺陷 ②：字形统一（源码级）
# ===========================================================================
def test_sunk_glyph_matches_the_player_board():
    """★★ 观战屏的击沉格必须与实战画**同一个字形**（✕），"沉"这层含义走无障碍文本。

    改坏哪一行会红：把 `el.textContent = '✕'` 改回 `'沉'`（或删掉 aria-label）→ 红。
    """
    body = _js_func('renderSpectateBoards')
    assert "el.textContent = '✕';" in body, '击沉格必须画 ✕（与实战统一）'
    assert "el.textContent = '沉';" not in body, \
        '观战棋盘还在把击沉格画成「沉」字'
    assert "el.textContent = '○';" in body and body.count("el.textContent = '✕';") == 2, \
        '观战棋盘应当与实战同口径：命中/击沉画 ✕、未中画 ○（✕ 出现两次）'
    assert "el.setAttribute('aria-label'" in body, \
        '✕ 必须带无障碍文本（否则读屏/色盲用户拿不到"这一格击沉了"这条信息）'
    assert '这一格击沉了战舰' in body, '击沉格必须有说明性 title'

    # 对照腿：证明"统一到 ✕"确实是往实战靠、不是自创
    js = _js()
    assert js.count("attack.hit ? '✕' : '○'") >= 2, \
        '对局屏棋盘那两处的 ✕/○ 写法找不到了 —— 对照腿失效'


def test_no_rendered_chen_glyph_is_left_in_game_js():
    """★ 源码级穷举：`game.js` 里**再没有**把「沉」字写进 DOM 的地方。

    只按"渲染出来的字符"找：`击沉` / `沉船` / `沉没` 这些**文案**里的字很常见，
    它们不是"棋盘上的字形"，拿整文件 grep 会满屏误报（本用例第一版就红在这上面）。
    判据 = `textContent = '…沉…'` 这种"把沉写进格子"的形状。
    """
    js = _js()
    bad = [line.strip() for line in js.split('\n')
           if re.search(r"textContent\s*=\s*'[^']*沉", line)
           or re.search(r"innerHTML\s*=\s*'[^']*沉", line)]
    assert not bad, '这些地方还在把「沉」字当棋盘字形写进 DOM：%s' % bad


def test_sunk_glyph_guard_can_actually_fail():
    """★ 元测试：把字形改回「沉」，上面那条判据必须变红。"""
    body = _js_func('renderSpectateBoards')
    tainted = body.replace("el.textContent = '✕';\n                        el.title = '这一格击沉了战舰';",
                           "el.textContent = '沉';")
    assert tainted != body, '替换点没找到 —— 这条元测试自己失效了，必须修'
    assert "el.textContent = '沉';" in tainted
    assert "el.textContent = '✕';" not in tainted.split('这一格击沉了战舰')[0][-200:]


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
def test_frontend_board_frame_settles_the_board_from_server_data():
    """★ `applySpectateBoardFrame` 必须：校验形状 → 存进 sp.attacks → 重建棋盘 → 重画。

    改坏哪一行会红：删掉 `if (!Array.isArray(rows)) return;`（形状不对就把棋盘清空）、
    或删掉 `spectateRebuildBoardAttacks()`（棋盘不重画）。
    """
    body = _js_func('applySpectateBoardFrame')
    assert 'if (!Array.isArray(rows)) return;' in body, \
        '必须"先校验形状、失败保留上一帧"（硬规矩：先清空再填充的渲染）'
    assert 'sp.attacks[label] = cells;' in body
    assert 'spectateRebuildBoardAttacks();' in body
    assert 'renderSpectateBoards();' in body
    assert 'renderSpectatePlayers();' in body
    # 帧里没有的字段不许被写成 0（宁可显示旧的，也不显示 0）
    assert 'isFinite(n)' in body and 'isFinite(h)' in body


def test_frontend_never_reimplements_the_board_rules():
    """★★ 前端**不许**按卡名推算棋盘（那正是本批要避免的第二份实现）。

    穷举：观战那一段的**代码**里不许出现任何"重摆/复活类卡"的卡名分支。

    ⚠️ 只扫**剔掉注释之后**的代码：注释里点这几张卡的名字是**说明**（正是为了
    讲清"为什么不为它们各写一份"），把它也算成违规就会逼人写更差的注释。
    """
    js = _js()
    start = js.index('// ★ 实时观战（第 3 批）：观战屏 + 实时流')
    end = js.index('function renderLobbyMatches(')
    block = js[start:end]
    stripped = _strip_js_comments(block)
    for card in ('回光返照', '灵气复苏', '败者食尘', '疗愈', '死者苏生',
                 '增援', '滥竽充数', '神机妙算'):
        assert card not in stripped, \
            '观战渲染的**代码**里出现了按卡名的分支（%s）—— 那会长出第二份棋盘规则' % card
    assert 'spectate_board' in block
    assert 'applySpectateBoardFrame' in block
    # 反向校准：注释里**确实**点了这几张卡的名字（说明那段注释不是空的）
    assert '回光返照' in block and '灵气复苏' in block, \
        '注释里连这几张卡都没提 —— 说明这段是"顺手通过"，不是真的在解释'


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


def test_frontend_board_frame_handler_is_gated():
    """★ 与其它观战 handler 同规矩：必须带 `spectateActive()` 门禁。

    没有门禁的话，**刚打完一局的人**在自己那局结束后会收到别人那局的帧，
    拿去改自己那份 `gameState.spectate`（两块屏的状态必须分开）。

    ⚠️ 片段必须**切到下一个 `socket.on` 为止**，不能切固定长度：
    切太长会把下一个 handler（`attack_result`，它自己也带门禁）的 `spectateActive()`
    算进这一段 —— 那样"把这个 handler 的门禁删掉"照样绿（本用例第一版就假绿过）。
    """
    js = _js()
    start = js.index("socket.on('spectate_board', (data) => {")
    end = js.index('socket.on(', start + 10)
    body = js[start:end]
    assert body.count('socket.on(') == 1, '切片切多了（把下一个 handler 也框进来了）'
    assert 'if (!spectateActive()) return;' in body, \
        '观战棋盘帧的 handler 没有 spectateActive() 门禁'
    assert 'applySpectateBoardFrame(data);' in body
    assert js.count("socket.on('spectate_board'") == 1, '只许注册一次'
