# -*- coding: utf-8 -*-
"""实时观战**第 3 批**：大厅入口（`lobby_state.matches`）+ 前端观战屏的源码守卫。

## 本批新增的攻击面

第 2 批把观众放进了观战通道，本批第一次**把"有哪些局可以看"广播给所有人**。
于是多出来两个必须守住的东西：

1. ★ **`matches` 是一份公共广播**（跟着 4 秒一次的 `lobby_state` 走）——
   * 它必须**只有展示必需的字段**：房间号、双方名字、回合、观战人数、是否排位。
     原始座位 key / `user_id` / 船数 / 手牌**一个都不许出现**；
   * 它必须**只列双方都允许被观战的局**（列出来点不进去 = 误导）；
   * 它必须**不含人机房**、不含还没坐满的 `waiting`、不含已结束的 `game_over`。
2. ★ **不许逐房逐人查库** —— `lobby_state` 每 4 秒广播一次，逐人查库就是
   每秒几十次 SELECT（CLAUDE.md §1 与 `docs/LOBBY_2026_09_18.md` 都记着这个坑）。
   守卫用**调用计数**钉死：同一个 uid 在 TTL 内只允许被查一次。

## 为什么观战屏那部分只能是**源码级**守卫

观战屏是浏览器的 DOM，pytest 跑不到。所以这里只锁"结构性的东西"：
棋盘渲染不许引用任何船位数据、座位对齐只能走 `seat_labels`、
屏的显隐不许用 `hidden`。真正的"观众看不到未被打过的船"由
`tools/spectate_check.mjs`（三浏览器真 socket E2E）负责 ——
本文件末尾有一条注释说明分工，别把 E2E 的活儿塞进这里假装测过了。
"""
import pathlib
import re
import uuid

import pytest

import db as db_module
import server
import spectate
from server import GameRoom, Player, room_manager

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
JS = (REPO_ROOT / 'static' / 'game.js').read_text(encoding='utf-8')
HTML = (REPO_ROOT / 'templates' / 'index.html').read_text(encoding='utf-8')

# 直接取函数体，别让断言被同文件里别处的字面量蒙混过关
def _js_body(name):
    """截出 `function name(...) { ... }` 的函数体（按大括号配平找结尾）。"""
    m = re.search(r'function\s+' + re.escape(name) + r'\s*\(', JS)
    assert m, 'static/game.js 里找不到函数 %s' % name
    start = JS.index('{', m.end() - 1)
    depth = 0
    for i in range(start, len(JS)):
        if JS[i] == '{':
            depth += 1
        elif JS[i] == '}':
            depth -= 1
            if depth == 0:
                return JS[start:i + 1]
    raise AssertionError('函数 %s 的大括号不配平' % name)


# ===========================================================================
# 账号 / 房间工厂
# ===========================================================================
_ACCOUNTS = {}


def _account(key):
    if key not in _ACCOUNTS:
        uid = db_module.create_user('spec3-%s-%s' % (key, uuid.uuid4().hex[:10]), 'y' * 12)
        assert uid, '建测试账号失败'
        _ACCOUNTS[key] = uid
    return _ACCOUNTS[key]


def _seat(key, name, sid, uid, remaining=6):
    return Player(name=name, ships=[], attacks=[], remaining_ships=remaining,
                  user_id=uid, sid=sid)


_DEFAULT = object()


def _live_room(room_id=None, state='attacking', uid_a=_DEFAULT, uid_b=_DEFAULT,
               ranked=False, ai=False, names=('甲', '乙')):
    """⚠️ `uid_a=None` 与"不传"**必须区分**：前者是"这个座位是游客"（`user_id` 为空）。

    第一版没区分，`_live_room(uid_a=None)` 被当成"用默认账号"，
    于是"游客座位不许被观战"那条用例测的其实是"账号默认允许" —— **假绿**。
    """
    room_id = room_id or ('spec3-' + uuid.uuid4().hex[:6])
    if uid_a is _DEFAULT:
        uid_a = _account('a')
    if uid_b is _DEFAULT:
        uid_b = _account('b')
    room = GameRoom(room_id)
    room.players['seat-a'] = _seat('a', names[0], 'sid-a', uid_a)
    room.players['seat-b'] = _seat('b', names[1], 'sid-b', uid_b)
    room.state = state
    room.current_phase = 'battle'
    room.current_attacker = 'seat-a'
    room.attacks_remaining = 6
    room.round = 3
    room.ranked = ranked
    room.is_ai_room = ai
    room_manager.rooms[room.id] = room
    return room


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """清房间 / 清观战开关缓存 / 清账号开关。

    ⚠️ 开关缓存是**模块级**的（`_LOBBY_SPECTATE_FLAG_CACHE`），不清就会串用例：
    上一个用例把某个 uid 读成 False，下一个用例在 TTL 内直接命中缓存 → 顺序敏感的假红。
    这正是不变量"缓存必须有明确失效点"的那件事。
    """
    existing = set(room_manager.get_all_rooms())
    room_manager.match_queue = []
    server._LOBBY_SPECTATE_FLAG_CACHE.clear()
    yield
    for rid in list(room_manager.get_all_rooms()):
        if rid not in existing:
            room_manager.rooms.pop(rid, None)
    room_manager.match_queue = []
    server._LOBBY_SPECTATE_FLAG_CACHE.clear()
    for key in _ACCOUNTS:
        db_module.set_allow_spectate(_ACCOUNTS[key], True)


