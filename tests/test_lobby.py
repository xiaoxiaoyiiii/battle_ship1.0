
# -*- coding: utf-8 -*-
"""大厅系统（Lobby）回归测试（2026-09-18）。

冻结契约见 docs/LOBBY_2026_09_18.md。本文件覆盖 6 组：

  1. **房间级新状态三件齐**（`GameRoom.name` / `GameRoom.public` 的初始化）；
  2. `LobbyManager` 本身：在线表 / 成员表 / 名字清洗 / 频率闸门 / 公屏积压；
  3. `build_lobby_state()` 的形状与 status 三态判据；
  4. **房间列表的四条可见规则**（waiting / 非人机 / public / 房主仍在线且恰好 1 人）
     —— 其中"房主仍在线"是最容易漏的一条，漏了就是一堆点进去没人的僵尸房；
  5. 公屏聊天：非成员拒绝 / 空白丢弃 / 超长截断 / 防刷 / 积压上限；
  6. **真实 socket 层**（socketio.test_client）：订阅握手、广播只发给大厅成员、
     退订生效、从大厅建房能出现在别人的列表里、私密房不上榜、
     `/api/online_count` 与在线表同口径。

⚠️ 与 test_ranked_match.py 同一套写法：直调 handler 时用假 request/session/emit，
   但**能用真实 test_client 的地方一律用真的** —— 直调绕过的是"事件到底有没有发出去"，
   而这正是本项目出过最多问题的地方（CLAUDE.md 通用教训：工具全绿、线上全坏）。

⚠️ autouse 夹具里把 `_LOBBY_TICKER_STARTED` 预置成 True：那个 4 秒兜底广播是
   为了线上兜底，在测试里只会随机往事件队列里塞 lobby_state，让"恰好收到 N 条"
   的断言变成偶发假红。它的幂等性由 test_lobby_ticker_is_idempotent 单独覆盖。
"""
import types

import pytest

import db
import server

_TAG = 'lobby9'


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _clean_globals(monkeypatch):
    """每个用例前后恢复房间 / 匹配队列 / 大厅三张表，并关掉兜底定时广播。"""
    existing = set(server.room_manager.get_all_rooms())
    server.room_manager.match_queue = []
    monkeypatch.setattr(server, '_LOBBY_TICKER_STARTED', True)
    yield
    for rid in list(server.room_manager.get_all_rooms()):
        if rid not in existing:
            server.room_manager.rooms.pop(rid, None)
    server.room_manager.match_queue = []
    server.lobby_manager._presence.clear()
    server.lobby_manager._members.clear()
    server.lobby_manager._chat.clear()
    server.lobby_manager._last_chat_at.clear()


@pytest.fixture
def sockets():
    """建真实 socket 测试连接（与 test_ranked_match.py 同一套）。"""
    made = []

    def _make(uid=None, name=None):
        http = server.app.test_client()
        if uid:
            with http.session_transaction() as sess:
                sess['user_id'] = uid
                sess['username'] = name or uid
        client = server.socketio.test_client(server.app, flask_test_client=http)
        client.get_received()          # 丢掉 connect 期间的噪音
        made.append(client)
        return client

    yield _make
    for client in made:
        try:
            client.disconnect()
        except Exception:
            pass


def _pick(events, name):
    out = []
    for m in events:
        if m['name'] != name:
            continue
        args = m['args']
        if isinstance(args, dict):
            args = [args]
        out.extend(a for a in (args or ()) if isinstance(a, dict))
    return out


def _recv(client, name):
    return _pick(client.get_received(), name)


def _last(client, name):
    got = _recv(client, name)
    assert got, f'应当收到 {name}，实际一条都没有'
    return got[-1]


def _capture_emit(monkeypatch):
    """直调 handler 时把 server.emit 换成记录器（无请求上下文）。"""
    sent = []

    def fake_emit(event, data, to=None, room=None):
        sent.append({'name': event, 'data': data, 'to': to, 'room': room})

    monkeypatch.setattr(server, 'emit', fake_emit)
    return sent


