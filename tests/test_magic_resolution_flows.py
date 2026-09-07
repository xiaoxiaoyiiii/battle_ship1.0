# -*- coding: utf-8 -*-
"""魔法卡跨回合结算闭环测试（极限增援/无暇圣心/神机妙算/跳过回合/教皇旨意弃卡攻击等）。"""
import pytest

import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def events(monkeypatch):
    captured = []
    monkeypatch.setattr(server, 'emit',
                        lambda event, data, to=None, room=None: captured.append((event, data, to, room)))
    return captured


@pytest.fixture
def room():
    r = GameRoom('test-room')
    r.players[P1] = Player(name='p1', ships=[], attacks=[], remaining_ships=0, sid='sid-p1')
    r.players[P2] = Player(name='p2', ships=[], attacks=[], remaining_ships=0, sid='sid-p2')
    r.state = 'attacking'
    r.current_attacker = P1
    r.current_phase = 'battle'
    r.attack_order = [P1, P2]
    r.attacks_remaining = 6
    r.round = 1
    room_manager.rooms[r.id] = r
    yield r
    room_manager.rooms.pop(r.id, None)


def ship(*cells):
    return PlayerShip(positions=[Position(x, y) for x, y in cells], hits=[])


def card(name):
    return MagicCard(name)


def end_turn(room, pid):
    return server.end_turn({'room_id': room.id, 'player_id': pid})


def new_round_cycle(room):
    """让双方各走完结束阶段，使 end_turn 进入 next_index == 0 的新大回合分支。"""
    room.current_attacker = P1
    room.current_phase = 'end'
    end_turn(room, P1)          # P1 -> P2 准备阶段
    room.current_phase = 'end'  # 当前攻击者已是 P2
    return end_turn(room, P2)   # 触发新大回合结算


# ---------------------------------------------------------------------------
# 极限增援：两个大回合后船数少的一方直接获胜
# ---------------------------------------------------------------------------
def test_jixian_full_resolution_fewer_ships_wins(room):
    server.apply_magic_effect(room, P1, card('极限增援'), {})
    room.players[P1].ships = [ship((0, 0)), ship((1, 1))]
    room.players[P1].remaining_ships = 2
    room.players[P2].ships = [ship((3, 3))]
    room.players[P2].remaining_ships = 1

    # 第一个大回合结束：仅更新倒计时
    new_round_cycle(room)
    assert room.state != 'game_over'
    assert room.game_effects['reinforcement_check']['remaining_turns'] == 1

    # 第二个大回合结束：结算，船少的 P2 获胜
    new_round_cycle(room)
    assert room.state == 'game_over'
    assert room.winner == P2


# ---------------------------------------------------------------------------
# 无暇圣心：两个大回合内双方均未造成伤害，施法者直接获胜
# ---------------------------------------------------------------------------
def test_wuxia_shengxin_full_resolution_caster_wins(room):
    server.apply_magic_effect(room, P1, card('无暇圣心'), {})

    new_round_cycle(room)
    assert room.state != 'game_over'
    assert room.game_effects['holy_heart']['remaining_turns'] == 1

    new_round_cycle(room)
    assert room.state == 'game_over'
    assert room.winner == P1


def test_wuxia_shengxin_no_win_when_damaged(room):
    """造成过伤害则到期不能获胜（no_damage=False 时不推进倒计时）"""
    server.apply_magic_effect(room, P1, card('无暇圣心'), {})
    room.game_effects['holy_heart']['no_damage'] = False

    new_round_cycle(room)
    new_round_cycle(room)
    assert room.state != 'game_over'
    assert room.game_effects['holy_heart']['remaining_turns'] == 2


