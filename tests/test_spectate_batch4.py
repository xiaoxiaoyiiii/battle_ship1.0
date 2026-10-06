# -*- coding: utf-8 -*-
"""实时观战**第 4 批**：观战席名单 + 观战席聊天（对局双方不可见）+ 两条动作流守卫。

## 本批只有两条产品规则，但两条都靠**通道**而不是靠判断来保证

1. **观战席名单**：观众彼此看得到**名字**、进出**实时**；
   对局双方**只看得到人数**（`spectate_count_changed` 里**没有任何名字**）。
2. **观战席聊天**：只在观众之间可见；**对局双方一个字节都收不到**。
   而玩家之间的聊天**照旧发给观众**（第 1 批就登记在 `SPECTATE_EVENTS` 里）。

隔离**靠通道，不靠过滤**：观众只 `join_room('spectate:<id>')`、**从不进对局 room**；
玩家只在对局 room 里。两个 room 没有交集 ⇒ 玩家收不到不是因为"我们发完判了一下
谁是玩家"（那种写法每加一条发送路径就要重判一次，漏一个分支就当场破功，
而且**运行时毫无症状**）—— 是**结构上**就不在收件人集合里。

## 为什么全部断言都**两侧同时看**

只断言"玩家没收到"是**空转绿**：发送路径整个坏掉时它照样通过。
所以每条隔离用例都配一条**对照腿**（"观众/另一个观众确实收到了"）——
`test_chat_isolation_legs_are_both_real` 就是给这件事做的元测试。

## 为什么必须**真 socket**

`server._identity_ok` 在无请求上下文时会退化成"只要在 `room.players` 里就放行"，
而且 `_spectate_room_of_sid` 认的是 `request.sid`。直调 handler 会**绕过**
"他到底在不在席上"这条唯一鉴权 → 用例假绿。所以进出席与聊天一律走
`socketio.test_client`（session 与 `request.sid` 都是真的）。
"""
import ast
import io
import json
import pathlib
import re
import time
import uuid

import pytest

import db as db_module
import quick_chat
import server
import spectate
from server import GameRoom, Player, PlayerShip, Position, room_manager

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER_PY = REPO_ROOT / 'server.py'
GAME_JS = REPO_ROOT / 'static' / 'game.js'
INDEX_HTML = REPO_ROOT / 'templates' / 'index.html'

MAX_CHAT_MSG_LEN = server.MAX_CHAT_MSG_LEN
assert MAX_CHAT_MSG_LEN > 0


# ===========================================================================
# 房间 / 账号工厂（与第 2 批同一套约定）
# ===========================================================================
_ACCOUNTS = {}


def _account(key):
    """按 key 缓存一个**真账号**（观战席只收登录用户，且座位背后要有真账号）。"""
    if key not in _ACCOUNTS:
        uid = db_module.create_user('spec4-%s-%s' % (key, uuid.uuid4().hex[:10]), 'x' * 12)
        assert uid, '建测试账号失败'
        _ACCOUNTS[key] = uid
    return _ACCOUNTS[key]


# 座位 key 用**匹配房的约定**（key = socket sid）—— 最容易出问题的那套。
SID_A, SID_B = 'spec4-sid-a', 'spec4-sid-b'

P1_SHIPS = (((0, 0),), ((1, 0),), ((2, 0),), ((3, 0),), ((4, 0),), ((5, 0),))
P2_SHIPS = (((0, 5),), ((1, 5),), ((2, 5),), ((3, 5),), ((4, 5),), ((5, 5),))


def _ships(shape):
    return [PlayerShip(positions=[Position(x, y) for (x, y) in cells], hits=[])
            for cells in shape]


