# -*- coding: utf-8 -*-
"""实时观战**第 2 批**：快照 / 观战席 / 观众进出 / 观战开关（端到端）。

## 这一批把"观众真的能进来"接上了，所以每条用例都在守一条不变量

1. ★ **观众永远拿不到船的位置** ——
   * `test_spectate_snapshot_has_no_unhit_ship_cells`：造一个**船位已知**的房间
     （两格船只挨过一格炮），断言快照里**一个未被轰过的船坐标都不出现**；
   * `test_spectate_snapshot_gives_the_bombed_cells`（**反向**）：断言"已轰过的格子"
     必须**在**，防"为了安全把该给的也砍了"（那会让观众从"看得到"退化成"看不到"）；
   * `test_game_log_detail_positions_are_stripped`：`game_log` 的 detail 里藏着
     **整艘船的坐标**（`_sacrifice_ship` 那条日志）—— 实测发现的真泄漏，已修。
2. ★ **双方所有动作都看得到** —— `test_spectator_receives_actions`（真 socket 收件）。
3. ★ **实时**：`test_join_sends_a_snapshot_to_this_spectator_only`（进席即快照）。
4. 观战席与人数：上限 20 / 只给人看人数 / 断线即离席。

## 为什么全部用**真 socket**（`socketio.test_client`）而不是直调 handler

`server._identity_ok` 在**无请求上下文**时会退化成"只要在 `room.players` 里就放行"
（那是给单测留的口子）。所以"观众被拒绝"这种断言如果直调 handler，可能**因为根本
没走身份校验而假绿**（CLAUDE.md 本次任务专门警告过的陷阱）。
于是：所有**进出观战**的用例都走真连接（session 与 `request.sid` 都是真的），
只有"写操作 handler 一律拒绝观众"那几条才直调 —— 而且配了
`test_membership_guard_can_actually_fail` 做"故意改坏 → 变红"的反向校准。
"""
import ast
import io
import json
import pathlib
import time
import uuid

import pytest

import db as db_module
import server
import spectate
from server import GameRoom, Player, PlayerShip, Position, room_manager

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER_PY = REPO_ROOT / 'server.py'


# ===========================================================================
# 测试账号 / 房间工厂
# ===========================================================================
_ACCOUNTS = {}


def _account(key):
    """按 key 缓存一个**真账号**（`_spectate_seat_allow` 要求座位背后有真账号）。

    游客（无账号）在本批是**不许被观战**的（`can_spectate(None, ...) is False`），
    所以这些守卫用例必须坐在真账号上，否则测的是"游客不许"而不是设置开关。
    """
    if key not in _ACCOUNTS:
        uid = db_module.create_user('spec-%s-%s' % (key, uuid.uuid4().hex[:10]), 'x' * 12)
        assert uid, '建测试账号失败'
        _ACCOUNTS[key] = uid
    return _ACCOUNTS[key]


# 座位 key 用**匹配房的约定**（key = socket sid）—— 那正是"sid 会被当成 player_id
# 发给观众"的那套约定，最容易出问题；自定义房（key = user_id）另有一条用例覆盖。
SID_A, SID_B = 'sid-a-conn', 'sid-b-conn'

# 两格船都只挨过一格炮：(1,0) / (1,5) 就是"没挨过炮的船格"。
P1_SHIPS = (((0, 0), (1, 0)), ((2, 0),), ((3, 0),), ((4, 0),), ((5, 0),), ((0, 1),))
P2_SHIPS = (((0, 5), (1, 5)), ((2, 5),), ((3, 5),), ((4, 5),), ((5, 5),), ((0, 4),))

# (x, y, hit, ship_sunk)：p1 打出去的三格（落在 p2 棋盘上）
P1_ATTACKS = ((0, 5, True, False), (2, 5, True, True), (3, 3, False, False))
# p2 打出去的三格（落在 p1 棋盘上）
P2_ATTACKS = ((0, 0, True, False), (3, 0, True, True), (4, 2, False, False))

