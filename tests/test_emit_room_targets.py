# -*- coding: utf-8 -*-
"""`emit(..., room=...)` 到底发给了谁（2026-09-23，单独一批，与观战功能无关）。

## 这一批在修什么

`server.py` 的统一出口 `emit(event, data, to=None, room=None)` 里两个关键字
**语义不同**：

* `to=`   = 只发给**一条连接**（私人消息，`emit` 不复制观战副本）；
* `room=` = 发给一个 **socket.io 房间**（只有"活着的对局房间号"才走观战第三条腿）。

修之前，全文件有 **9 处**把玩家的 sid 写进了 `room=` —— 想写的是"只发给这个人"，
写法却是"发给这个房间"：

| # | 函数 | 事件 | 真实意图（判断依据） |
| --- | --- | --- | --- |
| 1 | `GameRoom.draw_card` | `hand_updated` | 手牌只给本人（payload 是完整手牌） |
| 2 | `test_add_all_magic_cards` | `hand_updated` | 同上 |
| 3 | `test_add_specific_magic_card` | `hand_updated` | 同上 |
| 4 | `handle_join_room`（房间不存在） | `error` | 提示只回给发起这次 join 的连接 |
| 5 | `handle_join_room`（房间已满） | `error` | 同上 |
| 6 | `handle_chat_message`（无房间 fallback） | `chat_message` | `isMe: True` —— 只对**一个**收件人有意义 |
| 7 | `_grant_match_achievements` | `achievements_unlocked` | 注释原文：「只发本人」 |
| 8 | `_grant_match_xp` | `xp_gained` | 注释原文：「单独推给本人」 |
| 9 | `_emit_rank_events_now` | `rank_changed` | 注释原文：「只发本人那一份」 |

⚠️ 这 **9** 处不是文档里那个"5 处"：`docs/SPECTATE_2026_09_22.md` §4 列的 5 个行号
早已漂移，且它漏掉了 `xp_gained` 与三处 `request.sid`。这里是**按 AST 重新穷举**的
结果（`emit(...)` 包装 + `semit`，不含 `socketio.emit` 直调）。

它们没有当场炸掉，是因为 `_live_room_id` 那层门禁把这种参数**悄悄**挡在观战腿
之外 —— 症状被盖住了，写法本身还是错的（教训 #32/#34）。本批 9 处全部改成 `to=`。

## 为什么"谁收到了"不足以当判据

`room=<sid>` 与 `to=<sid>` 在 socket.io 里**收件人集合完全相同**
（socket.io 的每条连接都自带一个以自己 sid 命名的房间）。所以"某个人收到了、
另一个人没收到"这句话对两种写法**都成立**，光靠它分不出对错。

真正分得出的是：**这一发被当成了"单发"还是"房间广播"**。本文件因此给出口加了一层
探针（`emit_spy`），逐处断言 `(to=<sid>, room=None)`，再叠上"谁收到 / 谁没收到"。
两半都要有 —— 只断言写法，就会出现"根本没发出去"也照样绿的假绿。

## 两类断言

1. **源码级穷举守卫**（`test_no_wrapper_emit_passes_a_sid_as_a_room` 等）：
   扫 `server.py` 里全部 `emit(...)` / `semit(...)` / `socketio.emit(...)` 调用，
   凡 `room=` 传的值"看起来是 sid"就报错。
   ⚠️ **`to=player.sid` 是完全正确的常见写法**，扫的只是 `room=`（有假阳性用例钉住）。
2. **9 处各自的回归**：走真 socket（`socketio.test_client`），断言
   "该收的收到 / 不该收的没收到 / 没进观战通道 / 写法是单发"。

## 能红的证据

* `test_guard_actually_catches_a_sid_in_room` —— 把 `to=player.sid` 改回
  `room=player.sid` → 守卫必须报出来；
* `test_single_send_probe_actually_catches_a_room_broadcast` —— 证明第 2 类断言
  用的判据本身抓得住"写成了房间广播"；
* `test_all_nine_sites_are_single_sends_now` —— 9 处逐处点名（按内容登记，不按行号）。
"""
import ast
import io
import itertools
import pathlib
import uuid

