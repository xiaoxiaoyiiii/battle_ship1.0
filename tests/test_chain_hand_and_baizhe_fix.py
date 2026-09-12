# -*- coding: utf-8 -*-
"""连锁手牌同步 + 败者食尘「重启对局」语义 的回归测试（2026-09-14）。

【问题 1 · 连锁里打出的牌"还在手上"】
  玩家实测：对方出牌 → 我连锁盗亦有道 → 对方再连锁失灵
  → 我的盗亦有道仍在手牌里。
  根因：chain_response 确实把牌移出手牌并进了弃牌堆，但**从不推送
  hand_updated**；前端手牌是照服务端数据渲染的，没收到推送就停在旧状态。
  这条路径影响所有速阶3响应（失灵！/看破！/加百列之光…），不只是盗亦有道。
  另外结算期间还会改手牌（盗亦有道偷牌、桃园结义分配、摸牌效果），
  因此 resolve_chain 收尾统一重推一次双方手牌。

【问题 2 · 败者食尘不是"重启"】
  卡面："立即重启正常对局但保留双方的手牌。"
  旧实现把双方的 max_ships **互换**（caster.max_ships = opponent_ships），
  卡面里根本没有这回事。改为双方一律重置为默认 6 艘。
  同时按作者确认：不重新猜拳（保留原先后手与阶段）、只保留手牌，
  场地魔法 / 生效效果 / 弃牌堆一律回到开局状态。
"""
import pytest

import server
from server import ChainItem, GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def events(monkeypatch):
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    monkeypatch.setattr(server.socketio, 'start_background_task',
                        lambda target, *a, **k: None)
    monkeypatch.setattr(server, '_schedule_chain_timeout', lambda *a, **k: None)
    return captured


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def make_room():
    room = GameRoom('test-room')
    room.players[P1] = Player(name='p1', ships=[], attacks=[], remaining_ships=6, sid='sid-p1')
    room.players[P2] = Player(name='p2', ships=[], attacks=[], remaining_ships=6, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 1
    room_manager.rooms[room.id] = room
    return room


def ship(*cells):
    return PlayerShip(positions=[Position(x, y) for x, y in cells], hits=[])


def card(name):
    return MagicCard(name)


def hand_events(events, sid):
    """取发给某个 sid 的 hand_updated 事件。"""
    return [d for e, d, to, r in events if e == 'hand_updated' and to == sid]


# ---------------------------------------------------------------------------
# 问题 1：连锁打出的牌必须从手牌消失，且前端收到通知
# ---------------------------------------------------------------------------
def test_chain_response_consumes_card_from_hand(room):
    """连锁响应扣牌后，服务端手牌里必须真的没有这张牌。"""
    room.players[P2].magic_hand = [card('失灵！')]
    room.chain = [ChainItem(P1, card('盗亦有道'), [], 0)]
    room.chain_waiting = True
    room.chain_window = P2
    room.chain_timer = 1

    res = server.chain_response({
        'room_id': room.id, 'player_id': P2, 'chain': True,
        'card': {'name': '失灵！', 'speed': 3}, 'targets': [],
    })
    assert res.get('status') == 'success', res
    names = [c.name for c in room.players[P2].magic_hand]
    assert '失灵！' not in names, f'连锁打出的牌应从手牌移除，实际：{names}'


def test_chain_response_emits_hand_updated(room, events):
    """关键回归：扣牌后必须推送 hand_updated，否则前端手牌不刷新。

    这正是玩家看到「打出的牌还在手上」的根因。
    """
    room.players[P2].magic_hand = [card('失灵！')]
    room.chain = [ChainItem(P1, card('盗亦有道'), [], 0)]
    room.chain_waiting = True
    room.chain_window = P2
    room.chain_timer = 1

    server.chain_response({
        'room_id': room.id, 'player_id': P2, 'chain': True,
        'card': {'name': '失灵！', 'speed': 3}, 'targets': [],
    })

    updates = hand_events(events, 'sid-p2')
    assert updates, '扣牌后必须给该玩家推 hand_updated'
    sent = [c.name for c in updates[-1]['hand']]
    assert '失灵！' not in sent, f'推送的手牌里不该还有这张牌，实际：{sent}'


def test_resolve_chain_resyncs_both_hands(room, events):
    """连锁结算收尾时，双方都要收到一次手牌同步。"""
    room.players[P1].magic_hand = [card('盗亦有道')]
    room.players[P2].magic_hand = [card('八方来财')]
    room.chain = [ChainItem(P2, card('八方来财'), [], 0)]

    server.resolve_chain(room)

    assert hand_events(events, 'sid-p1'), '结算后应给 P1 推手牌'
    assert hand_events(events, 'sid-p2'), '结算后应给 P2 推手牌'


def test_stolen_card_reflected_in_hand_push(room, events):
    """盗亦有道偷到牌后，推送的手牌里要包含偷来的那张。"""
    room.current_attacker = P2
    room.players[P2].magic_hand = [card('八方来财')]
    room.players[P1].magic_hand = [card('盗亦有道')]
    room.magic_deck = []

    server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P2,
        'card': {'name': '八方来财'}, 'targets': {},
    })
    server.chain_response({
        'room_id': room.id, 'player_id': P1, 'chain': True,
        'card': {'name': '盗亦有道'}, 'targets': [],
    })
    server.resolve_chain(room)

    updates = hand_events(events, 'sid-p1')
    assert updates, 'P1 应收到手牌推送'
    sent = [c.name for c in updates[-1]['hand']]
    assert '盗亦有道' not in sent, f'打出的盗亦有道不该还在手牌：{sent}'
    assert '八方来财' in sent, f'偷到的牌应出现在手牌里：{sent}'


