# -*- coding: utf-8 -*-
"""观战第 7 批：**连锁响应**这条动作的实时观战守卫。

## 为什么单独加这一批

`tools/spectate_check.mjs` 里那条「连锁响应应当实时出现在观众的连锁区」
从第 4 批起就**红一半的次数**（第 6 批 8 次里红 5 次），第 4~6 批都只记了
"已知 flakiness：读 DOM 时可能已结算"，没人查清。

第 7 批查清后的结论（原始输出见 `docs/SPECTATE_BATCH7_2026_09_23.md`）：

* 观众那条连接**每次都收到了** `magic_chain_updated`（栈里两张牌都在），
  前端也**每次都画出来了**；
* 只是那一帧 DOM 只存在 **3~17 毫秒**：响应把栈顶康掉之后
  `_advance_chain_window(room, 对方)` 发现**双方都拿不出速阶3**
  （响应者刚把自己的那一张用掉）⇒ **同一个栈帧内** `resolve_chain`
  ⇒ `chain_resolved` ⇒ 前端把连锁区清空；
* 工具在 ack 之后 18~33ms 才第一次读 DOM ⇒ 正好读到"清空之后"。

⇒ **不是玩家可见的缺口**（(甲) 工具脆），服务端这一侧的语义一直是好的。
但"观众能不能看到连锁响应"是核心不变量二（双方动作都看得见）的一条，
原来**只有**那条脆工具在守 ⇒ 用 pytest 把服务端这一半钉死，
再让工具去守"前端真的收到并画出来了"那一半（台账口径）。

## 本文件的守卫

1. `test_chain_response_reaches_spectators`：响应之后观众**收件队列**里有
   `magic_chain_updated`，且 payload 里**两张牌都在**、座位标签是 `p1`/`p2`；
2. `test_chain_response_is_not_sent_to_spectators_as_raw_chain`：净化没有把
   动作砍掉（两张牌的名字都在）也没有把 `player_id` 漏出去；
3. `test_chain_response_guard_can_fail`：**证明守卫能红** —— 把响应路径上的
   `magic_chain_updated` 广播掐掉（模拟"漏了这条动作"），守卫必须变红。
"""
import json
import uuid

import pytest

import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, ChainItem
from spectate import spectate_room_id

import db as db_module


_ACCOUNTS = {}
_room_manager = server.room_manager


def _account(key):
    if key not in _ACCOUNTS:
        uid = db_module.create_user('spec7-%s-%s' % (key, uuid.uuid4().hex[:10]), 'x' * 12)
        assert uid, '建测试账号失败'
        _ACCOUNTS[key] = uid
    return _ACCOUNTS[key]


# 座位 key 用**匹配房的约定**（key = socket sid）—— 最容易出问题的那一套。
# ⚠️ 必须是**真连接**的 sid：`socket_for` 建出来的客户端自己也有 sid，
#    但房间是**先建好**的（`room` fixture），所以这里用两个假 key + 把它们登记成
#    那两个 socket 的 sid —— 见 `_bind_sids()`。
SID_A, SID_B = 'spec7-sid-a', 'spec7-sid-b'

P1_SHIPS = (((0, 0),), ((1, 0),), ((2, 0),), ((3, 0),), ((4, 0),), ((5, 0),))
P2_SHIPS = (((0, 5),), ((1, 5),), ((2, 5),), ((3, 5),), ((4, 5),), ((5, 5),))


def _ships(shape):
    return [PlayerShip(positions=[Position(x, y) for (x, y) in cells], hits=[])
            for cells in shape]


def _make_room():
    room_id = 'spec7-' + uuid.uuid4().hex[:6]
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
    _room_manager.rooms[room.id] = room
    return room


@pytest.fixture
def room():
    r = _make_room()
    yield r
    _room_manager.rooms.pop(r.id, None)


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
def socket_for():
    """真登录的 socket 连接（session 与 `request.sid` 都是真的）。"""
    made = []

    def _make(uid, enter=None, username=None):
        client = server.socketio.test_client(server.app, flask_test_client=_http(uid, username))
        if enter:
            server.socketio.server.enter_room(_sid_of(client), enter)
        client.get_received()
        made.append(client)
        return client

    yield _make
    for client in made:
        try:
            client.disconnect()
        except Exception:                   # noqa: BLE001 - 清理失败不该让用例变红
            pass


