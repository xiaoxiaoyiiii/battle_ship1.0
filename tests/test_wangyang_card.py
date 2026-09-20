# -*- coding: utf-8 -*-
"""亡羊补牢（普通魔法卡）的回归测试。

按 CLAUDE.md 第 7 节「改卡要同步 4 处」要求覆盖：
  · magic_card.json / magic_cards.js 一致性
  · apply_magic_effect 的亡羊补牢分支
  · 发动条件「弃牌区有卡牌」在扣牌前拦截
  · n = max(双方剩余船数) 的候选数
  · 候选不含刚打出的亡羊补牢自己
  · 选中入手中其余回堆 + 自己回堆
  · cancel 时弃牌区还原
  · 看破 / 禁忌果实反制
"""
import json
import os

import pytest

import server
from server import (GameRoom, MagicCard, Player, PlayerShip, Position,
                    room_manager)

P1, P2 = 'p1', 'p2'


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------
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
    room = GameRoom('test-wangyang-room')
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
    room.round = 1
    room_manager.rooms[room.id] = room
    return room


def card(name):
    return MagicCard(name)


def give_hand(player, names):
    player.magic_hand = [card(n) for n in names]


def find_emit(events, event_name, to=None):
    out = []
    for ev, data, t, r in events:
        if ev == event_name and (to is None or t == to):
            out.append((ev, data, t, r))
    return out


def apply_wangyang(room, caster):
    """直接调用 apply_magic_effect，模拟扣牌流程已把亡羊补牢自己加入 magic_discard 末尾。

    在真实对局中：handle_use_magic_card 扣牌 → 入连锁 → resolve_chain 调 apply_magic_effect。
    测试为了直奔分支，手动模拟扣牌副作用。
    """
    # 模拟扣牌：把亡羊补牢自己放到 magic_discard 末尾
    own = card('亡羊补牢')
    room.magic_discard.append(own)
    res = server.apply_magic_effect(room, caster, card('亡羊补牢'), {})
    return res


def confirm_wangyang(room, player, chosen_index):
    return server.confirm_magic_target({
        'room_id': room.id,
        'player_id': player,
        'temp_data_id': 'wangyang_choice',
        'target_data': {'chosen_index': chosen_index},
    })


# ---------------------------------------------------------------------------
# 卡牌定义一致性（JSON 与 JS 必须逐字符一致 —— CLAUDE.md §7）
# ---------------------------------------------------------------------------
def test_card_definition_consistent():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, 'static', 'magic_card.json'), encoding='utf-8') as f:
        json_cards = json.load(f)
    wangyang_json = [c for c in json_cards if c['name'] == '亡羊补牢']
    assert len(wangyang_json) == 1
    wj = wangyang_json[0]
    assert wj['speed'] == 1
    assert wj['type'] == '普通'

    with open(os.path.join(here, 'static', 'magic_cards.js'), encoding='utf-8') as f:
        js_src = f.read()
    assert f'name: "亡羊补牢"' in js_src
    assert f'speed: {wj["speed"]}' in js_src
    assert f'type: "{wj["type"]}"' in js_src
    assert wj['description'] in js_src


def test_wangyang_card_enters_deck():
    """亡羊补牢应已进 magic_cards 列表。"""
    names = [c.name for c in server.magic_cards]
    assert '亡羊补牢' in names


def test_deck_size_grew():
    """新加一张普通卡，牌池规模从 44 → 47。"""
    deck = server.build_magic_deck() if hasattr(server, 'build_magic_deck') else server.magic_cards
    assert len(deck) == 47, f'卡池应 47 条，实际 {len(deck)}'


# ---------------------------------------------------------------------------
# 发动条件：弃牌区为空不能发动（扣牌前拦截，不消耗手牌）
# ---------------------------------------------------------------------------
def test_blocked_when_discard_empty(room):
    """弃牌区为空时，handle_use_magic_card 应直接拒绝，且手牌不丢。"""
    give_hand(room.players[P1], ['亡羊补牢'])
    room.magic_discard = []

    resp = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '亡羊补牢', 'speed': 1, 'type': '普通', 'description': ''},
        'targets': {},
    })
    assert resp['status'] == 'error'
    assert '弃牌区' in resp['message']
    # 手牌不应被扣掉
    assert len(room.players[P1].magic_hand) == 1
    assert room.players[P1].magic_hand[0].name == '亡羊补牢'
    # 弃牌区仍然空
    assert room.magic_discard == []