def _make_room(room_id=None):
    room_id = room_id or ('spec4-' + uuid.uuid4().hex[:6])
    room = GameRoom(room_id)
    room.players[SID_A] = Player(name='甲', ships=_ships(P1_SHIPS), attacks=[],
                                 remaining_ships=6, sid=SID_A, user_id=_account('alpha'))
    room.players[SID_B] = Player(name='乙', ships=_ships(P2_SHIPS), attacks=[],
                                 remaining_ships=6, sid=SID_B, user_id=_account('beta'))
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

    def _make(uid, enter=None, username=None):
        client = server.socketio.test_client(server.app, flask_test_client=_http(uid, username))
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


def _chat(client, room, message):
    return client.emit('spectate_chat_send',
                       {'room_id': room.id, 'message': message}, callback=True)


def _drain(client):
    """收件队列按事件名归组（**一次取完**，避免多次 get_received 互相掏空）。"""
    out = {}
    for msg in client.get_received():
        out.setdefault(msg['name'], []).append(msg['args'][0] if msg['args'] else None)
    return out


def _spectator_sid(room, name):
    """按显示名找回观众在这张席位上的 sid（席位 key 就是 socket sid）。"""
    for sid, info in room.spectators.items():
        if (info or {}).get('name') == name:
            return sid
    return None


