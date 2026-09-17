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
def test_required_line_is_verbatim():
    """★ 作者点名的那句必须逐字一致（一个字、一个标点都不能错）。"""
    item = quick_chat.by_id(REQUIRED_ID)
    assert item is not None
    assert item['text'] == REQUIRED_TEXT
    # 逐字符再钉一遍：全角逗号 + 结尾没有"了"以外的尾巴
    assert item['text'] == '快点儿吧，我等的花都谢了'
    assert len(item['text']) == 12, '字数变了说明这句被改过'
    assert '，' in item['text'] and item['text'].count('，') == 1


def test_required_line_is_in_the_table_and_catalog():
    raw = [m for m in quick_chat.QUICK_CHAT if m['id'] == REQUIRED_ID]
    assert len(raw) == 1, '不能有两条同 id'
    assert raw[0]['text'] == REQUIRED_TEXT
    cat = [m for m in quick_chat.catalog() if m['id'] == REQUIRED_ID]
    assert cat and cat[0]['text'] == REQUIRED_TEXT


def test_table_matches_frozen_plan_exactly():
    """整张表（id / group / 文案 / 顺序）与计划 §4.3 完全一致。"""
    assert [(m['id'], m['group'], m['text']) for m in quick_chat.QUICK_CHAT] == PLANNED


def test_table_ids_are_unique():
    assert len(set(PLANNED_IDS)) == len(PLANNED_IDS)
    assert len(quick_chat.QUICK_CHAT) == len(PLANNED)


def test_texts_are_unique():
    texts = [m['text'] for m in quick_chat.QUICK_CHAT]
    assert len(set(texts)) == len(texts), '重复文案在界面上分不出来'


def test_every_item_has_three_non_empty_fields():
    for m in quick_chat.QUICK_CHAT:
        assert set(m) == {'id', 'group', 'text'}, m
        assert all(isinstance(m[k], str) and m[k].strip() for k in m), m


def test_groups_constant_is_the_frozen_order():
    assert quick_chat.GROUPS == ['开局', '催促', '交手', '被击沉', '投降前', '结束']


def test_every_group_used_and_no_unknown_group():
    used = {m['group'] for m in quick_chat.QUICK_CHAT}
    assert used == set(quick_chat.GROUPS), f'有分组没条目或有条目没分组: {used}'


def test_table_order_follows_group_order():
    """条目顺序必须按 GROUPS 的顺序排（界面直接顺序渲染，乱序会分组重复出现）。"""
    seen = [quick_chat.GROUPS.index(m['group']) for m in quick_chat.QUICK_CHAT]
    assert seen == sorted(seen), '分组顺序在表里被打乱了'


def test_catalog_shape_is_only_id_group_text():
    for m in quick_chat.catalog():
        assert set(m) == {'id', 'group', 'text'}


def test_catalog_order_matches_table_order():
    assert [m['id'] for m in quick_chat.catalog()] == [m['id'] for m in quick_chat.QUICK_CHAT]


def test_catalog_and_by_id_return_copies():
    """返回副本：调用方改返回值不该污染这张常量表（否则"单一来源"会当场漂移）。"""
    quick_chat.catalog()[0]['text'] = '被改了'
    quick_chat.by_id('hi')['text'] = '又被改了'
    assert quick_chat.by_id('hi')['text'] == '你好，开打吧！'
    assert quick_chat.catalog()[0]['text'] == '你好，开打吧！'


@pytest.mark.parametrize('msg_id', ['hurry_flowers', 'hi', 'gg'])
def test_by_id_found(msg_id):
    assert quick_chat.by_id(msg_id)['id'] == msg_id


@pytest.mark.parametrize('msg_id', ['', 'nope', 'HURRY_FLOWERS', 'hi ', None, 123, ['hi'], {'id': 'hi'}])
def test_by_id_missing_returns_none(msg_id):
    assert quick_chat.by_id(msg_id) is None


@pytest.mark.parametrize('msg_id,expected', [
    ('hi', True), ('hurry_flowers', True), ('', False), ('nope', False),
    (None, False), (0, False), (['hi'], False), ({'hi'}, False),
])
def test_is_valid(msg_id, expected):
    assert quick_chat.is_valid(msg_id) is expected


def test_is_valid_never_raises_on_unhashable():
    """非字符串直接 false，不能因为拿 list 去查 dict 而抛 TypeError。"""
    assert quick_chat.is_valid(['hi']) is False
    assert quick_chat.by_id(['hi']) is None


# ===========================================================================
# 2. check_rate：窗口 3 条 + 同句不重复
# ===========================================================================
def test_rate_constants():
    assert quick_chat.WINDOW_SECONDS == 10
    assert quick_chat.MAX_PER_WINDOW == 3