def test_requirement_reason_function():
    """_wangyang_requirement_reason 直接单元测试。"""
    room = GameRoom('test-reason')
    room.players[P1] = Player(name='p1', ships=[], attacks=[], remaining_ships=3, sid='s1')
    room.players[P2] = Player(name='p2', ships=[], attacks=[], remaining_ships=3, sid='s2')
    # 非「亡羊补牢」不拦
    assert server._wangyang_requirement_reason(room, P1, card('无中生有')) is None
    # 弃牌区空 → 拒
    room.magic_discard = []
    assert server._wangyang_requirement_reason(room, P1, card('亡羊补牢')) is not None
    # 弃牌区有牌 → 放行
    room.magic_discard = [card('轰炸')]
    assert server._wangyang_requirement_reason(room, P1, card('亡羊补牢')) is None


# ---------------------------------------------------------------------------
# 发动条件：弃牌区非空可以发动
# ---------------------------------------------------------------------------
def test_playable_when_discard_has_cards(room):
    """弃牌区有牌 → 亡羊补牢发动成立，进入待选择状态。"""
    room.magic_discard = [card('轰炸'), card('冻结'), card('增援')]
    give_hand(room.players[P1], ['亡羊补牢'])

    res = apply_wangyang(room, P1)
    assert res.success is True
    assert res.temp_data_id == 'wangyang_choice'
    assert res['cards'] is not None
    # n = max(6, 6) = 6，但弃牌区只有 3 张非自己牌，所以候选 = 3
    assert len(res['cards']) == 3
    # 临时数据已写入
    assert room.magic_temp_data.get('type') == 'wangyang_choice'
    assert room.magic_temp_data.get('caster') == P1


# ---------------------------------------------------------------------------
# n = max(双方剩余船数)
# ---------------------------------------------------------------------------
def test_n_is_max_of_both_ship_counts(room):
    """n 取双方剩余船数的最大值（施法者 4 / 对手 7 → 候选 7 张）。"""
    room.players[P1].remaining_ships = 4
    room.players[P2].remaining_ships = 7
    # 弃牌区放 10 张牌（> 7），验证候选数 = 7
    room.magic_discard = [card('轰炸') for _ in range(10)]
    give_hand(room.players[P1], ['亡羊补牢'])

    res = apply_wangyang(room, P1)
    assert res.success is True
    assert len(res['cards']) == 7


def test_n_smaller_than_ship_count_takes_all(room):
    """弃牌区比 n 张少时，全部取出。"""
    room.players[P1].remaining_ships = 6
    room.players[P2].remaining_ships = 6
    room.magic_discard = [card('轰炸'), card('冻结')]  # 只有 2 张
    give_hand(room.players[P1], ['亡羊补牢'])

    res = apply_wangyang(room, P1)
    assert res.success is True
    assert len(res['cards']) == 2


# ---------------------------------------------------------------------------
# 候选不含刚打出的亡羊补牢自己
# ---------------------------------------------------------------------------
def test_own_card_not_in_candidates(room, events):
    """刚打出的亡羊补牢自己不应在候选牌里。"""
    room.magic_discard = [card('轰炸'), card('冻结'), card('增援')]
    give_hand(room.players[P1], ['亡羊补牢'])

    res = apply_wangyang(room, P1)
    candidate_names = [c['name'] for c in res['cards']]
    assert '亡羊补牢' not in candidate_names, '候选不应包含刚打出的亡羊补牢自己'
    # 临时数据 own_card 暂存了亡羊补牢自己
    own = room.magic_temp_data.get('own_card')
    assert own is not None and own.name == '亡羊补牢'