def _json_text(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


# ===========================================================================
# 1. ★★ 观战席聊天：观众之间可见，**对局双方不可见**
# ===========================================================================
def test_spectate_chat_reaches_other_spectators_but_no_player(room, socket_for):
    """★★ 本批的核心断言：观众 A 发言 → 观众 B 收到；**对局双方都收不到**。

    两侧同时断言：`no_player` 那一半单独看是**空转绿**（没发出去时它照样通过），
    所以必须有 `w2` 那一半证明这条事件真的飞出去过。
    """
    user_a, user_b, user_w1, user_w2 = (_account('alpha'), _account('beta'),
                                        _account('watcher'), _account('watcher2'))
    player_a = socket_for(user_a, enter=room.id, username='甲')
    player_b = socket_for(user_b, enter=room.id, username='乙')
    w1 = socket_for(user_w1, username='观众一号')
    w2 = socket_for(user_w2, username='观众二号')
    assert _join(w1, room)['status'] == 'success'
    assert _join(w2, room)['status'] == 'success'

    for client in (player_a, player_b, w1, w2):
        client.get_received()               # 丢掉进席期间的名单/人数噪音

    secret = '观战席上的一句话'
    ack = _chat(w1, room, secret)
    assert ack and ack['status'] == 'success', ack

    # —— 对照腿：**另一个观众**收到了 ——
    got_w2 = _drain(w2)
    rows = got_w2.get('spectate_chat') or []
    assert len(rows) == 1 and rows[0]['message'] == secret, (
        '另一个观众没收到观战席聊天 —— 那么"玩家没收到"只是因为根本没人收到：%r' % got_w2)
    assert rows[0]['name'] == '观众一号'
    assert isinstance(rows[0]['ts'], int) and rows[0]['ts'] > 0

    # —— 主断言：**两个玩家都收不到** ——
    for client, who in ((player_a, '甲'), (player_b, '乙')):
        got = _drain(client)
        assert not got.get('spectate_chat'), (
            '%s（对局玩家）收到了观战席聊天！这条需求当场作废：%r' % (who, got.get('spectate_chat')))
        # 而且在**任何**其它事件里也找不到那句话（防"换了个事件名漏出去"）
        assert secret not in _json_text(got), (
            '%s 收到的收件队列里出现了观战席聊天的正文：%r' % (who, got))








# ===========================================================================
# 2. 观战席聊天的鉴权与校验（每一条拒绝都要有文案 —— 教训 #32）
# ===========================================================================
def test_chat_requires_login(room, socket_for):
    """未登录 → 明确拒绝（观战席只收登录用户）。"""
    guest = socket_for(None)
    out = _chat(guest, room, '我是游客')
    assert out and out['status'] == 'error', out
    assert out['message'], '拒绝必须带文案（静默 return = 点了没反应）'
    assert '登录' in out['message']


def test_chat_requires_a_seat_on_this_room(room, socket_for):
    """**不在观战席上** → 拒绝；而且不许把消息发进任何通道。"""
    user_a, user_w1 = _account('alpha'), _account('watcher')
    player_a = socket_for(user_a, enter=room.id, username='甲')
    w1 = socket_for(user_w1, username='观众一号')          # 登录了，但没进席
    assert _join(w1, room)['status'] == 'success'
    player_a.get_received()

    # 先在席上发一条（证明这条路径本身是通的），再退席发第二条
    assert _chat(w1, room, '在席上说的话')['status'] == 'success'
    assert _leave(w1, room)['status'] == 'success'
    player_a.get_received()
    out = _chat(w1, room, '退席之后说的话')
    assert out and out['status'] == 'error', out
    assert '观战席' in (out['message'] or '')
    assert not _drain(player_a).get('spectate_chat'), '退席的人还能往通道里说话'
















def test_chat_never_touches_the_game_log(room, socket_for):
    """★★ 观战聊天**绝不进对局日志**（同一个行为的端到端证据）。

    `add_game_log` 是**房间级广播**，一走玩家当场就看到；而且 `game_logs` 同一份
    数据还会进 `spectate_sync` 与玩家侧的重连快照 → 连"只写不广播"也不行。
    """
    user_a = _account('alpha')
    player_a = socket_for(user_a, enter=room.id, username='甲')
    w1 = socket_for(_account('watcher'), username='观众一号')
    assert _join(w1, room)['status'] == 'success'
    for client in (player_a, w1):
        client.get_received()

    before = len(room.game_logs)
    assert _chat(w1, room, '这句话不该进对局日志')['status'] == 'success'
    assert len(room.game_logs) == before, '观战聊天写进了 game_logs：%r' % room.game_logs[before:]
    assert not _drain(player_a).get('game_log'), '观战聊天借 game_log 广播了出去'
    # 重连快照 / 观战快照里也不许出现它
    snap = server._build_spectate_snapshot(room)
    assert '这句话不该进对局日志' not in _json_text(snap)


# ===========================================================================
# 3. ★★ 观战席名单：观众看得到，**对局双方看不到**
# ===========================================================================


def test_roster_never_reaches_the_players(room, socket_for):
    """★★ 对局双方**收不到名单**（只有人数）—— 两侧同时断言。"""
    user_a, user_b = _account('alpha'), _account('beta')
    player_a = socket_for(user_a, enter=room.id, username='甲')
    player_b = socket_for(user_b, enter=room.id, username='乙')
    w1 = socket_for(_account('watcher'), username='观众一号')
    w2 = socket_for(_account('watcher2'), username='观众二号')
    for client in (player_a, player_b):
        client.get_received()

    assert _join(w1, room)['status'] == 'success'
    assert _join(w2, room)['status'] == 'success'
    # 对照腿：观众 A 收得到名单（否则下面"玩家没收到"可能只是根本没发）
    assert (_drain(w1).get('spectate_roster') or []), '观众连名单都收不到，这条用例是空转的'

    for client, who in ((player_a, '甲'), (player_b, '乙')):
        got = _drain(client)
        assert got.get('spectate_count_changed'), '%s 没收到人数变化' % who
        for payload in got['spectate_count_changed']:
            assert set(payload) == {'count'}, '人数事件里多了字段：%r' % payload
        # 最后一次（两位观众都入席之后）必须是 2 —— 人数是**实时**的
        assert got['spectate_count_changed'][-1]['count'] == 2, \
            '%s 收到的最后一份人数不对：%r' % (who, got['spectate_count_changed'])
        # ★ 名单类事件一个都不许到玩家手里
        for event in ('spectate_roster', 'spectate_joined', 'spectate_left'):
            assert not got.get(event), '%s（玩家）收到了 %s：%r' % (who, event, got.get(event))
        # 而且在**任何**其它事件里也不许出现观众的名字
        text = _json_text(got)
        assert '观众一号' not in text and '观众二号' not in text, (
            '%s 收到的某个事件里夹带了观众名字：%s' % (who, text[:400]))


def test_roster_has_no_user_id_or_socket_or_seat_key(room, socket_for):
    """★ 名单里**只有显示名**（不给 uid / socket sid / 座位 key）。"""
    user_w1 = _account('watcher')
    w1 = socket_for(user_w1, username='观众一号')
    assert _join(w1, room)['status'] == 'success'
    roster = (_drain(w1).get('spectate_roster') or [])[-1]
    for row in roster['spectators']:
        assert set(row) == {'name', 'joined_at'}, '名单字段要逐个交代：%r' % row
    text = _json_text(roster)
    assert user_w1 not in text, '名单里带着观众的 user_id'
    assert _sid_of(w1) not in text, '名单里带着观众的 socket sid'
    assert SID_A not in text and SID_B not in text, '名单里带着对局座位的 key'
    # 顶层也只该有这三个键
    assert set(roster) == {'spectators', 'count', 'limit'}, set(roster)










# ===========================================================================
# 4. ★★ 源码级守卫（这类坏法 pytest 的行为断言抓不到）
# ===========================================================================
def _func_src(name):
    """按函数名取出 `server.py` 里那个函数的源码片段（**按名字，不按行号**）。"""
    src = io.open(SERVER_PY, encoding='utf-8').read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ''
    raise AssertionError('server.py 里找不到函数 %s（改名了？）' % name)


def _emits_in(src):
    """取出源码片段里所有 `emit(...)` / `socketio.emit(...)` 调用 → [(函数名, room 关键字源码)]。

    ⚠️ **只取 `room=` 那个关键字的值**（取不到给 None），而不是整行做字符串匹配：
    整行匹配会把 `to=sid` 那条路径里出现的 `room` 也当成嫌疑（那是**没有 room**
    的单发，本来就到不了别人手里）。取关键字还能顺带证明"这条 emit 到底发给谁"。
    """
    out = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, 'attr', None)
        if name not in ('emit', 'semit'):
            continue
        room_kw = None
        for kw in node.keywords:
            if kw.arg == 'room':
                room_kw = ast.unparse(kw.value)
        out.append((name, room_kw))
    return out