@pytest.mark.parametrize('sent', [0, 1, 2])
def test_first_three_pass(sent):
    now = 1000.0
    recent = [now - 0.5 * i for i in range(1, sent + 1)]
    ok, reason = quick_chat.check_rate(recent, now, None, 'hi')
    assert ok is True
    assert reason == '', '通过时 reason 必须是空串'


def test_fourth_in_window_rejected():
    now = 1000.0
    recent = [now - 0.3, now - 0.2, now - 0.1]
    ok, reason = quick_chat.check_rate(recent, now, None, 'hi')
    assert ok is False
    assert reason and '10' in reason and '3' in reason, reason


def test_window_slides_and_recovers():
    """三条都滑出窗口后必须能再发（否则一次连点会被永久封口）。"""
    now = 1000.0
    recent = [now - 12, now - 11, now - 10.5]
    ok, reason = quick_chat.check_rate(recent, now, None, 'hi')
    assert ok is True, reason


def test_timestamp_exactly_at_window_edge_is_outside():
    """窗口边界：now - t == WINDOW_SECONDS 算窗口外（严格小于 10 才计数）。"""
    now = 1000.0
    assert quick_chat.check_rate([now - 10, now - 10, now - 10], now, None, 'hi')[0] is True
    assert quick_chat.check_rate([now - 9.9, now - 9.9, now - 9.9], now, None, 'hi')[0] is False


def test_many_old_timestamps_do_not_block():
    now = 1000.0
    recent = [now - 60 - i for i in range(50)]
    assert quick_chat.check_rate(recent, now, None, 'hi')[0] is True


def test_duplicate_same_id_within_window_rejected():
    now = 1000.0
    ok, reason = quick_chat.check_rate([], now, {'id': 'hi', 'ts': now - 3}, 'hi')
    assert ok is False
    assert '重复' in reason, reason


def test_duplicate_same_id_after_window_allowed():
    now = 1000.0
    assert quick_chat.check_rate([], now, {'id': 'hi', 'ts': now - 11}, 'hi')[0] is True
    assert quick_chat.check_rate([], now, {'id': 'hi', 'ts': now - 10}, 'hi')[0] is True


def test_different_id_unaffected_by_last():
    now = 1000.0
    assert quick_chat.check_rate([], now, {'id': 'hi', 'ts': now - 0.5}, 'gg')[0] is True


def test_last_id_only_blocks_that_exact_id():
    """同一句的判定必须严格比 id —— 前缀/大小写不同不算同一句。"""
    now = 1000.0
    assert quick_chat.check_rate([], now, {'id': 'hi', 'ts': now}, 'hi2')[0] is True
    assert quick_chat.check_rate([], now, {'id': 'hi', 'ts': now}, 'HI')[0] is True


def test_bare_string_last_id_is_fail_closed():
    """只有 id、没有 ts 时无法证明窗口已过 → 保守拒绝同 id。"""
    now = 1000.0
    assert quick_chat.check_rate([], now, 'hi', 'hi')[0] is False
    assert quick_chat.check_rate([], now, 'hi', 'gg')[0] is True


def test_tuple_last_id_accepted():
    now = 1000.0
    assert quick_chat.check_rate([], now, ('hi', now - 1), 'hi')[0] is False
    assert quick_chat.check_rate([], now, ('hi', now - 11), 'hi')[0] is True


def test_rate_reasons_are_distinct_and_clear():
    now = 1000.0
    rate_reason = quick_chat.check_rate([now, now, now], now, None, 'hi')[1]
    dup_reason = quick_chat.check_rate([], now, {'id': 'hi', 'ts': now}, 'hi')[1]
    assert rate_reason and dup_reason and rate_reason != dup_reason


@pytest.mark.parametrize('recent', [None, [], (), [None], ['x'], [None, 'x', 1.0]])
def test_rate_tolerates_empty_and_dirty_recent(recent):
    """房间状态脏了也不该 500 —— 脏条目忽略，数字条目照常计数。"""
    ok, reason = quick_chat.check_rate(recent, 1000.0, None, 'hi')
    assert ok is True, reason


def test_rate_does_not_mutate_inputs():
    now = 1000.0
    recent = [now - 1]
    last = {'id': 'gg', 'ts': now - 1}
    before = (list(recent), dict(last))
    quick_chat.check_rate(recent, now, last, 'hi')
    assert (recent, last) == before


# ===========================================================================
# 3. GET /api/quick_chat：游客也要能拿到
# ===========================================================================
@pytest.fixture
def api_client():
    return server.app.test_client()