# ---------------------------------------------------------------------------
# 候选从末尾取（最新 N 张）
# ---------------------------------------------------------------------------
def test_candidates_are_latest_n(room):
    """候选应当是弃牌区最末尾的 n 张。"""
    # 顺序：[轰炸, 冻结, 增援, 看破！, 饮血] —— 末尾最新
    room.magic_discard = [card('轰炸'), card('冻结'), card('增援'),
                          card('看破！'), card('饮血')]
    give_hand(room.players[P1], ['亡羊补牢'])
    room.players[P1].remaining_ships = 3
    room.players[P2].remaining_ships = 3  # n = 3

    res = apply_wangyang(room, P1)
    candidate_names = [c['name'] for c in res['cards']]
    # 应该是末尾 3 张：增援, 看破！, 饮血
    assert candidate_names == ['增援', '看破！', '饮血']
    # 前两张（轰炸、冻结）应仍在 magic_discard 里
    assert [c.name for c in room.magic_discard] == ['轰炸', '冻结']


# ---------------------------------------------------------------------------
# confirm：选中那张入手牌，其余回堆，亡羊补牢自己也回堆
# ---------------------------------------------------------------------------
def test_confirm_chosen_goes_to_hand(room, events):
    """选中候选 index=1 的牌，应进入施法者手牌。"""
    room.magic_discard = [card('轰炸'), card('冻结'), card('增援')]
    give_hand(room.players[P1], ['亡羊补牢'])
    # P1 现在手牌只有 1 张（亡羊补牢）；apply 后会被扣走，但模拟路径不扣
    res = apply_wangyang(room, P1)
    assert res.success is True

    # 选中候选 index=1（冻结）
    resp = confirm_wangyang(room, P1, 1)
    assert resp['status'] == 'success'
    # 选中那张在手牌里
    hand_names = [c.name for c in room.players[P1].magic_hand]
    assert '冻结' in hand_names
    # 临时数据已清空
    assert room.magic_temp_data == {}


def test_confirm_remaining_return_to_discard(room, events):
    """未选中的候选牌应回归弃牌堆末尾，且按原顺序。"""
    # 候选 = [轰炸, 冻结, 增援]（来自 magic_discard 末尾 3 张）
    room.magic_discard = [card('轰炸'), card('冻结'), card('增援')]
    give_hand(room.players[P1], ['亡羊补牢'])
    res = apply_wangyang(room, P1)
    assert res.success is True

    # 选中 index=1（冻结）
    confirm_wangyang(room, P1, 1)
    # 弃牌堆：应包含未选中的「轰炸」「增援」+ 亡羊补牢自己
    # 顺序：未选中的按原顺序回堆，最后是亡羊补牢自己
    discard_names = [c.name for c in room.magic_discard]
    assert '轰炸' in discard_names
    assert '增援' in discard_names
    assert '冻结' not in discard_names  # 已入手
    # 亡羊补牢自己应在最末尾
    assert discard_names[-1] == '亡羊补牢'


def test_confirm_own_card_returns_to_discard_end(room, events):
    """暂存的亡羊补牢自己应回归弃牌堆末尾。"""
    room.magic_discard = [card('轰炸')]
    give_hand(room.players[P1], ['亡羊补牢'])
    res = apply_wangyang(room, P1)
    assert res.success is True

    confirm_wangyang(room, P1, 0)  # 选中唯一候选「轰炸」
    # 弃牌堆末尾应该是亡羊补牢自己
    assert room.magic_discard[-1].name == '亡羊补牢'
    # 手牌里有「轰炸」
    assert '轰炸' in [c.name for c in room.players[P1].magic_hand]


def test_confirm_broadcasts_to_opponent(room, events):
    """confirm 时应给对手发 wangyang_complete 事件。"""
    room.magic_discard = [card('轰炸'), card('冻结')]
    give_hand(room.players[P1], ['亡羊补牢'])
    apply_wangyang(room, P1)
    confirm_wangyang(room, P1, 0)

    complete = find_emit(events, 'wangyang_complete', to='sid-p2')
    assert len(complete) == 1
    assert complete[0][1]['chosen'] == '轰炸'


def test_confirm_invalid_index_returns_error(room):
    """越界 index 应返回错误，状态不被破坏。"""
    room.magic_discard = [card('轰炸'), card('冻结')]
    give_hand(room.players[P1], ['亡羊补牢'])
    apply_wangyang(room, P1)

    resp = confirm_wangyang(room, P1, 99)
    assert resp['status'] == 'error'
    # 临时数据还在
    assert room.magic_temp_data.get('type') == 'wangyang_choice'