# ---------------------------------------------------------------------------
# 神机妙算：结束阶段船数减少x时，那些船不减并在原位/安全位重新部署
# ---------------------------------------------------------------------------
def test_shenji_end_phase_restore_predicted_loss(room):
    """文本：对方结束阶段后自己船数减少x，那些船不减并重新部署"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 1))]
    room.players[P1].remaining_ships = 2
    room.magic_temp_data = {'prediction': 1}
    res = server.apply_magic_effect(room, P1, card('神机妙算'), {})
    assert res.success is True

    # 模拟本大回合内 P1 损失一艘船
    lost = room.players[P1].ships.pop()
    room.players[P1].sunken_ships.append(lost)
    room.players[P1].remaining_ships -= 1

    new_round_cycle(room)
    # 预言命中：船数恢复
    assert len(room.players[P1].ships) == 2
    assert room.players[P1].remaining_ships == 2
    assert room.players[P1].sunken_ships == []
    assert room.players[P1].effect_flags.prediction == 0


def test_shenji_prediction_miss_keeps_loss(room):
    room.players[P1].ships = [ship((0, 0)), ship((1, 1))]
    room.players[P1].remaining_ships = 2
    room.magic_temp_data = {'prediction': 2}  # 宣言减2，实际只减1
    server.apply_magic_effect(room, P1, card('神机妙算'), {})

    lost = room.players[P1].ships.pop()
    room.players[P1].sunken_ships.append(lost)
    room.players[P1].remaining_ships -= 1

    new_round_cycle(room)
    assert len(room.players[P1].ships) == 1


# ---------------------------------------------------------------------------
# Freezing！/神之宣告：跳过对方整个回合
# ---------------------------------------------------------------------------
def test_freezing_full_skip_back_to_caster(room):
    res = server.apply_magic_effect(room, P1, card('Freezing！'), {})
    assert res.success is True

    room.current_attacker = P1
    room.current_phase = 'end'
    end_turn(room, P1)
    # P2 的回合被跳过，直接回到 P1 的准备阶段
    assert room.current_attacker == P1
    assert room.current_phase == 'preparation'


def test_shenzhi_option2_full_skip(room):
    room.players[P1].ships = [ship((0, 0)), ship((1, 1))]
    room.players[P1].remaining_ships = 2
    room.magic_temp_data = {'effect_choice': 2}
    server.apply_magic_effect(room, P1, card('神之宣告'), {})

    room.current_attacker = P1
    room.current_phase = 'end'
    end_turn(room, P1)
    assert room.current_attacker == P1
    assert room.current_phase == 'preparation'


# ---------------------------------------------------------------------------
# 教皇旨意：弃置一张魔法卡攻击对方两次
# ---------------------------------------------------------------------------
def test_jiaohuang_papal_attack_two_hits(room):
    """教皇旨意下弃置一张魔法卡攻击对方两次（papal_edict 标志闸门可用）"""
    server.apply_magic_effect(room, P1, card('教皇旨意'), {})
    room.players[P1].magic_hand = [card('冻结')]
    # 目标为 2 格船：弃卡攻击同一格两次 => 两次命中应击沉
    room.players[P2].ships = [ship((2, 2), (2, 3))]
    room.players[P2].remaining_ships = 1

    res = server.handle_papal_attack({
        'room_id': room.id, 'player_id': P1,
        'x': 2, 'y': 2, 'discard_card_index': 0
    })
    assert res['status'] == 'success'
    assert room.players[P1].magic_hand == []
    assert room.players[P2].remaining_ships == 0


def test_jiaohuang_papal_attack_requires_card(room):
    room.game_effects['papal_edict'] = True
    room.field_magic = card('教皇旨意')
    room.players[P1].magic_hand = []
    res = server.handle_papal_attack({
        'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 0
    })
    assert res['status'] == 'error'


# ---------------------------------------------------------------------------
# 桃园结义：n=1 时优先给自己摸到的那张牌
# ---------------------------------------------------------------------------
def test_taoyuan_single_ship_gives_self(room):
    room.magic_deck = [card('轰炸'), card('冻结')]
    room.players[P1].ships = [ship((0, 0))]
    room.players[P1].remaining_ships = 1

    res = server.apply_magic_effect(room, P1, card('桃园结义'), {})
    assert res.success is True
    assert len(room.magic_temp_data['cards']) == 1

    ok = server.confirm_magic_target({
        'room_id': room.id, 'player_id': P1,
        'temp_data_id': 'taoyuan_choice',
        'target_data': {'caster_choice': 0}
    })
    assert ok['status'] == 'success'
    assert [c.name for c in room.players[P1].magic_hand] == ['轰炸']
    assert room.players[P2].magic_hand == []


# ---------------------------------------------------------------------------
# 回光返照：使用后进入重摆阶段且本回合战斗阶段被跳过
# ---------------------------------------------------------------------------
def test_huiguang_skips_own_battle_phase(room):
    room.players[P1].ships = [ship((0, 0))]
    room.players[P1].remaining_ships = 1
    server.apply_magic_effect(room, P1, card('回光返照'), {})
    assert room.current_phase == 'end'
    assert room.players[P1].needs_reset is True


# ---------------------------------------------------------------------------
# 败者食尘/灵气复苏后保留手牌且进入摆船阶段（闭环校验）
# ---------------------------------------------------------------------------
def test_baizhe_then_place_ships_flow(room):
    room.players[P1].magic_hand = [card('轰炸')]
    room.players[P2].magic_hand = [card('冻结')]
    room.players[P1].ships = [ship((0, 0))]
    room.players[P1].remaining_ships = 1
    room.players[P2].ships = [ship((1, 1)), ship((2, 2))]
    room.players[P2].remaining_ships = 2

    server.apply_magic_effect(room, P1, card('败者食尘'), {})
    assert room.state == 'placing_ships'
    assert room.players[P1].max_ships == 2  # 互换后的新船数上限
    assert room.players[P2].max_ships == 1
    assert len(room.players[P1].magic_hand) == 1


# ---------------------------------------------------------------------------
# 冻结：扣减攻击次数与到期解冻（修复后的行为回归）
# ---------------------------------------------------------------------------
def test_dongjie_reduces_attack_count_and_thaws(room):
    """被冻结的船不计入攻击次数；冻结跨本大回合+下一大回合后解除"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3
    server.apply_magic_effect(room, P2, card('冻结'),
                              {'target_area': {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}})
    assert all(getattr(s, 'frozen', None) for s in room.players[P1].ships)

    # 回合切换到 P1：3 艘全冻结 => 攻击次数为 0（文本：总攻击次数减去被冻结的船数）
    room.attack_order = [P2, P1]
    room.current_attacker = P2
    room.current_phase = 'end'
    end_turn(room, P2)
    assert room.current_attacker == P1
    assert room.attacks_remaining == 0

    # 走完一个大回合（下一大回合仍冻结）
    room.current_phase = 'end'
    end_turn(room, P1)
    assert all(getattr(s, 'frozen', None) for s in room.players[P1].ships)
    room.current_attacker = P2
    room.current_phase = 'end'
    end_turn(room, P2)

    # 再走一个大回合（第三大回合开始时解冻）
    room.current_phase = 'end'
    end_turn(room, P1)
    assert all(getattr(s, 'frozen', None) is None for s in room.players[P1].ships)