def test_api_is_public_and_ok(api_client):
    """★ 不要求登录：游客也能对局，这里全是静态文案。"""
    resp = api_client.get('/api/quick_chat')
    assert resp.status_code == 200, '未登录必须 200，不是 401'
    body = resp.get_json()
    assert body['success'] is True


def test_api_shape(api_client):
    body = api_client.get('/api/quick_chat').get_json()
    assert body['groups'] == quick_chat.GROUPS
    assert isinstance(body['items'], list) and len(body['items']) == len(PLANNED)
    for m in body['items']:
        assert set(m) == {'id', 'group', 'text'}


def test_api_items_match_pure_functions(api_client):
    body = api_client.get('/api/quick_chat').get_json()
    assert body['items'] == quick_chat.catalog()
    assert [m['id'] for m in body['items']] == PLANNED_IDS


def test_api_contains_the_required_line_verbatim(api_client):
    items = api_client.get('/api/quick_chat').get_json()['items']
    hit = [m for m in items if m['id'] == REQUIRED_ID]
    assert hit and hit[0]['text'] == REQUIRED_TEXT


def test_api_logged_in_user_gets_same_payload(api_client):
    """登录与否下发同一份（前端不该有两条分支）。"""
    with api_client.session_transaction() as sess:
        sess['user_id'] = 'someone'
        sess['username'] = 'someone'
    assert api_client.get('/api/quick_chat').get_json() == \
        server.app.test_client().get('/api/quick_chat').get_json()


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


def test_send_broadcasts_to_both_players(room, socket_for):
    """★ 通过后双方都收到 `quick_chat`，文案逐字来自 quick_chat.by_id()。"""
    ca, cb = socket_for(A), socket_for(B)
    ack = _send(ca, room, A, REQUIRED_ID)
    assert ack['status'] == 'success'

    got_a, got_b = _recv(ca, 'quick_chat'), _recv(cb, 'quick_chat')
    assert len(got_a) == 1 and len(got_b) == 1
    for payload in (got_a[0], got_b[0]):
        assert payload['player_id'] == A
        assert payload['name'] == '甲'
        assert payload['msg_id'] == REQUIRED_ID
        assert payload['text'] == REQUIRED_TEXT
        assert isinstance(payload['ts'], int) and payload['ts'] > 0
        assert set(payload) == {'player_id', 'name', 'msg_id', 'text', 'ts'}


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


def test_send_writes_one_log_line(room, socket_for):
    """日志里多一句，且用的是既有日志助手（进 room.game_logs）。"""
    ca = socket_for(A)
    before = len(room.game_logs)
    _send(ca, room, A, 'gg')
    assert len(room.game_logs) == before + 1
    entry = room.game_logs[-1]
    assert 'GG，打得好' in entry['text']
    assert '甲' in entry['text']
    assert entry['type'] == 'quick_chat'
    assert entry['detail']['msg_id'] == 'gg'


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


def test_fourth_message_rejected_but_frequency_state_clean(room, socket_for):
    """★ 第 4 条被频率挡下；被拒的那条不占窗口（否则拒绝本身会把口子越堵越死）。"""
    ca = socket_for(A)
    assert _send(ca, room, A, 'hi')['status'] == 'success'
    assert _send(ca, room, A, 'lets_go')['status'] == 'success'
    assert _send(ca, room, A, 'nice_shot')['status'] == 'success'
    ack = _send(ca, room, A, 'oops')
    assert ack['status'] == 'error'
    assert ack['message'] and '10' in ack['message']
    assert len(room.quick_chat_recent[A]) == 3, '被拒的不许写进时间戳'
    assert room.quick_chat_last[A]['id'] == 'nice_shot', '被拒的不许改写"最近一条"'


def test_fourth_message_not_delivered(room, socket_for):
    ca, cb = socket_for(A), socket_for(B)
    for mid in ('hi', 'lets_go', 'nice_shot'):
        _send(ca, room, A, mid)
    for c in (ca, cb):
        c.get_received()                            # 清空前三条
    assert _send(ca, room, A, 'oops')['status'] == 'error'
    assert _recv(cb, 'quick_chat') == []


def test_same_message_twice_rejected(room, socket_for):
    ca, cb = socket_for(A), socket_for(B)
    assert _send(ca, room, A, 'lucky')['status'] == 'success'
    _recv(ca, 'quick_chat'), _recv(cb, 'quick_chat')
    ack = _send(ca, room, A, 'lucky')
    assert ack['status'] == 'error'
    assert '重复' in ack['message']
    assert _recv(cb, 'quick_chat') == []


