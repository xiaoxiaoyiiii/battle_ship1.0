# -*- coding: utf-8 -*-
"""第 4 批「局内快捷语 / 表情」回归测试（契约见 `docs/BATCH_2_3_4_PLAN.md` §4）。

分四段：
  1. 数据表本身（`quick_chat.py`）—— 作者点名的那句**逐字**校验在这里钉死；
  2. 频率纯函数 `check_rate()` 的全部边界；
  3. `GET /api/quick_chat`（**未登录也要 200**，游客也能对局）；
  4. socket 事件 `quick_chat`（真实 test_client 双端）：白名单 / 频率 / 身份 / 广播 /
     日志，以及最要紧的一条 —— **发送前后回合状态一个字节都不许变**。

第 4 段的写法说明：用 `socketio.test_client(app, flask_test_client=<带 session 的 http client>)`
（`_identity_ok` 靠 session['user_id'] 认人），再用 `server.enter_room` 把测试连接
放进 socketio 房间 —— 这样 `emit(..., room=room.id)` 的**真实性**也一起被验到了
（只 monkeypatch `emit` 记账的话，"广播给谁"这件事根本没测）。
"""

import copy
import time

import pytest

import quick_chat
import server
from server import GameRoom, Player, PlayerShip, Position, room_manager

A, B = 'u1', 'u2'          # 自定义房约定：key = 登录用户的 user_id
REQUIRED_ID = 'hurry_flowers'
REQUIRED_TEXT = '快点儿吧，我等的花都谢了'

# 计划 §4.3 表里的全部条目（顺序即界面顺序）。这一份是**期望值**，
# 与 quick_chat.QUICK_CHAT 是两份独立数据 —— 拿同一份去比会永远相等。
PLANNED = [
    ('hi', '开局', '你好，开打吧！'),
    ('lets_go', '开局', '来，先手我拿走了'),
    ('hurry_flowers', '催促', '快点儿吧，我等的花都谢了'),
    ('think_fast', '催促', '想好了没呀？'),
    ('nice_shot', '交手', '打得漂亮！'),
    ('oops', '交手', '哎呀，手滑了'),
    ('lucky', '交手', '这运气也没谁了'),
    ('almost', '交手', '就差一点'),
    ('watch_this', '交手', '看我这手'),
    ('ouch', '被击沉', '我的船！'),
    ('surrender_soon', '投降前', '我快撑不住了…'),
    ('gg', '结束', 'GG，打得好'),
    ('rematch', '结束', '再来一局？'),
    ('thanks', '结束', '多谢指教'),
]
PLANNED_IDS = [row[0] for row in PLANNED]


# ===========================================================================
# 1. 数据表：单一来源 + 作者点名的那句
# ===========================================================================
























# ===========================================================================
# 2. check_rate：窗口 3 条 + 同句不重复
# ===========================================================================




def test_fourth_in_window_rejected():
    now = 1000.0
    recent = [now - 0.3, now - 0.2, now - 0.1]
    ok, reason = quick_chat.check_rate(recent, now, None, 'hi')
    assert ok is False
    assert reason and '10' in reason and '3' in reason, reason
















# ===========================================================================
# 3. GET /api/quick_chat：游客也要能拿到
# ===========================================================================
@pytest.fixture
def api_client():
    return server.app.test_client()








# ===========================================================================
# 4. socket 事件 quick_chat（真实 test_client，双端）
# ===========================================================================
def _ship(y):
    return PlayerShip(positions=[Position(i, y) for i in range(6)], hits=[])


def _make_room(room_id='qc-room'):
    r = GameRoom(room_id)
    r.players[A] = Player(name='甲', ships=[_ship(0)], attacks=[], remaining_ships=6,
                          sid='sid-a', user_id=A)
    r.players[B] = Player(name='乙', ships=[_ship(5)], attacks=[], remaining_ships=6,
                          sid='sid-b', user_id=B)
    r.state = 'attacking'
    r.current_attacker = A
    r.current_phase = 'battle'
    r.attack_order = [A, B]
    r.attacks_remaining = 6
    r.round = 3
    room_manager.rooms[r.id] = r
    return r


@pytest.fixture
def room():
    r = _make_room()
    yield r
    room_manager.rooms.pop(r.id, None)
    room_manager.match_queue = []