import pytest

import db as db_module
import server
import spectate
from server import GameRoom, Player, room_manager

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER_PY = REPO_ROOT / 'server.py'
SERVER_SRC = io.open(SERVER_PY, encoding='utf-8').read()


# ===========================================================================
# 1. 源码级穷举守卫
# ===========================================================================
def _looks_like_sid(expr):
    """这个表达式看起来是不是一个 **socket id**（而不是房间号）。

    四类都算：属性取值（`player.sid` / `request.sid` / `self.sid`）、
    变量名（`sid` / `owner_sid` / `player_sid`）、`getattr(x, 'sid')`、`x['sid']`。
    对局房间里没有这些形状 —— 房间号一律叫 `room.id` / `room_id`
    （或者 `getattr(room, 'id', None) or None`、`spectate_room_id(...)`）。
    """
    if isinstance(expr, ast.Attribute):
        return expr.attr == 'sid'
    if isinstance(expr, ast.Name):
        return expr.id == 'sid' or expr.id.endswith('_sid')
    if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) \
            and expr.func.id == 'getattr':
        return any(isinstance(a, ast.Constant) and a.value == 'sid' for a in expr.args[1:])
    if isinstance(expr, ast.Subscript):
        return isinstance(expr.slice, ast.Constant) and expr.slice.value == 'sid'
    return False


def _emit_label(func):
    """出口标注：`emit` / `semit`（本文件的统一包装）与 `socketio.emit`（直调）要分开。

    ⚠️ 分开是**必须**的：`socketio.emit(..., room=<sid>)` 是 python-socketio 自己的
    "发给某一条连接"写法（它的签名里 `to` 只是 `room` 的别名），不经 `emit` 包装、
    也就没有"被当成房间广播"这个问题。把两者混为一谈会误伤那处合法调用。
    """
    if isinstance(func, ast.Name) and func.id in ('emit', 'semit'):
        return func.id
    if isinstance(func, ast.Attribute) and func.attr in ('emit', 'semit'):
        return ast.unparse(func)
    return None


def _iter_emit_kwargs(source, kwarg):
    """扫全文件，产出每个 `emit(...)` 调用里 `kwarg=` 的值。

    每行 = `{'line', 'callee', 'in', 'src', 'node'}`。`in` = **所在函数名**
    （登记表按它 + 表达式来认，行号会漂）。
    """
    rows = []

    def walk(node, fn):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, child.name)
                continue
            if isinstance(child, ast.Call):
                label = _emit_label(child.func)
                if label:
                    for kw in child.keywords:
                        if kw.arg == kwarg:
                            rows.append({'line': child.lineno, 'callee': label,
                                         'in': fn, 'src': ast.unparse(kw.value),
                                         'node': kw.value})
            walk(child, fn)

    walk(ast.parse(source), '<module>')
    return sorted(rows, key=lambda r: r['line'])


def _sid_room_emits(source):
    """源码里全部"`room=` 传 sid"的调用点。"""
    return [r for r in _iter_emit_kwargs(source, 'room') if _looks_like_sid(r['node'])]


# 唯一的例外登记表：值 = 直调 python-socketio 的单连接发送。
# 理由**必须非空**（写不出理由 = 没想清楚，与 `spectate.NOT_FOR_SPECTATORS` 同一口径）。
_ALLOWED_SID_ROOM_EMITS = {
    ('_push_friend_event', 'socketio.emit', 'sid'):
        'python-socketio 直调的单连接发送（`to` 只是 `room` 的别名，不经 emit 包装，'
        '没有观战第三条腿）：把一条好友事件发给同一个人的**每一张在线标签页**。',
}

# 9 处"本该单发"的调用点：按 (所在函数, 出口, 表达式) 登记 —— **不按行号**。
# 值 = 该形状在源码里**应当出现的次数**（`handle_join_room` 有两条相同的提示）。
_SID_SEND_SITES = {
    ('draw_card', 'emit', 'player.sid'): 1,
    ('test_add_all_magic_cards', 'emit', 'player.sid'): 1,
    ('test_add_specific_magic_card', 'emit', 'player.sid'): 1,
    ('handle_join_room', 'emit', 'request.sid'): 2,
    ('handle_chat_message', 'emit', 'request.sid'): 1,
    ('_grant_match_achievements', 'emit', 'sid'): 1,
    ('_grant_match_xp', 'emit', 'sid'): 1,
    ('_emit_rank_events_now', 'emit', 'sid'): 1,
}


