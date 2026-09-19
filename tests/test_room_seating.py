# -*- coding: utf-8 -*-
"""自定义房的**座位**语义（2026-09-19 双浏览器实测挖出来的缺陷）。

`room.players` 的 key 是 `session['user_id']`（游客是 sid），而容量判据曾经是
`len(room.players) >= 2` —— 于是**同一个账号的两条连接**只会占**一个 key**：
长度永远到不了 2 → 那间房**永远开不了局**，而每次 `join_room` 的 ack 都是 `success`、
页面上零提示。症状与用户报的"好友约战开不了局"一模一样（两边都停在布船屏互相等）。

这两条用例把语义钉死：**同一身份 = 同一个座位**（换标签页/刷新只是换连接），
**另一个账号**进来才占第二个座位、才推进 `placing_ships`。
"""
import os
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import db  # noqa: E402
import server  # noqa: E402


def _mk_user(prefix='seat'):
    uid = db.create_user(f'{prefix}_{uuid.uuid4().hex[:8]}', 'x' * 12)
    assert uid, '建号失败'
    return uid


def _client(uid=None, name=None):
    """一条已登录的 socket 测试连接（session 带 user_id，`connect` handler 才认）。

    ⚠️ 座位的显示名取的是 `session['username']`（`handle_join_room` 的取值顺序），
    所以这里要把显示名也放进 session —— 只放进 payload 的话服务端根本看不到它。
    """
    http = server.app.test_client()
    if uid:
        with http.session_transaction() as sess:
            sess['user_id'] = uid
            sess['username'] = name or uid
    c = server.socketio.test_client(server.app, flask_test_client=http)
    c.get_received()          # 丢掉 connect 期间的噪音
    return c


def _game_state_of(client):
    """从这条连接收到的 `game_state` 里挑出 (player_name, opponent_name)。"""
    for ev in client.get_received():
        if ev['name'] == 'game_state':
            a = ev['args'][0]
            return (a.get('player_name'), a.get('opponent_name'))
    return None


def test_same_account_two_tabs_take_one_seat_and_another_account_still_starts_it():
    """★ 同一账号两条连接只占一个座位；另一个账号进来照样能开局。"""
    a, b = _mk_user(), _mk_user()
    room_id = server.room_manager.create_room()
    try:
        c1 = _client(a, '甲')
        c1.emit('join_room', {'room_id': room_id, 'player_name': '甲'})
        c2 = _client(a, '甲')          # 同一个账号的**第二个标签页**
        c2.emit('join_room', {'room_id': room_id, 'player_name': '甲'})

        room = server.room_manager.get_room(room_id)
        assert list(room.players) == [str(a)], f'同一身份不该占两个座位：{list(room.players)}'
        assert room.state == 'waiting', '只有一个人（同一身份的两次连接）时不该推进阶段'

        c3 = _client(b, '乙')
        c3.emit('join_room', {'room_id': room_id, 'player_name': '乙'})
        room = server.room_manager.get_room(room_id)
        assert sorted(room.players) == sorted([str(a), str(b)]), room.players
        assert room.state == 'placing_ships', '两个**不同身份**的人到齐就该推进到布船'
        # ⚠️ 座位上的连接会被换成**最后进来的那条**（c2）：这是有意的 —— 刷新页面时
        #    sid 会变，不接管的话"刷新之后收不到任何事件"。所以 game_state 应当发给 c2。
        assert _game_state_of(c2) == ('甲', '乙'), '接管座位的第二条连接应当收到 game_state 且对手是乙'
        assert _game_state_of(c3) == ('乙', '甲'), '乙那侧也应当收到 game_state 且对手是甲'
    finally:
        server.room_manager.delete_room(room_id)


def test_same_account_rejoin_after_the_match_started_is_refused():
    """局已开打之后，同一身份的再连接**不走座位复用**（那时该走重连链路）→ 回「房间已满」。"""
    a, b = _mk_user(), _mk_user()
    room_id = server.room_manager.create_room()
    try:
        ca = _client(a)
        ca.emit('join_room', {'room_id': room_id, 'player_name': '甲'})
        cb = _client(b)
        cb.emit('join_room', {'room_id': room_id, 'player_name': '乙'})
        room = server.room_manager.get_room(room_id)
        assert room.state == 'placing_ships'

        c3 = _client(a)          # 甲又开了一个标签页，但局已经开了
        c3.emit('join_room', {'room_id': room_id, 'player_name': '甲'})
        room = server.room_manager.get_room(room_id)
        # 座位没被改动、房也没被搞乱（具体回什么文案由服务端定，这里只钉"没有新增/替换座位"）
        assert sorted(room.players) == sorted([str(a), str(b)]), room.players
        assert room.state == 'placing_ships', '开打的局不该因为一次重连被推回别的阶段'
    finally:
        server.room_manager.delete_room(room_id)


def test_joining_another_room_drops_my_own_lonely_waiting_room():
    """★ 我独自占着的旧等待房会在进新房时被清掉（不留僵尸房、也不让我同时占两间）。

    ⚠️ 守的是一条真实路径：邀战让**双方都进房**，所以"我在自己那间等待房里，
    又接受了别人的邀请"很常见；旧房若不清就成了没人管的僵尸房（TTL 一小时 + 挂着大厅）。
    房里**还有别人**时不许清（有人在等），另有一条断言钉这一点。
    """
    a, b, c = _mk_user(), _mk_user(), _mk_user()
    old_room = server.room_manager.create_room()
    new_room = server.room_manager.create_room()
    try:
        ca = _client(a, '甲')
        ca.emit('join_room', {'room_id': old_room, 'player_name': '甲'})
        assert server.room_manager.get_room(old_room) is not None

        # 甲又进了另一间房 → 旧那间只有他自己 → 应当被清掉
        ca2 = _client(a, '甲')
        ca2.emit('join_room', {'room_id': new_room, 'player_name': '甲'})
        assert server.room_manager.get_room(old_room) is None, '只有自己一个人的旧等待房应当被清掉'
        assert server.room_manager.get_room(new_room) is not None
    finally:
        server.room_manager.delete_room(old_room)
        server.room_manager.delete_room(new_room)


def test_joining_another_room_keeps_a_waiting_room_where_someone_else_waits():
    """★ 旧房里**还有别人在等**时不许清（不替玩家做决定）。"""
    a, b, c = _mk_user(), _mk_user(), _mk_user()
    busy_room = server.room_manager.create_room()
    other_room = server.room_manager.create_room()
    try:
        ca = _client(a, '甲')
        ca.emit('join_room', {'room_id': busy_room, 'player_name': '甲'})
        cb = _client(b, '乙')                      # 乙在等甲 → 这间房不再是"只有甲自己"
        cb.emit('join_room', {'room_id': busy_room, 'player_name': '乙'})
        room = server.room_manager.get_room(busy_room)
        assert room.state == 'placing_ships', '两人到齐应当已推进（用的是真实入房链路）'

        # 甲（已在 busy_room 里，且房已开打）又去 join 另一间 → 那间**不该**被清
        cc = _client(a, '甲')
        cc.emit('join_room', {'room_id': other_room, 'player_name': '甲'})
        assert server.room_manager.get_room(busy_room) is not None, '房里还有别人在等，不许清'
    finally:
        server.room_manager.delete_room(busy_room)
        server.room_manager.delete_room(other_room)
