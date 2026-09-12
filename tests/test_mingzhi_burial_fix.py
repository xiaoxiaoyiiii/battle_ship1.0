# -*- coding: utf-8 -*-
"""「明智埋葬」真实链路修复的回归测试。

背景：前端出牌后走 confirm_magic_target，但该 handler 的 bury_choice 分支
把 card_index 当成「施法者自己手牌的下标」（实现还停在"弃掉手牌第 N 张"的
旧描述上），于是：

- 施法者手牌为空（把明智埋葬打出去后的常见情况）→ 直接报「无效的选择」，
  牌不进弃牌堆、也不摸牌；
- 施法者手牌非空 → 埋掉的是自己手牌里的牌，玩家选中的那张（牌堆/对方手牌）
  从头到尾没进弃牌堆；
- 对方手牌里的牌既不会被移除也不会进弃牌堆。

现在 select_magic_target 与 confirm_magic_target 共用 _apply_bury_choice，
下面按卡面文本「选择一张牌堆中或对方手牌中的魔法卡，将那张牌放到弃牌堆中，
自己再摸一张牌」逐条校验真实链路。
"""
import pytest

import server
from server import GameRoom, MagicCard, Player, room_manager

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def events(monkeypatch):
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    return captured


@pytest.fixture
def room():
    r = GameRoom('bury-room')
    r.players[P1] = Player(name='p1', ships=[], attacks=[], remaining_ships=0,
                           sid='sid-p1', user_id='u1')
    r.players[P2] = Player(name='p2', ships=[], attacks=[], remaining_ships=0,
                           sid='sid-p2', user_id='u2')
    r.state = 'attacking'
    r.current_attacker = P1
    r.current_phase = 'battle'
    r.attack_order = [P1, P2]
    r.attacks_remaining = 6
    r.round = 1
    room_manager.rooms[r.id] = r
    yield r
    room_manager.rooms.pop(r.id, None)


def card(name):
    return MagicCard(name)


def cast(room, caster=P1, deck=(), opp_hand=()):
    """按真实顺序出牌：牌堆/对方手牌就位 → apply_magic_effect。返回结果。"""
    room.magic_deck = [card(n) for n in deck]
    room.players[P2].magic_hand = [card(n) for n in opp_hand]
    return server.apply_magic_effect(room, caster, card('明智埋葬'), {})


def confirm(room, target_data, pid=P1):
    return server.confirm_magic_target({
        'room_id': room.id, 'player_id': pid,
        'temp_data_id': 'bury_choice', 'target_data': target_data})


def names(cards):
    return [c.name for c in cards]


# ---------------------------------------------------------------------------
# 复现的三条现场（修复前全部不通过）
# ---------------------------------------------------------------------------
def test_empty_hand_buries_deck_card_and_draws(room):
    """手牌为空也必须能埋牌并摸牌（修复前：报「无效的选择」，什么都不发生）。"""
    res = cast(room, deck=['轰炸', '冻结'])
    assert res.success is True

    out = confirm(room, {'card_index': 0, 'source': 'deck', 'source_index': 0})
    assert out['status'] == 'success'
    assert names(room.magic_discard) == ['轰炸']
    assert names(room.magic_deck) == []          # 轰炸真的被拿走了
    assert names(room.players[P1].magic_hand) == ['冻结']
    assert room.magic_temp_data == {}


def test_buries_selected_deck_card_not_own_hand(room):
    """选的是牌堆第 0 张，就绝不能埋成自己手牌里的牌。"""
    room.players[P1].magic_hand = [card('疗愈')]
    res = cast(room, deck=['轰炸', '冻结'])
    assert res.success is True

    out = confirm(room, {'card_index': 0, 'source': 'deck', 'source_index': 0})
    assert out['status'] == 'success'
    assert '轰炸' in names(room.magic_discard)          # 选中的牌进弃牌堆
    assert '疗愈' not in names(room.magic_discard)      # 自己的牌没被误埋
    assert '疗愈' in names(room.players[P1].magic_hand)


def test_buries_opponent_hand_card(room):
    """埋葬对方手牌：对方失去该牌、该牌进弃牌堆、自己摸一张、对方收到同步。"""
    res = cast(room, deck=['轰炸'], opp_hand=['冻结', '饮血'])
    assert res.success is True
    assert [c['source'] for c in res['cards']] == ['deck', 'opponent_hand', 'opponent_hand']

    # 前端按候选扁平顺序展示：对方手牌第 0 张的扁平下标是 1、来源内下标是 0
    out = confirm(room, {'card_index': 1, 'source': 'opponent_hand', 'source_index': 0})
    assert out['status'] == 'success'
    assert names(room.players[P2].magic_hand) == ['饮血']
    assert '冻结' in names(room.magic_discard)
    assert names(room.players[P1].magic_hand) == ['轰炸']   # 自己摸到的正是牌堆那张