@pytest.fixture
def socket_for(room):
    """建一个已登录的 socket 测试连接；默认把它放进房间（真实广播才收得到）。

    `enter=False` 用于造一个"连着但不在这个房间"的旁观者 —— 用来证明
    `room=room.id` 的广播真的是有边界的，而不是"谁都能收到"。
    """
    made = []

    def _make(uid, enter=True):
        http = server.app.test_client()
        with http.session_transaction() as sess:
            sess['user_id'] = uid
            sess['username'] = uid
        client = server.socketio.test_client(server.app, flask_test_client=http)
        if enter:
            sid = server.socketio.server.manager.sid_from_eio_sid(client.eio_sid, '/')
            server.socketio.server.enter_room(sid, room.id)
        client.get_received()          # 丢掉 connect 期间的噪音
        made.append(client)
        return client

    yield _make
    for client in made:
        try:
            client.disconnect()
        except Exception:              # noqa: BLE001 - 清理失败不该让用例变红
            pass


def _send(client, room, pid, msg_id):
    return client.emit('quick_chat',
                       {'room_id': room.id, 'player_id': pid, 'msg_id': msg_id},
                       callback=True)


def _recv(client, name):
    return [m['args'][0] for m in client.get_received() if m['name'] == name]


def _fingerprint(room):
    """回合状态的指纹：发快捷语前后必须一字不差。"""
    return {
        'attacks_remaining': room.attacks_remaining,
        'state': room.state,
        'current_phase': room.current_phase,
        'current_attacker': room.current_attacker,
        'round': room.round,
        'winner': room.winner,
        'chain_len': len(room.chain),
        'chain_waiting': room.chain_waiting,
        'chain_window': room.chain_window,
        'chain_passes': room.chain_passes,
        'magic_temp_data': copy.deepcopy(room.magic_temp_data),
        'hand_a': len(room.players[A].magic_hand),
        'attacks_a': len(room.players[A].attacks),
        'ships_a': len(room.players[A].ships),
        'ships_b': len(room.players[B].ships),
    }




def test_outsider_not_in_room_receives_nothing(room, socket_for):
    """广播是有边界的：连着的、但不在这个房间里的连接收不到。

    这条同时是上面"双方都收到"用例的**可信度证据** —— 证明 test_client 的
    收件队列真的按 socketio 房间投递，而不是谁都能收到。
    """
    ca = socket_for(A)
    outsider = socket_for('u3', enter=False)
    assert _send(ca, room, A, 'hi')['status'] == 'success'
    assert _recv(outsider, 'quick_chat') == []
    assert _recv(outsider, 'game_log') == []




def test_rejected_whitelist_is_not_broadcast_and_not_logged(room, socket_for):
    """★ 白名单外的 msg_id：报错、不广播、不写日志。"""
    ca, cb = socket_for(A), socket_for(B)
    before_logs = len(room.game_logs)
    ack = _send(ca, room, A, 'hack_not_in_whitelist')
    assert ack['status'] == 'error'
    assert _recv(cb, 'quick_chat') == []
    assert len(room.game_logs) == before_logs
    # 失败原因必须明确发出去，不许静默 return
    assert [e['message'] for e in _recv(ca, 'error')]






def test_two_players_have_independent_quotas(room, socket_for):
    """频率按玩家记账：A 连点不该把 B 的嘴也堵上。"""
    ca, cb = socket_for(A), socket_for(B)
    for mid in ('hi', 'lets_go', 'nice_shot'):
        _send(ca, room, A, mid)
    assert _send(ca, room, A, 'oops')['status'] == 'error'
    assert _send(cb, room, B, 'oops')['status'] == 'success'






def test_forged_player_id_rejected(room, socket_for):
    """★ 拿别人的 player_id 发（冒名）：报错且不广播。"""
    ca, cb = socket_for(A), socket_for(B)
    ack = ca.emit('quick_chat', {'room_id': room.id, 'player_id': B, 'msg_id': 'hi'},
                  callback=True)
    assert ack['status'] == 'error'
    assert _recv(cb, 'quick_chat') == []
    assert room.quick_chat_recent.get(B, []) == []




def test_missing_or_malformed_payload_rejected_without_crash(room, socket_for):
    """空载荷 / 垃圾载荷都要报错返回，不许抛 AttributeError 把 handler 打崩。"""
    ca = socket_for(A)
    for payload in (None, {}, 'hi', ['hi'], 42):
        ack = ca.emit('quick_chat', payload, callback=True)
        assert ack['status'] == 'error', f'载荷 {payload!r} 应被拒绝'
        assert ack['message']




# ===========================================================================
# 5. 房间级频率状态（第 2 批的硬规矩：__init__ 初始化 + 消费点 + 回归测试）
# ===========================================================================