def test_no_wrapper_emit_passes_a_sid_as_a_room():
    """★★ 本批的穷举守卫：`room=` 一律不许传 sid（登记过的直调除外）。"""
    bad = [r for r in _sid_room_emits(SERVER_SRC)
           if (r['in'], r['callee'], r['src']) not in _ALLOWED_SID_ROOM_EMITS]
    assert bad == [], (
        '这些地方把 sid 当成房间号传给了 `emit`（"只发给某一个人"要写 `to=`）：\n'
        + '\n'.join('  server.py:%d  %s(.%s) 的 room=%s' % (r['line'], r['in'], r['callee'], r['src'])
                    for r in bad))


def test_registered_exceptions_still_exist():
    """登记表不许烂在原地：源码里已经没这处写法时必须删掉它，否则守卫会放行空气。"""
    found = {(r['in'], r['callee'], r['src']) for r in _sid_room_emits(SERVER_SRC)}
    missing = sorted(set(_ALLOWED_SID_ROOM_EMITS) - found)
    assert missing == [], '登记表里有源码中已不存在的写法，请删掉：%r' % (missing,)


def test_every_exception_states_a_reason():
    """例外必须写明理由（空理由 = 没表态）。"""
    for key, reason in _ALLOWED_SID_ROOM_EMITS.items():
        assert isinstance(reason, str) and reason.strip(), '这条例外没写理由：%r' % (key,)


def test_guard_scans_the_whole_file_not_a_corner():
    """扫描器确实覆盖了全文件 —— 否则上面那条"没扫到"就是空转绿。"""
    rows = _iter_emit_kwargs(SERVER_SRC, 'room')
    assert len(rows) >= 100, '只扫到 %d 处 room=，扫描器坏了' % len(rows)
    assert len({r['in'] for r in rows}) >= 40, '覆盖到的函数太少，扫描器坏了'
    # 而且**确实**扫到过 sid 形状（登记表里那一处）—— 证明判据不是恒假
    assert len(_sid_room_emits(SERVER_SRC)) == len(_ALLOWED_SID_ROOM_EMITS)


def test_all_nine_sites_are_single_sends_now():
    """★ 9 处逐处点名：每一处现在都是 `to=<sid>`（按内容登记，不按行号）。"""
    rows = _iter_emit_kwargs(SERVER_SRC, 'to')
    counts = {}
    for r in rows:
        if _looks_like_sid(r['node']):
            key = (r['in'], r['callee'], r['src'])
            counts[key] = counts.get(key, 0) + 1
    missing = {k: v for k, v in _SID_SEND_SITES.items() if counts.get(k) != v}
    assert missing == {}, (
        '这些"本该单发"的地方没找到（或次数不对）：%r\n实际扫到：%r' % (missing, counts))
    assert sum(_SID_SEND_SITES.values()) == 9, '这一批修的是 9 处'


def test_guard_actually_catches_a_sid_in_room():
    """★★ 元测试：把 `to=player.sid` 改回 `room=player.sid`，守卫必须变红。"""
    broken = SERVER_SRC.replace('}, to=player.sid)', '}, room=player.sid)', 1)
    assert broken != SERVER_SRC, '没插进去 —— 源码写法变了，这条元测试要跟着改'
    hit = _sid_room_emits(broken)
    unregistered = [r for r in hit
                    if (r['in'], r['callee'], r['src']) not in _ALLOWED_SID_ROOM_EMITS]
    assert unregistered, '把 sid 塞回 `room=` 之后守卫还是绿的 —— 这条守卫是空的'
    assert unregistered[0]['src'] == 'player.sid'