def _as_request(monkeypatch, sid, uid=None, name=None):
    """把 request / session / join_room / leave_room 换成直调友好的假对象。"""
    monkeypatch.setattr(server, 'request', types.SimpleNamespace(sid=sid))
    monkeypatch.setattr(
        server, 'session',
        types.SimpleNamespace(
            get=lambda k, d=None: (uid if k == 'user_id' else (name if k == 'username' else d))))
    monkeypatch.setattr(server, 'join_room', lambda *a, **k: None)
    monkeypatch.setattr(server, 'leave_room', lambda *a, **k: None)


def _mk_user(prefix=_TAG):
    uid = db.create_user(f'{prefix}{len(server.lobby_manager._presence)}{id(object()) % 100000}',
                         'x' * 12)
    assert uid, '建号失败'
    return uid


# ===========================================================================
# 1. 房间级新状态三件齐（初始化这一件）
# ===========================================================================
def test_room_defaults_are_lobby_safe():
    """★ 新增房间级状态三件齐之一：__init__ 必须初始化 name / public。

    漏了就是 AttributeError（在 build_lobby_state 里炸，症状是"大厅整个打不开"）。
    """
    room = server.GameRoom('lobby-defaults')
    assert room.name == ''
    assert room.public is True, '默认公开是有意的：大厅要能列房间'


def test_create_room_accepts_name_and_visibility(monkeypatch):
    """handle_create_room 的两个新字段：名字清洗截断、public 可置 False。"""
    _as_request(monkeypatch, 'sid-host', uid='u-host', name='房主')
    res = server.handle_create_room({'name': '  ' + 'x' * 40, 'public': False})
    assert res['status'] == 'success'
    room = server.room_manager.get_room(res['room_id'])
    assert room is not None
    assert room.public is False
    assert len(room.name) == server.LOBBY_ROOM_NAME_MAX_LEN, '房间名必须截断'


def test_create_room_without_new_fields_keeps_defaults(monkeypatch):
    """不传新字段时沿用默认（旧的调用点一个都不用改）。"""
    _as_request(monkeypatch, 'sid-host2', uid='u-host2', name='房主')
    res = server.handle_create_room({})
    room = server.room_manager.get_room(res['room_id'])
    assert room.name == ''
    assert room.public is True


# ===========================================================================
# 2. LobbyManager 本体
# ===========================================================================
def test_presence_tracks_connections():
    lm = server.lobby_manager
    lm.add_connection('s1', '小明', 'u1')
    lm.add_connection('s2')
    assert lm.online_count() == 2
    assert lm.remove_connection('s1') is True
    assert lm.remove_connection('s1') is False, '重复移除应当返回 False'
    assert lm.online_count() == 1


def test_name_is_cleaned_and_truncated():
    lm = server.lobby_manager
    lm.add_connection('s1', '  空格名  ')
    lm.add_connection('s2', '')
    lm.add_connection('s3', 'x' * 100)
    rows = lm.presence()
    assert rows['s1']['name'] == '空格名'
    # 名字未知时在线表存空串（update_identity 不许用空串冲掉已有的名字），
    # 展示层的回落发生在 build_lobby_state 里 —— 所以这里两边都断言。
    assert rows['s2']['name'] == ''
    assert len(rows['s3']['name']) == server.LOBBY_NAME_MAX_LEN
    by_key = {p['key']: p['name'] for p in server.build_lobby_state()['players']}
    assert by_key['s2'] == '游客', '展示层必须把空名回落成游客'
    assert by_key['s3'] == 'x' * server.LOBBY_NAME_MAX_LEN


def test_subscribe_is_idempotent():
    lm = server.lobby_manager
    assert lm.subscribe('s1', '甲') is True
    assert lm.subscribe('s1', '甲') is False, '第二次订阅不该重复入表'
    assert lm.member_count() == 1


def test_subscribe_registers_unknown_connection():
    """订阅时连接还没进在线表（测试直调 / 重连换 sid）也要能自愈。"""
    lm = server.lobby_manager
    lm.subscribe('s-unknown', '乙')
    assert lm.online_count() == 1
    assert lm.is_member('s-unknown') is True


def test_unsubscribe_keeps_presence():
    """离开大厅 ≠ 掉线：人还连着，只是不在大厅页面上。"""
    lm = server.lobby_manager
    lm.subscribe('s1', '甲')
    assert lm.unsubscribe('s1') is True
    assert lm.member_count() == 0
    assert lm.online_count() == 1


