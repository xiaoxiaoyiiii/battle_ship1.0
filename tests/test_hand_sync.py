# -*- coding: utf-8 -*-
"""手牌同步的回归测试（2026-09-14）。

背景（作者反馈）：
    「每一次有手牌通过之后，剩下的自己的手牌总是会莫名其妙消失，
      我无法描述具体场景，但是刷新网页之后就会重新出现。」

真实根因（tools/hand_play_check.mjs 在真实浏览器 + 真服务端上复现）：
    `handle_use_magic_card` 扣掉手牌后会走 `_advance_chain_window`；对方手上
    没有速阶3时，它会【在同一个请求里同步 `resolve_chain`】，而 `resolve_chain`
    收尾会向双方各推一次 `hand_updated`。于是客户端拿到的是这个顺序：
        hand_updated（已扣牌）  →  use_magic_card 的 ack
    前端 `sendMagicCard` 的 ack 回调要"本地把打出的牌从手牌里删掉"：
        · 按 name+speed 身份找 → 找不到（服务端早就推过新手牌了）
        · 兜底分支 `hand.length === sentIndex + 1` 成立 → 按旧下标删一张
    打出【倒数第二张】时这个条件恰好成立，于是把剩下的最后一张也删掉，
    界面手牌清空，而服务端手牌完好 —— 刷新（走重连快照）就"回来"了。

本文件守两件事：
    1. 服务端扣牌后必须【立刻】以自己为准推一次手牌（前端才不用猜）；
    2. 客户端能主动 `request_hand_sync` 要一份权威手牌（免刷新自愈）。
"""
import pytest

import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def events(monkeypatch):
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    monkeypatch.setattr(server.socketio, 'start_background_task',
                        lambda target, *a, **k: target(*a, **k))
    monkeypatch.setattr(server, '_schedule_chain_timeout', lambda *a, **k: None)
    monkeypatch.setattr(server, 'record_card_use', lambda *a, **k: None)
    monkeypatch.setattr(server, '_has_request_context', lambda: True)
    return captured


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def make_room(ai=False):
    room = GameRoom('hand-sync-room')
    room.players[P1] = Player(name='p1',
                              ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(6)],
                              attacks=[], remaining_ships=6, sid='sid-p1')
    room.players[P2] = Player(name='p2',
                              ships=[PlayerShip(positions=[Position(i, 5)], hits=[]) for i in range(6)],
                              attacks=[], remaining_ships=6, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'preparation'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 5
    room.is_ai_room = ai
    room.magic_deck = [MagicCard(n) for n in ['冻结', '轰炸', '疗愈', '饮血']]
    room_manager.rooms[room.id] = room
    return room


def hand_pushes(events, player_sid):
    """该玩家收到的 hand_updated payload 列表（按顺序）。"""
    return [d for e, d, to, r in events
            if e == 'hand_updated' and to == player_sid]


# ── 1. 扣牌后立刻以服务端为准推手牌 ────────────────────────────────

def test_playing_a_card_pushes_the_new_hand_before_returning(room, events):
    """打出「五险一金」→ 在 handler 返回之前就要推一次新手牌。

    这是 bug 的正向防线：前端拿到的新手牌来自服务端，不需要自己按下标猜。
    """
    room.players[P1].magic_hand = [MagicCard('五险一金'), MagicCard('看破！')]

    resp = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '五险一金'}, 'targets': {},
    })

    assert resp['status'] == 'success'
    pushes = hand_pushes(events, 'sid-p1')
    assert pushes, '扣牌后必须立刻推一次 hand_updated'
    # 推的是扣掉这张之后的手牌
    assert [c['name'] if isinstance(c, dict) else c.name for c in pushes[0]['hand']] == ['看破！'], \
        '推给玩家的手牌应该已经不含刚打出的那张'