def _chat_handler_source():
    """`handle_spectate_chat_send` 的源码。

    ⚠️ 用 AST 取函数体，**不按行号**、也不整文件 grep —— 整文件 grep 会被
    别处的 `add_game_log`（全文件 40+ 处）淹没，那样的守卫永远变不红。
    """
    return _func_src('handle_spectate_chat_send')


def _chat_handler_offences(src):
    """扫出观战聊天 handler 里**会漏给玩家**的写法，返回 [(kind, 片段)]。

    三条：
      ① `add_game_log(...)` —— 房间级广播，一走玩家当场就看到；
      ② `game_logs`       —— 同一份数据会进 `spectate_sync` 与玩家侧重连快照；
      ③ `room=<对局房间号>` —— 直接发进对局房间。
    """
    offences = []
    for name, room_kw in _emits_in(src):
        # `room=` 的值必须写死成**观战通道名**（`spectate.spectate_room_id(...)`）；
        # 取不到（`to=sid` 单发）时也算合规 —— 单发到不了第二个收件人手里。
        # ⚠️ 这里**不看** `room=None` 那条兜底分支（它本来就是"没有收件人"）。
        if room_kw is None or room_kw == 'None':
            continue
        if 'spectate.spectate_room_id(' not in room_kw.replace(' ', ''):
            offences.append(('emit-to-non-spectate-room', '%s(room=%s)' % (name, room_kw)))
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            fn = node.func
            fname = fn.id if isinstance(fn, ast.Name) else getattr(fn, 'attr', None)
            if fname == 'add_game_log':
                offences.append(('add_game_log', ast.unparse(node)[:160]))
        if isinstance(node, ast.Attribute) and node.attr == 'game_logs':
            offences.append(('game_logs', ast.unparse(node)[:160]))
    return offences