def test_remove_connection_clears_membership_and_ratelimit():
    lm = server.lobby_manager
    lm.subscribe('s1', '甲')
    lm.chat_allowed('s1')
    lm.remove_connection('s1')
    assert lm.member_count() == 0
    assert lm.online_count() == 0
    assert 's1' not in lm._last_chat_at


def test_lobby_ticker_is_idempotent(monkeypatch):
    """兜底定时广播只启动一次（与 _ensure_reaper 同一套幂等写法）。"""
    calls = []
    monkeypatch.setattr(server, '_LOBBY_TICKER_STARTED', False)
    monkeypatch.setattr(server.socketio, 'start_background_task',
                        lambda fn, *a, **k: calls.append(fn))
    server._ensure_lobby_ticker()
    server._ensure_lobby_ticker()
    assert len(calls) == 1


# ===========================================================================
# 3. build_lobby_state 的形状与 status
# ===========================================================================
def test_lobby_state_shape_when_empty():
    state = server.build_lobby_state()
    assert set(state) == {'ts', 'online_count', 'lobby_count', 'queue', 'players', 'rooms'}
    assert state['players'] == [] and state['rooms'] == []
    assert state['queue'] == {'casual': 0, 'ranked': 0}


def test_lobby_state_never_leaks_user_id():
    """★ 大厅是公共广播：只发 key（sid）与 guest 标记，不发账号 id。"""
    lm = server.lobby_manager
    lm.add_connection('s1', '甲', 'uid-secret')
    lm.subscribe('s1', '甲', 'uid-secret')
    row = server.build_lobby_state()['players'][0]
    assert 'user_id' not in row
    assert row['key'] == 's1'
    assert row['guest'] is False


def test_status_four_states():
    """★ 四态：idle / matching / in_room / in_game。

    in_room 与 in_game **必须分开** —— 建房者一按下「创建房间」就坐在自己那间
    state='waiting' 的房里了，算成"对局中"的话大厅里所有开过房的人永远显示对局中。
    （浏览器工具实测抓到过这个：A 建房后自己那一行写着"对局中"。）
    """
    lm = server.lobby_manager
    lm.add_connection('s-idle', '闲')
    lm.add_connection('s-queue', '排')
    lm.add_connection('s-room', '房')
    lm.add_connection('s-game', '战')
    server.room_manager.add_to_match_queue('s-queue', '排')

    def _room(sid, name, state):
        rid = server.room_manager.create_room()
        room = server.room_manager.get_room(rid)
        room.state = state
        room.players['p-' + sid] = server.Player(
            name=name, ships=[], attacks=[], remaining_ships=0, user_id=None, sid=sid)
        return room

    _room('s-room', '房', 'waiting')
    _room('s-game', '战', 'placing_ships')

    by_key = {p['key']: p['status'] for p in server.build_lobby_state()['players']}
    assert by_key['s-idle'] == 'idle'
    assert by_key['s-queue'] == 'matching'
    assert by_key['s-room'] == 'in_room', '在等待房里等人 ≠ 对局中'
    assert by_key['s-game'] == 'in_game'


def test_matching_beats_in_game():
    """★ 判据顺序：匹配中优先于对局中。

    匹配成功后队列条目立刻被 pop，两者不会同时成立；但先判对局会让
    "刚配到、还没进房"的一瞬显示成空闲。这里直接把两个条件同时摆上，
    锁住优先级。
    """
    lm = server.lobby_manager
    lm.add_connection('s-both', '双')
    server.room_manager.add_to_match_queue('s-both', '双')
    rid = server.room_manager.create_room()
    room = server.room_manager.get_room(rid)
    room.state = 'placing_ships'
    room.players['p1'] = server.Player(name='双', ships=[], attacks=[],
                                       remaining_ships=0, user_id=None, sid='s-both')
    by_key = {p['key']: p['status'] for p in server.build_lobby_state()['players']}
    assert by_key['s-both'] == 'matching'