def test_hand_push_payload_is_the_players_own_hand(room, events):
    """推给谁的就必须是谁的手牌 —— 发错人会让对面看到（或被覆盖成）别人的手牌。"""
    room.players[P1].magic_hand = [MagicCard('五险一金'), MagicCard('看破！')]

    server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '五险一金'}, 'targets': {},
    })

    def names_of(payload):
        return [c['name'] if isinstance(c, dict) else c.name for c in payload['hand']]

    for push in hand_pushes(events, 'sid-p1'):
        assert '五险一金' not in names_of(push), \
            'P1 已经打出的牌不该再出现在 P1 的手牌推送里'
    # 推给 P1 的手牌绝不能送到 P2 的座位上（P2 手上是空的）
    leaked = [names_of(d) for e, d, to, r in events
              if e == 'hand_updated' and to == 'sid-p2' and '看破！' in names_of(d)]
    assert not leaked, f'不该把 P1 的手牌推给 P2：{leaked}'


# ── 2. request_hand_sync：客户端主动要权威手牌（免刷新自愈）────────────

def test_request_hand_sync_returns_own_hand(room, events):
    room.players[P1].magic_hand = [MagicCard('冻结'), MagicCard('轰炸'), MagicCard('疗愈')]

    resp = server.handle_request_hand_sync({'room_id': room.id, 'player_id': P1})

    assert resp['status'] == 'success'
    assert resp['count'] == 3
    pushes = hand_pushes(events, 'sid-p1')
    assert len(pushes) == 1
    assert pushes[0].get('resync') is True, '重同步要能被前端认出（打日志/区分来源）'
    assert [c['name'] if isinstance(c, dict) else c.name for c in pushes[0]['hand']] == \
        ['冻结', '轰炸', '疗愈']


def test_request_hand_sync_only_goes_to_the_requester(room, events):
    room.players[P1].magic_hand = [MagicCard('冻结')]
    room.players[P2].magic_hand = [MagicCard('轰炸')]

    server.handle_request_hand_sync({'room_id': room.id, 'player_id': P1})

    assert not hand_pushes(events, 'sid-p2'), '对手的手牌不能被牵连下发'


def test_request_hand_sync_rejects_unknown_player(room, events):
    resp = server.handle_request_hand_sync({'room_id': room.id, 'player_id': 'nobody'})
    assert resp['status'] == 'error'
    assert not hand_pushes(events, 'sid-p1')


def test_request_hand_sync_rejects_unknown_room(events):
    resp = server.handle_request_hand_sync({'room_id': 'no-such-room', 'player_id': P1})
    assert resp['status'] == 'error'


def test_request_hand_sync_can_return_empty_hand(room, events):
    """空手牌也要如实回一份空数组 —— 这样前端才能"确认"自己是空的，
    而不是把"没收到推送"和"真的是空的"混为一谈。"""
    room.players[P1].magic_hand = []

    resp = server.handle_request_hand_sync({'room_id': room.id, 'player_id': P1})

    assert resp['status'] == 'success' and resp['count'] == 0
    pushes = hand_pushes(events, 'sid-p1')
    assert len(pushes) == 1 and pushes[0]['hand'] == []


# ── 3. 测试事件要能给出卡名（E2E 对账靠它）─────────────────────────

def test_test_get_game_state_exposes_hand_names(room, monkeypatch):
    """tools/e2e_hand_sync.py 要拿服务端真实手牌和客户端收到的对比，
    只给数量会漏掉"张数对但内容错/发错人"。"""
    # 该 handler 带 @_test_event 门禁（默认关闭），这里显式打开
    monkeypatch.setattr(server, 'ENABLE_TEST_EVENTS', True)
    room.players[P1].magic_hand = [MagicCard('冻结'), MagicCard('疗愈')]

    resp = server.test_get_game_state({'room_id': room.id})

    info = resp['game_state']['players'][P1]
    assert info['magic_hand_count'] == 2
    assert info['magic_hand'] == ['冻结', '疗愈']