def test_guard_does_not_flag_to_sid():
    """⚠️ 假阳性守卫：`to=player.sid` / `to=request.sid` 是完全正确的写法。"""
    snippet = (
        "def _demo():\n"
        "    emit('hand_updated', {}, to=player.sid)\n"
        "    emit('error', {'message': 'x'}, to=request.sid)\n"
        "    emit('rank_changed', {}, to=sid)\n"
        "    emit('attack_result', {}, room=room.id)\n"
        "    emit('game_over', {'winner': 'p1'}, room=room_id)\n"
        "    emit('spectate_ended', {}, room=spectate.spectate_room_id(room_id))\n"
        "    emit('game_canceled', {}, room=getattr(room, 'id', None) or None)\n"
        "    emit('error', {'message': 'x'}, room=None)\n"
    )
    assert _sid_room_emits(snippet) == [], '合法形状被误报了'
    # 反过来：真源码里那 9 处 `to=<sid>` 必须**确实存在**
    assert len(_iter_emit_kwargs(SERVER_SRC, 'to')) >= 9


def test_guard_catches_the_other_sid_shapes_too():
    """`*_sid` / `getattr(x,'sid')` / `x['sid']` 这些形状也得抓住（不然守卫只认字面量）。"""
    snippet = (
        "def _demo():\n"
        "    emit('hand_updated', {}, room=player_sid)\n"
        "    emit('hand_updated', {}, room=getattr(player, 'sid', None))\n"
        "    emit('hand_updated', {}, room=data['sid'])\n"
    )
    got = sorted(r['src'] for r in _sid_room_emits(snippet))
    assert got == ["data['sid']", 'getattr(player, \'sid\', None)', 'player_sid']


def test_a_non_room_room_value_is_never_silent(capsys):
    """★ 那层门禁不许再**静默**（教训 #32/#34）：挡住观战腿的同时必须留下痕迹。"""
    server.emit('hand_updated', {'hand': []}, room='some-browser-sid')
    out = capsys.readouterr().out
    assert '[emit]' in out and 'some-browser-sid' in out, \
        '把一个不是房间的值当房间号传时，门禁静默跳过了（症状会被盖住）：%r' % out
    # 行为不变：依然不发观战副本
    assert spectate.is_spectate_room('some-browser-sid') is False


# ===========================================================================
# 2. 真 socket + 出口探针
# ===========================================================================
_SEQ = itertools.count(1)


def _mk_user(prefix='emitsid'):
    name = '%s%d%s' % (prefix, next(_SEQ), uuid.uuid4().hex[:6])
    uid = db_module.create_user(name, 'x' * 12)
    assert uid, '建测试账号失败: %s' % name
    return uid


def _http(uid=None, username=None):
    http = server.app.test_client()
    if uid:
        with http.session_transaction() as sess:
            sess['user_id'] = uid
            sess['username'] = username or uid
    return http


def _sid_of(client):
    return server.socketio.server.manager.sid_from_eio_sid(client.eio_sid, '/')


def _msg_payload(msg):
    """收件队列里一条消息的 payload。

    ⚠️ `get_received()` 的 `args` **可能是 list 也可能是 dict**（本机实测两种都出现过，
    `test_perks_and_unlock_notice.py` 里也记过这个坑）—— 当成 list 去取 `[0]`
    会 `KeyError: 0`，那是"取形状取错"的假红，不是产品问题。
    """
    args = msg.get('args')
    if isinstance(args, dict):
        return args or None
    if isinstance(args, (list, tuple)):
        return args[0] if args else None
    return args


def _drain(client):
    """收件队列按事件名归组（**一次取完**，`get_received()` 会清空队列）。"""
    out = {}
    for msg in client.get_received():
        out.setdefault(msg['name'], []).append(_msg_payload(msg))
    return out


def _two_seat_room(uid_a=None, uid_b=None):
    """两个座位的对局房间（座位 key 用 `pa`/`pb`，sid 由用例按真连接改写）。"""
    room = GameRoom('emitsid-' + uuid.uuid4().hex[:6])
    room.players['pa'] = Player(name='甲', ships=[], attacks=[], remaining_ships=6,
                                sid='sid-pa', user_id=uid_a)
    room.players['pb'] = Player(name='乙', ships=[], attacks=[], remaining_ships=6,
                                sid='sid-pb', user_id=uid_b)
    room.state = 'attacking'
    room.current_phase = 'battle'
    room.current_attacker = 'pa'
    room.attack_order = ['pa', 'pb']
    room.attacks_remaining = 5
    room.round = 3
    room.game_logs = []
    room_manager.rooms[room.id] = room
    return room