def test_finished_room_does_not_count_as_in_game():
    """game_over 房里的座位不算"对局中"（否则打完不退出的玩家永远显示对局中）。"""
    lm = server.lobby_manager
    lm.add_connection('s-done', '完')
    rid = server.room_manager.create_room()
    room = server.room_manager.get_room(rid)
    room.state = 'game_over'
    room.players['p1'] = server.Player(name='完', ships=[], attacks=[],
                                       remaining_ships=0, user_id=None, sid='s-done')
    by_key = {p['key']: p['status'] for p in server.build_lobby_state()['players']}
    assert by_key['s-done'] == 'idle'


def test_queue_counts_split_by_mode():
    server.room_manager.add_to_match_queue('s1', '甲', None, 'casual')
    server.room_manager.add_to_match_queue('s2', '乙', 'u2', 'ranked')
    server.room_manager.add_to_match_queue('s3', '丙', 'u3', 'ranked')
    assert server.build_lobby_state()['queue'] == {'casual': 1, 'ranked': 2}


def test_players_capped_at_max(monkeypatch):
    monkeypatch.setattr(server, 'LOBBY_MAX_PLAYERS', 3)
    lm = server.lobby_manager
    for i in range(6):
        lm.add_connection(f's{i}', f'玩家{i}')
    assert len(server.build_lobby_state()['players']) == 3


# ===========================================================================
# 4. 房间列表的四条可见规则
# ===========================================================================
def _make_waiting_room(sid, host='房主', public=True, name=''):
    rid = server.room_manager.create_room()
    room = server.room_manager.get_room(rid)
    room.name = name
    room.public = public
    room.players['host'] = server.Player(name=host, ships=[], attacks=[],
                                         remaining_ships=0, user_id=None, sid=sid)
    server.lobby_manager.add_connection(sid, host)
    return room


def test_room_list_shows_waiting_public_room():
    room = _make_waiting_room('s-host', host='小明', name='小明的房')
    rooms = server.build_lobby_state()['rooms']
    assert len(rooms) == 1
    assert rooms[0]['room_id'] == room.id
    assert rooms[0]['name'] == '小明的房'
    assert rooms[0]['host'] == '小明'
    assert rooms[0]['players'] == 1 and rooms[0]['capacity'] == 2


def test_room_list_falls_back_to_host_name_when_unnamed():
    _make_waiting_room('s-host2', host='无名房主')
    assert server.build_lobby_state()['rooms'][0]['name'] == '无名房主' + '的房间'


def test_started_room_is_not_listed():
    room = _make_waiting_room('s-host3')
    room.state = 'attacking'
    assert server.build_lobby_state()['rooms'] == []


def test_ai_room_is_not_listed():
    rid = server.room_manager.create_ai_room('s-ai', '人类', None, 'normal')
    room = server.room_manager.get_room(rid)
    room.players['s-ai'] = server.Player(name='人类', ships=[], attacks=[],
                                         remaining_ships=0, user_id=None, sid='s-ai')
    server.lobby_manager.add_connection('s-ai', '人类')
    assert server.build_lobby_state()['rooms'] == [], '人机房不该出现在大厅'


def test_private_room_is_not_listed():
    _make_waiting_room('s-host4', public=False)
    assert server.build_lobby_state()['rooms'] == []


def test_full_room_is_not_listed():
    room = _make_waiting_room('s-host5')
    room.players['guest'] = server.Player(name='客人', ships=[], attacks=[],
                                          remaining_ships=0, user_id=None, sid='s-guest')
    assert server.build_lobby_state()['rooms'] == [], '满员房不该还在列表里'


def test_room_with_offline_host_is_not_listed():
    """★ 最容易漏的一条：房主关掉标签页后房间还要在内存里躺 1 小时。"""
    _make_waiting_room('s-host6')
    assert len(server.build_lobby_state()['rooms']) == 1
    server.lobby_manager.remove_connection('s-host6')
    assert server.build_lobby_state()['rooms'] == [], '房主离线后不该还挂着这个房'


# ===========================================================================
# 5. 公屏聊天
# ===========================================================================
def test_chat_drops_blank_and_clamps_length():
    lm = server.lobby_manager
    assert lm.add_chat('s1', '甲', '   ') is None
    assert lm.add_chat('s1', '甲', '') is None
    item = lm.add_chat('s1', '甲', 'x' * 500)
    assert len(item['message']) == server.LOBBY_CHAT_MAX_LEN


