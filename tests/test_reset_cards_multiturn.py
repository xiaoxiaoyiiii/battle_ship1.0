# -*- coding: utf-8 -*-
"""跨回合效果遇到「重摆棋盘」卡牌时的残留问题（2026-09-20）。

作者实测症状：**极限增援 / 无暇圣心等持续多回合的卡牌，在经过败者食尘、
灵气复苏等重置棋盘的卡牌之后将会出现问题。**

根因（读码确认）：三张重摆卡对 `game_effects` 的处理**互不一致** ——

| 卡 | 处理 | 后果 |
| --- | --- | --- |
| 败者食尘 | `_clear_board_effects()` 后 `game_effects = {}` | 清了，但**没通知前端**（角标永远挂着） |
| 灵气复苏 | 只调 `_clear_board_effects()` | `holy_heart`/`reinforcement_check` **残留** |
| 回光返照 | 只清自己那半边 | 同上 |
| 绝处逢生 | 只清自己那半边 | 同上 |

`_clear_board_effects` 只覆盖**范围类**（神威洞 / 冻结区），**不管计数类**
（`holy_heart` / `reinforcement_check` / `demon_contract` / `prediction`）。

残留的后果不只是显示问题 —— 那两个效果的 `remaining_turns` 会继续递减，
到 0 时**凭空判某人获胜**（holy_heart → 施法者胜；reinforcement → 船少的一方胜）。

本文件断言：重摆后 `game_effects` 里**不许有**跨回合计数类残留，
且**必须**给前端发过对应的清除事件。
"""
import itertools

import pytest

import server
from server import GameRoom, Player, PlayerShip, Position

_seq = itertools.count(1)

# 跨回合「计数类」效果的键（与实现里的名单同源）。
MULTITURN_KEYS = ('holy_heart', 'reinforcement_check')


def _mk_room():
    room = GameRoom('reset-test')
    room.round = 3
    room.state = 'attacking'
    room.current_phase = 'preparation'
    room.attack_order = ['p1', 'p2']
    room.current_attacker = 'p1'
    room.players = {
        'p1': Player('甲', [], [], 2, user_id='u1', sid='sid-1'),
        'p2': Player('乙', [], [], 2, user_id='u2', sid='sid-2'),
    }
    # 给双方各一艘船，避免"空棋盘"干扰别的判据
    for pid in ('p1', 'p2'):
        room.players[pid].ships = [PlayerShip([Position(0, 0)], [])]
        room.players[pid].remaining_ships = 1
    return room


def _capture(monkeypatch):
    sent = []

    def fake_emit(event, data, to=None, room=None):
        sent.append({'name': event, 'data': data, 'to': to, 'room': room})

    monkeypatch.setattr(server, 'emit', fake_emit)
    return sent


def _seed_multiturn(room, caster='p1'):
    """挂上两个跨回合计数效果（模拟刚打出极限增援 + 无暇圣心）。"""
    room.game_effects['reinforcement_check'] = {
        'caster': caster, 'activated_round': room.round, 'remaining_turns': 2,
    }
    room.game_effects['holy_heart'] = {
        'caster': caster, 'remaining_turns': 2, 'no_damage': True,
    }


# ===========================================================================
# ★ 核心：重摆后不许残留跨回合效果
# ===========================================================================
@pytest.mark.parametrize('why', ['灵气复苏', '败者食尘', '回光返照', '绝处逢生'])
def test_multiturn_effects_cleared_by_reset(why, monkeypatch):
    """★ 四张重摆卡之后，跨回合计数效果**一律不许残留**。"""
    room = _mk_room()
    _seed_multiturn(room)
    _capture(monkeypatch)

    server._clear_multiturn_effects(room, why)

    for key in MULTITURN_KEYS:
        assert key not in room.game_effects, (
            f'{why} 之后 {key} 仍残留 → 它会在后续大回合继续递减并凭空判胜负'
        )


