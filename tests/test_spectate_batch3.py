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
def test_matches_row_contract():
    """★ 每条的字段**恰好**是这七个 —— 多一个都要在这里表态。"""
    room = _live_room()
    rows = _matches()
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {'room_id', 'names', 'round', 'spectators',
                        'spectator_limit', 'ranked'}
    assert row['room_id'] == room.id
    assert row['names'] == ['甲', '乙']
    assert row['round'] == 3
    assert row['spectators'] == 0
    assert row['spectator_limit'] == spectate.SPECTATOR_LIMIT
    assert row['ranked'] is False


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
@pytest.mark.parametrize('state', ['placing_ships', 'rock_paper_scissors', 'attacking'])
def test_all_three_live_states_are_listed(state):
    _live_room(state=state)
    assert len(_matches()) == 1


@pytest.mark.parametrize('state', ['waiting', 'game_over'])
def test_waiting_and_finished_are_not_listed(state):
    _live_room(state=state)
    assert _matches() == [], '%s 不该出现在「进行中的对局」里' % state


def test_ai_room_is_not_listed():
    """产品规则：**不含人机房**（列表里就没有人机房，观战接口也拒）。"""
    _live_room(ai=True)
    assert _matches() == []


def test_only_rooms_with_two_seats_are_listed():
    """没坐满 = 不是"进行中的对局"（异常房同样按未坐满处理）。"""
    room = _live_room()
    room.players.pop('seat-b')
    assert _matches() == []


def test_ranked_flag_comes_from_the_room():
    _live_room(ranked=True)
    assert _matches()[0]['ranked'] is True


def test_matches_are_sorted_by_spectator_count_then_room_id():
    """列表顺序必须**确定**（否则每 4 秒重画一次会看到条目跳来跳去）。"""
    r1 = _live_room(room_id='spec3-aaa')
    r2 = _live_room(room_id='spec3-bbb')
    r2.spectators['s1'] = {'name': '观众', 'user_id': 'u', 'joined_at': 1}
    rows = _matches()
    assert [r['room_id'] for r in rows] == [r2.id, r1.id], '观战人数多的应当排前面'
    r2.spectators.clear()
    rows = _matches()
    assert [r['room_id'] for r in rows] == [r1.id, r2.id], '人数相同时按房间号稳定排序'


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


def test_turning_it_back_on_restores_the_match():
    """★ 反向：关掉再打开必须能回来（防"一旦关过就再也不出现"）。"""
    uid_a = _account('a')
    _live_room(uid_a=uid_a)
    _set_allow(uid_a, False)
    assert _matches() == []
    _set_allow(uid_a, True)
    assert len(_matches()) == 1


def test_guest_seat_makes_the_match_unlistable():
    """游客座位没有账号 → 设置未知 → **不许**（教训 #21：未知一律朝安全那侧兜）。"""
    _live_room(uid_a=None)
    assert _matches() == []


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
def test_setting_is_read_at_most_once_per_uid_within_ttl(monkeypatch):
    """★ 同一次广播里 4 个座位、2 个账号 → `get_allow_spectate` 只许被调 2 次。

    没有缓存的话，每 4 秒一次广播 × 每次每个座位一次 SELECT ——
    正是"每秒几十次查询"那个坑。
    """
    uid_a, uid_b = _account('a'), _account('b')
    _live_room(uid_a=uid_a, uid_b=uid_b)
    _live_room(uid_a=uid_a, uid_b=uid_b)
    _live_room(uid_a=uid_a, uid_b=uid_b)
    server._LOBBY_SPECTATE_FLAG_CACHE.clear()

    calls = []
    original = server.db.get_allow_spectate
    monkeypatch.setattr(server.db, 'get_allow_spectate',
                        lambda uid: (calls.append(uid), original(uid))[1])
    server.build_lobby_state()
    assert sorted(calls) == sorted([uid_a, uid_b]), \
        '一次广播里每个 uid 只该读一次，实际 %d 次：%r' % (len(calls), calls)
    # 第二次广播：TTL 内必须**一次都不读**
    calls.clear()
    server.build_lobby_state()
    assert calls == [], 'TTL 内不该再查库，实际又查了 %r' % calls