def test_chat_rate_limit():
    lm = server.lobby_manager
    assert lm.chat_allowed('s1', now=1000.0) is True
    assert lm.chat_allowed('s1', now=1000.1) is False
    assert lm.chat_allowed('s1', now=1000.0 + server.LOBBY_CHAT_MIN_INTERVAL + 0.01) is True


def test_chat_seq_is_monotonic_and_unique():
    """★ 每条公屏消息带一个单调序号：前端靠它做"这条我有没有"的去重。

    没有它就只能靠文案/时间猜，而**补发的历史与实时推送是会重叠的** ——
    第一版前端用"清空重铺"处理历史，实测把自己刚发的那条冲掉了
    （tools/lobby_check.mjs 里有一条专门的回归断言）。
    """
    lm = server.lobby_manager
    a = lm.add_chat('s1', '甲', '一')
    b = lm.add_chat('s2', '乙', '二')
    assert b['seq'] > a['seq']
    assert len({m['seq'] for m in lm.recent_chat()}) == 2


def test_chat_backlog_is_capped():
    lm = server.lobby_manager
    for i in range(server.LOBBY_CHAT_BACKLOG + 12):
        lm.add_chat('s1', '甲', f'消息{i}')
    backlog = lm.recent_chat()
    assert len(backlog) == server.LOBBY_CHAT_BACKLOG
    assert backlog[-1]['message'] == f'消息{server.LOBBY_CHAT_BACKLOG + 11}'


def test_chat_send_requires_membership(monkeypatch):
    _as_request(monkeypatch, 's-outsider')
    _capture_emit(monkeypatch)
    res = server.handle_lobby_chat_send({'message': '我还没进大厅'})
    assert res['status'] == 'error'
    assert server.lobby_manager.recent_chat() == []


def test_chat_send_broadcasts_to_lobby_room(monkeypatch):
    server.lobby_manager.subscribe('s1', '甲')
    sent = _capture_emit(monkeypatch)
    _as_request(monkeypatch, 's1')
    res = server.handle_lobby_chat_send({'message': '大家好'})
    assert res['status'] == 'success'
    chats = [m for m in sent if m['name'] == 'lobby_chat']
    assert len(chats) == 1
    assert chats[0]['to'] == server.LOBBY_ROOM, '公屏必须发给大厅房间，不是回发给自己'
    assert chats[0]['data']['message'] == '大家好'
    assert chats[0]['data']['key'] == 's1'


def test_chat_rate_limited_emits_error(monkeypatch):
    server.lobby_manager.subscribe('s1', '甲')
    server.lobby_manager.chat_allowed('s1')          # 先占掉这一秒的额度
    sent = _capture_emit(monkeypatch)
    _as_request(monkeypatch, 's1')
    res = server.handle_lobby_chat_send({'message': '又是我'})
    assert res['status'] == 'error'
    assert any(m['name'] == 'error' for m in sent), '被限流必须给玩家提示，不能静默吞掉'


# ===========================================================================
# 6. 真实 socket 层
# ===========================================================================
def test_subscribe_handshake(sockets):
    client = sockets()
    client.emit('lobby_subscribe', {'player_name': '游客甲'})
    # ⚠️ get_received() 会**清空**队列，三个断言必须共用同一份 events
    events = client.get_received()
    hello = _pick(events, 'lobby_hello')[-1]
    assert hello['key'], 'lobby_hello 必须带身份键'
    assert hello['name'] == '游客甲'
    assert hello['guest'] is True
    assert _pick(events, 'lobby_chat_history'), '订阅时必须补发公屏历史'
    state = _pick(events, 'lobby_state')[-1]
    assert state['lobby_count'] == 1
    assert [p['key'] for p in state['players']] == [hello['key']]


def test_state_broadcast_only_reaches_members(sockets):
    """★ 只有真的站在大厅页面上的连接才收推送（否则对局中也会被大厅广播打扰）。"""
    a = sockets()
    b = sockets()
    a.emit('lobby_subscribe', {'player_name': '甲'})
    _last(a, 'lobby_state')
    a.get_received()
    b.get_received()
    # b 没订阅，a 再订阅一次触发广播
    a.emit('lobby_subscribe', {'player_name': '甲'})
    assert _recv(a, 'lobby_state'), '成员应当收到广播'
    assert _recv(b, 'lobby_state') == [], '非成员不该收到大厅广播'