def test_two_players_have_independent_quotas(room, socket_for):
    """频率按玩家记账：A 连点不该把 B 的嘴也堵上。"""
    ca, cb = socket_for(A), socket_for(B)
    for mid in ('hi', 'lets_go', 'nice_shot'):
        _send(ca, room, A, mid)
    assert _send(ca, room, A, 'oops')['status'] == 'error'
    assert _send(cb, room, B, 'oops')['status'] == 'success'


def test_send_does_not_mutate_turn_state(room, socket_for):
    """★ 不消耗攻击次数 / 不改阶段 / 不进连锁 / 不留待处理状态。"""
    ca = socket_for(A)
    before = _fingerprint(room)
    assert _send(ca, room, A, 'hi')['status'] == 'success'
    assert _send(ca, room, A, 'lets_go')['status'] == 'success'
    assert _send(ca, room, A, 'not_in_whitelist')['status'] == 'error'  # 被拒的也不许有副作用
    assert _fingerprint(room) == before


def test_send_after_game_over_still_works(room, socket_for):
    """终局后「结束」组仍要能发（所以 handler 刻意不挂 @_require_live_room）。"""
    room.state = 'game_over'
    room.winner = A
    ca, cb = socket_for(A), socket_for(B)
    assert _send(ca, room, A, 'gg')['status'] == 'success'
    assert _recv(cb, 'quick_chat')[0]['text'] == 'GG，打得好'
    assert room.state == 'game_over' and room.winner == A


def test_forged_player_id_rejected(room, socket_for):
    """★ 拿别人的 player_id 发（冒名）：报错且不广播。"""
    ca, cb = socket_for(A), socket_for(B)
    ack = ca.emit('quick_chat', {'room_id': room.id, 'player_id': B, 'msg_id': 'hi'},
                  callback=True)
    assert ack['status'] == 'error'
    assert _recv(cb, 'quick_chat') == []
    assert room.quick_chat_recent.get(B, []) == []


def test_unknown_player_id_rejected(room, socket_for):
    ca = socket_for(A)
    ack = _send(ca, room, 'nobody', 'hi')
    assert ack['status'] == 'error'
    assert [e['message'] for e in _recv(ca, 'error')]


def test_unknown_room_rejected(socket_for, room):
    ca = socket_for(A)
    ack = ca.emit('quick_chat', {'room_id': 'no-such-room', 'player_id': A, 'msg_id': 'hi'},
                  callback=True)
    assert ack['status'] == 'error'
    assert '房间不存在' in ack['message']


@pytest.mark.parametrize('payload', [None, {}, 'hi', ['hi'], 42])
def test_missing_or_malformed_payload_rejected_without_crash(room, socket_for, payload):
    """空载荷 / 垃圾载荷都要报错返回，不许抛 AttributeError 把 handler 打崩。"""
    ca = socket_for(A)
    ack = ca.emit('quick_chat', payload, callback=True)
    assert ack['status'] == 'error'
    assert ack['message']


def test_every_rejection_emits_an_error_event(room, socket_for):
    """每一步失败都要有明确提示 —— 静默 return 的表现是"点了没反应"。"""
    ca = socket_for(A)
    ca.get_received()
    _send(ca, room, A, 'nope')
    errors = _recv(ca, 'error')
    assert len(errors) == 1 and errors[0]['message']


# ===========================================================================
# 5. 房间级频率状态（第 2 批的硬规矩：__init__ 初始化 + 消费点 + 回归测试）
# ===========================================================================
def test_new_room_initializes_quick_chat_state():
    """★ 漏了 __init__ 就会在第一个真人身上 AttributeError。"""
    r = GameRoom('fresh-room')
    assert r.quick_chat_recent == {}
    assert r.quick_chat_last == {}


def test_quick_chat_state_is_per_room():
    """状态住房间，不是模块级全局 —— 两个房间互不影响。"""
    r1, r2 = GameRoom('r1'), GameRoom('r2')
    r1.quick_chat_recent[A] = [time.time()] * 3
    r1.quick_chat_last[A] = {'id': 'hi', 'ts': time.time()}
    assert r2.quick_chat_recent == {} and r2.quick_chat_last == {}
    assert r1.quick_chat_recent is not r2.quick_chat_recent


def test_recent_list_is_pruned_to_window(room, socket_for):
    """过期时间戳会被淘汰，不会无限增长（长对局里连发几百条也不涨）。"""
    ca = socket_for(A)
    room.quick_chat_recent[A] = [time.time() - 3600] * 5
    assert _send(ca, room, A, 'hi')['status'] == 'success'
    assert len(room.quick_chat_recent[A]) == 1
    assert room.quick_chat_last[A]['id'] == 'hi'