@pytest.fixture
def sockets():
    """建**真登录**的 socket 连接（session 与 `request.sid` 都是真的）。"""
    made = []

    def _make(uid=None, username=None):
        client = server.socketio.test_client(
            server.app, flask_test_client=_http(uid, username))
        client.get_received()                 # 丢掉 connect 期间的噪音
        made.append(client)
        return client

    yield _make
    for client in made:
        try:
            client.disconnect()
        except Exception:                     # noqa: BLE001 - 清理失败不该让用例变红
            pass


@pytest.fixture
def emit_spy(monkeypatch):
    """两个出口收到的 `(出口, 事件, to, room)`。

    ★ 这是本批的**主判据**：`room=<sid>` 与 `to=<sid>` 的收件人集合完全相同，
    光看"谁收到了"分不出写法对错；分得出的是"这一发被当成单发还是房间广播"。

    `semit` 在没有请求上下文时（单测直调）本来就会抛 RuntimeError 让 `emit` 走
    `socketio.emit` 兜底 —— 两个出口都记，断言只关心 `to` / `room` 这两个值。
    """
    calls = []
    real_semit = server.semit
    real_socketio_emit = server.socketio.emit

    # ⚠️ payload 必须**按位置**转交：`flask_socketio.emit` 的签名是
    #    `emit(event, *args, **kwargs)`，写成 `data=payload` 会被它当未知 kwarg
    #    **悄悄丢掉**（消息照样发出去，只是 payload 没了）—— 那会把这个文件里
    #    一半的断言变成"收件队列里挂着一个没有 payload 的同名事件"的假红。
    def spy_semit(event, data=None, to=None, room=None, **kw):
        calls.append(('semit', event, to, room))
        return real_semit(event, data, to=to, room=room, **kw)

    def spy_socketio_emit(event, data=None, to=None, room=None, **kw):
        calls.append(('socketio', event, to, room))
        return real_socketio_emit(event, data, to=to, room=room, **kw)

    monkeypatch.setattr(server, 'semit', spy_semit)
    monkeypatch.setattr(server.socketio, 'emit', spy_socketio_emit)
    calls.clear()
    return calls


def _rows(calls, event):
    return [c for c in calls if c[1] == event]


def _assert_single_send(calls, event, sids, who):
    """★ 写法判据：这一发的收件人必须**逐个用 `to=<sid>` 指定**（没有任何一条带 room）。

    `sids` 可以是一个 sid（一个人）或一串 sid（"各发各的那一份"的结算类事件）——
    两种情形都要求：每一条记录的 `to` 都落在名单里、且**至少每条路都走不到房间广播**。
    """
    if isinstance(sids, str):
        sids = [sids]
    rows = _rows(calls, event)
    assert rows, '%s 的 `%s` 根本没发出去 —— 用例失去意义' % (who, event)
    bad = [c for c in rows if c[3] is not None or c[2] not in sids]
    assert bad == [], (
        '%s 的 `%s` 不是发给 %r 的单发，而是被当成了房间广播：%r'
        % (who, event, sids, bad))
    got = {c[2] for c in rows}
    assert got == set(sids), (
        '%s 的 `%s` 收件人不全：期望 %r，实际 %r' % (who, event, sorted(sids), sorted(got)))


def _assert_no_spectate_copy(calls):
    """这一批发的事件一个字节都不许进观战通道。"""
    bad = [c for c in calls if c[3] and str(c[3]).startswith(spectate.SPECTATE_ROOM_PREFIX)]
    assert bad == [], '这些发进观战通道了：%r' % (bad,)