def _bind_sids(room, player_a, player_b):
    """把房间里的两个座位 key **登记成这两个真连接的 sid**。

    为什么必须这么做：`chain_response` 的鉴权是
    「座位登记的 sid == 当前连接」（`_identity_check` 第 2 条），
    座位 key 本身是匹配房那套（= 入队时的 socket sid）。用假 key 建房间、
    再用真连接去发事件，会在鉴权处被拦下 —— 那样测的就不是观战广播了。
    这里只是把连接换上真实的 sid，**不改任何被测逻辑**。
    """
    sid_a, sid_b = _sid_of(player_a), _sid_of(player_b)
    room.players[sid_a] = room.players.pop(SID_A)
    room.players[sid_b] = room.players.pop(SID_B)
    room.players[sid_a].sid = sid_a
    room.players[sid_b].sid = sid_b
    if room.current_attacker == SID_A:
        room.current_attacker = sid_a
    room.attack_order = [sid_a if p == SID_A else sid_b for p in room.attack_order]
    return sid_a, sid_b


def _drain(client):
    out = {}
    for msg in client.get_received():
        out.setdefault(msg['name'], []).append(msg['args'][0] if msg['args'] else None)
    return out


def _arm_chain(room, caster_sid, responder_sid, card_name='失灵！'):
    """把房间摆成"甲打了一张牌、窗口在乙手里、乙手里有速阶3"。

    ⚠️ 形状必须与 `handle_use_magic_card` 压栈之后的真实状态一致：
    `chain` 里一项、`chain_waiting=True`、`chain_window=<响应者>`。
    ⚠️ 两个 sid 都由调用方传入**真连接**的 sid（见 `_bind_sids`）——
       座位标签 `p1/p2` 就是按 `room.players` 的顺序算的，
       这里用假 key 会让标签退化成 `unknown`（那测的就不是观众看到什么了）。
    """
    top = ChainItem(caster_sid, MagicCard(name='无中生有', speed=1, type='普通',
                                          description=''), [], 0.0)
    room.chain = [top]
    room.chain_passes = 0
    room.chain_waiting = True
    room.chain_window = responder_sid
    room.chain_timer = 1
    card = MagicCard(name=card_name, speed=3, type='普通', description='')
    room.players[responder_sid].magic_hand.append(card)
    return card


def _respond(client, room, pid, card_name='失灵！'):
    return client.emit('chain_response', {
        'room_id': room.id, 'player_id': pid,
        'chain': True,
        'card': {'name': card_name, 'speed': 3},
        'targets': [],
    }, callback=True)


def _chain_frames(queue):
    """收件队列里所有 `magic_chain_updated` 的 payload。"""
    return queue.get('magic_chain_updated') or []


def _setup(room, socket_for, arm=True):
    """一份公共布置：观众进席 + 乙这条真连接 + 把房间摆成"等乙响应"。"""
    watcher = socket_for(_account('watcher'), username='观众')
    assert watcher.emit('spectate_join', {'room_id': room.id},
                        callback=True)['status'] == 'success'
    player_a = socket_for(_account('alpha'), enter=room.id, username='甲')
    player_b = socket_for(_account('beta'), enter=room.id, username='乙')
    sid_a, sid_b = _bind_sids(room, player_a, player_b)
    if arm:
        _arm_chain(room, caster_sid=sid_a, responder_sid=sid_b)
    watcher.get_received()                  # 丢掉进席/人数噪音
    player_a.get_received()
    player_b.get_received()
    return watcher, player_a, player_b, sid_a, sid_b


# ===========================================================================
# 1. ★★ 主守卫：观众的收件队列里**真的有**这一帧（且两张牌都在）
# ===========================================================================
def test_chain_response_reaches_spectators(room, socket_for):
    """★★ 乙响应「失灵！」→ **观众**那条连接收到带两张牌的 `magic_chain_updated`。

    这是不变量二（双方所有动作都看得到）里"连锁响应"这一条的服务端半边。
    ⚠️ 判据取的是**收件队列**（这条连接真的收到了什么），不是 DOM ——
       见本文件头部说明：DOM 上那一帧只存在 3~17ms，读 DOM 的判据一半会假红。
    """
    watcher, player_a, player_b, sid_a, sid_b = _setup(room, socket_for)

    ack = _respond(player_b, room, sid_b)
    assert ack and ack['status'] == 'success', ack

    got = _drain(watcher)
    frames = _chain_frames(got)
    assert frames, (
        '观众**没有收到**连锁响应这一帧（`magic_chain_updated` 一个都没有）'
        '—— 这是真缺口（不变量二的连锁响应那一条）：%r' % got)

    names = [it.get('card_name') or (it.get('card') or {}).get('name')
             for it in (frames[-1].get('chain') or [])]
    assert names == ['无中生有', '失灵！'], (
        '观众收到的连锁帧里不是那两张牌（动作没传全）：%r' % (frames[-1],))
    assert frames[-1].get('chain_len') == 2

    seats = [it.get('seat') for it in frames[-1]['chain']]
    assert seats == ['p1', 'p2'], '座位标签不对（必须是 p1/p2，不是原始 sid）：%r' % (seats,)


