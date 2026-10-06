
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






# ===========================================================================
# 2. LobbyManager 本体
# ===========================================================================














# ===========================================================================
# 3. build_lobby_state 的形状与 status
# ===========================================================================


def test_lobby_state_never_leaks_user_id():
    """★ 大厅是公共广播：只发 key（sid）与 guest 标记，不发账号 id。"""
    lm = server.lobby_manager
    lm.add_connection('s1', '甲', 'uid-secret')
    lm.subscribe('s1', '甲', 'uid-secret')
    players = server.build_lobby_state()['players']
    row = next(player for player in players if player['key'] == 's1')
    assert 'user_id' not in row
    assert row['key'] == 's1'
    assert row['guest'] is False












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
















# ===========================================================================
# 5. 公屏聊天
# ===========================================================================








def test_chat_send_requires_membership(monkeypatch):
    _as_request(monkeypatch, 's-outsider')
    _capture_emit(monkeypatch)
    res = server.handle_lobby_chat_send({'message': '我还没进大厅'})
    assert res['status'] == 'error'
    assert server.lobby_manager.recent_chat() == []






# ===========================================================================
# 6. 真实 socket 层
# ===========================================================================


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



















# ===========================================================================
# 7. 「连点创建房间 → 大厅堆出一串同名房」（2026-09-18 实测缺陷的回归）
# ===========================================================================
# 缺陷原貌（作者截图）：大厅房间列表挂着 **7 间一模一样的房**（同名、同房主、都是 1/2）。
# 实测复现确认「一次点击 = 一间房」（ack 正常、界面也正常跳到自定义房界面），
# 所以**不是**双击或重复绑定 —— 而是旧房永远不会消失：
#   · 等待房的回收 TTL 是 1 小时（_WAITING_ROOM_TTL）；
#   · 大厅的可见规则只要求「房主仍在线」，而房主就是他自己，当然一直在线上。
# 两条规则各自都"没错"，合起来却把 7 间房全留在了榜上。










# ===========================================================================
# 8. 解散房间（等待房此前没有任何主动出口）
# ===========================================================================