BOMBED_CELLS = frozenset((x, y) for (x, y, _h, _s) in (P1_ATTACKS + P2_ATTACKS))
ALL_SHIP_CELLS = frozenset(P1_SHIPS + P2_SHIPS)          # 注意：这是"格"的集合
ALL_SHIP_CELLS = frozenset(cell for ship in (P1_SHIPS + P2_SHIPS) for cell in ship)
UNHIT_SHIP_CELLS = ALL_SHIP_CELLS - BOMBED_CELLS
assert (1, 0) in UNHIT_SHIP_CELLS and (1, 5) in UNHIT_SHIP_CELLS, '样例失效：两格船的未挨炮格必须在'
# 故意把**没挨过炮的整艘船**坐标塞进日志 detail（server.py 约 10490 那条的真实形状）
LEAKY_LOG_CELLS = ((4, 5), (5, 5))
assert set(LEAKY_LOG_CELLS) <= UNHIT_SHIP_CELLS


def _ships(shape):
    return [PlayerShip(positions=[Position(x, y) for (x, y) in cells], hits=[])
            for cells in shape]


def _attacks(rows):
    return [Position(x, y, hit=hit, ship_sunk=sunk) for (x, y, hit, sunk) in rows]


def _make_room(room_id=None):
    room_id = room_id or ('spec2-' + uuid.uuid4().hex[:6])
    room = GameRoom(room_id)
    room.players[SID_A] = Player(name='甲', ships=_ships(P1_SHIPS), attacks=_attacks(P1_ATTACKS),
                                 remaining_ships=6, sid=SID_A, user_id=_account('alpha'))
    room.players[SID_B] = Player(name='乙', ships=_ships(P2_SHIPS), attacks=_attacks(P2_ATTACKS),
                                 remaining_ships=5, sid=SID_B, user_id=_account('beta'))
    room.state = 'attacking'
    room.current_phase = 'battle'
    room.current_attacker = SID_A
    room.attack_order = [SID_A, SID_B]
    room.attacks_remaining = 5
    room.round = 4
    room.ranked = False
    # 手牌：**张数**是公开的，牌面不是 —— 名字取得和连锁里的卡名不同，
    # 这样"手牌内容有没有被下发"能被 json 文本断言抓住。
    room.players[SID_A].magic_hand = [{'name': '流星雨', 'speed': 2},
                                      {'name': '流星雨', 'speed': 2}]
    room.players[SID_B].magic_hand = [{'name': '海啸', 'speed': 3},
                                      {'name': '海啸', 'speed': 3},
                                      {'name': '海啸', 'speed': 3}]
    # 连锁：caster 用的是**匹配房那套 sid**（就是要被换成 p1/p2 的那个值）。
    # ⚠️ 默认**留空**：`handle_attack` 见到非空连锁会拒（"连锁结算中"），
    #    那样"真玩家能打一炮"的对照腿就失效了。要用连锁的用例自己塞。
    room.chain = []
    room.game_logs = [
        # 已公开的被轰格（观众该看到它）
        {'ts': 1, 'type': 'attack', 'text': '第4回合 · 甲 攻击 (0,5) — 命中',
         'detail': {'attacker': SID_A, 'target': {'x': 0, 'y': 5}, 'hit': True,
                    'ship_sunk': False}},
        # ★ 真泄漏那条：被牺牲那艘船的**全部坐标**（两格都没挨过炮）
        {'ts': 2, 'type': 'magic', 'text': '第4回合 · 乙 因恶魔契约牺牲一艘战舰',
         'detail': {'player': SID_B, 'reason': 'demon_contract',
                    'positions': [{'x': x, 'y': y} for (x, y) in LEAKY_LOG_CELLS]}},
    ]
    room_manager.rooms[room.id] = room
    return room


@pytest.fixture
def room():
    r = _make_room()
    yield r
    room_manager.rooms.pop(r.id, None)
    room_manager.match_queue = []