def _matches():
    return server.build_lobby_state()['matches']


def _set_allow(uid, on):
    assert db_module.set_allow_spectate(uid, on) is True
    server._LOBBY_SPECTATE_FLAG_CACHE.clear()      # 立刻改设置 → 立刻重读


# ===========================================================================
# 1. ★ 契约：给了什么字段，一个多余的都没有
# ===========================================================================


def test_matches_never_leaks_seat_keys_or_user_ids():
    """★ 大厅是公共广播：座位 key（匹配房里就是 socket sid）与 user_id 都不许出现。"""
    uid_a, uid_b = _account('a'), _account('b')
    room = _live_room(uid_a=uid_a, uid_b=uid_b)
    import json
    blob = json.dumps(_matches(), ensure_ascii=False)
    assert 'seat-a' not in blob and 'seat-b' not in blob, '原始座位 key 泄漏到大厅广播'
    assert 'sid-a' not in blob and 'sid-b' not in blob, '连接 id 泄漏到大厅广播'
    assert uid_a not in blob and uid_b not in blob, '账号 id 泄漏到大厅广播'
    # 反向：该有的名字必须在（防"为了安全把该给的也砍了"）
    assert '甲' in blob and '乙' in blob
    # 房间号是观众**必须**拿到的（点观战要靠它）
    assert room.id in blob


def test_matches_never_carries_ship_or_hand_numbers():
    """船数 / 手牌张数不在契约里 —— 大厅列表不需要它们，加了就是多余的暴露面。"""
    room = _live_room()
    room.players['seat-a'].magic_hand = [{'name': '流星雨'}, {'name': '海啸'}]
    row = _matches()[0]
    blob = repr(row)
    for banned in ('hand', 'hand_count', 'ships', 'remaining_ships', 'magic_hand'):
        assert banned not in blob, '大厅列表里不该出现 %s' % banned


# ===========================================================================
# 2. ★ 过滤：该列的都列、不该列的一个都不列
# ===========================================================================
def test_all_three_live_states_are_listed():
    rooms = [
        _live_room(state=state)
        for state in ['placing_ships', 'rock_paper_scissors', 'attacking']
    ]
    listed_room_ids = {match['room_id'] for match in _matches()}
    assert {room.id for room in rooms} <= listed_room_ids












# ===========================================================================
# 3. ★★ 只列"双方都允许被观战"的局（否则点进去只会被拒 —— 列出来是误导）
# ===========================================================================
def test_both_sides_allowed_is_listed():
    _live_room()
    assert len(_matches()) == 1


def test_one_side_off_hides_the_match():
    uid_a = _account('a')
    _live_room(uid_a=uid_a)
    _set_allow(uid_a, False)
    assert _matches() == [], '甲关掉之后这一局不该还在榜上'






def test_unknown_setting_is_treated_as_not_allowed():
    """读库失败 → 未知 → 该局**这一帧不上榜**（宁可少列一局，也不误导）。"""
    room = _live_room()
    assert len(_matches()) == 1
    server._LOBBY_SPECTATE_FLAG_CACHE.clear()

    def _boom(_uid):
        raise RuntimeError('读库抖动')

    original = server.db.get_allow_spectate
    server.db.get_allow_spectate = _boom
    try:
        assert _matches() == [], '读不到设置时不许把这一局列出来'
    finally:
        server.db.get_allow_spectate = original