def test_single_send_probe_actually_catches_a_room_broadcast(emit_spy):
    """★ 元测试：证明第 2 类断言用的探针抓得住"写成房间广播"（判据不是恒真）。"""
    room = _two_seat_room()
    try:
        emit_spy.clear()
        server.emit('hand_updated', {'hand': []}, room='sid-pa')   # 故意的错误写法
        with pytest.raises(AssertionError):
            _assert_single_send(emit_spy, 'hand_updated', 'sid-pa', '甲')
    finally:
        room_manager.rooms.pop(room.id, None)


# ---------------------------------------------------------------------------
# 2.1 手牌三处（`hand_updated` 是这一批里唯一会外发**完整手牌**的事件）
# ---------------------------------------------------------------------------
def test_draw_card_sends_hand_updated_to_that_player_only(emit_spy, sockets):
    """`GameRoom.draw_card`：本人收到手牌，对手**收不到**，且是单发。"""
    room = _two_seat_room()
    try:
        sa, sb = sockets(), sockets()
        pa, pb = room.players['pa'], room.players['pb']
        pa.sid, pb.sid = _sid_of(sa), _sid_of(sb)
        room.magic_deck = [server.magic_cards[0]]
        emit_spy.clear()
        card = room.draw_card('pa')
        assert card is not None, '没抽到牌 —— 这条用例没验到 emit'

        got_a, got_b = _drain(sa), _drain(sb)
        assert len(got_a.get('hand_updated') or []) == 1, '本人没收到手牌更新'
        assert got_a['hand_updated'][0]['hand'][0]['name'] == card.name
        assert not got_b.get('hand_updated'), '对手收到了别人的**完整手牌**！'
        _assert_single_send(emit_spy, 'hand_updated', pa.sid, '甲')
        _assert_no_spectate_copy(emit_spy)
    finally:
        room_manager.rooms.pop(room.id, None)


def test_add_all_cards_debug_only_to_that_player(emit_spy, sockets, monkeypatch):
    """调试事件 `test_add_all_magic_cards`：只回给被加牌的那个座位。"""
    monkeypatch.setattr(server, 'ENABLE_TEST_EVENTS', True)
    room = _two_seat_room()
    try:
        sa, sb = sockets(), sockets()
        pa, pb = room.players['pa'], room.players['pb']
        pa.sid, pb.sid = _sid_of(sa), _sid_of(sb)
        emit_spy.clear()
        ack = sa.emit('test_add_all_magic_cards',
                      {'room_id': room.id, 'player_id': 'pa'}, callback=True)
        assert ack and ack.get('status') == 'success', ack

        got_a, got_b = _drain(sa), _drain(sb)
        assert len(got_a.get('hand_updated') or []) == 1, '被加牌的人没收到手牌'
        assert len(got_a['hand_updated'][0]['hand']) == len(server.magic_cards)
        assert not got_b.get('hand_updated'), '对手收到了别人的完整手牌！'
        _assert_single_send(emit_spy, 'hand_updated', pa.sid, '甲')
        _assert_no_spectate_copy(emit_spy)
    finally:
        room_manager.rooms.pop(room.id, None)


def test_add_specific_card_debug_only_to_that_player(emit_spy, sockets, monkeypatch):
    """调试事件 `test_add_specific_magic_card`：同上。"""
    monkeypatch.setattr(server, 'ENABLE_TEST_EVENTS', True)
    room = _two_seat_room()
    try:
        sa, sb = sockets(), sockets()
        pa, pb = room.players['pa'], room.players['pb']
        pa.sid, pb.sid = _sid_of(sa), _sid_of(sb)
        card_name = server.magic_cards[0].name
        emit_spy.clear()
        ack = sa.emit('test_add_specific_magic_card',
                      {'room_id': room.id, 'player_id': 'pa', 'card_name': card_name},
                      callback=True)
        assert ack and ack.get('status') == 'success', ack

        got_a, got_b = _drain(sa), _drain(sb)
        assert len(got_a.get('hand_updated') or []) == 1, '被加牌的人没收到手牌'
        assert [c['name'] for c in got_a['hand_updated'][0]['hand']] == [card_name]
        assert not got_b.get('hand_updated'), '对手收到了别人的手牌！'
        _assert_single_send(emit_spy, 'hand_updated', pa.sid, '甲')
        _assert_no_spectate_copy(emit_spy)
    finally:
        room_manager.rooms.pop(room.id, None)