def test_unsubscribe_stops_updates(sockets):
    a = sockets()
    b = sockets()
    a.emit('lobby_subscribe', {'player_name': '甲'})
    b.emit('lobby_subscribe', {'player_name': '乙'})
    a.get_received()
    a.emit('lobby_unsubscribe', {})
    a.get_received()
    b.emit('lobby_subscribe', {'player_name': '乙'})     # 触发一次广播
    assert _recv(a, 'lobby_state') == [], '退订后不该再收到状态'


def test_online_count_endpoint_matches_presence(sockets):
    a = sockets()
    b = sockets()
    with server.app.test_client() as http:
        payload = http.get('/api/online_count').get_json()
    assert payload['online_count'] == server.lobby_manager.online_count()
    assert payload['online_count'] >= 2


def test_lobby_create_room_appears_in_other_member_list(sockets):
    a = sockets()
    b = sockets()
    b.emit('lobby_subscribe', {'player_name': '看客'})
    b.get_received()
    a.emit('lobby_subscribe', {'player_name': '房主'})
    a.emit('lobby_create_room', {'name': '来打一局', 'public': True})
    state = _last(b, 'lobby_state')
    rooms = state['rooms']
    assert len(rooms) == 1, f'建房后应当出现在大厅列表里，实际 {rooms}'
    assert rooms[0]['name'] == '来打一局'
    assert rooms[0]['host'] == '房主'


def test_lobby_create_room_private_is_hidden(sockets):
    a = sockets()
    b = sockets()
    b.emit('lobby_subscribe', {'player_name': '看客'})
    b.get_received()
    a.emit('lobby_subscribe', {'player_name': '房主'})
    a.emit('lobby_create_room', {'name': '私密房', 'public': False})
    assert _last(b, 'lobby_state')['rooms'] == [], '私密房只认房间号，不该上大厅榜'


def test_lobby_create_room_registers_real_room(sockets):
    """大厅建房必须真的建出房间（`lobby_create_room` 复用 create_room，不是自己写一份）。

    ⚠️ socketio.test_client 的 emit **不支持 ack 回调**，所以这里不看返回值，
    直接查服务端状态 + 广播出去的状态 —— 反而更接近真实（ack 丢了也不影响房间建出来）。
    """
    a = sockets()
    a.emit('lobby_subscribe', {'player_name': '房主'})
    a.get_received()
    a.emit('lobby_create_room', {'name': '大厅开的房', 'public': True})
    events = a.get_received()
    state = _pick(events, 'lobby_state')[-1]
    assert state['rooms'], '建房后自己的列表里就该有这一间'
    room_id = state['rooms'][0]['room_id']
    room = server.room_manager.get_room(room_id)
    assert room is not None
    assert room.name == '大厅开的房'
    assert list(room.players.values())[0].name == '房主'


def test_chat_broadcast_and_identity_key(sockets):
    a = sockets()
    b = sockets()
    a.emit('lobby_subscribe', {'player_name': '甲'})
    b.emit('lobby_subscribe', {'player_name': '乙'})
    a.get_received()
    b.get_received()
    a.emit('lobby_chat_send', {'message': '有人吗'})
    msg_a = _last(a, 'lobby_chat')
    msg_b = _last(b, 'lobby_chat')
    assert msg_a['message'] == msg_b['message'] == '有人吗'
    assert msg_a['name'] == '甲'
    # 身份键两边都拿到的是**同一条消息**的发送者 key，前端据此标"我"
    assert msg_a['key'] == msg_b['key']


def test_match_marks_player_as_matching(sockets):
    a = sockets()
    a.emit('lobby_subscribe', {'player_name': '甲'})
    a.get_received()
    a.emit('find_match', {'player_name': '甲', 'mode': 'casual'})
    state = _last(a, 'lobby_state')
    me = [p for p in state['players'] if p['status'] != 'idle']
    assert me, f'入队后应当有人的 status 变成 matching，实际 {state["players"]}'
    assert me[0]['status'] == 'matching'
    assert state['queue']['casual'] == 1