@pytest.fixture(autouse=True)
def _restore_spectate_switches():
    """用例之间把两个座位的观战开关复位成"允许"。

    ⚠️ 账号是模块级缓存的（`_ACCOUNTS`），一个用例把甲关掉不复位，
       后面的用例就会按测试顺序**随机**变红/变绿 —— 这种"顺序敏感"的测试
       比没有测试更坏。
    """
    yield
    for key in ('alpha', 'beta'):
        uid = _ACCOUNTS.get(key)
        if uid:
            db_module.set_allow_spectate(uid, True)


# ===========================================================================
# 真 socket 工具
# ===========================================================================
def _sid_of(client):
    return server.socketio.server.manager.sid_from_eio_sid(client.eio_sid, '/')


def _rooms_of(client):
    return set(server.socketio.server.rooms(_sid_of(client)))


def _http(uid=None, username=None):
    http = server.app.test_client()
    if uid:
        with http.session_transaction() as sess:
            sess['user_id'] = uid
            sess['username'] = username or uid
    return http


@pytest.fixture
def socket_for(room):
    """建一个**真登录**的 socket 连接。`enter=<room_id>` 时同时进对局房间。"""
    made = []

    def _make(uid, enter=None):
        client = server.socketio.test_client(server.app, flask_test_client=_http(uid))
        if enter:
            server.socketio.server.enter_room(_sid_of(client), enter)
        client.get_received()               # 丢掉 connect 期间的噪音
        made.append(client)
        return client

    yield _make
    for client in made:
        try:
            client.disconnect()
        except Exception:                   # noqa: BLE001 - 清理失败不该让用例变红
            pass


def _join(client, room):
    return client.emit('spectate_join', {'room_id': room.id}, callback=True)


def _leave(client, room):
    return client.emit('spectate_leave', {'room_id': room.id}, callback=True)


def _drain(client):
    """收件队列按事件名归组（**一次取完**，避免多次 get_received 互相掏空）。"""
    out = {}
    for msg in client.get_received():
        out.setdefault(msg['name'], []).append(msg['args'][0] if msg['args'] else None)
    return out


def _fingerprint(room):
    """对局状态指纹：观众的任何尝试都不许改动它。"""
    return {
        'state': room.state,
        'phase': room.current_phase,
        'attacker': room.current_attacker,
        'attacks_remaining': room.attacks_remaining,
        'round': room.round,
        'winner': room.winner,
        'players': sorted(room.players),
        'attacks_a': len(room.players[SID_A].attacks),
        'attacks_b': len(room.players[SID_B].attacks),
        'hand_a': len(room.players[SID_A].magic_hand),
        'hand_b': len(room.players[SID_B].magic_hand),
        'chain': len(room.chain),
    }


# ===========================================================================
# 快照的坐标扫描（与第 1 批守卫同一套形状识别）
# ===========================================================================
def _collect_coords(node, out=None):
    """递归收集所有"坐标形状"：`{x,y}` / `{x1,y1,x2,y2}` / `{'cell': [x,y]}`。"""
    if out is None:
        out = []
    if isinstance(node, dict):
        if isinstance(node.get('x'), int) and isinstance(node.get('y'), int):
            out.append((node['x'], node['y']))
        if all(isinstance(node.get(k), int) for k in ('x1', 'y1', 'x2', 'y2')):
            out.append((node['x1'], node['y1']))
            out.append((node['x2'], node['y2']))
        cell = node.get('cell')
        if isinstance(cell, (list, tuple)) and len(cell) == 2 \
                and all(isinstance(v, int) for v in cell):
            out.append(tuple(cell))
        for value in node.values():
            _collect_coords(value, out)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _collect_coords(value, out)
    return out


def _collect_keys(node, out=None):
    if out is None:
        out = set()
    if isinstance(node, dict):
        out.update(node.keys())
        for value in node.values():
            _collect_keys(value, out)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _collect_keys(value, out)
    return out


