# -*- coding: utf-8 -*-
"""命运骰子（判定魔法卡）的回归测试。

按 CLAUDE.md 第 7 节「改卡要同步 4 处」要求覆盖：
  · magic_card.json / magic_cards.js 一致性
  · apply_magic_effect 的判定魔法卡分支
  · 6 个点数的效果结算
  · 弃牌待办的房间级状态生命周期（_action_wait_reason 门禁 + 终局清理）
"""
import json
import os

import pytest

import server
from server import (GameRoom, MagicCard, Player, PlayerShip, Position,
                    room_manager)

P1, P2 = 'p1', 'p2'


# ---------------------------------------------------------------------------
# 基础设施（与 test_all_magic_cards 同口径，便于交叉复用）
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def events(monkeypatch):
    """拦截所有 socket emit，避免需要请求上下文。"""
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    return captured


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def make_room():
    room = GameRoom('test-dice-room')
    room.players[P1] = Player(name='p1', ships=[], attacks=[], remaining_ships=0, sid='sid-p1')
    room.players[P2] = Player(name='p2', ships=[], attacks=[], remaining_ships=0, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'preparation'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 1
    room_manager.rooms[room.id] = room
    return room


def ship(*cells):
    return PlayerShip(positions=[Position(x, y) for x, y in cells], hits=[])


def card(name):
    return MagicCard(name)


def apply_dice(room, caster, roll):
    """固定摇出 roll 点，调用命运骰子结算。"""
    server.random.randint = lambda a, b: roll
    return server.apply_magic_effect(room, caster, card('命运骰子'), {})


def give_deck(room, names):
    room.magic_deck = [card(n) for n in names]


def give_hand(player, names):
    player.magic_hand = [card(n) for n in names]


def find_emit(events, event_name, to=None):
    """从拦截到的事件里挑出指定事件（可选过滤 to）。"""
    out = []
    for ev, data, t, r in events:
        if ev == event_name and (to is None or t == to):
            out.append((ev, data, t, r))
    return out


# ---------------------------------------------------------------------------
# 卡牌定义一致性（JSON 与 JS 必须逐字符一致 —— CLAUDE.md §7）
# ---------------------------------------------------------------------------
def test_card_definition_consistent():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, 'static', 'magic_card.json'), encoding='utf-8') as f:
        json_cards = json.load(f)
    dice_json = [c for c in json_cards if c['name'] == '命运骰子']
    assert len(dice_json) == 1
    dj = dice_json[0]
    assert dj['speed'] == 1
    assert dj['type'] == '判定'

    # JS 文件用对象字面量，简单 substring 校验关键字段一致
    with open(os.path.join(here, 'static', 'magic_cards.js'), encoding='utf-8') as f:
        js_src = f.read()
    assert f'name: "命运骰子"' in js_src
    assert f'speed: {dj["speed"]}' in js_src
    assert f'type: "{dj["type"]}"' in js_src
    # 描述必须逐字符一致
    assert dj['description'] in js_src


def test_dice_card_enters_deck():
    """命运骰子应已进 magic_cards 列表（HIDDEN_CARD_NAMES 不含它）。"""
    names = [c.name for c in server.magic_cards]
    assert '命运骰子' in names
    assert '命运骰子' not in server.HIDDEN_CARD_NAMES


# ---------------------------------------------------------------------------
# 摇骰子：dice_rolled 事件 + 日志
# ---------------------------------------------------------------------------
def test_dice_rolled_broadcast_to_room(room, events):
    res = apply_dice(room, P1, 4)
    dice_events = find_emit(events, 'dice_rolled')
    assert len(dice_events) == 1
    ev, data, t, r = dice_events[0]
    # 广播给整个房间（room=room.id），不是 to=某玩家
    assert r == room.id
    assert data['roll'] == 4
    assert data['caster'] == P1
    assert data['effect_text'] == '自己抽两张牌'
    assert res.success is True


def test_dice_rolled_writes_game_log(room, events):
    apply_dice(room, P1, 2)
    log_events = find_emit(events, 'game_log')
    assert any('命运骰子' in (e[1].get('text') or '') and '2' in (e[1].get('text') or '')
               for e in log_events)