def test_cache_expires_so_a_setting_change_shows_up(monkeypatch):
    """★ 缓存的另一面：TTL 过期后必须重读 —— 否则玩家关了开关，列表永远不改。"""
    uid_a = _account('a')
    _live_room(uid_a=uid_a)
    assert len(_matches()) == 1
    db_module.set_allow_spectate(uid_a, False)
    # 缓存还没过期：仍按旧值显示（这正是缓存该有的行为，不当成 bug）
    assert len(_matches()) == 1
    # 把缓存时间戳往前推过 TTL
    stamp, value = server._LOBBY_SPECTATE_FLAG_CACHE[uid_a]
    server._LOBBY_SPECTATE_FLAG_CACHE[uid_a] = (
        stamp - server.LOBBY_SPECTATE_FLAG_TTL - 1.0, value)
    assert _matches() == [], 'TTL 过期后必须重读到"已关闭"'


def test_no_other_lobby_query_grows_with_match_count(monkeypatch):
    """★ 房间数增长不许让查库次数增长（批量是硬要求，不是"看着还行"）。"""
    uid_a, uid_b = _account('a'), _account('b')
    for _ in range(5):
        _live_room(uid_a=uid_a, uid_b=uid_b)
    server._LOBBY_SPECTATE_FLAG_CACHE.clear()
    calls = []
    original = server.db.get_allow_spectate
    monkeypatch.setattr(server.db, 'get_allow_spectate',
                        lambda uid: (calls.append(uid), original(uid))[1])
    server.build_lobby_state()
    assert len(calls) == 2, '5 间房 2 个账号 → 只该读 2 次，实际 %d 次' % len(calls)


# ===========================================================================
# 5. ★ 观战屏的源码级守卫（DOM 跑不进 pytest，这里只锁结构性事实）
# ===========================================================================
def test_spectate_screen_exists_once_and_is_not_hidden_based():
    assert HTML.count('id="spectate-screen"') == 1, '观战屏必须恰好一个'
    m = re.search(r'<div id="spectate-screen" class="screen">', HTML)
    assert m, '观战屏必须是 .screen（test_screen_overlay_registry 的清单按这个形状取）'


def test_spectate_screen_is_registered_in_all_screens():
    body = _js_body('allScreens')
    assert 'spectateScreen' in body, '观战屏没登记进 allScreens() → 切走时不会摘 active'


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


def test_seat_alignment_only_uses_seat_labels():
    """★ 座位对齐只走 `seat_labels` —— 前端不许自己把 key 猜成 p1/p2。"""
    body = _js_body('spectateSeatLabel')
    assert 'seatLabels' in body
    assert "'unknown'" in body, '认不出的座位必须退化成 unknown（绝不回显原始 key）'
    # 退化值不许是原始 key
    assert 'return seatId' not in body and 'return label ||' not in body


def test_spectate_handlers_are_gated_on_spectate_active():
    """★ 观战的事件处理必须带门禁 —— 观众与玩家的状态在同一份 gameState 里。"""
    block = JS.split("// ★ 实时观战（第 3 批）：观众侧的实时流")[1]
    block = block.split("socket.on('achievements_unlocked'")[0]
    handlers = re.findall(r"socket\.on\('(\w+)'", block)
    assert 'spectate_sync' in handlers and 'attack_result' in handlers
    assert handlers.count('game_over') == 1, 'game_over 不许有两份观战处理（必然漂移）'
    # 除了 spectate_sync（它要在 ack 之前先把快照存下来），其余都要先判 active
    for name in handlers:
        chunk = block.split("socket.on('%s'" % name)[1].split('});')[0]
        gated = ('spectateActive()' in chunk) or ('sp.active' in chunk)
        assert gated, '%s 的处理缺少 active 门禁' % name


def test_spectate_screen_never_uses_the_hidden_class():
    """★ 屏的显隐只能用 `active`（.hidden{display:none!important} 会永久锁死这一屏）。"""
    assert 'spectateScreen.classList.add' in JS or 'switchScreen(spectateScreen)' in JS
    assert not re.search(r"spectateScreen\.classList\.add\(['\"]hidden['\"]\)", JS)
    assert not re.search(r"getElementById\(['\"]spectate-screen['\"]\)[^\n]{0,60}classList\.add\(['\"]hidden", JS)