def _assert_snapshot_is_leak_free(snapshot):
    """★ 快照的两条硬规矩（守卫本体，被下面的用例与元测试共用）。

    ① 任何层级都不许出现 `spectate.SNAPSHOT_FORBIDDEN_KEYS` 里的键；
    ② 不许出现**未被轰过的**船坐标（在这个房间里"轰过的格"是唯一合法坐标来源）。
    """
    bad_keys = set(spectate.SNAPSHOT_FORBIDDEN_KEYS) & _collect_keys(snapshot)
    assert not bad_keys, '快照里出现了禁字段：%s' % sorted(bad_keys)
    leaked = set(_collect_coords(snapshot)) & UNHIT_SHIP_CELLS
    assert not leaked, '快照里出现了**没挨过炮**的船坐标：%s' % sorted(leaked)


# ===========================================================================
# 1. 快照：无泄漏（正向）+ 该给的都给了（反向）
# ===========================================================================
def test_spectate_snapshot_has_no_unhit_ship_cells(room):
    """★ 不变量 #1：快照里一个"没挨过炮的船格"都不许出现。"""
    snapshot = server._build_spectate_snapshot(room)
    _assert_snapshot_is_leak_free(snapshot)

    # 更要紧的一格：两格船只挨了一格，另一格**必须**看不见
    assert (1, 0) not in set(_collect_coords(snapshot))
    assert (1, 5) not in set(_collect_coords(snapshot))
    # 日志 detail 里那两格（4,5)/(5,5) 是整艘没挨过炮的船 —— 同样不许出现
    coords = set(_collect_coords(snapshot))
    assert not ({tuple(c) for c in LEAKY_LOG_CELLS} & coords), \
        '日志 detail 里的整艘船坐标漏出去了'






def test_snapshot_chain_is_sanitized_with_seat_labels(room):
    """★ 连锁：座位标签 `p1`/`p2`，**原始 sid 一个字节都不留**；`targets` 剥掉。

    ⚠️ 2026-09-27 区域预览批起，链项**不再**带 `card` 的完整对象
    （白名单只允许卡名，见 `spectate.PREVIEW_KEYS`）：`item['card']` 是
    **卡名字符串**。区域预览是 `item['preview']`。
    """
    room.chain = [server.ChainItem(SID_A, {'name': '卧薪尝胆', 'speed': 1},
                                   [{'x': 0, 'y': 0}], 1.0)]
    snapshot = server._build_spectate_snapshot(room)
    chain = snapshot['chain']
    assert chain['chain_len'] == 1
    item = chain['chain'][0]
    assert item['seat'] == 'p1'
    assert item['card'] == '卧薪尝胆'
    assert 'targets' not in item and 'player_id' not in item
    text = json.dumps(chain, ensure_ascii=False)
    assert SID_A not in text and SID_B not in text, '连锁里还留着原始 sid'
    assert _account('alpha') not in text and _account('beta') not in text

    # 实时流那条广播走的**同一份**净化逻辑（同一实现，不是另写一份）
    live = spectate.sanitize_event(
        'magic_chain_updated',
        {'chain': [{'player_id': SID_A, 'card': {'name': '卧薪尝胆'},
                    'targets': [{'x': 0, 'y': 0}], 'negated': False}]},
        room=room)
    assert live['chain'][0]['seat'] == 'p1'
    assert SID_A not in json.dumps(live, ensure_ascii=False)




def test_game_log_detail_positions_are_stripped(room):
    """★ 实测发现的真泄漏：`game_log` 的 detail 里带着**整艘船**的坐标。

    `server._sacrifice_ship` 那条日志把被牺牲战舰的全部格子塞进 detail
    （约 `server.py:10490`）。被牺牲的船往往**一格都没挨过炮**（恶魔契约 /
    神之宣告 / 命运骰子）—— 第 1 批把 `game_log` 登记成"原样转发"时没抓到它，
    因为守卫用例给的样例 detail 里只有已公开的被轰格。
    """
    snapshot = server._build_spectate_snapshot(room)
    logs = snapshot['game_logs']
    assert len(logs) == 2
    for entry in logs:
        assert entry['text'], '日志文字被砍掉了 —— 观众会看到一片空白'
        assert 'positions' not in (entry.get('detail') or {})
    # 未净化的原始日志**确实**带着没挨过炮的船坐标（反向校准，防这条用例空转）
    raw = json.dumps(room.game_logs, ensure_ascii=False)
    assert all(json.dumps({'x': x, 'y': y})[1:-1] in raw for (x, y) in LEAKY_LOG_CELLS)
    # 净化后：文字、归属、已公开的被轰格都还在
    assert logs[0]['detail']['target'] == {'x': 0, 'y': 5}
    assert logs[0]['detail']['attacker'] == SID_A
    assert logs[1]['detail']['player'] == SID_B and logs[1]['detail']['reason'] == 'demon_contract'