# ---------------------------------------------------------------------------
# 问题 2：败者食尘 = 双方重置为 6 艘
# ---------------------------------------------------------------------------
def test_baizhe_resets_both_to_default_ships(room):
    """核心：双方都重置为 6 艘，不是交换船数。"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3
    room.players[P2].ships = [ship((4, 4)), ship((5, 5))]
    room.players[P2].remaining_ships = 2

    server.apply_magic_effect(room, P1, card('败者食尘'), {})

    assert room.players[P1].max_ships == 6, '施法者应重置为 6 艘'
    assert room.players[P2].max_ships == 6, '对方也应重置为 6 艘（旧实现是互换）'


def test_baizhe_keeps_hands_clears_board(room):
    """只保留手牌：棋盘清空、双方回到摆放阶段。"""
    room.players[P1].magic_hand = [card('轰炸')]
    room.players[P2].magic_hand = [card('冻结')]
    room.players[P1].ships = [ship((0, 0))]
    room.players[P1].remaining_ships = 1

    server.apply_magic_effect(room, P1, card('败者食尘'), {})

    assert room.state == 'placing_ships'
    assert room.players[P1].ships == []
    assert room.players[P2].ships == []
    assert [c.name for c in room.players[P1].magic_hand] == ['轰炸']
    assert [c.name for c in room.players[P2].magic_hand] == ['冻结']


def test_baizhe_clears_field_magic_and_effects(room):
    """「其余全部重置」：场地魔法、生效效果、弃牌堆都回到开局状态。"""
    room.field_magic = card('伊甸园')
    room.field_magic_owner = P1
    room.game_effects = {'last_ship_change': {'round': 1}}
    room.magic_discard = [card('轰炸')]
    room.players[P1].effect_flags.vampire = True
    room.players[P2].magic_blocked = True

    server.apply_magic_effect(room, P1, card('败者食尘'), {})

    assert room.field_magic is None, '场地魔法应被清除'
    assert room.game_effects == {}, '房间级效果应被清除'
    assert room.magic_discard == [], '弃牌堆应被清空'
    assert room.players[P1].effect_flags.vampire is False, '玩家效果标记应清零'
    assert room.players[P2].magic_blocked is False, '看破封锁应解除'


def test_baizhe_keeps_turn_order_no_rps(room):
    """不重新猜拳：保留原先后手与阶段（作者确认）。"""
    room.attack_order = [P2, P1]
    room.current_attacker = P2

    server.apply_magic_effect(room, P1, card('败者食尘'), {})

    assert room.attack_order == [P2, P1], '先后手应保留'
    assert room.current_attacker == P2, '当前攻击者应保留'
    assert room.lingqi_resurgence_applied is True, '应走"摆放完成即恢复"的分支'


def test_baizhe_zeroes_attacks(room):
    """卡面第二句：生效的大回合内攻击次数为 0。"""
    room.attacks_remaining = 5
    server.apply_magic_effect(room, P1, card('败者食尘'), {})
    assert room.attacks_remaining == 0


def test_baizhe_attacks_stay_zero_after_replacing(room):
    """重新摆放完成、回到攻击阶段后，攻击次数仍必须是 0。

    旧实现把这条挂在"猜拳结束"分支上；败者食尘现在不重新猜拳，
    走不到那里 —— 不补一处就会静默失效。
    """
    room.current_phase = 'preparation'
    server.apply_magic_effect(room, P1, card('败者食尘'), {})
    assert room.polar_reversal_applied is True

    # 双方各摆 6 艘（reset_gameboard 之后玩家会这么做）
    for pid in (P1, P2):
        cells = [(i, 0) for i in range(6)] if pid == P1 else [(i, 5) for i in range(6)]
        res = server.handle_place_ships({
            'room_id': room.id, 'player_id': pid,
            'ships': [{'positions': [{'x': x, 'y': y}], 'hits': []} for x, y in cells],
        })
        assert res.get('status') == 'success', res

    assert room.state == 'attacking', '双方摆完后应回到攻击阶段'
    assert room.attacks_remaining == 0, (
        f'败者食尘生效的大回合内攻击次数必须为 0，实际 {room.attacks_remaining}')
    assert room.polar_reversal_applied is False, '标记应已消费'


def test_baizhe_emits_reset_gameboard_to_both(room, events):
    """双方都要收到 reset_gameboard，且带上新的船数 6。"""
    server.apply_magic_effect(room, P1, card('败者食尘'), {})

    resets = [(d, to) for e, d, to, r in events if e == 'reset_gameboard']
    assert len(resets) == 2, f'双方都应收通知，实际 {len(resets)} 条'
    for d, to in resets:
        assert d['new_max_ships'] == 6
        assert '6' in d['message'] or '败者食尘' in d['message']
    targets = {to for _, to in resets}
    assert targets == {'sid-p1', 'sid-p2'}, '且要发给各自的 socket sid'


def test_baizhe_not_game_over(room):
    """重置后不得被末尾的"对手船数<=0"兜底判成 game_over。"""
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 0

    res = server.apply_magic_effect(room, P1, card('败者食尘'), {})
    assert res.success is True
    assert room.state == 'placing_ships'
    assert room.state != 'game_over'