# ---------------------------------------------------------------------------
# 点数 1：复活对方一艘战舰（无沉船则不复活）
# ---------------------------------------------------------------------------
def test_roll_1_revives_opponent_ship(room):
    sunk = ship((3, 3))
    sunk.hits = [Position(3, 3)]  # 已沉
    room.players[P2].ships = [sunk]
    room.players[P2].sunken_ships = [sunk]
    room.players[P2].remaining_ships = 0

    res = apply_dice(room, P1, 1)
    assert res.success is True
    # 复活：hits 清空、remaining_ships +1
    assert sunk.hits == []
    assert room.players[P2].remaining_ships == 1
    assert sunk not in room.players[P2].sunken_ships


def test_roll_1_no_sunken_no_revive(room):
    """对方没有沉船时，摇到1不复活（也不报错）。"""
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].sunken_ships = []
    room.players[P2].remaining_ships = 1
    before = room.players[P2].remaining_ships

    res = apply_dice(room, P1, 1)
    assert res.success is True
    assert room.players[P2].remaining_ships == before


# ---------------------------------------------------------------------------
# 点数 2：对方抽一张牌
# ---------------------------------------------------------------------------
def test_roll_2_opponent_draws_one(room):
    give_deck(room, ['轰炸', '冻结'])
    room.players[P2].magic_hand = []
    before_deck = len(room.magic_deck)

    res = apply_dice(room, P1, 2)
    assert res.success is True
    assert len(room.players[P2].magic_hand) == 1
    assert len(room.magic_deck) == before_deck - 1


def test_roll_2_empty_deck_no_draw(room):
    """牌堆空时，对方未能抽牌（不报错）。"""
    room.magic_deck = []
    room.players[P2].magic_hand = []
    res = apply_dice(room, P1, 2)
    assert res.success is True
    assert room.players[P2].magic_hand == []


def test_roll_2_respects_no_draw_flag(room):
    """无中生有生效期间（no_draw），对方不抽。"""
    give_deck(room, ['轰炸'])
    room.players[P2].magic_hand = []
    room.players[P2].effect_flags.no_draw = True
    apply_dice(room, P1, 2)
    assert room.players[P2].magic_hand == []


# ---------------------------------------------------------------------------
# 点数 3：双方各弃一张（登记待办 + handler 收尾）
# ---------------------------------------------------------------------------
def test_roll_3_starts_discard_pending(room, events):
    give_hand(room.players[P1], ['轰炸'])
    give_hand(room.players[P2], ['冻结'])

    res = apply_dice(room, P1, 3)
    assert res.success is True
    # 房间级待办登记
    assert isinstance(room.pending_dice_discard, dict)
    assert room.pending_dice_discard[P1] is False
    assert room.pending_dice_discard[P2] is False
    # 双方各自收到 dice_discard_request（to=sid）
    req_p1 = find_emit(events, 'dice_discard_request', to='sid-p1')
    req_p2 = find_emit(events, 'dice_discard_request', to='sid-p2')
    assert len(req_p1) == 1
    assert len(req_p2) == 1


def test_roll_3_discard_choose_completes(room, events):
    give_hand(room.players[P1], ['轰炸', '冻结'])
    give_hand(room.players[P2], ['溅射'])

    apply_dice(room, P1, 3)
    # P1 选第一张弃
    r1 = server.handle_dice_discard_choose({
        'room_id': room.id, 'player_id': P1, 'card_index': 0
    })
    assert r1['status'] == 'success'
    assert room.players[P1].magic_hand[0].name == '冻结'  # 剩下第二张
    # 还没完成全部 → 不会广播 dice_discard_complete
    assert not find_emit(events, 'dice_discard_complete')

    # P2 选第一张弃
    r2 = server.handle_dice_discard_choose({
        'room_id': room.id, 'player_id': P2, 'card_index': 0
    })
    assert r2['status'] == 'success'
    assert room.players[P2].magic_hand == []
    # 双方都完成 → 广播 dice_discard_complete + 清掉待办
    assert find_emit(events, 'dice_discard_complete')
    assert room.pending_dice_discard == {}