# ===========================================================================
# 2. 通道隔离（★ 本批最要紧的一条）
# ===========================================================================
def test_spectator_cannot_receive_position_broadcasts(room, socket_for):
    """★ 观众：收得到**动作**，收不到任何**带位置的广播**。"""
    player = socket_for(_account('alpha'), enter=room.id)
    watcher = socket_for(_account('watcher'))
    assert _join(watcher, room)['status'] == 'success'
    watcher.get_received()                     # 丢掉快照

    server.emit('attack_result', {'attacker': SID_A, 'x': 0, 'y': 5, 'hit': True,
                                  'ship_sunk': False, 'remaining_attacks': 4},
                room=room.id)
    private = {
        'ships_updated': {'ships': [{'positions': [{'x': 0, 'y': 0}], 'hits': []}]},
        'player_ships_updated': {'ships': [{'positions': [{'x': 1, 'y': 0}]}]},
        'hand_updated': {'hand': [{'name': '流星雨'}]},
        'game_state': {'ships': [{'positions': [{'x': 2, 'y': 0}]}]},
        'board_attacks_updated': {'attacks': [{'x': 3, 'y': 0}]},
        'revealed_positions': {'positions': [{'x': 4, 'y': 0}]},
        'room_sync': {'ships': [{'positions': [{'x': 5, 'y': 0}]}]},
    }
    for event, payload in private.items():
        server.emit(event, payload, room=room.id)

    got = _drain(watcher)
    assert len(got.get('attack_result') or []) == 1, '动作事件没到观众手里'
    assert got['attack_result'][0]['x'] == 0 and got['attack_result'][0]['hit'] is True
    for event in private:
        assert not got.get(event), '%s 被推给了观众（那里带位置/手牌）' % event

    # ★ 可信度证据：玩家**确实**收到了那些私有广播 ——
    #   否则上面那串"观众没收到"可能只是"根本没发出去"（空转绿）。
    player_got = _drain(player)
    assert player_got.get('attack_result'), '玩家都没收到 attack_result，这条用例是空转的'
    assert player_got.get('ships_updated'), 'ships_updated 没发给玩家 —— 上面等于什么都没验'
    assert player_got.get('hand_updated')


def test_spectator_is_only_in_the_spectate_channel(room, socket_for):
    """★ 观众只进 `spectate:<id>`，**绝不在对局 room 里**。"""
    watcher = socket_for(_account('watcher'))
    assert _join(watcher, room)['status'] == 'success'
    rooms = _rooms_of(watcher)
    assert spectate.spectate_room_id(room.id) in rooms
    assert room.id not in rooms, '观众进了对局房间 = 93 处广播全灌给他'


def test_spectator_is_never_written_into_room_players(room, socket_for):
    """★ 观众**绝不写进 `room.players`**（那是全部写操作鉴权的基础）。"""
    before = set(room.players)
    watcher = socket_for(_account('watcher'))
    assert _join(watcher, room)['status'] == 'success'
    assert set(room.players) == before == {SID_A, SID_B}
    assert _sid_of(watcher) in room.spectators
    assert _sid_of(watcher) not in room.players




# ===========================================================================
# 3. 观众进不来 / 进得来（每一条拒绝都看得到原因）
# ===========================================================================
def test_join_requires_login(room, socket_for):
    """**只限登录用户**（作者裁定）。"""
    anon = server.socketio.test_client(server.app)      # 没有 session
    try:
        anon.get_received()
        ack = _join(anon, room)
        assert ack['status'] == 'error' and '登录' in ack['message']
        assert room.spectators == {}
    finally:
        anon.disconnect()




