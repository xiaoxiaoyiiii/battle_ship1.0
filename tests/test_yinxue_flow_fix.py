# -*- coding: utf-8 -*-
"""饮血「通过」流程修复的回归测试（2026-09-14）。

玩家实测报的问题：
  打沉对方一艘船 → 又打了一个空格 → 使用饮血
  → 弹出「无法使用饮血」，但牌从手牌里消失了。

拆成三个独立缺陷：

【缺陷 1 · 牌被吞掉】
  `handle_use_magic_card` 先把牌移出手牌、塞进弃牌堆，再压进连锁栈；
  而「需要自己上一发攻击」的条件要到 `apply_magic_effect` 结算时才判 ——
  那时牌已经离手，失败也不会退还。所以玩家看到「无法使用」+ 牌没了。
  溅射 / 雷达子弹 走的是同一条路，同样中招。

【缺陷 2 · 发动条件口径】
  饮血原实现判 `last_attack['hit']`（击中），但卡面后半句是「每击杀一艘船
  摸一张牌」。打中一艘没沉的船就以为自己能发动，实际什么都不会发生。
  经与作者确认，收紧为「击沉」，并同步了 magic_card.json / magic_cards.js 卡面。

【缺陷 3 · 漏算刚打完的那一发】
  饮血是在击沉之后才打出的。若只对"以后的击杀"生效，玩家会觉得自己刚打沉的
  那艘白沉了。改为发动时立刻为那一艘补摸一张（每张饮血只补一次）。
"""
import pytest

import server
from server import ChainItem, GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

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


def give_deck(room, names):
    room.magic_deck = [card(n) for n in names]


def use(room, caster, name, targets=None):
    """走真实的出牌入口（不是直接调 apply_magic_effect）。"""
    return server.handle_use_magic_card({
        'room_id': room.id, 'player_id': caster,
        'card': {'name': name}, 'targets': targets or {},
    })


# ---------------------------------------------------------------------------
# 缺陷 1：条件不满足时不得扣牌
# ---------------------------------------------------------------------------
def test_yinxue_after_miss_does_not_consume_card(room):
    """复现玩家实测：打沉一艘 → 又打空 → 用饮血。

    旧行为：返回「无法使用饮血」，但牌已经进了弃牌堆。
    正确行为：出牌被拒，牌【留在手牌里】。
    """
    room.players[P1].magic_hand = [card('饮血')]
    # 最后一下打空了（这一发覆盖了之前那次击沉）
    room.last_attack = {'attacker': P1, 'x': 3, 'y': 3, 'hit': False,
                        'ship_sunk': False, 'round': room.round}

    res = use(room, P1, '饮血')

    assert res.get('status') == 'error', res
    assert '饮血' in res['message']
    hand = [c.name for c in room.players[P1].magic_hand]
    assert hand == ['饮血'], f'被拒时牌必须留在手牌里，实际手牌：{hand}'
    assert not any(c.name == '饮血' for c in room.magic_discard), '牌不该进弃牌堆'


def test_yinxue_without_any_attack_does_not_consume_card(room):
    """一次都没打过时同样不扣牌。"""
    room.players[P1].magic_hand = [card('饮血')]
    room.last_attack = None

    res = use(room, P1, '饮血')
    assert res.get('status') == 'error', res
    assert [c.name for c in room.players[P1].magic_hand] == ['饮血']


def test_yinxue_after_hit_but_not_sunk_does_not_consume_card(room):
    """只命中、没击沉 → 不满足新口径，同样不扣牌。"""
    room.players[P1].magic_hand = [card('饮血')]
    room.last_attack = {'attacker': P1, 'x': 1, 'y': 1, 'hit': True,
                        'ship_sunk': False, 'round': room.round}

    res = use(room, P1, '饮血')
    assert res.get('status') == 'error', res
    assert [c.name for c in room.players[P1].magic_hand] == ['饮血']


def test_yinxue_from_opponent_attack_does_not_consume_card(room):
    """last_attack 是对方打出的 → 不算"自己上一发"，不扣牌。"""
    room.players[P1].magic_hand = [card('饮血')]
    room.last_attack = {'attacker': P2, 'x': 2, 'y': 2, 'hit': True,
                        'ship_sunk': True, 'round': room.round}

    res = use(room, P1, '饮血')
    assert res.get('status') == 'error', res
    assert [c.name for c in room.players[P1].magic_hand] == ['饮血']


def test_splash_after_miss_does_not_consume_card(room):
    """溅射同样"先扣牌后判定"，一并修好。"""
    room.players[P1].magic_hand = [card('溅射')]
    room.last_attack = {'attacker': P1, 'x': 3, 'y': 3, 'hit': False,
                        'ship_sunk': False, 'round': room.round}

    res = use(room, P1, '溅射')
    assert res.get('status') == 'error', res
    assert [c.name for c in room.players[P1].magic_hand] == ['溅射']


def test_radar_bullet_after_miss_does_not_consume_card(room):
    """雷达子弹同理。"""
    room.players[P1].magic_hand = [card('雷达子弹')]
    room.last_attack = {'attacker': P1, 'x': 3, 'y': 3, 'hit': False,
                        'ship_sunk': False, 'round': room.round}

    res = use(room, P1, '雷达子弹')
    assert res.get('status') == 'error', res
    assert [c.name for c in room.players[P1].magic_hand] == ['雷达子弹']