def test_roll_3_action_wait_reason_blocks_play(room):
    """弃牌待办期间，_action_wait_reason 应拒绝该玩家打牌/攻击。"""
    give_hand(room.players[P1], ['轰炸'])
    give_hand(room.players[P2], ['冻结'])
    apply_dice(room, P1, 3)

    # P1 有未完成弃牌 → 被门禁拦下
    assert server._action_wait_reason(room, P1) is not None
    # P2 同样
    assert server._action_wait_reason(room, P2) is not None


def test_roll_3_no_hand_skips(room, events):
    """无手牌的玩家直接跳过（不弹窗、不要求选择）。"""
    give_hand(room.players[P1], ['轰炸'])
    room.players[P2].magic_hand = []  # P2 无手牌

    apply_dice(room, P1, 3)
    assert room.pending_dice_discard[P2] is True  # P2 已标记完成
    assert room.pending_dice_discard[P1] is False  # P1 仍待选
    # P2 不会收到 dice_discard_request
    assert not find_emit(events, 'dice_discard_request', to='sid-p2')


def test_roll_3_invalid_card_index(room):
    give_hand(room.players[P1], ['轰炸'])
    give_hand(room.players[P2], ['冻结'])
    apply_dice(room, P1, 3)
    r = server.handle_dice_discard_choose({
        'room_id': room.id, 'player_id': P1, 'card_index': 99
    })
    assert r['status'] == 'error'


def test_roll_3_choose_without_pending(room):
    """没有待办时调用 handler 应拒绝。"""
    give_hand(room.players[P1], ['轰炸'])
    r = server.handle_dice_discard_choose({
        'room_id': room.id, 'player_id': P1, 'card_index': 0
    })
    assert r['status'] == 'error'


# ---------------------------------------------------------------------------
# 点数 4：自己抽两张
# ---------------------------------------------------------------------------
def test_roll_4_caster_draws_two(room):
    give_deck(room, ['轰炸', '冻结', '溅射'])
    room.players[P1].magic_hand = []
    res = apply_dice(room, P1, 4)
    assert res.success is True
    assert len(room.players[P1].magic_hand) == 2


def test_roll_4_partial_draw_when_deck_low(room):
    """牌堆只剩1张时，只抽到1张（不报错，文案如实反映）。"""
    give_deck(room, ['轰炸'])
    room.players[P1].magic_hand = []
    res = apply_dice(room, P1, 4)
    assert res.success is True
    assert len(room.players[P1].magic_hand) == 1


# ---------------------------------------------------------------------------
# 点数 5：复活自己至多两艘
# ---------------------------------------------------------------------------
def test_roll_5_revives_self_up_to_two(room):
    s1 = ship((1, 1)); s1.hits = [Position(1, 1)]
    s2 = ship((2, 2)); s2.hits = [Position(2, 2)]
    s3 = ship((3, 3)); s3.hits = [Position(3, 3)]
    room.players[P1].ships = [s1, s2, s3]
    room.players[P1].sunken_ships = [s1, s2, s3]
    room.players[P1].remaining_ships = 0

    res = apply_dice(room, P1, 5)
    assert res.success is True
    # 至多两艘 → remaining_ships +2
    assert room.players[P1].remaining_ships == 2


def test_roll_5_revives_only_available(room):
    """沉船只有1艘时，只复活1艘。"""
    s1 = ship((1, 1)); s1.hits = [Position(1, 1)]
    room.players[P1].ships = [s1]
    room.players[P1].sunken_ships = [s1]
    room.players[P1].remaining_ships = 0

    apply_dice(room, P1, 5)
    assert room.players[P1].remaining_ships == 1


def test_roll_5_no_sunken_no_revive(room):
    room.players[P1].ships = [ship((0, 0))]
    room.players[P1].sunken_ships = []
    room.players[P1].remaining_ships = 1
    before = room.players[P1].remaining_ships

    res = apply_dice(room, P1, 5)
    assert res.success is True
    assert room.players[P1].remaining_ships == before