# ---------------------------------------------------------------------------
# 2.2 `join_room` 的两条失败提示（只该回给发起这次 join 的连接）
# ---------------------------------------------------------------------------
def test_join_missing_room_error_only_to_the_requester(emit_spy, sockets):
    """房间不存在 → 只有**发起 join 的那条连接**收到 error。"""
    sa, sb = sockets(uid=_mk_user()), sockets(uid=_mk_user())
    emit_spy.clear()
    ack = sa.emit('join_room', {'room_id': 'no-such-room-emitsid'}, callback=True)
    assert ack and ack.get('status') == 'error', ack

    got_a, got_b = _drain(sa), _drain(sb)
    msgs = [m['message'] for m in (got_a.get('error') or [])]
    assert msgs == ['房间不存在'], '发起方没收到（或收到了别的）：%r' % (got_a,)
    assert not got_b.get('error'), '**别的连接**收到了这条失败提示：%r' % (got_b,)
    _assert_single_send(emit_spy, 'error', _sid_of(sa), '发起 join 的连接')
    _assert_no_spectate_copy(emit_spy)


def test_join_full_room_error_only_to_the_requester(emit_spy, sockets):
    """房间已满 → 同上。"""
    room = _two_seat_room()
    room.state = 'waiting'
    try:
        sa, sb = sockets(uid=_mk_user()), sockets(uid=_mk_user())
        emit_spy.clear()
        ack = sa.emit('join_room', {'room_id': room.id}, callback=True)
        assert ack and ack.get('status') == 'error', ack

        got_a, got_b = _drain(sa), _drain(sb)
        msgs = [m['message'] for m in (got_a.get('error') or [])]
        assert msgs == ['房间已满'], '发起方没收到（或收到了别的）：%r' % (got_a,)
        assert not got_b.get('error'), '**别的连接**收到了这条失败提示：%r' % (got_b,)
        _assert_single_send(emit_spy, 'error', _sid_of(sa), '发起 join 的连接')
        _assert_no_spectate_copy(emit_spy)
    finally:
        room_manager.rooms.pop(room.id, None)


# ---------------------------------------------------------------------------
# 2.3 聊天 fallback
# ---------------------------------------------------------------------------
def test_chat_without_a_room_only_echoes_to_the_sender(emit_spy, sockets):
    """没有房间时的聊天 fallback：payload 里带着 `isMe: True` ⇒ 只能发给一个人。"""
    sa, sb = sockets(uid=_mk_user()), sockets(uid=_mk_user())
    emit_spy.clear()
    sa.emit('chat_message', {'room_id': 'no-such-room-emitsid', 'message': '在吗'})

    got_a, got_b = _drain(sa), _drain(sb)
    rows = got_a.get('chat_message') or []
    assert len(rows) == 1 and rows[0]['message'] == '在吗', '发起方没收到：%r' % (got_a,)
    assert rows[0]['isMe'] is True, 'isMe 是"相对某一位收件人"的字段，单发才成立'
    assert not got_b.get('chat_message'), '**别的连接**收到了"我发的"这条聊天：%r' % (got_b,)
    _assert_single_send(emit_spy, 'chat_message', _sid_of(sa), '发言的连接')
    _assert_no_spectate_copy(emit_spy)