def test_splash_after_hit_still_enters_chain(room):
    """反证：命中后溅射照常可出（别把正常路径改坏）。"""
    room.players[P1].magic_hand = [card('溅射')]
    room.last_attack = {'attacker': P1, 'x': 3, 'y': 3, 'hit': True,
                        'ship_sunk': False, 'round': room.round}

    res = use(room, P1, '溅射')
    assert res.get('status') == 'success', res
    # 速阶2 无人可响应，出牌后连锁会立刻结算完 —— 断言牌确实被消耗掉了
    assert not any(c.name == '溅射' for c in room.players[P1].magic_hand), '出牌成功应移出手牌'


# ---------------------------------------------------------------------------
# 缺陷 2 + 3：发动条件与「补算刚打完的那一发」
# ---------------------------------------------------------------------------
def test_yinxue_after_kill_draws_immediately(room):
    """核心需求：击沉一艘后用饮血 → 立刻摸一张（刚打沉的那艘也算）。"""
    room.players[P1].magic_hand = [card('饮血')]
    give_deck(room, ['冻结'])
    room.players[P1].magic_hand = []          # 清空，便于断言摸到的牌
    room.players[P1].magic_hand = [card('饮血')]
    room.last_attack = {'attacker': P1, 'x': 0, 'y': 0, 'hit': True,
                        'ship_sunk': True, 'round': room.round}

    res = use(room, P1, '饮血')
    assert res.get('status') == 'success', res

    server.resolve_chain(room)               # 结算连锁
    assert room.players[P1].effect_flags.vampire is True
    names = [c.name for c in room.players[P1].magic_hand]
    assert '冻结' in names, f'应为刚击沉的那艘补摸一张，实际手牌：{names}'


def test_yinxue_immediate_draw_emits_message(room, events):
    """补摸时要有明确提示，玩家才知道发生了什么。"""
    room.players[P1].magic_hand = [card('饮血')]
    give_deck(room, ['冻结'])
    room.last_attack = {'attacker': P1, 'x': 0, 'y': 0, 'hit': True,
                        'ship_sunk': True, 'round': room.round}

    use(room, P1, '饮血')
    server.resolve_chain(room)

    texts = [d.get('text', '') for e, d, to, r in events if e == 'message']
    assert any('饮血' in t for t in texts), f'应有饮血提示，实际：{texts}'


def test_yinxue_immediate_draw_only_once(room):
    """补摸只发生一次：同一张饮血不会每次结算都再摸一张。"""
    room.players[P1].magic_hand = [card('饮血'), card('饮血')]
    give_deck(room, ['冻结', '轰炸', '增援'])
    room.last_attack = {'attacker': P1, 'x': 0, 'y': 0, 'hit': True,
                        'ship_sunk': True, 'round': room.round}

    server.apply_magic_effect(room, P1, card('饮血'), {})
    first = len(room.players[P1].magic_hand)

    # 再来一张饮血：仍应只补一张（对应它自己的那次击沉）
    server.apply_magic_effect(room, P1, card('饮血'), {})
    second = len(room.players[P1].magic_hand)
    assert second == first + 1, f'每张饮血只补一次，{first} -> {second}'


def test_yinxue_still_draws_on_later_kills(room):
    """补算之后，「接下来每击杀一艘船摸一张」的持续效果照常生效。"""
    room.players[P1].magic_hand = [card('饮血')]
    give_deck(room, ['冻结'])
    room.last_attack = {'attacker': P1, 'x': 0, 'y': 0, 'hit': True,
                        'ship_sunk': True, 'round': room.round}
    use(room, P1, '饮血')
    server.resolve_chain(room)
    assert room.players[P1].effect_flags.vampire is True

    # 之后击杀一艘
    give_deck(room, ['增援'])
    room.players[P2].ships = [ship((5, 5))]
    room.players[P2].remaining_ships = 1
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 5, 'y': 5})

    names = [c.name for c in room.players[P1].magic_hand]
    assert '增援' in names, f'后续击杀应继续摸牌，实际手牌：{names}'


def test_yinxue_flag_not_set_when_rejected(room):
    """被拒时不得留下 vampire 标记（否则白送持续效果）。"""
    room.players[P1].magic_hand = [card('饮血')]
    room.last_attack = {'attacker': P1, 'x': 0, 'y': 0, 'hit': False,
                        'ship_sunk': False, 'round': room.round}

    use(room, P1, '饮血')
    assert room.players[P1].effect_flags.vampire is False


# ---------------------------------------------------------------------------
# 参数化：三张卡在各阶段都不该被吞
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('name', ['饮血', '溅射', '雷达子弹'])
def test_dependent_cards_never_swallowed(room, name):
    """未满足条件时，三张卡都必须原样留在手牌。"""
    room.players[P1].magic_hand = [card(name)]
    room.last_attack = None

    res = use(room, P1, name)
    assert res.get('status') == 'error', res
    assert [c.name for c in room.players[P1].magic_hand] == [name]
    assert not any(c.name == name for c in room.magic_discard)