# ===========================================================================
# 2. 净化口径：动作留着、连接标识不许留
# ===========================================================================
def test_chain_frame_keeps_action_and_drops_player_id(room, socket_for):
    """净化**不许**为了安全把动作也砍掉；也**不许**把 `player_id`（socket sid）发出去。"""
    watcher, player_a, player_b, sid_a, sid_b = _setup(room, socket_for)

    assert _respond(player_b, room, sid_b)['status'] == 'success'
    frames = _chain_frames(_drain(watcher))
    assert frames, '没收到帧，本用例的前提不成立'

    blob = json.dumps(frames[-1], ensure_ascii=False)
    assert sid_a not in blob and sid_b not in blob, '帧里出现了原始座位 sid：%r' % (blob,)
    # ⚠️ 别用 `'targets' not in blob`：净化结果里**有一项就叫 `targets_dropped`**
    #    （它是"剥掉了几个目标"的计数，是本批要保留的东西）。要判的是
    #    `ChainItem.targets` 那个**字段**有没有被带出来 —— 逐项看键名。
    for item in frames[-1]['chain']:
        assert set(item) == {'card', 'timestamp', 'negated', 'negated_by', 'seat'}, (
            '连锁项里出现了多余的键（`targets` 就是客户端提交的原始目标，形状不受控）：%r'
            % (sorted(item),))


# ===========================================================================
# 3. ★★ 证明守卫能红：把这条动作的广播掐掉 → 主守卫必须变红
# ===========================================================================
def test_chain_response_guard_can_fail(room, socket_for, monkeypatch):
    """把响应路径上的 `magic_chain_updated` 广播掐掉（模拟"漏了这条动作"），
    主守卫的判据**必须**变红 —— 否则它就是一条永远绿（空转）的扫描。

    掐法：`server.emit` 包一层，把"事件名 == `magic_chain_updated` 且发往对局房间"
    的那一次调用丢掉（其余事件照常发）。这正是"漏一个动作"的最小形态：
    服务端状态照常前进，只有观众的播出流少一帧。
    """
    watcher, player_a, player_b, sid_a, sid_b = _setup(room, socket_for)

    real_emit = server.emit
    dropped = []
    room_arg = room.id

    def sabotage(event, data, to=None, room=None):
        if event == 'magic_chain_updated' and room == room_arg:
            dropped.append(event)
            return None
        return real_emit(event, data, to=to, room=room)

    monkeypatch.setattr(server, 'emit', sabotage)
    try:
        ack = _respond(player_b, room, sid_b)
    finally:
        monkeypatch.undo()

    assert ack and ack['status'] == 'success', ack
    assert dropped == ['magic_chain_updated'], (
        '掐点没生效（说明 chain_response 里那条广播的位置/形状变了），'
        '本用例证明不了任何事：%r' % (dropped,))

    frames = _chain_frames(_drain(watcher))
    assert not frames, (
        '把 `magic_chain_updated` 掐掉之后观众**居然还是收到了**连锁帧 —— '
        '那说明它走的是另一条路，主守卫盯错了地方：%r' % (frames,))


# ===========================================================================
# 4. ★★ 证明守卫能红（第二种口径）：整张事件表把这条动作摘掉
# ===========================================================================
def test_guard_fails_when_event_is_removed_from_the_allow_list(room, socket_for,
                                                              monkeypatch):
    """把 `magic_chain_updated` 从 `spectate.SPECTATE_EVENTS` 里摘掉（默认拒绝），
    观众就再也收不到连锁帧 —— 主守卫必须红。

    ⚠️ 与第 3 条不同：那条掐的是"发不发"，这条掐的是"发不发得出去"（净化表）。
       两条一起才能证明主守卫盯的是**观众真的收到了什么**，而不是某个中间变量。
    """
    watcher, player_a, player_b, sid_a, sid_b = _setup(room, socket_for)

    import spectate as spectate_mod
    table = dict(spectate_mod.SPECTATE_EVENTS)
    table.pop('magic_chain_updated')
    monkeypatch.setattr(spectate_mod, 'SPECTATE_EVENTS', table)
    try:
        ack = _respond(player_b, room, sid_b)
    finally:
        monkeypatch.undo()

    assert ack and ack['status'] == 'success', ack
    frames = _chain_frames(_drain(watcher))
    assert not frames, (
        '`magic_chain_updated` 已经从允许表里摘掉了，观众还是收到了 —— '
        '那说明净化那条路没接上：%r' % (frames,))