def test_confirm_wrong_owner_returns_error(room):
    """非施法者不能确认选择。"""
    room.magic_discard = [card('轰炸'), card('冻结')]
    give_hand(room.players[P1], ['亡羊补牢'])
    apply_wangyang(room, P1)

    resp = confirm_wangyang(room, P2, 0)  # P2 不是施法者
    assert resp['status'] == 'error'


def test_confirm_without_pending_returns_error(room):
    """没有待处理的亡羊补牢选择时，confirm 应拒绝。"""
    resp = confirm_wangyang(room, P1, 0)
    assert resp['status'] == 'error'


# ---------------------------------------------------------------------------
# cancel：候选 + 自己全部回归弃牌堆
# ---------------------------------------------------------------------------
def test_cancel_restores_discard(room, events):
    """取消选择时，候选牌与暂存的亡羊补牢自己应回归弃牌堆。"""
    room.magic_discard = [card('轰炸'), card('冻结'), card('增援')]
    give_hand(room.players[P1], ['亡羊补牢'])
    apply_wangyang(room, P1)
    # 取消前的弃牌堆：扣牌流程已模拟，自己已 pop 出来 → 此处只剩前 2 张非自己
    # （apply_wangyang 把末尾 3 张取走 + 自己 pop 出来）
    # 所以 magic_discard 当前是 []
    assert room.magic_discard == []

    resp = server.handle_cancel_magic_selection({
        'room_id': room.id, 'player_id': P1,
    })
    assert resp['status'] == 'success'
    # 取消后：候选 3 张 + 自己 1 张全部回归
    discard_names = [c.name for c in room.magic_discard]
    assert sorted(discard_names) == sorted(['轰炸', '冻结', '增援', '亡羊补牢'])
    # 临时数据已清空
    assert room.magic_temp_data == {}
    # 对手收到 wangyang_complete（cancelled）
    complete = find_emit(events, 'wangyang_complete', to='sid-p2')
    assert len(complete) == 1
    assert complete[0][1].get('cancelled') is True


def test_cancel_wrong_owner_returns_error(room):
    """非施法者不能取消。"""
    room.magic_discard = [card('轰炸')]
    give_hand(room.players[P1], ['亡羊补牢'])
    apply_wangyang(room, P1)

    resp = server.handle_cancel_magic_selection({
        'room_id': room.id, 'player_id': P2,
    })
    assert resp['status'] == 'error'


# ---------------------------------------------------------------------------
# 速阶 1 在自己回合的准备阶段可用
# ---------------------------------------------------------------------------
def test_playable_in_preparation_phase(room):
    """准备阶段、自己回合 → can_play_magic_card 返回 True。"""
    room.current_phase = 'preparation'
    room.current_attacker = P1
    room.magic_discard = [card('轰炸')]
    assert server.can_play_magic_card(room, P1, card('亡羊补牢')) is True


def test_not_playable_in_opponent_turn(room):
    """不是自己回合 → can_play_magic_card 返回 False。"""
    room.current_phase = 'preparation'
    room.current_attacker = P2  # 对手回合
    room.magic_discard = [card('轰炸')]
    assert server.can_play_magic_card(room, P1, card('亡羊补牢')) is False


# ---------------------------------------------------------------------------
# 看破 / 禁忌果实反制（沿用 dice_card 的反制模式）
# ---------------------------------------------------------------------------
def test_kanpo_blocks_wangyang(room):
    """看破！生效时，被封锁的玩家不能用亡羊补牢（handler 层拦截）。"""
    room.players[P1].magic_blocked = True
    give_hand(room.players[P1], ['亡羊补牢'])
    room.magic_discard = [card('轰炸')]
    room.current_phase = 'preparation'
    room.current_attacker = P1

    r = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '亡羊补牢', 'speed': 1, 'type': '普通', 'description': ''},
        'targets': {},
    })
    assert r['status'] == 'error'
    assert '看破' in r['message']


def test_forbidden_fruit_blocks_wangyang(room):
    """禁忌果实生效时，非场地非失灵类卡不能发动（按普通卡对待）。"""
    room.field_magic = card('禁忌果实')
    give_hand(room.players[P1], ['亡羊补牢'])
    room.magic_discard = [card('轰炸')]
    room.current_phase = 'preparation'
    room.current_attacker = P1

    assert server.can_play_magic_card(room, P1, card('亡羊补牢')) is False