def test_roster_and_chat_go_only_to_the_spectate_channel():
    """★ 源码级：名单/进出/聊天这几个发送函数里的 `room=` **只许**用观战通道名。

    这条防的是"顺手让玩家也看看"——那种改动让玩家**当场可见**，且没有任何症状。
    """
    checked = 0
    for fname in ('_spectate_broadcast_roster', '_spectate_announce',
                  'handle_spectate_chat_send', '_spectate_count_task'):
        src = _func_src(fname)
        for name, room_kw in _emits_in(src):
            if room_kw is None or room_kw == 'None':
                continue                    # `to=sid` 单发 / 无收件人兜底分支
            checked += 1
            assert 'spectate.spectate_room_id(' in room_kw.replace(' ', ''), (
                '%s 里的 %s 发去了非观战通道：room=%s' % (fname, name, room_kw))
    assert checked >= 3, '扫描面太窄（只看到 %d 处带 room 的 emit），守卫可能已失真' % checked

    # 反向校准：把广播改成发对局房间，这条守卫**必须**变红
    broken = _func_src('_spectate_broadcast_roster').replace(
        'room=spectate.spectate_room_id(room.id)', 'room=room.id', 1)
    assert broken != _func_src('_spectate_broadcast_roster'), '（前提）注入点没找到'
    offenders = [rk for _n, rk in _emits_in(broken)
                 if rk and 'spectate.spectate_room_id(' not in rk]
    assert offenders, '把名单广播改成发对局房间，守卫却没扫到 —— 它是摆设'








# ===========================================================================
# 5. 前端契约（源码级：id 对得上、只用 textContent）
# ===========================================================================


def test_spectate_chat_renders_with_text_content_only():
    """★ 渲染纪律：观战席聊天的每一处都必须 `textContent`（不许把服务端文本塞 innerHTML）。

    服务端下发的 `message` / `name` 都是**自由输入**。任何一处把它们拼进 innerHTML
    就是一个持久化 XSS —— 而观战屏上还挂着两块棋盘。

    ⚠️ `el.innerHTML = ''`（清空）是**合规**的：那是最省事也最安全的清空写法，
    里面没有任何外部文本。这里禁的是"给 innerHTML **赋上带变量的值**"。
    """
    src = io.open(GAME_JS, encoding='utf-8').read()
    blk_start = src.index('const SPECTATE_CHAT_LIMIT')
    blk_end = src.index('function renderSpectateScreen()')
    block = src[blk_start:blk_end]
    assert block.count('function ') >= 5, '取到的聊天渲染块太小了，守卫可能已失真'
    offenders = []
    for line in block.splitlines():
        if 'innerHTML' not in line:
            continue
        # 只放行 `innerHTML = ''` / `"")` 这种**清空**
        if re.search(r"innerHTML\s*=\s*(''|\"\")", line):
            continue
        offenders.append(line.strip())
    assert offenders == [], '观战席聊天的渲染里把内容塞进了 innerHTML：%r' % offenders
    assert 'textContent' in block
    # 反向校准：把一句服务端文本拼进 innerHTML，守卫**必须**抓到
    tainted = block.replace("div.textContent = String(row.text || '');",
                            "div.innerHTML = String(row.text || '');", 1)
    assert tainted != block, '（前提）注入点没找到 —— 反向校准失效了'
    assert [l.strip() for l in tainted.splitlines()
            if 'innerHTML' in l and not re.search(r"innerHTML\s*=\s*(''|\"\")", l)], \
        '把 textContent 换成 innerHTML，守卫却没抓到 —— 它是摆设'