# ---------------------------------------------------------------------------
# 神威！：除外战舰在下一大回合开始时回归（修复后的行为回归）
# ---------------------------------------------------------------------------
def test_shenwei_excluded_ships_return_next_round(room):
    room.players[P2].ships = [ship((0, 0)), ship((2, 2)), ship((5, 5))]
    room.players[P2].remaining_ships = 3
    server.apply_magic_effect(room, P1, card('神威！'),
                              {'target_area': {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}})
    assert len(room.players[P2].ships) == 1
    assert len(room.game_effects['excluded_ships']['ships']) == 2

    # 走完一个大回合：P1 结束 -> P2 结束（触发新大回合分支）
    room.current_attacker = P1
    room.current_phase = 'end'
    end_turn(room, P1)
    room.current_phase = 'end'
    end_turn(room, P2)

    assert len(room.players[P2].ships) == 3
    assert room.players[P2].remaining_ships == 3
    assert 'excluded_ships' not in room.game_effects


# ---------------------------------------------------------------------------
# 绝处逢生：手牌保留 + 生效回合内其余魔法卡无效（修复后的行为回归）
# ---------------------------------------------------------------------------
def test_juechu_keeps_hand_and_blocks_other_cards(room):
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3
    room.players[P1].magic_hand = [card('轰炸')]

    server.apply_magic_effect(room, P1, card('绝处逢生'), {})
    # 文本仅要求生效回合内其余魔法卡无效，不再清空手牌
    assert [c.name for c in room.players[P1].magic_hand] == ['轰炸']
    assert server.can_play_magic_card(room, P1, card('轰炸')) is False

    # 模拟回合切换的标志重置后，禁卡解除（last_stand 随临时标志自然过期）
    room.players[P1].effect_flags.__dict__ = {}
    assert server.can_play_magic_card(room, P1, card('轰炸')) is True


# ---------------------------------------------------------------------------
# 连锁服务端超时兜底（修复后的行为回归）
# ---------------------------------------------------------------------------
def test_chain_timeout_auto_resolves(monkeypatch, room):
    """对端未响应连锁时，超时后服务端自动结算"""
    monkeypatch.setattr(server.time, 'sleep', lambda s: None)
    monkeypatch.setattr(server.socketio, 'start_background_task',
                        lambda target, *a, **k: target(*a))

    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1
    room.chain.append(server.ChainItem(
        P1, card('轰炸'), {'target_line': {'type': 'row', 'index': 0}}, 0))
    room.chain_waiting = True
    room.chain_timer += 1

    server._schedule_chain_timeout(room.id, room.chain_timer)
    # 超时回调已同步执行：连锁被结算、等待标志清除
    assert room.chain_waiting is False
    assert room.chain == []
    assert room.players[P2].remaining_ships == 0


def test_chain_timeout_stale_token_noop(monkeypatch, room):
    """代际令牌失配的旧定时器不会重复结算"""
    monkeypatch.setattr(server.time, 'sleep', lambda s: None)
    monkeypatch.setattr(server.socketio, 'start_background_task',
                        lambda target, *a, **k: target(*a))

    room.chain.append(server.ChainItem(P1, card('余音绕梁'), {}, 0))
    room.chain_waiting = True
    room.chain_timer += 1

    server._schedule_chain_timeout(room.id, room.chain_timer - 1)  # 旧令牌
    assert room.chain_waiting is True
    assert len(room.chain) == 1