# ---------------------------------------------------------------------------
# 下标语义：扁平 / 来源内 / 旧约定 都必须落到同一张牌
# ---------------------------------------------------------------------------
def test_flat_index_matches_per_source_index(room):
    """前端只回传扁平下标（未带 source_index）时也必须命中同一张牌。"""
    res = cast(room, deck=['轰炸'], opp_hand=['冻结', '饮血'])
    assert res.success is True

    out = confirm(room, {'card_index': 1, 'source': 'opponent_hand'})
    assert out['status'] == 'success'
    assert names(room.players[P2].magic_hand) == ['饮血']
    assert '冻结' in names(room.magic_discard)


def test_result_cards_carry_per_source_index(room):
    """下发候选必须带来源内下标，前端才能回传 source_index。"""
    res = cast(room, deck=['轰炸'], opp_hand=['冻结'])
    assert res.success is True
    assert [(c['source'], c['index']) for c in res['cards']] == [
        ('deck', 0), ('opponent_hand', 0)]
    # 候选里不能夹带 MagicCard 实例（magic_temp_data 会被原样 emit）
    assert all(isinstance(c, dict) and 'card' not in c for c in res['cards'])
    assert all(isinstance(c, dict) for c in room.magic_temp_data['candidates'])


def test_temp_data_is_json_serializable(room):
    """get_magic_temp_data 会原样 emit，候选必须是可 JSON 序列化的纯数据。"""
    import json
    cast(room, deck=['轰炸'], opp_hand=['冻结'])
    json.dumps(room.magic_temp_data)   # 修复前含 MagicCard 实例，这里会抛 TypeError


# ---------------------------------------------------------------------------
# 边界与防作弊
# ---------------------------------------------------------------------------
def test_bury_choice_rejects_out_of_range(room):
    res = cast(room, deck=['轰炸'])
    out = confirm(room, {'card_index': 9, 'source': 'deck', 'source_index': 9})
    assert out['status'] == 'error'
    assert names(room.magic_deck) == ['轰炸']      # 牌堆没被动过
    assert room.magic_discard == []


def test_bury_choice_rejects_non_numeric_index(room):
    cast(room, deck=['轰炸'])
    for bad in (None, 'x', [], True, -1):
        out = confirm(room, {'card_index': bad, 'source': 'deck'})
        assert out['status'] == 'error'
    assert names(room.magic_deck) == ['轰炸']


def test_bury_choice_rejects_non_caster(room):
    """选择权只属于施法者：对方不能替你确认并挑走一张牌。"""
    cast(room, deck=['轰炸', '冻结'])
    out = confirm(room, {'card_index': 0, 'source': 'deck'}, pid=P2)
    assert out['status'] == 'error'
    assert names(room.magic_deck) == ['轰炸', '冻结']
    assert room.magic_discard == []


def test_bury_choice_requires_matching_temp_type(room):
    """没有待处理的埋葬选择时（例如重复点击）不能凭空埋牌。"""
    room.magic_temp_data = {'type': 'shield_choice', 'caster': P1}
    out = confirm(room, {'card_index': 0, 'source': 'deck'})
    assert out['status'] == 'error'


def test_second_confirm_cannot_rebury(room):
    """第一次确认后 temp data 清空，重复确认不能二次结算。"""
    cast(room, deck=['轰炸', '冻结'])
    assert confirm(room, {'card_index': 0, 'source': 'deck'})['status'] == 'success'
    out = confirm(room, {'card_index': 0, 'source': 'deck'})
    assert out['status'] == 'error'
    assert names(room.magic_discard) == ['轰炸']


def test_no_draw_effect_still_buries(room):
    """被「无中生有」封锁抽牌时仍然埋牌，但必须说清为什么没摸到牌。"""
    cast(room, deck=['轰炸', '冻结'])
    room.players[P1].effect_flags.no_draw = True
    out = confirm(room, {'card_index': 0, 'source': 'deck'})
    assert out['status'] == 'success'
    assert names(room.magic_discard) == ['轰炸']
    assert room.players[P1].magic_hand == []
    assert '无中生有' in out['message']       # 不再谎报「摸了一张牌」


def test_empty_deck_reports_no_draw(room):
    """牌堆已空（只剩对方手牌可埋）时要说清「牌堆已空」，不能假装摸到牌。"""
    res = cast(room, deck=[], opp_hand=['冻结'])
    assert res.success is True
    out = confirm(room, {'card_index': 0, 'source': 'opponent_hand', 'source_index': 0})
    assert out['status'] == 'success'
    assert names(room.players[P2].magic_hand) == []
    assert '冻结' in names(room.magic_discard)
    assert room.players[P1].magic_hand == []
    assert '牌堆已空' in out['message']


def test_duplicate_draw_is_reported(room):
    """摸到重名牌按既有规则进弃牌堆，但要让玩家知道「为什么手牌没变多」。"""
    room.players[P1].magic_hand = [card('冻结')]
    cast(room, deck=['轰炸', '冻结'])
    out = confirm(room, {'card_index': 0, 'source': 'deck'})
    assert out['status'] == 'success'
    assert names(room.players[P1].magic_hand) == ['冻结']   # 手牌没变多
    assert '重复' in out['message']