# ---------------------------------------------------------------------------
# 点数 6：对方牺牲两艘（入队 ship_pick，AI 自动）
# ---------------------------------------------------------------------------
def test_roll_6_queues_two_sacrifices(room):
    """人类对手：摇到6入队两次牺牲待办。"""
    room.players[P2].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P2].remaining_ships = 3

    res = apply_dice(room, P1, 6)
    assert res.success is True
    picks = [p for p in room.pending_ship_picks
             if p.get('player') == P2 and p.get('reason') == 'dice_sacrifice']
    assert len(picks) == 2


def test_roll_6_only_one_alive_ship(room):
    """对方只有1艘活船时，只入队1次（不要求点选不存在的船）。"""
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1

    res = apply_dice(room, P1, 6)
    assert res.success is True
    picks = [p for p in room.pending_ship_picks
             if p.get('player') == P2 and p.get('reason') == 'dice_sacrifice']
    assert len(picks) == 1


def test_roll_6_no_alive_ship(room):
    """对方没有活船时，不入队，也不报错。"""
    room.players[P2].ships = []
    room.players[P2].remaining_ships = 0
    res = apply_dice(room, P1, 6)
    assert res.success is True
    picks = [p for p in room.pending_ship_picks
             if p.get('player') == P2 and p.get('reason') == 'dice_sacrifice']
    assert len(picks) == 0


def test_roll_6_ai_auto_sacrifices(room, monkeypatch):
    """AI 房间里，对方（AI）由 _request_ship_pick 自动选并立即牺牲。"""
    room.is_ai_room = True
    # _ai_player_id 默认按 'ai-' 前缀找；直接给 P2 起个 AI id
    room.players[P2].user_id = None
    monkeypatch.setattr(server, '_ai_player_id', lambda r: P2)
    # 让 random.choice 稳定选第一艘
    monkeypatch.setattr(server.random, 'choice', lambda seq: seq[0])

    room.players[P2].ships = [ship((0, 0)), ship((1, 1))]
    room.players[P2].remaining_ships = 2

    res = apply_dice(room, P1, 6)
    assert res.success is True
    # AI 应已牺牲两艘（_do_demon_contract_sacrifice 立即执行）
    assert room.players[P2].remaining_ships == 0
    # 不应残留待办
    picks = [p for p in room.pending_ship_picks
             if p.get('player') == P2 and p.get('reason') == 'dice_sacrifice']
    assert len(picks) == 0


# ---------------------------------------------------------------------------
# 终局清理：pending_dice_discard 不应残留
# ---------------------------------------------------------------------------
def test_finish_game_clears_dice_discard(room):
    give_hand(room.players[P1], ['轰炸'])
    give_hand(room.players[P2], ['冻结'])
    apply_dice(room, P1, 3)
    assert room.pending_dice_discard  # 有待办

    server._finish_game(room, P1, P2, 'test')
    assert room.pending_dice_discard == {}


# ---------------------------------------------------------------------------
# 判定魔法卡与「禁忌果实」「看破！」的交互（按用户裁定：按普通卡对待）
# ---------------------------------------------------------------------------
def test_jinjing_guoshi_blocks_dice(room):
    """禁忌果实生效时，命运骰子不能用（按普通卡对待）。"""
    room.field_magic = card('禁忌果实')
    assert server.can_play_magic_card(room, P1, card('命运骰子')) is False


def test_kanpo_blocks_dice(room):
    """看破！生效时，被封锁的玩家不能用命运骰子（在 handler 层拦截）。"""
    room.players[P1].magic_blocked = True
    give_hand(room.players[P1], ['命运骰子'])
    # 确保阶段合法（速阶1在自己准备阶段可用），排除其它拒绝原因
    room.current_phase = 'preparation'
    room.current_attacker = P1
    r = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '命运骰子', 'speed': 1, 'type': '判定', 'description': ''},
        'targets': {}
    })
    assert r['status'] == 'error'
    assert '看破' in r['message']


def test_dice_playable_in_preparation(room):
    """正常情况下，速阶1的命运骰子在自己的准备阶段可用。"""
    room.current_phase = 'preparation'
    room.current_attacker = P1
    assert server.can_play_magic_card(room, P1, card('命运骰子')) is True