def test_spectate_events_are_not_sent_through_game_state():
    """★ 不许给 `game_state` 发新 state 值（它的 default 分支会提示"请刷新页面"）。"""
    assert 'spectate' not in server.__dict__.get('GAME_STATES', ())
    # 前端也不许把观战状态塞进 gameState.currentPhase 那套对局字段
    for banned in ('gameState.playerId = ', 'gameState.ships = '):
        block = JS.split('// ★ 实时观战（第 3 批）：观战屏 + 实时流')[1]
        block = block.split('// 大厅建房：走服务端的 lobby_create_room')[0]
        assert banned not in block, '观战屏不许写对局屏的状态字段：%s' % banned


def test_lobby_match_button_has_a_delegated_handler():
    """列表每 4 秒重建 → 必须用事件委托，否则点「观战」没反应（不报错）。"""
    assert "lobbyMatchesList.addEventListener('click'" in JS
    assert '.lobby-match-spectate' in JS
    assert 'renderLobbyMatches(Array.isArray(state.matches)' in JS


def test_spectate_failure_reason_is_shown():
    """★ 失败必须把服务端给的理由显示出来（教训 #32：静默 = 点了没反应）。"""
    body = _js_body('joinSpectate')
    assert 'showAlert' in body
    assert 'response.message' in body


def test_setting_checkbox_state_comes_from_the_server():
    """★ 观战开关的状态只许来自服务端（前端不许自己给默认值糊弄）。"""
    body = _js_body('loadSpectateSetting')
    assert '/api/spectate/setting' in body
    assert 'allow_spectate' in body
    save = _js_body('saveSpectateSetting')
    assert 'method: \'POST\'' in save or "method: 'POST'" in save
    assert 'checked = !(on === true)' in save, '保存失败必须回滚勾选状态'
    assert 'settings-spectate-msg' in JS, '保存结果必须写进提示位'


def test_no_python_style_string_formatting_in_js():
    """★★ 本批真实踩过的坑：把 Python 的 `'p%d' % (…)` 写进 JS。

    JS 里 `%` 是**取余**：`(index + 1) % undefined` = NaN，于是座位标签恒为
    `"NaN"`、`data["NaN"]` 恒为 undefined → **棋盘一格都不画、名字全退化成默认值**，
    而 `node --check` 通过、控制台干干净净（教训 #34 的形状）。

    这里扫全文（**剔掉注释**，注释里正是在讲这件事），任何 `% (` 一律判红。
    """
    lines = []
    in_block = False
    for line in JS.splitlines():
        stripped = line.strip()
        if in_block:
            if '*/' in stripped:
                in_block = False
            continue
        if stripped.startswith('/*'):
            if '*/' not in stripped:
                in_block = True
            continue
        if stripped.startswith('//'):
            continue
        # 去掉行尾注释（本项目的 `//` 注释不会出现在字符串字面量里带 % 的地方）
        code = stripped.split('//')[0]
        lines.append(code)
    code_only = '\n'.join(lines)
    bad = [ln for ln in code_only.splitlines() if re.search(r"%\s*\(", ln)]
    assert not bad, (
        'static/game.js 里出现了 Python 式的 `% (…)` 格式化 —— 在 JS 里它不报错，'
        '只会静默算出 NaN：%r' % bad)


def test_spectate_label_is_built_by_concatenation():
    """正向：座位标签必须是**拼字符串**拼出来的（`'p' + (i + 1)`）。"""
    body = _js_body('renderSpectatePlayers')
    assert "'p' + (index + 1)" in body, '座位标签必须用字符串拼接'
    board_body = _js_body('renderSpectateBoards')
    assert "'p' + (index + 1)" in board_body, '棋盘渲染里的座位标签同样要拼字符串'


def test_leave_clears_the_spectate_screen():
    """★ 退出观战必须把屏清干净（棋盘 36 格留着会让下一局"串台"）。"""
    body = _js_body('leaveSpectateScreen')
    assert 'spectateBoards.forEach' in body, '退出时要遍历两块棋盘做清理'
    assert 'innerHTML' in body, '棋盘内容要被清掉'
    # 只清内容，不许给屏加 hidden（那条铁律有专门的用例）
    assert "classList.add('hidden')" not in body
    assert 'showLobby()' in body, '退出后要回到大厅'