def test_bury_is_written_to_game_log(room, events):
    """埋葬结果要进对局日志，玩家在日志面板能看到摸没摸到牌。"""
    cast(room, deck=['轰炸', '冻结'])
    confirm(room, {'card_index': 0, 'source': 'deck'})
    logs = [d for e, d, to, _ in events if e == 'game_log']
    assert logs and '明智埋葬' in logs[-1]['text'] and '余音' not in logs[-1]['text']
    assert logs[-1]['text'].count('摸') >= 1


def test_duplicate_draw_goes_to_discard_not_hand(room):
    """摸到重名卡按既有规则进弃牌堆，不会复制出第二张。"""
    room.players[P1].magic_hand = [card('冻结')]
    cast(room, deck=['轰炸', '冻结'])
    out = confirm(room, {'card_index': 0, 'source': 'deck'})
    assert out['status'] == 'success'
    assert names(room.players[P1].magic_hand) == ['冻结']
    assert sorted(names(room.magic_discard)) == ['冻结', '轰炸']


def test_legacy_select_magic_target_uses_same_path(room):
    """旧事件 select_magic_target 与真实链路共用同一实现，不再各写一份。"""
    cast(room, deck=['轰炸', '冻结'])
    out = server.handle_magic_target({
        'room_id': room.id, 'player_id': P1,
        'temp_data_id': 'bury_choice',
        'target_data': {'card_index': 0, 'source': 'deck'}})
    assert out['status'] == 'success'
    assert names(room.magic_discard) == ['轰炸']
    assert names(room.players[P1].magic_hand) == ['冻结']


def test_bury_follows_card_when_pile_index_shifted(room):
    """候选下发后牌堆被同一连锁里的其它卡改动过：按下标会埋错牌，要按卡名找回。"""
    res = cast(room, deck=['轰炸', '冻结'])
    assert res.success is True
    # 模拟结算后牌堆被抽走一张：'轰炸' 从下标 0 挪到下标 0 的位置上换了别人
    room.magic_deck = [card('疗愈'), card('轰炸')]

    out = confirm(room, {'card_index': 0, 'source': 'deck', 'source_index': 0})
    assert out['status'] == 'success'
    assert '轰炸' in names(room.magic_discard)      # 仍是玩家点的那张
    assert '疗愈' not in names(room.magic_discard)
    assert names(room.magic_deck) == []              # 只少了被埋的那张
    assert names(room.players[P1].magic_hand) == ['疗愈']   # 摸到的还是那张


def test_bury_errors_when_card_gone(room):
    """选中的牌在确认前已不在牌堆/手牌里 → 明确报错，不误埋别的牌。"""
    res = cast(room, deck=['轰炸'])
    assert res.success is True
    room.magic_deck = [card('疗愈')]

    out = confirm(room, {'card_index': 0, 'source': 'deck', 'source_index': 0})
    assert out['status'] == 'error'
    assert names(room.magic_deck) == ['疗愈']
    assert room.magic_discard == []


def test_full_flow_use_magic_card_then_confirm(room, events):
    """走完整真实协议：出牌 → 连锁放弃 → 结算下发候选 → 玩家点选。"""
    room.magic_deck = [card('冻结'), card('饮血')]
    room.players[P2].magic_hand = [card('疗愈')]
    room.players[P1].magic_hand = [card('明智埋葬')]

    ack = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '明智埋葬', 'speed': 2, 'type': '普通'}, 'targets': {}})
    assert ack['status'] == 'success'
    assert names(room.magic_discard) == ['明智埋葬']   # 打出的牌本身进弃牌堆

    # 对方放弃连锁；施法者没有速阶3手牌，连锁随即结算
    server.chain_response({'room_id': room.id, 'player_id': P2, 'chain': False})

    resolved = [d for e, d, to, _ in events if e == 'chain_resolved']
    assert resolved, '连锁应已结算并下发结果'
    cards = resolved[-1]['results'][0]['cards']
    assert [c['source'] for c in cards] == ['deck', 'deck', 'opponent_hand']

    # 前端点击「对方手牌」那张：扁平下标 2 + 来源内下标 0
    out = confirm(room, {'card_index': 2, 'source': 'opponent_hand',
                         'source_index': cards[2]['index']})
    assert out['status'] == 'success'
    assert names(room.magic_discard) == ['明智埋葬', '疗愈']
    assert names(room.players[P2].magic_hand) == []
    assert names(room.players[P1].magic_hand) == ['冻结']
    # 对方手牌变化必须同步给对方（draw_card 只通知施法者）
    assert any(e == 'hand_updated' and to == 'sid-p2' for e, d, to, _ in events)


def test_cancel_magic_selection_does_not_pollute_deck(room):
    """取消选择时不能把纯数据候选塞进牌堆。"""
    cast(room, deck=['轰炸', '冻结'])
    out = server.handle_cancel_magic_selection({
        'room_id': room.id, 'player_id': P1})
    assert out['status'] == 'success'
    assert names(room.magic_deck) == ['轰炸', '冻结']
    assert all(isinstance(c, MagicCard) for c in room.magic_deck)