# ---------------------------------------------------------------------------
# 2.4 结算三条（徽章 / 经验 / 段位）
# ---------------------------------------------------------------------------
def test_achievements_unlocked_only_to_that_player(emit_spy, sockets):
    """`_grant_match_achievements`：本人收到结构化徽章事件，对手收不到。"""
    uid_a, uid_b = _mk_user(), _mk_user()
    room = _two_seat_room(uid_a, uid_b)
    try:
        sa, sb = sockets(uid_a, '甲'), sockets(uid_b, '乙')
        pa, pb = room.players['pa'], room.players['pb']
        for client, player in ((sa, pa), (sb, pb)):
            player.sid = _sid_of(client)
            # 房间级那句「解锁了新徽章」是发到 socket.io **房间**里的，
            # 连接没进房间就收不到（`test_perks_and_unlock_notice.py` 同写法）。
            server.socketio.server.enter_room(_sid_of(client), room.id)
        # 让甲直接满足"首胜"（wins ≥ 1）
        with db_module.db._lock:
            db_module.db.conn.execute('UPDATE users SET wins = 1 WHERE id = ?', (uid_a,))
            db_module.db.conn.commit()
        emit_spy.clear()
        server._grant_match_achievements(room, ((pa, uid_a), (pb, uid_b)))

        got_a, got_b = _drain(sa), _drain(sb)
        rows = got_a.get('achievements_unlocked') or []
        assert len(rows) == 1, '本人应当收到一条结算提示，实际 %d' % len(rows)
        assert 'first_win' in [i['id'] for i in rows[0]['items']]
        assert not got_b.get('achievements_unlocked'), '对手收到了别人的解锁提示'
        # 房间级那句「解锁了新徽章」是**改动前就有**的广播行为，这里只确认没被改坏
        assert any('解锁了新徽章' in str((m or {}).get('text', ''))
                   for m in (got_a.get('message') or [])), '房间播报没了：%r' % (got_a,)
        _assert_single_send(emit_spy, 'achievements_unlocked', pa.sid, '甲')
        # ⚠️ 那句房间播报会**照常**复制给观众（`message` 本来就在白名单里）——
        #    所以这里只断言"私人那一条"没进观战通道。
        private = [c for c in emit_spy
                   if c[1] == 'achievements_unlocked'
                   and c[3] and str(c[3]).startswith(spectate.SPECTATE_ROOM_PREFIX)]
        assert private == [], '私人结算事件进了观战通道：%r' % (private,)
    finally:
        room_manager.rooms.pop(room.id, None)


def test_xp_gained_only_to_that_player(emit_spy, sockets):
    """`_grant_match_xp`：两个人各收到**自己那一份**，旁观连接一条也收不到。"""
    uid_a, uid_b = _mk_user(), _mk_user()
    room = _two_seat_room(uid_a, uid_b)
    try:
        sa, sb, sc = sockets(uid_a, '甲'), sockets(uid_b, '乙'), sockets(_mk_user(), '丙')
        pa, pb = room.players['pa'], room.players['pb']
        pa.sid, pb.sid = _sid_of(sa), _sid_of(sb)
        emit_spy.clear()
        server._grant_match_xp(room, (('pa', pa, uid_a, True), ('pb', pb, uid_b, False)))

        got_a, got_b, got_c = _drain(sa), _drain(sb), _drain(sc)
        assert [r['player_id'] for r in (got_a.get('xp_gained') or [])] == ['pa']
        assert [r['player_id'] for r in (got_b.get('xp_gained') or [])] == ['pb']
        assert got_a['xp_gained'][0]['xp_after'] == db_module.get_user_xp(uid_a)
        assert got_b['xp_gained'][0]['xp_after'] == db_module.get_user_xp(uid_b)
        assert not got_c.get('xp_gained'), '旁观连接收到了别人的经验事件'
        _assert_single_send(emit_spy, 'xp_gained', [pa.sid, pb.sid], '双方')
        _assert_no_spectate_copy(emit_spy)
    finally:
        room_manager.rooms.pop(room.id, None)


def test_rank_changed_only_to_that_player(emit_spy, sockets):
    """`_emit_rank_events_now`：段位变化只发本人那一份。"""
    sa, sb = sockets(uid=_mk_user(), username='甲'), sockets(uid=_mk_user(), username='乙')
    sid_a = _sid_of(sa)
    emit_spy.clear()
    server._emit_rank_events_now(((sid_a, {'delta': 12, 'tier': 'gold'}),))

    got_a, got_b = _drain(sa), _drain(sb)
    assert [r['delta'] for r in (got_a.get('rank_changed') or [])] == [12]
    assert not got_b.get('rank_changed'), '别的连接收到了别人的段位变化'
    _assert_single_send(emit_spy, 'rank_changed', sid_a, '甲')
    _assert_no_spectate_copy(emit_spy)