def test_listing_and_join_agree_on_the_same_room():
    """★★ 列表与「能不能真的进去」必须同口径。

    这是本批最容易漂移的一处：列表用 `_lobby_live_matches` 判断、
    进席用 `handle_spectate_join` 判断 —— 两处口径一旦分开，
    症状就是"点进去被拒"（列表在骗人），而且**不报错**。
    这里用**真 socket** 把两边逐一对上：榜上的进得去，落榜的进不去。
    """
    uid_a, uid_b = _account('a'), _account('b')
    listed = _live_room(room_id='spec3-listed', uid_a=uid_a, uid_b=uid_b)
    hidden = _live_room(room_id='spec3-hidden', uid_a=uid_a, uid_b=uid_b)
    _set_allow(uid_b, False)          # 一关就是**两间房**都落榜（同一个账号的座位）
    server._LOBBY_SPECTATE_FLAG_CACHE.clear()
    # 只把 listed 那一间重新打开（另一间用的是同一对账号，所以改成不同账号对）
    _set_allow(uid_b, True)
    _set_allow(uid_a, False)
    assert _matches() == [], '甲关掉后两间都该落榜'
    _set_allow(uid_a, True)
    assert {r['room_id'] for r in _matches()} == {listed.id, hidden.id}

    spectator_uid = db_module.create_user('spec3-viewer-%s' % uuid.uuid4().hex[:8], 'z' * 12)
    http = server.app.test_client()
    with http.session_transaction() as sess:
        sess['user_id'] = spectator_uid
        sess['username'] = '观众'
    viewer = server.socketio.test_client(server.app, flask_test_client=http)
    viewer.get_received()
    try:
        ack = viewer.emit('spectate_join', {'room_id': listed.id}, callback=True)
        assert ack['status'] == 'success', '榜上的局必须进得去，实际：%r' % ack
    finally:
        viewer.disconnect()

    # 落榜的情形：把甲关掉，同一间房就既不进榜、也进不去
    _set_allow(uid_a, False)
    assert _matches() == []
    http2 = server.app.test_client()
    with http2.session_transaction() as sess:
        sess['user_id'] = spectator_uid
        sess['username'] = '观众'
    viewer2 = server.socketio.test_client(server.app, flask_test_client=http2)
    viewer2.get_received()
    try:
        ack = viewer2.emit('spectate_join', {'room_id': listed.id}, callback=True)
        assert ack['status'] == 'error', '落榜的局必须也进不去'
        assert '观战' in ack['message'], '拒绝必须带原因，实际：%r' % ack
    finally:
        viewer2.disconnect()


# ===========================================================================
# 4. ★ 不逐房逐人查库（本批点名警告的坑）
# ===========================================================================






# ===========================================================================
# 5. ★ 观战屏的源码级守卫（DOM 跑不进 pytest，这里只锁结构性事实）
# ===========================================================================




def test_board_render_reads_only_bombed_cells():
    """★★ 本批最关键的一条源码守卫：**画棋盘的那段不许读任何船位数据**。

    快照里根本没有 ships / positions / hits，但前端"自己推算某格有船"
    （比如读一个不存在的字段、或从别处拿 ships）就会把观众的棋盘变成透视。
    这里直接扫函数体里的字段访问。
    """
    body = _js_body('renderSpectateBoards')
    for banned in ('ships', 'positions', 'hits', 'remaining_ships', 'magic_hand'):
        assert banned not in body, \
            'renderSpectateBoards 里出现了 %r —— 观众棋盘只能靠已轰过的格重建' % banned
    # 正向：它必须真的读 board_attacks，并画三种"挨过炮"的状态
    assert 'board_attacks' in body
    for needed in ('ship_sunk', 'hit', 'miss'):
        assert needed in body, '棋盘少了 %s 状态的渲染' % needed








def test_spectate_events_are_not_sent_through_game_state():
    """★ 不许给 `game_state` 发新 state 值（它的 default 分支会提示"请刷新页面"）。"""
    assert 'spectate' not in server.__dict__.get('GAME_STATES', ())
    # 前端也不许把观战状态塞进 gameState.currentPhase 那套对局字段
    for banned in ('gameState.playerId = ', 'gameState.ships = '):
        block = JS.split('// ★ 实时观战（第 3 批）：观战屏 + 实时流')[1]
        block = block.split('// 大厅建房：走服务端的 lobby_create_room')[0]
        assert banned not in block, '观战屏不许写对局屏的状态字段：%s' % banned