def test_player_cannot_spectate_his_own_game(room, socket_for):
    """对局中的玩家不许观战自己那局（三种命中方式：座位 key / 座位连接 / 同账号）。"""
    player = socket_for(_account('alpha'))
    sid = _sid_of(player)
    room.players[sid] = Player(name='甲', ships=_ships(P1_SHIPS), attacks=[],
                               remaining_ships=6, sid=sid, user_id=_account('alpha'))
    try:
        ack = _join(player, room)
        assert ack['status'] == 'error' and '玩家' in ack['message']
        assert sid not in room.spectators
    finally:
        room.players.pop(sid, None)

    # 座位登记的连接是这条连接（key 与 sid 不同）也要拦
    room.players[SID_A].sid = sid
    try:
        ack = _join(player, room)
        assert ack['status'] == 'error' and '玩家' in ack['message']
    finally:
        room.players[SID_A].sid = SID_A

    # 同一账号开第二个标签页：座位上的账号就是我
    other_tab = socket_for(_account('alpha'))
    ack = _join(other_tab, room)
    assert ack['status'] == 'error' and '玩家' in ack['message']
    assert room.spectators == {}






# ===========================================================================
# 4. ★ 观战开关（端到端：HTTP 写 → 真的进不来）
# ===========================================================================
def test_spectate_switch_blocks_entry_end_to_end(room, socket_for):
    """★ 任一玩家关掉 → 进不来；双方都开 → 进得来。**两侧都断言**。"""
    a, b = _account('alpha'), _account('beta')
    watcher = socket_for(_account('watcher'))

    assert db_module.get_allow_spectate(a) is True, '默认必须是"允许"（作者裁定 default on）'
    assert db_module.get_allow_spectate(b) is True
    assert _join(watcher, room)['status'] == 'success', '双方都开着就该进得来'
    _leave(watcher, room)

    # 甲关掉 → 进不来
    assert db_module.set_allow_spectate(a, False)
    ack = _join(watcher, room)
    assert ack['status'] == 'error' and '没有开放观战' in ack['message']
    assert _sid_of(watcher) not in room.spectators
    assert spectate.spectate_room_id(room.id) not in _rooms_of(watcher)

    # 甲开回来、乙关掉 → 还是进不来（**另一侧**单独也拦得住）
    db_module.set_allow_spectate(a, True)
    db_module.set_allow_spectate(b, False)
    ack = _join(watcher, room)
    assert ack['status'] == 'error' and '没有开放观战' in ack['message']

    # 双方都开 → 进得来
    db_module.set_allow_spectate(b, True)
    assert _join(watcher, room)['status'] == 'success'




def test_guest_seats_are_not_spectatable(room, socket_for):
    """游客座位没有设置 → **未知 → 不允许**（第 1 批定的口径，教训 #21）。"""
    room.players[SID_A].user_id = None
    watcher = socket_for(_account('watcher'))
    ack = _join(watcher, room)
    assert ack['status'] == 'error' and '没有开放观战' in ack['message']








def _mk_user_account(prefix):
    for _ in range(20):
        uid = db_module.create_user('spec-%s-%s' % (prefix, uuid.uuid4().hex[:10]), 'x' * 12)
        if uid:
            return uid
    raise AssertionError('建账号失败')


# ===========================================================================
# 5. 观战人数（对局双方只看得到人数）
# ===========================================================================