def test_clear_emits_events_to_frontend(monkeypatch):
    """★ 清掉效果时**必须通知前端**。

    否则前端收到过 `holy_heart_activated` / `reinforcement_activated`，
    却永远等不到"清掉"的事件 → 角标一直亮着，玩家以为效果还在。
    """
    room = _mk_room()
    _seed_multiturn(room)
    sent = _capture(monkeypatch)
    server._clear_multiturn_effects(room, '灵气复苏')

    names = [e['name'] for e in sent]
    assert any('holy_heart' in n for n in names), \
        f'必须通知前端无暇圣心已清除，实际发出: {names}'
    assert any('reinforcement' in n for n in names), \
        f'必须通知前端极限增援已清除，实际发出: {names}'


def test_clear_is_idempotent(monkeypatch):
    """幂等：没有效果时调用不许抛、也不许白发事件。"""
    room = _mk_room()
    sent = _capture(monkeypatch)
    server._clear_multiturn_effects(room, '灵气复苏')
    server._clear_multiturn_effects(room, '灵气复苏')
    assert not sent, '无事不该发事件'


def test_clear_never_raises_on_garbage():
    """脏输入不许抛（失败开放）。"""
    server._clear_multiturn_effects(None, 'x')
    room = _mk_room()
    room.game_effects = 'not-a-dict'
    server._clear_multiturn_effects(room, 'x')


# ===========================================================================
# ★ 后果验证：残留会让后续大回合凭空判胜负
# ===========================================================================
def test_leaked_holy_heart_would_decide_match(monkeypatch):
    """★ 反证：若 holy_heart 残留，下一个大回合它会**凭空判施法者获胜**。

    这是"残留在实战里到底坏在哪"的直接演示 —— 不只是显示问题。
    """
    room = _mk_room()
    room.game_effects['holy_heart'] = {
        'caster': 'p1', 'remaining_turns': 0, 'no_damage': True,
    }
    _capture(monkeypatch)
    # 模拟大回合轮转时的那段判断（与 end_turn 内联逻辑同形）
    check = room.game_effects['holy_heart']
    if check['no_damage'] and check['remaining_turns'] <= 0:
        room.state = 'game_over'
        room.winner = check['caster']
    assert room.state == 'game_over' and room.winner == 'p1', \
        '残留的 holy_heart 确实会凭空判胜 —— 这就是必须清掉它的原因'


def test_after_clear_no_phantom_win(monkeypatch):
    """★ 清掉之后就不会再有凭空判胜。"""
    room = _mk_room()
    room.game_effects['holy_heart'] = {
        'caster': 'p1', 'remaining_turns': 0, 'no_damage': True,
    }
    _capture(monkeypatch)
    server._clear_multiturn_effects(room, '灵气复苏')
    assert 'holy_heart' not in room.game_effects
    assert room.state == 'attacking', '清掉后不该有任何终局状态'
    # `GameRoom.winner` 的默认值是空串（不是 None）—— 判"没判胜"要看它是空
    assert not room.winner, f'不该有胜者，实际 winner={room.winner!r}'


# ===========================================================================
# 不许误伤：范围类效果与无关状态不受影响
# ===========================================================================
def test_does_not_clear_unrelated_effects(monkeypatch):
    """不许顺手清掉不在名单里的东西（比如回合级标记）。"""
    room = _mk_room()
    _seed_multiturn(room)
    room.game_effects['no_draw'] = True          # 这是别的机制的标记
    _capture(monkeypatch)
    server._clear_multiturn_effects(room, '灵气复苏')
    assert room.game_effects.get('no_draw') is True, \
        '不在名单里的效果不该被顺手清掉'


def test_clear_board_effects_still_works(monkeypatch):
    """反向守卫：既有的范围类清理（神威洞 / 冻结区）不许被改坏。"""
    room = _mk_room()
    server._add_shenwei_hole(room, 'p1', {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}, 9)
    room.game_effects['frozen_area'] = {'owner': 'p1', 'until_round': 9}
    sent = _capture(monkeypatch)
    server._clear_board_effects(room, ['p1'], '灵气复苏')
    assert not room.game_effects.get('shenwei_holes'), '神威洞该被清掉'
    assert 'frozen_area' not in room.game_effects, '冻结区该被清掉'
    names = [e['name'] for e in sent]
    assert 'shenwei_hole_restored' in names and 'frozen_area' in names