# ===========================================================================
# 6. 观众做不了任何对局操作
# ===========================================================================
def test_spectator_cannot_take_any_game_action(room, socket_for):
    """观众拿自己的 sid 去调写 handler —— 一律被拒，且对局状态一字不变。"""
    player = socket_for(_account('alpha'), enter=room.id)
    watcher = socket_for(_account('watcher'))
    assert _join(watcher, room)['status'] == 'success'
    watcher_sid = _sid_of(watcher)
    # 让甲的座位"登记的连接"是这条真连接 —— 否则连真玩家自己都过不了
    # `_identity_check` 的第 ② 条（座位 sid == 当前连接），对照腿就没有意义了。
    room.players[SID_A].sid = _sid_of(player)
    before = _fingerprint(room)

    # 真玩家先打一炮：证明这份 payload 形状本身是有效的（否则"被拒"可能只是参数不对）
    ok = player.emit('attack', {'room_id': room.id, 'player_id': SID_A, 'x': 5, 'y': 4},
                     callback=True)
    assert ok['status'] == 'success', '真玩家都打不动 —— 这条用例的对照腿失效了'
    landed = _fingerprint(room)
    assert landed['attacks_a'] == before['attacks_a'] + 1, '那一炮没落账，说明状态没动过'
    assert landed['attacks_remaining'] == before['attacks_remaining'] - 1

    attempts = [
        ('attack', {'room_id': room.id, 'player_id': watcher_sid, 'x': 4, 'y': 4}),
        ('end_turn', {'room_id': room.id, 'player_id': watcher_sid}),
        ('place_ships', {'room_id': room.id, 'player_id': watcher_sid, 'ships': []}),
        ('use_magic_card', {'room_id': room.id, 'player_id': watcher_sid,
                            'card': {'name': '流星雨', 'speed': 2, 'type': '普通',
                                     'description': ''}}),
        ('surrender', {'room_id': room.id, 'player_id': watcher_sid}),
    ]
    for event, payload in attempts:
        ack = watcher.emit(event, payload, callback=True)
        assert isinstance(ack, dict) and ack.get('status') == 'error', \
            '观众居然能用 %s：%r' % (event, ack)

    # 观众的每一次尝试之后，局面必须与"真玩家打完那一炮"时**一字不差**
    assert _fingerprint(room) == landed, '观众改动了局面'




# ===========================================================================
# 7. 快照只发给本人（不变量 #3：中途加入立刻拿到当前局面）
# ===========================================================================






# ===========================================================================
# 8. 离开 / 断线 / 房间回收
# ===========================================================================






def test_reaper_reclaims_a_finished_room_and_ends_spectating(room, socket_for):
    """真正的回收路径（reaper）也要把观众收尾，不能只在 `_drop_room` 里做。"""
    watcher = socket_for(_account('watcher'))
    assert _join(watcher, room)['status'] == 'success'
    watcher.get_received()

    room.state = 'game_over'
    server._reap_ended_rooms(now=time.time() + 1)            # 首次观察，只打标记
    assert room_manager.get_room(room.id) is not None
    server._reap_ended_rooms(now=time.time() + 1000)         # 超宽限 → 回收
    assert room_manager.get_room(room.id) is None
    ended = _drain(watcher).get('spectate_ended')
    assert ended, '房间被回收了，观众却一直等在死通道上'


# ===========================================================================
# 9. 源码级守卫（这些坏法 pytest 抓不到，只能扫源码）
# ===========================================================================
def _spectator_players_writes(src):
    """扫出"把观战席写进 `room.players`"的语句（返回 [(lineno, 源码片段)]）。

    这是**启发式**守卫：它抓的是"赋值目标上有 `.players[...]`，而右值里提到
    spectators"这类写法（也就是真正会出事的形状）。行为上的保证仍然靠
    `test_spectator_is_never_written_into_room_players` 那条端到端断言。
    """
    offenders = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = ast.unparse(node.value) if getattr(node, 'value', None) is not None else ''
            if 'spectator' not in value:
                continue
            for target in targets:
                target_src = ast.unparse(target)
                if '.players[' in target_src or target_src.endswith('.players'):
                    offenders.append((node.lineno, ast.unparse(node)[:120]))
        if isinstance(node, ast.Call):
            fn = ast.unparse(node.func)
            if ('spectator' in ast.unparse(node)
                    and (fn.endswith('.players.update') or fn.endswith('.players.setdefault'))):
                offenders.append((node.lineno, ast.unparse(node)[:120]))
    return offenders
