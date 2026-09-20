# -*- coding: utf-8 -*-
"""按照魔法卡文本描述对后端效果进行全量回归测试。

每张卡至少一个用例，断言以卡面文本描述为准；
与文本不符的已知实现偏差用 xfail 标注并说明原因。
"""
import pytest

import server
from server import (ChainItem, GameRoom, MagicCard, Player, PlayerShip,
                    Position, room_manager)

P1, P2 = 'p1', 'p2'


# ---------------------------------------------------------------------------
# 基础设施
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
    room = GameRoom('test-room')
    room.players[P1] = Player(name='p1', ships=[], attacks=[], remaining_ships=0, sid='sid-p1')
    room.players[P2] = Player(name='p2', ships=[], attacks=[], remaining_ships=0, sid='sid-p2')
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


def apply(room, caster, name, target=None):
    return server.apply_magic_effect(room, caster, card(name), target or {})


def give_deck(room, names):
    room.magic_deck = [card(n) for n in names]


def give_hand(player, names):
    player.magic_hand = [card(n) for n in names]


def attack(room, attacker, x, y):
    """直接调用服务端 attack 事件处理函数。"""
    return server.handle_attack({
        'room_id': room.id, 'player_id': attacker, 'x': x, 'y': y
    })


# ---------------------------------------------------------------------------
# 失灵！
# ---------------------------------------------------------------------------
def test_shiling_negates_opponent_last_magic(room):
    """无效化对方使用的上一张魔法卡"""
    room.magic_history = [{'card': card('轰炸'), 'caster': P2}]
    res = apply(room, P1, '失灵！')
    assert res.success is True
    assert room.magic_history == []
    assert res.negated['card'].name == '轰炸'


def test_shiling_fails_without_target(room):
    res = apply(room, P1, '失灵！')
    assert res.success is False


def test_shiling_cannot_negate_gabriel_light(room):
    """加百列之光不受'失灵'影响"""
    room.magic_history = [{'card': card('加百列之光'), 'caster': P2}]
    res = apply(room, P1, '失灵！')
    assert res.success is False
    assert len(room.magic_history) == 1


def test_shiling_integration_history_written(room):
    """真实使用一张魔法卡后，历史记录应被写入（供失灵！/盗亦有道/加百列之光使用）"""
    give_hand(room.players[P1], ['轰炸'])
    server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '轰炸', 'speed': 2, 'type': '普通',
                 'description': ''},
        'targets': {'target_line': {'type': 'row', 'index': 0}}
    })
    assert len(room.magic_history) > 0


# ---------------------------------------------------------------------------
# 溅射
# ---------------------------------------------------------------------------
def test_jianshe_damages_four_neighbors(room):
    """击中格子的上下左右四格造成同等伤害"""
    room.players[P2].ships = [ship((3, 2))]
    room.players[P2].remaining_ships = 1
    room.last_attack = {'attacker': P1, 'x': 3, 'y': 3, 'hit': True}

    res = apply(room, P1, '溅射')
    assert res.success is True
    hit_pos = [(p.x, p.y) for p in res['affected_positions'] if p.hit]
    assert (3, 2) in hit_pos
    # 单格战舰应被击沉
    assert room.players[P2].remaining_ships == 0
    assert len(room.players[P2].sunken_ships) == 1


def test_jianshe_requires_prior_hit(room):
    res = apply(room, P1, '溅射')
    assert res.success is False
    room.last_attack = {'attacker': P2, 'x': 1, 'y': 1, 'hit': True}
    res = apply(room, P1, '溅射')
    assert res.success is False


def test_jianshe_bypasses_invincible(room):
    """文本: 溅射伤害不受'无敌'影响 => 无敌船也应被击杀"""
    s = ship((3, 2))
    s.invincible = True
    room.players[P2].ships = [s]
    room.players[P2].remaining_ships = 1
    room.last_attack = {'attacker': P1, 'x': 3, 'y': 3, 'hit': True}
    apply(room, P1, '溅射')
    assert room.players[P2].remaining_ships == 0


def test_jianshe_shield_blocks_once(room):
    """护盾抵挡一次溅射伤害"""
    s = ship((3, 2))
    s.shield = True
    room.players[P2].ships = [s]
    room.players[P2].remaining_ships = 1
    room.last_attack = {'attacker': P1, 'x': 3, 'y': 3, 'hit': True}
    apply(room, P1, '溅射')
    assert s.shield is False
    assert room.players[P2].remaining_ships == 1


# ---------------------------------------------------------------------------
# 雷达子弹
# ---------------------------------------------------------------------------
def test_radar_bullet_reveals_eight_cells(room):
    """对击中位置周围八格扫描并显形"""
    room.players[P2].ships = [ship((3, 2))]
    room.players[P2].remaining_ships = 1
    room.last_attack = {'attacker': P1, 'x': 3, 'y': 3, 'hit': True}

    res = apply(room, P1, '雷达子弹')
    assert res.success is True
    revealed = {(p.x, p.y) for p in room.players[P1].revealed_positions}
    expected = {(3 + dx, 3 + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - {(3, 3)}
    assert expected == revealed


def test_radar_bullet_requires_hit(room):
    room.last_attack = {'attacker': P1, 'x': 0, 'y': 0, 'hit': False}
    res = apply(room, P1, '雷达子弹')
    assert res.success is False


# ---------------------------------------------------------------------------
# 越战越勇
# ---------------------------------------------------------------------------
def test_yuezhan_requires_sunk(room):
    """仅可在击沉对方一艘战舰后立即使用"""
    room.last_attack = {'attacker': P1, 'x': 0, 'y': 0, 'hit': True, 'ship_sunk': False}
    res = apply(room, P1, '越战越勇')
    assert res.success is False


def test_yuezhan_sets_flag(room):
    room.last_attack = {'attacker': P1, 'x': 0, 'y': 0, 'hit': True, 'ship_sunk': True}
    res = apply(room, P1, '越战越勇')
    assert res.success is True
    assert room.players[P1].effect_flags.battle_spirit is True


def test_yuezhan_grants_one_extra_attack(room):
    """击沉敌舰后使用，此后每次击沉攻击次数净增加1"""
    room.players[P2].ships = [ship((0, 0)), ship((1, 1))]
    room.players[P2].remaining_ships = 2
    attack(room, P1, 0, 0)  # 击沉第一艘
    apply(room, P1, '越战越勇')
    before = room.attacks_remaining
    attack(room, P1, 1, 1)  # 再次击沉 => 净+1（本次消耗1次，增加2次为偏差）
    assert room.attacks_remaining == before - 1 + 1


# ---------------------------------------------------------------------------
# 余音绕梁
# ---------------------------------------------------------------------------
def test_yuyin_forced_kill_next_attacks(room):
    """生效后接下来的攻击强制击杀（可杀无敌/盾牌），且按攻击阶段而非击杀次数计数"""
    # 卡面：只能在自己的准备阶段使用
    room.current_phase = 'preparation'
    apply(room, P1, '余音绕梁')
    assert room.players[P1].effect_flags.forced_kill == 2

    room.current_phase = 'battle'
    s = ship((0, 0), (0, 1))
    s.invincible = True
    room.players[P2].ships = [s]
    room.players[P2].remaining_ships = 1
    attack(room, P1, 0, 0)
    # 强制击杀无视无敌
    assert room.players[P2].remaining_ships == 0
    # 一次击杀不消耗攻击阶段数
    assert room.players[P1].effect_flags.forced_kill == 2


# ---------------------------------------------------------------------------
# 神威！
# ---------------------------------------------------------------------------
def test_shenwei_single_ship_dies(room):
    """对方3*3区域内只有一艘船时直接死亡"""
    room.players[P2].ships = [ship((1, 1))]
    room.players[P2].remaining_ships = 1
    res = apply(room, P1, '神威！', {'target_area': {'x1': 0, 'x2': 2, 'y1': 0, 'y2': 2}})
    assert res.success is True
    assert room.players[P2].remaining_ships == 0
    assert len(room.players[P2].sunken_ships) == 1


def test_shenwei_multiple_ships_excluded(room):
    """多艘船被暂时除外，并登记下一大回合回归"""
    room.players[P2].ships = [ship((0, 0)), ship((2, 2)), ship((5, 5))]
    room.players[P2].remaining_ships = 3
    apply(room, P1, '神威！', {'target_area': {'x1': 0, 'x2': 2, 'y1': 0, 'y2': 2}})
    assert len(room.players[P2].ships) == 1
    entries = room.game_effects['excluded_ships']
    assert len(entries) == 1
    assert len(entries[0]['ships']) == 2
    assert entries[0]['return_turn'] == room.round + 1


def test_shenwei_self_board_only_excludes(room):
    """己方棋盘：只除外与回归，不触发单船死亡"""
    room.players[P1].ships = [ship((1, 1))]
    room.players[P1].remaining_ships = 1
    res = apply(room, P1, '神威！',
                {'target_area': {'x1': 0, 'x2': 2, 'y1': 0, 'y2': 2}, 'board': 'self'})
    assert res.success is True
    assert len(room.players[P1].sunken_ships) == 0      # 不死亡
    assert len(room.players[P1].ships) == 0
    assert len(room.game_effects['excluded_ships'][0]['ships']) == 1


def test_shenwei_hole_blocks_attack(room):
    """被扣掉的区域不可攻击"""
    room.players[P2].ships = [ship((0, 0)), ship((1, 1)), ship((5, 5))]
    room.players[P2].remaining_ships = 3
    apply(room, P1, '神威！', {'target_area': {'x1': 0, 'x2': 2, 'y1': 0, 'y2': 2}})
    assert server._cell_in_shenwei_hole(room, P2, 1, 1) is True
    assert server._cell_in_shenwei_hole(room, P2, 5, 5) is False
    res = attack(room, P1, 1, 1)
    assert res['status'] == 'error'


def test_shenwei_wipes_all_opponent_ships_wins(room):
    """对方船被全部除外 = 直接获胜（斩杀）"""
    room.players[P2].ships = [ship((0, 0)), ship((1, 1))]
    room.players[P2].remaining_ships = 2
    apply(room, P1, '神威！', {'target_area': {'x1': 0, 'x2': 2, 'y1': 0, 'y2': 2}})
    assert room.players[P2].remaining_ships == 0
    assert room.state == 'game_over'
    assert room.winner == P1


def test_shenwei_exclusion_triggers_linkage(room):
    """除外的船算船数变化：触发八方来财抽牌"""
    room.players[P2].ships = [ship((0, 0)), ship((1, 1)), ship((5, 5))]
    room.players[P2].remaining_ships = 3
    room.players[P2].effect_flags.treasure_hunter = True
    room.magic_deck = [card('增援')]
    before = len(room.players[P2].magic_hand)
    apply(room, P1, '神威！', {'target_area': {'x1': 0, 'x2': 2, 'y1': 0, 'y2': 2}})
    assert len(room.players[P2].magic_hand) == before + 1


# ---------------------------------------------------------------------------
# 增援
# ---------------------------------------------------------------------------
def test_zengyuan_waits_for_placement(room):
    """召唤战舰并部署在未被对方打过的格子"""
    res = apply(room, P1, '增援')
    assert res.success is True
    assert room.magic_temp_data['pending_placement']['caster'] == P1
    assert room.magic_temp_data['pending_placement']['kind'] == 'reinforce'

    ok = server.handle_confirm_reinforcement({
        'room_id': room.id, 'player_id': P1, 'position': {'x': 2, 'y': 2}
    })
    assert ok['status'] == 'success'
    assert room.players[P1].remaining_ships == 1
    # 放置完成，待放置状态清空
    assert 'pending_placement' not in room.magic_temp_data


def test_zengyuan_can_be_cancelled(room):
    """放弃放置不会卡死"""
    apply(room, P1, '增援')
    res = server.handle_cancel_placement({'room_id': room.id, 'player_id': P1})
    assert res['status'] == 'success'
    assert 'pending_placement' not in room.magic_temp_data
    assert room.players[P1].remaining_ships == 0


def test_zengyuan_rejects_attacked_cell(room):
    """不能部署在对方打过的格子"""
    apply(room, P1, '增援')
    room.players[P2].attacks = [Position(1, 1)]
    res = server.handle_confirm_reinforcement({
        'room_id': room.id, 'player_id': P1, 'position': {'x': 1, 'y': 1}
    })
    assert res['status'] == 'error'


def test_zengyuan_no_ship_cap(room):
    """增援没有"6 艘上限"（作者确认：船数只受棋盘格数限制）。

    2026-09-14 规则修正：原先 remaining_ships >= 6 会直接判失败，
    但那时牌已经离手（handle_use_magic_card 先扣牌再结算），玩家被白吞一张卡
    —— 实测玩家报的"弹出船数已达上限无法使用，但增援卡牌被吞掉了"。
    """
    room.players[P1].ships = [ship((i, 0)) for i in range(6)]
    room.players[P1].remaining_ships = 6
    res = apply(room, P1, '增援')
    assert res.success is True, '不该再有船数上限'
    assert room.magic_temp_data.get('pending_placement', {}).get('kind') == 'reinforce', (
        '应进入放置流程，而不是拒绝')


def test_zengyuan_can_exceed_six_ships(room):
    """真的能摆到 7 艘（只受棋盘格数限制）。"""
    room.players[P1].ships = [ship((i, 0)) for i in range(6)]
    room.players[P1].remaining_ships = 6
    room.players[P2].remaining_ships = 3
    room.current_attacker = P1
    room.attacks_remaining = 6
    apply(room, P1, '增援')

    out = server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 3, 'y': 3}})
    assert out.get('status') == 'success', out
    assert room.players[P1].remaining_ships == 7, '应能超过 6 艘'


def test_zengyuan_updates_attacks_immediately(room):
    """增援放置完成后，本回合攻击次数要立刻 +1（绝境中多一艘船=多一条命）。"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 1))]
    room.players[P1].remaining_ships = 2
    room.players[P2].remaining_ships = 3   # 对手尚有船，避免被判 game_over
    room.attacks_remaining = 2
    room.current_attacker = P1

    apply(room, P1, '增援')
    server.handle_confirm_reinforcement({
        'room_id': room.id, 'player_id': P1, 'position': {'x': 3, 'y': 3}
    })

    assert room.players[P1].remaining_ships == 3
    assert room.attacks_remaining == 3, '增援后攻击次数应随船数同步增加'


def test_zengyuan_does_not_touch_opponent_turn(room):
    """增援在对方回合放置时，不应改动对方的攻击次数。"""
    room.players[P1].ships = [ship((0, 0))]
    room.players[P1].remaining_ships = 1
    room.players[P2].remaining_ships = 3
    room.current_attacker = P2
    room.attacks_remaining = 5

    apply(room, P1, '增援')
    server.handle_confirm_reinforcement({
        'room_id': room.id, 'player_id': P1, 'position': {'x': 3, 'y': 3}
    })

    assert room.players[P1].remaining_ships == 2
    assert room.attacks_remaining == 5, '对方回合不应被改攻击次数'


def test_revive_updates_attacks_immediately(room):
    """复活同样增加船数，攻击次数也应同步。"""
    sunk = ship((0, 0))
    sunk.hits = [Position(0, 0)]
    room.players[P1].sunken_ships = [sunk]
    room.players[P1].ships = [ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 2
    room.players[P2].remaining_ships = 3
    room.attacks_remaining = 2
    room.current_attacker = P1

    apply(room, P1, '死者苏生')
    server.handle_confirm_reinforcement({
        'room_id': room.id, 'player_id': P1, 'position': {'x': 4, 'y': 4}
    })

    assert room.players[P1].remaining_ships == 3
    assert room.attacks_remaining == 3, '复活后攻击次数应随船数同步增加'


# ---------------------------------------------------------------------------
# 恶魔契约（场地）
# ---------------------------------------------------------------------------
def test_demon_contract_binding_on_attack(room):
    """对方船被击杀时，己方也必须牺牲一艘 —— 由自己点选，不再随机"""
    apply(room, P1, '恶魔契约')
    assert room.game_effects.get('demon_contract') is True

    room.players[P1].ships = [ship((4, 4)), ship((5, 5))]
    room.players[P1].remaining_ships = 2
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1

    attack(room, P1, 0, 0)
    assert room.players[P2].remaining_ships == 0
    # 不再立刻随机牺牲，而是等 P1 自己点选
    assert len(room.players[P1].ships) == 2, '不应在未选择前就随机牺牲'
    assert server._top_ship_pick(room, P1)['player'] == P1


def test_demon_contract_sacrifice_requires_own_ship(room):
    """恶魔契约的牺牲必须点自己船所在格，选空格要被拒。"""
    apply(room, P1, '恶魔契约')
    room.players[P1].ships = [ship((4, 4)), ship((5, 5))]
    room.players[P1].remaining_ships = 2
    # 对手留一艘不打的船：否则这一炮直接把对局打结束，
    # 终局后的 confirm_sacrifice 会被门禁拒绝（那才是正确行为）
    room.players[P2].ships = [ship((0, 0)), ship((5, 0))]
    room.players[P2].remaining_ships = 2
    attack(room, P1, 0, 0)

    # 选空格 → 拒绝
    bad = server.handle_confirm_sacrifice({
        'room_id': room.id, 'player_id': P1, 'position': {'x': 1, 'y': 1}})
    assert bad['status'] == 'error'
    assert len(room.players[P1].ships) == 2

    # 选自己的船 → 成功
    good = server.handle_confirm_sacrifice({
        'room_id': room.id, 'player_id': P1, 'position': {'x': 4, 'y': 4}})
    assert good['status'] == 'success'
    assert len(room.players[P1].ships) == 1
    assert room.players[P1].remaining_ships == 1


# ---------------------------------------------------------------------------
# 八方来财
# ---------------------------------------------------------------------------
def test_bafang_draw_on_ship_change(room):
    """场上战舰数主动变化时自己摸一张牌"""
    give_deck(room, ['轰炸'])
    apply(room, P2, '八方来财')
    assert room.players[P2].effect_flags.treasure_hunter is True

    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1
    attack(room, P1, 0, 0)  # P2 的船被击败 => 船数变化
    assert any(c.name == '轰炸' for c in room.players[P2].magic_hand)


# ---------------------------------------------------------------------------
# 平等条约
# ---------------------------------------------------------------------------
def test_pingdeng_cannot_negate_attack_kill(room):
    """炮击造成的击沉【无法】被无效化 —— 卡面只针对魔法卡。"""
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1
    attack(room, P1, 0, 0)
    assert room.players[P2].remaining_ships == 0
    assert room.game_effects['last_ship_change']['source'] == 'attack'

    res = apply(room, P1, '平等条约')
    assert res.success is False
    assert '炮击' in res.message
    # 船没回来（击沉时船仍留在 ships 里，所以看 remaining_ships 与沉船堆），
    # 快照也不能被吃掉
    assert room.players[P2].remaining_ships == 0
    assert room.players[P2].ships[0] in room.players[P2].sunken_ships
    assert 'last_ship_change' in room.game_effects


def test_pingdeng_negates_magic_ship_change(room):
    """魔法卡造成的船数改变仍然可以被无效化（保留的那一半效果）。"""
    victim = ship((0, 0))
    room.players[P2].ships = []
    room.players[P2].remaining_ships = 0
    room.game_effects['last_ship_change'] = {
        'round': room.round, 'player': P2, 'count': 1,
        'ship': victim, 'hits_added': [], 'source': 'magic',
    }

    res = apply(room, P1, '平等条约')
    assert res.success is True, res
    assert room.players[P2].remaining_ships == 1
    assert victim in room.players[P2].ships
    assert 'last_ship_change' not in room.game_effects


def test_pingdeng_rejected_attack_keeps_snapshot_usable(room):
    """攻击被拒后快照必须留着，否则随后的魔法船数变化会莫名无效化不了。"""
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1
    attack(room, P1, 0, 0)

    first = apply(room, P1, '平等条约')
    assert first.success is False
    assert 'last_ship_change' in room.game_effects, '被拒时不能消费快照'

    # 换成魔法来源（模拟随后的区域魔法击沉）后应能无效化
    room.game_effects['last_ship_change']['source'] = 'magic'
    room.players[P2].remaining_ships = 0
    second = apply(room, P1, '平等条约')
    assert second.success is True
    assert room.players[P2].remaining_ships == 1
    assert 'last_ship_change' not in room.game_effects


def test_pingdeng_fails_without_change(room):
    res = apply(room, P1, '平等条约')
    assert res.success is False


# ---------------------------------------------------------------------------
# 禁忌果实（场地）
# ---------------------------------------------------------------------------
def test_jinji_blocks_normal_magic(room):
    """双方都无法使用任何魔法卡，除去失灵！与其他场地魔法卡"""
    apply(room, P1, '禁忌果实')
    assert room.field_magic.name == '禁忌果实'
    assert server.can_play_magic_card(room, P1, card('轰炸')) is False
    assert server.can_play_magic_card(room, P1, card('失灵！')) is True
    assert server.can_play_magic_card(room, P1, card('伊甸园')) is True


# ---------------------------------------------------------------------------
# 硫磺火焰
# ---------------------------------------------------------------------------
def test_liuhuang_kills_six_cells(room):
    """连续6格上的战舰强制击杀（含无敌/盾牌）"""
    s = ship((2, 0), (3, 0))
    s.invincible = True
    room.players[P2].ships = [s]
    room.players[P2].remaining_ships = 1
    cells = [{'x': i, 'y': 0} for i in range(6)]

    res = apply(room, P1, '硫磺火焰', {'target_cells': cells})
    assert res.success is True
    assert room.players[P2].ships == []
    assert len(room.players[P2].sunken_ships) == 1


def test_liuhuang_requires_exactly_six_cells(room):
    res = apply(room, P1, '硫磺火焰', {'target_cells': [{'x': 0, 'y': 0}]})
    assert res.success is False


def test_liuhuang_ship_count_correct(room):
    room.players[P2].ships = [ship((2, 0))]
    room.players[P2].remaining_ships = 1
    cells = [{'x': i, 'y': 0} for i in range(6)]
    apply(room, P1, '硫磺火焰', {'target_cells': cells})
    assert room.players[P2].remaining_ships == 0  # 实际为 -1


# ---------------------------------------------------------------------------
# 百亿补贴
# ---------------------------------------------------------------------------
def test_baiyi_subsidy_on_own_ship_lost(room):
    """自己的船被击败时【自己】的攻击次数 +3（不是加给当前攻击者）"""
    apply(room, P2, '百亿补贴')          # 持卡者是 P2，此刻攻击者是 P1
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1
    before = room.attacks_remaining      # 属于 P1 的攻击池
    attack(room, P1, 0, 0)

    # P1 的攻击池只被自己消耗 1 次，不应拿到 P2 的补贴
    assert room.attacks_remaining == before - 1
    # 补贴累计在持卡者身上，轮到 P2 时计入其攻击次数
    assert room.players[P2].effect_flags.subsidy_bonus == 3
    room.current_attacker = P2
    server._recalc_attacker_attacks(room)
    assert room.attacks_remaining == room.players[P2].remaining_ships + 3


# ---------------------------------------------------------------------------
# 看破！
# ---------------------------------------------------------------------------
def test_kanpo_sets_block_flag(room):
    apply(room, P1, '看破！')
    assert room.players[P2].magic_blocked is True


def test_kanpo_blocks_opponent_magic(room):
    apply(room, P1, '看破！')
    room.players[P2].magic_hand = [card('冻结')]
    room.current_attacker = P2
    res = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P2,
        'card': {'name': '冻结', 'speed': 2, 'type': '普通', 'description': ''},
        'targets': {'target_area': {'x1': 0, 'x2': 2, 'y1': 0, 'y2': 2}}
    })
    assert res['status'] == 'error'


# ---------------------------------------------------------------------------
# 冻结
# ---------------------------------------------------------------------------
def test_dongjie_marks_ships_frozen(room):
    """3*3区域内的船被冻结"""
    room.players[P2].ships = [ship((1, 1)), ship((5, 5))]
    room.players[P2].remaining_ships = 2
    apply(room, P1, '冻结', {'target_area': {'x1': 0, 'x2': 2, 'y1': 0, 'y2': 2}})
    assert getattr(room.players[P2].ships[0], 'frozen', None) == room.round + 1
    assert not hasattr(room.players[P2].ships[1], 'frozen')


# ---------------------------------------------------------------------------
# 轰炸
# ---------------------------------------------------------------------------
def test_hongzha_row_kills_intersecting_ships(room):
    """一行/一列的船全部死亡"""
    room.players[P2].ships = [ship((0, 2), (1, 2)), ship((4, 4))]
    room.players[P2].remaining_ships = 2
    res = apply(room, P1, '轰炸', {'target_line': {'type': 'row', 'index': 2}})
    assert res.success is True
    assert room.players[P2].remaining_ships == 1
    assert room.players[P2].ships[0].positions[0] == Position(4, 4)


def test_hongzha_column(room):
    room.players[P2].ships = [ship((3, 0), (3, 1))]
    room.players[P2].remaining_ships = 1
    apply(room, P1, '轰炸', {'target_line': {'type': 'col', 'index': 3}})
    assert room.players[P2].remaining_ships == 0


# ---------------------------------------------------------------------------
# 探测雷达
# ---------------------------------------------------------------------------
def test_tance_reveals_2x2(room):
    """2*2区域探测显形"""
    room.players[P2].ships = [ship((1, 1))]
    room.players[P2].remaining_ships = 1
    res = apply(room, P1, '探测雷达', {'target_area': {'x1': 0, 'x2': 1, 'y1': 0, 'y2': 1}})
    assert res.success is True
    revealed = {(p.x, p.y) for p in room.players[P1].revealed_positions}
    assert {(0, 0), (0, 1), (1, 0), (1, 1)} == revealed


# ---------------------------------------------------------------------------
# 伊甸园（场地）
# ---------------------------------------------------------------------------
def test_yidian_attack_count_6_minus_n(room):
    """攻击次数变为 6-n（进入战斗阶段时结算）"""
    apply(room, P1, '伊甸园')
    assert room.field_magic.name == '伊甸园'

    room.players[P1].ships = [ship((0, 0)), ship((1, 1))]
    room.players[P1].remaining_ships = 2
    room.current_phase = 'preparation'
    room.attacks_remaining = 2
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert room.attacks_remaining == 6 - 2


# ---------------------------------------------------------------------------
# 神之宣告
# ---------------------------------------------------------------------------
def test_shenzhi_option1_kill_opponent_ship(room):
    """牺牲己方两艘船；效果1 由【对方自己点选】一艘阵亡的船"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3
    room.players[P2].ships = [ship((3, 3)), ship((4, 4))]
    room.players[P2].remaining_ships = 2
    room.magic_temp_data = {'effect_choice': 1}

    res = apply(room, P1, '神之宣告')
    assert res.success is True
    assert room.players[P1].remaining_ships == 1

    # 卡面：让对方选择自己的一艘船使其死亡 → 应挂起等待对方点选
    pending = server._top_ship_pick(room, P2)
    assert pending and pending['player'] == P2 and pending['reason'] == 'divine_decree'
    assert room.players[P2].remaining_ships == 2

    ok = server.handle_confirm_sacrifice({'room_id': room.id, 'player_id': P2,
                                          'position': {'x': 3, 'y': 3}})
    assert ok['status'] == 'success'
    assert room.players[P2].remaining_ships == 1


def test_shenzhi_honours_caster_selected_ships(room):
    """前端点选的两艘自己船应被牺牲（原先服务端随机）"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3
    room.players[P2].ships = [ship((5, 5))]
    room.players[P2].remaining_ships = 1

    res = server.apply_magic_effect(room, P1, card('神之宣告'), {
        'effect_choice': 2,
        'selected_cells': [{'x': 1, 'y': 1}, {'x': 2, 'y': 2}],
    })
    assert res.success is True
    left = {(p.x, p.y) for sh in room.players[P1].ships for p in sh.positions}
    assert left == {(0, 0)}, '玩家点选的两艘应被牺牲'
    assert room.players[P1].remaining_ships == 1


def test_shenzhi_option2_skip_opponent_turn(room):
    # ⚠️ 这里是 **3 艘**，不是 2 艘：2026-09-19 起发动条件收紧为「船数必须 > 2」
    #    （牺牲两艘后至少留一艘；≤2 会被直接拒绝，见
    #    `test_shenzhixuanga_refuses_when_two_ships_or_fewer`）。
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3
    room.magic_temp_data = {'effect_choice': 2}
    res = apply(room, P1, '神之宣告')
    assert res.success is True, res.message
    # ★ 2026-09-20 改用 `skip_opponent_stages`（语义修正，见下）。
    # 卡面：「跳过**这一个大回合内**对方的所有阶段」—— 不含翻页。
    # 旧实现与 Freezing！ 共用 `skip_opponent_turn`，而它跳完会**直接进新大回合**
    # （重新猜拳 + 重新发牌），等于白送一次状态重置。两张卡的作用域不同，故分开。
    # 语义由 `tests/test_divine_declaration_skip.py` 完整钉住（含 Freezing 反向守卫）。
    assert room.skip_opponent_stages == P2
    assert not room.skip_opponent_turn, '不该动 Freezing！ 的标记（那会把大回合翻页）'


def _sacrifice_events(events):
    return [d for (e, d, _to, _room) in events if e == 'ship_sacrificed']


def test_shenzhi_broadcasts_own_two_sacrifices_publicly(room, events):
    """自己牺牲的两艘船必须公开广播，否则对方完全看不到。

    这里回归的是一个真实漏洞：这两艘船以前是就地 remove/append 处理掉的，
    既不广播也不刷新船数 —— 对方棋盘上什么都没变化，等于凭空消失。
    """
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3
    room.players[P2].ships = [ship((5, 5))]
    room.players[P2].remaining_ships = 1

    res = server.apply_magic_effect(room, P1, card('神之宣告'), {
        'effect_choice': 2,
        'selected_cells': [{'x': 1, 'y': 1}, {'x': 2, 'y': 2}],
    })
    assert res.success is True

    got = _sacrifice_events(events)
    assert len(got) == 2, f'两艘牺牲的船都要广播，实际 {len(got)} 条'

    # 必须是房间级广播（room=room.id），只发给施法者自己的话对方看不到
    rooms = [r for (e, _d, _to, r) in events if e == 'ship_sacrificed']
    assert all(r == room.id for r in rooms), 'ship_sacrificed 必须广播到整个房间'

    cells = sorted(tuple(sorted((p['x'], p['y']) for p in d['positions'])) for d in got)
    assert cells == [((1, 1),), ((2, 2),)], '广播的位置应正是玩家点选的两艘'
    assert all(d['player'] == P1 and d['reason'] == 'divine_decree' for d in got)


def test_shenzhi_option1_broadcasts_opponent_ship_too(room, events):
    """效果1：对方点选的那艘船同样要公开广播（双方都能看到它沉了）。"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3
    room.players[P2].ships = [ship((3, 3)), ship((4, 4))]
    room.players[P2].remaining_ships = 2

    res = server.apply_magic_effect(room, P1, card('神之宣告'), {
        'effect_choice': 1,
        'selected_cells': [{'x': 1, 'y': 1}, {'x': 2, 'y': 2}],
    })
    assert res.success is True
    # 人类对手要自己点选，此时已挂起等待
    pending = server._top_ship_pick(room, P2)
    assert pending and pending['player'] == P2

    ok = server.handle_confirm_sacrifice({'room_id': room.id, 'player_id': P2,
                                          'position': {'x': 3, 'y': 3}})
    assert ok['status'] == 'success'

    got = _sacrifice_events(events)
    assert len(got) == 3, f'己方两艘 + 对方一艘 = 3 条广播，实际 {len(got)} 条'
    by_player = [(d['player'], d['positions'][0]['x'], d['positions'][0]['y']) for d in got]
    assert (P1, 1, 1) in by_player and (P1, 2, 2) in by_player
    assert (P2, 3, 3) in by_player


def test_shenzhi_requires_two_ships(room):
    room.players[P1].ships = [ship((0, 0))]
    room.players[P1].remaining_ships = 1
    res = apply(room, P1, '神之宣告')
    assert res.success is False


# ---------------------------------------------------------------------------
# 五险一金
# ---------------------------------------------------------------------------
def test_wuxian_arms_instead_of_granting_immediately(room):
    """出牌只是「挂上保险」—— 不能一打出就白送 3 次。

    卡面：「这一回合自己的攻击次数第一次用尽时，若自己未曾对对方造成一点伤害，
    则自己的攻击次数再加3。」所以时机是【攻击次数第一次归零】，不是出牌瞬间。
    """
    room.players[P1].damage_dealt_this_turn = 0
    before = room.attacks_remaining
    res = apply(room, P1, '五险一金')
    assert res.success is True
    assert room.attacks_remaining == before, '出牌时不该立刻加 3'
    assert room.players[P1].effect_flags.wuxian is True, '应挂上待触发的标记'


def test_wuxian_triggers_when_attacks_first_hit_zero(room):
    """攻击次数第一次归零、且本回合没让对方减船 → +3，并且只触发一次。"""
    room.players[P1].damage_dealt_this_turn = 0
    room.attacks_remaining = 1
    apply(room, P1, '五险一金')
    assert room.players[P1].effect_flags.wuxian is True

    # 打一发（未命中）→ 次数归零 → 触发
    attack(room, P1, 5, 5)
    assert room.attacks_remaining == 3, '归零时应补上 3 次'
    assert room.players[P1].effect_flags.wuxian is False, '触发后标记要清掉'

    # 再打光这 3 发 → 不能二次触发
    for _ in range(3):
        room.attacks_remaining -= 1
    room.attacks_remaining = max(0, room.attacks_remaining)
    server._maybe_trigger_wuxian_yijin(room, P1)
    assert room.attacks_remaining == 0, '只能触发一次'


def test_wuxian_not_triggered_after_dealing_damage(room):
    """归零那一刻若已经让对方减过船，就不给 +3。"""
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1
    room.players[P1].damage_dealt_this_turn = 0
    room.attacks_remaining = 1
    apply(room, P1, '五险一金')

    attack(room, P1, 0, 0)          # 命中并击沉 → damage_dealt_this_turn 变 1
    assert room.players[P1].damage_dealt_this_turn > 0
    assert room.attacks_remaining == 0, '造成过伤害就不该补次数'


def test_wuxian_triggers_when_played_at_zero_attacks(room):
    """出牌时攻击次数就已经是 0（还停在战斗阶段）→ 条件当场成立，立刻 +3。"""
    room.players[P1].damage_dealt_this_turn = 0
    room.attacks_remaining = 0
    res = apply(room, P1, '五险一金')
    assert res.success is True
    assert room.attacks_remaining == 3, '已经归零时出牌应立即触发'
    assert room.players[P1].effect_flags.wuxian is False


def test_wuxian_badge_clears_after_trigger(room, events):
    """触发后标记被消耗，角标要跟着消失（不能像以前那样一直亮着）。"""
    room.players[P1].damage_dealt_this_turn = 0
    room.attacks_remaining = 0
    events.clear()
    apply(room, P1, '五险一金')

    seen = [[b['name'] for b in d['self']] for (e, d, t, _r) in events
            if e == 'active_effects' and t == 'sid-p1']
    assert seen, '触发时应刷新一次角标'
    assert '五险一金' not in seen[-1], f'触发后不该还挂着角标，实际 {seen[-1]}'


def test_wuxian_flag_dies_with_the_turn(room):
    """D1：没触发就作废 —— 标记不在 permanent_flags 里，回合切换会被清掉。"""
    room.players[P1].effect_flags.wuxian = True
    # 复刻回合切换时的白名单过滤
    keep = ['holy_heart', 'reinforcement_check', 'no_draw', 'prediction', 'forced_kill']
    room.players[P1].effect_flags.__dict__ = {
        k: v for k, v in room.players[P1].effect_flags.__dict__.items() if k in keep}
    assert getattr(room.players[P1].effect_flags, 'wuxian', False) is False
    assert 'wuxian' not in keep, 'wuxian 一旦进了白名单就变成跨回合永久，与卡面「这一回合」矛盾'


def test_wuxian_blocked_by_pope_decree(room):
    """教皇旨意优先级高于五险一金：攻击次数被压成 0 是场地规则，不给补次数。"""
    room.players[P1].damage_dealt_this_turn = 0
    room.players[P1].effect_flags.wuxian = True      # 先挂上保险
    room.field_magic = card('教皇旨意')

    # 归零也不该触发
    room.attacks_remaining = 0
    assert server._maybe_trigger_wuxian_yijin(room, P1) is False
    assert room.attacks_remaining == 0, '教皇旨意生效时不能补次数'


def test_wuxian_cannot_be_played_under_pope_decree(room):
    """教皇旨意生效时五险一金这张牌一次都触发不了，应该直接拒绝出牌、别浪费。"""
    room.field_magic = card('教皇旨意')
    room.players[P1].damage_dealt_this_turn = 0
    res = apply(room, P1, '五险一金')
    assert res.success is False
    assert '教皇旨意' in res.message
    assert getattr(room.players[P1].effect_flags, 'wuxian', False) is False, '被拒时不该挂上标记'


def test_wuxian_rejected_before_play_under_pope_decree(room):
    """出牌前就拦掉 —— 卡不能被消耗掉，而且要给出具体原因（别只报「速阶2」）。"""
    room.field_magic = card('教皇旨意')
    room.players[P1].damage_dealt_this_turn = 0
    room.players[P1].magic_hand = [card('五险一金')]

    res = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '五险一金'}, 'targets': {}})
    assert res['status'] == 'error'
    assert '教皇旨意' in res['message']
    assert [c.name for c in room.players[P1].magic_hand] == ['五险一金'], '被拒时手牌不该少'


def test_wuxian_still_works_after_other_field_magic(room):
    """别的场地魔法不该误伤 —— 只有教皇旨意压得住五险一金。"""
    room.players[P1].damage_dealt_this_turn = 0
    room.field_magic = card('伊甸园')
    room.attacks_remaining = 0
    res = apply(room, P1, '五险一金')
    assert res.success is True
    assert room.attacks_remaining == 3


def test_wuxian_fails_after_damage(room):
    room.players[P1].damage_dealt_this_turn = 1
    res = apply(room, P1, '五险一金')
    assert res.success is False


# ---------------------------------------------------------------------------
# 绝处逢生
# ---------------------------------------------------------------------------
def test_juechu_requires_three_ships(room):
    room.players[P1].ships = [ship((0, 0)), ship((1, 1))]
    res = apply(room, P1, '绝处逢生')
    assert res.success is False


def test_juechu_sacrifices_all_and_places_one(room):
    """牺牲所有战舰（进沉船堆）并在原本有战舰的格子放置唯一一艘；之后击杀任意船直接获胜"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3
    give_hand(room.players[P1], ['轰炸', '冻结'])

    res = apply(room, P1, '绝处逢生')
    assert res.success is True
    assert len(room.players[P1].ships) == 0            # 先全部牺牲
    assert len(room.players[P1].sunken_ships) == 3     # 进沉船堆，而不是凭空消失
    assert room.players[P1].remaining_ships == 0
    assert room.players[P1].effect_flags.last_stand is True
    assert room.magic_temp_data['pending_placement']['kind'] == 'last_stand'

    # 只能放在"原本有自己战舰"的格子上
    bad = server.handle_confirm_reinforcement({'room_id': room.id, 'player_id': P1,
                                               'position': {'x': 5, 'y': 5}})
    assert bad['status'] == 'error'
    ok = server.handle_confirm_reinforcement({'room_id': room.id, 'player_id': P1,
                                              'position': {'x': 1, 'y': 1}})
    assert ok['status'] == 'success'
    assert room.players[P1].remaining_ships == 1
    assert len(room.players[P1].ships) == 1

    room.players[P2].ships = [ship((4, 4))]
    room.players[P2].remaining_ships = 1
    room.attacks_remaining = 3
    attack(room, P1, 4, 4)
    assert room.state == 'game_over'
    assert room.winner == P1


# ---------------------------------------------------------------------------
# 死者苏生
# ---------------------------------------------------------------------------
def test_sizhe_revives_last_sunken(room):
    s = ship((0, 0))
    s.hits = [Position(0, 0)]          # 沉船：命中已满
    room.players[P1].sunken_ships = [s]
    room.players[P1].remaining_ships = 0
    res = apply(room, P1, '死者苏生')
    assert res.success is True
    assert room.magic_temp_data['pending_placement']['kind'] == 'revive'

    ok = server.handle_confirm_reinforcement({
        'room_id': room.id, 'player_id': P1, 'position': {'x': 3, 'y': 3}})
    assert ok['status'] == 'success'
    assert room.players[P1].remaining_ships == 1
    # 复活后必须清空 hits（否则变成打不沉的幽灵船）
    revived = [sh for sh in room.players[P1].ships if sh is s][0]
    assert revived.hits == []
    assert revived.positions[0].x == 3 and revived.positions[0].y == 3


def test_sizhe_fails_without_sunken(room):
    res = apply(room, P1, '死者苏生')
    assert res.success is False


def test_revived_ship_can_be_sunk_again(room):
    """复活后的船必须能再次被打沉（否则变成打不死的幽灵船）"""
    s = ship((0, 0))
    s.hits = [Position(0, 0)]           # 沉船：命中已满
    room.players[P1].sunken_ships = [s]
    room.players[P1].remaining_ships = 0
    apply(room, P1, '死者苏生')
    server.handle_confirm_reinforcement({
        'room_id': room.id, 'player_id': P1, 'position': {'x': 4, 'y': 4}})

    revived = [sh for sh in room.players[P1].ships if sh is s][0]
    assert len(revived.hits) == 0
    assert room.players[P1].remaining_ships == 1

    # 对方攻击这个格子：应能击沉（船数 1 -> 0）
    room.current_attacker = P2
    room.current_phase = 'battle'
    room.attacks_remaining = 6
    server.handle_attack({'room_id': room.id, 'player_id': P2, 'x': 4, 'y': 4})
    assert room.players[P1].remaining_ships == 0, '复活后的船打不沉 = 幽灵船'


def test_liaoyu_placement_requires_sunken(room):
    """疗愈无沉船时不可用"""
    res = apply(room, P1, '疗愈')
    assert res.success is False


# ---------------------------------------------------------------------------
# 疗愈
# ---------------------------------------------------------------------------
def test_liaoyu_revives_up_to_two(room):
    """卡面：选定至多两艘被击杀的船并【在原地复活】"""
    s1, s2, s3 = ship((0, 0)), ship((1, 1)), ship((2, 2))
    for s in (s1, s2, s3):
        s.hits = list(s.positions)          # 已沉：命中已满
    room.players[P1].ships = [s1, s2, s3]
    room.players[P1].sunken_ships = [s1, s2, s3]
    room.players[P1].remaining_ships = 0

    res = apply(room, P1, '疗愈')
    assert res.success is True
    assert room.players[P1].remaining_ships == 2
    assert len(room.players[P1].sunken_ships) == 1
    # 原地复活：位置不变、命中清空，可再次被攻击
    assert s3.hits == [] and s2.hits == []
    assert s2.positions[0].x == 1 and s2.positions[0].y == 1
    assert 'pending_placement' not in room.magic_temp_data


# ---------------------------------------------------------------------------
# 桃园结义
# ---------------------------------------------------------------------------
def test_taoyuan_draw_n_and_assign(room):
    """抽n张（n=战舰数），自己挑一张，再挑一张给对方，其余放回"""
    give_deck(room, ['轰炸', '冻结', '探测雷达', '饮血', '溅射'])
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3

    res = apply(room, P1, '桃园结义')
    assert res.success is True
    assert len(room.magic_temp_data['cards']) == 3

    ok = server.confirm_magic_target({
        'room_id': room.id, 'player_id': P1,
        'temp_data_id': 'taoyuan_choice',
        'target_data': {'caster_choice': 0}
    })
    assert ok['status'] == 'success'
    assert len(room.players[P1].magic_hand) == 1
    assert len(room.players[P2].magic_hand) == 1
    assert len(room.magic_deck) == 3  # 2张剩余 + 1张未抽


# ---------------------------------------------------------------------------
# 无中生有
# ---------------------------------------------------------------------------
def test_wuzhong_draw_two_and_lock_draw(room):
    """摸两张牌；本大回合双方无法再获得魔法卡"""
    give_deck(room, ['轰炸', '冻结', '溅射'])
    res = apply(room, P1, '无中生有')
    assert res.success is True
    assert len(room.players[P1].magic_hand) == 2
    assert room.players[P1].effect_flags.no_draw is True
    assert room.players[P2].effect_flags.no_draw is True
    assert room.draw_card(P1) is None


# ---------------------------------------------------------------------------
# 饮血
# ---------------------------------------------------------------------------
def test_yinxue_draw_on_kill(room):
    """接下来自己的攻击每击杀一艘船摸一张牌"""
    give_deck(room, ['轰炸'])
    # 卡面要求"击沉对方一艘战舰后"才能使用（2026-09-14 由"击中"收紧为"击沉"）
    room.last_attack = {'attacker': P1, 'x': 0, 'y': 0, 'hit': True, 'ship_sunk': True}
    apply(room, P1, '饮血')
    assert room.players[P1].effect_flags.vampire is True

    # 发动时已为刚才那艘沉船补摸一张（牌堆只有这一张）
    assert any(c.name == '轰炸' for c in room.players[P1].magic_hand)

    # 之后的击杀仍会继续摸牌
    give_deck(room, ['冻结'])
    room.players[P2].ships = [ship((5, 5))]
    room.players[P2].remaining_ships = 1
    attack(room, P1, 5, 5)
    assert any(c.name == '冻结' for c in room.players[P1].magic_hand)


# ---------------------------------------------------------------------------
# 极限增援
# ---------------------------------------------------------------------------
def test_jixian_registers_two_turn_check(room):
    """两个大回合后比较船数，少的一方获胜"""
    apply(room, P1, '极限增援')
    check = room.game_effects['reinforcement_check']
    assert check['turn'] == room.round + 2
    assert check['caster'] == P1


# ---------------------------------------------------------------------------
# 教皇旨意（场地）
# ---------------------------------------------------------------------------
def test_jiaohuang_zero_attacks(room):
    """攻击次数变为0，改为弃卡攻击（papal_attack 通道）"""
    apply(room, P1, '教皇旨意')
    assert room.game_effects.get('papal_edict') is True
    room.current_phase = 'preparation'
    room.players[P1].remaining_ships = 3
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert room.attacks_remaining == 0


# ---------------------------------------------------------------------------
# 无暇圣心
# ---------------------------------------------------------------------------
def test_wuxia_shengxin_registered(room):
    apply(room, P1, '无暇圣心')
    effect = room.game_effects['holy_heart']
    assert effect['no_damage'] is True
    assert effect['turn'] == room.round + 2


def test_wuxia_shengxin_interrupted_by_sink(room):
    """有战舰被击沉时无暇圣心中断"""
    apply(room, P1, '无暇圣心')
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1
    attack(room, P1, 0, 0)
    assert 'holy_heart' not in room.game_effects


# ---------------------------------------------------------------------------
# 盗亦有道
# ---------------------------------------------------------------------------
def test_daoyi_steals_opponent_last_card(room):
    """立即获取对方打出的上一张魔法卡"""
    room.magic_history = [{'card': card('冻结'), 'caster': P2}]
    res = apply(room, P1, '盗亦有道')
    assert res.success is True
    assert any(c.name == '冻结' for c in room.players[P1].magic_hand)


def test_daoyi_fails_when_own_last(room):
    room.magic_history = [{'card': card('冻结'), 'caster': P1}]
    res = apply(room, P1, '盗亦有道')
    assert res.success is False


# ---------------------------------------------------------------------------
# 克苏鲁之眼
# ---------------------------------------------------------------------------
def test_kesulu_mutual_reveal(room):
    """施法者点选自己的一艘船暴露；随后【对方也点选一艘】暴露（只暴露不摧毁）"""
    room.players[P1].ships = [ship((0, 0))]
    room.players[P1].remaining_ships = 1
    room.players[P2].ships = [ship((5, 5))]
    room.players[P2].remaining_ships = 1
    res = apply(room, P1, '克苏鲁之眼',
                {'target_area': {'x1': 0, 'y1': 0, 'x2': 0, 'y2': 0}})
    assert res.success is True
    # 施法者那艘已暴露给对方
    assert {(0, 0)} <= {(p.x, p.y) for p in room.players[P2].revealed_positions}

    # 对方仍需自己点选一艘暴露
    pending = server._top_ship_pick(room, P2)
    assert pending and pending['player'] == P2 and pending['reason'] == 'kraken_eye'
    ok = server.handle_confirm_sacrifice({'room_id': room.id, 'player_id': P2,
                                          'position': {'x': 5, 'y': 5}})
    assert ok['status'] == 'success'
    assert {(5, 5)} <= {(p.x, p.y) for p in room.players[P1].revealed_positions}
    assert room.players[P2].remaining_ships == 1, '只暴露位置，不摧毁战舰'


def test_kesulu_rejects_empty_cell(room):
    """选空格不合法：必须是自己的船所在格"""
    room.players[P1].ships = [ship((0, 0))]
    room.players[P1].remaining_ships = 1
    room.players[P2].ships = [ship((5, 5))]
    room.players[P2].remaining_ships = 1
    res = apply(room, P1, '克苏鲁之眼',
                {'target_area': {'x1': 3, 'y1': 3, 'x2': 3, 'y2': 3}})
    assert res.success is False
    assert '战舰' in res.message


def test_kesulu_rejects_missing_target(room):
    """完全没给目标也应拒绝"""
    room.players[P1].ships = [ship((0, 0))]
    room.players[P1].remaining_ships = 1
    room.players[P2].ships = [ship((5, 5))]
    room.players[P2].remaining_ships = 1
    res = apply(room, P1, '克苏鲁之眼')
    assert res.success is False


# ---------------------------------------------------------------------------
# Freezing！
# ---------------------------------------------------------------------------
def test_freezing_skips_opponent_turn(room):
    """先手 + 结束阶段 + 未让对方减船 → 跳过对方所有阶段"""
    room.attack_order = [P1, P2]          # P1 先手
    room.current_attacker = P1
    room.current_phase = 'end'            # 必须结束阶段
    room.players[P1].damage_dealt_this_turn = 0
    res = apply(room, P1, 'Freezing！')
    assert res.success is True
    assert room.skip_opponent_turn == P2


def test_freezing_fails_after_damage(room):
    room.attack_order = [P1, P2]
    room.current_attacker = P1
    room.current_phase = 'end'
    room.players[P1].damage_dealt_this_turn = 1
    res = apply(room, P1, 'Freezing！')
    assert res.success is False


def test_freezing_fails_when_not_first_player(room):
    """后手不能发动"""
    room.attack_order = [P2, P1]          # P2 先手，P1 是后手
    room.current_attacker = P1
    room.current_phase = 'end'
    room.players[P1].damage_dealt_this_turn = 0
    res = apply(room, P1, 'Freezing！')
    assert res.success is False


def test_freezing_fails_outside_end_phase(room):
    """只在结束阶段可发动"""
    room.attack_order = [P1, P2]
    room.current_attacker = P1
    room.players[P1].damage_dealt_this_turn = 0
    for ph in ('preparation', 'battle'):
        room.current_phase = ph
        res = apply(room, P1, 'Freezing！')
        assert res.success is False, f'{ph} 阶段不应能发动'


# --- 走真实出牌入口的回归（此前只测 apply_magic_effect，漏掉了 can_play_magic_card
# 里的阶段校验，导致「结束阶段禁用魔法卡」把这张卡彻底堵死却没人发现）-----------

def _play_freezing(room, who):
    """走真实 socket 入口出牌。"""
    room.players[who].magic_hand = [card('Freezing！')]
    return server.handle_use_magic_card({
        'room_id': room.id, 'player_id': who,
        'card': {'name': 'Freezing！'}, 'targets': {}
    })


def test_freezing_rejected_before_end_phase_via_entry(room):
    """准备/战斗阶段出牌应被直接拒绝（而不是进连锁后再静默失败）"""
    room.attack_order = [P1, P2]
    room.current_attacker = P1
    room.players[P1].damage_dealt_this_turn = 0
    for ph in ('preparation', 'battle'):
        room.current_phase = ph
        res = _play_freezing(room, P1)
        assert res['status'] == 'error', f'{ph} 阶段不应能打出'
        assert '结束阶段' in res['message']


def test_freezing_rejected_when_not_first_player_via_entry(room):
    """后手出牌应被拒，且给出「先手」原因"""
    room.attack_order = [P2, P1]        # P2 先手，P1 后手
    room.current_attacker = P1
    room.current_phase = 'end'
    room.players[P1].damage_dealt_this_turn = 0
    res = _play_freezing(room, P1)
    assert res['status'] == 'error'
    assert '先手' in res['message']


def test_freezing_rejected_after_ship_loss_via_entry(room):
    """已让对方减船时应被拒"""
    room.attack_order = [P1, P2]
    room.current_attacker = P1
    room.current_phase = 'end'
    room.players[P1].damage_dealt_this_turn = 1
    res = _play_freezing(room, P1)
    assert res['status'] == 'error'
    assert '船数减少' in res['message']


def test_freezing_full_flow_skips_opponent_via_entry(room):
    """全链路：结束阶段出牌 → 结束回合 → P2 被跳过，直接进新大回合。

    2026-09-14 规则修正（作者裁定）：Freezing！ 跳过的不是"小回合轮转"，
    而是【直接进下一个大回合】—— 重新猜拳 + 重新发牌。
    旧行为只把索引绕回自己（P1 连续行动），不触发新大回合。
    """
    room.attack_order = [P1, P2]
    room.current_attacker = P1
    room.current_phase = 'end'
    room.attacks_remaining = 0
    room.players[P1].damage_dealt_this_turn = 0
    room.round = 5

    res = _play_freezing(room, P1)
    assert res['status'] == 'success', res
    assert room.skip_opponent_turn == P2

    server.end_turn({'room_id': room.id, 'player_id': P1})
    assert room.round == 6, '应进入新大回合'
    assert room.state == 'rock_paper_scissors', '应重新猜拳'
    assert room.current_phase != 'end'


def test_freezing_effect_survives_pending_chain_when_caster_holds_speed3(room):
    """施法者手上还有速阶3卡时（真实对局的常态），Freezing！ 依然要生效。

    曾经的漏洞：出牌会压入连锁栈，响应窗口先给对方、对方无法响应后
    又绕回施法者本人；此时若施法者手上有速阶3卡（可以自连锁），
    窗口就会挂起等 10 秒，apply_magic_effect 根本没执行。
    玩家在这 10 秒内点「结束回合」，skip_opponent_turn 就永远不会生效，
    并且在下一个大回合开始时被静默清空。
    """
    room.attack_order = [P1, P2]
    room.current_attacker = P1
    room.current_phase = 'end'
    room.attacks_remaining = 0
    room.players[P1].damage_dealt_this_turn = 0

    # 施法者手上同时握有速阶3卡 —— 这正是触发挂起窗口的条件
    room.players[P1].magic_hand = [card('Freezing！'), card('加百列之光')]
    res = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': 'Freezing！'}, 'targets': {}
    })
    assert res['status'] == 'success', res

    # 效果还没结算（挂在连锁里），此时必须拒绝结束回合 —— 否则效果会丢
    pending = server.end_turn({'room_id': room.id, 'player_id': P1})
    assert pending['status'] == 'error', '连锁挂起时不该放行换人'
    assert room.current_attacker == P1, '回合不该被交出去'

    # 响应窗口关闭（玩家点取消 / 倒计时归零）→ 连锁结算 → 效果落地
    server.resolve_chain(room)
    assert room.skip_opponent_turn == P2, 'Freezing！ 的效果被连锁窗口吞掉了'

    room.round = 5
    server.end_turn({'room_id': room.id, 'player_id': P1})
    assert room.round == 6, 'P2 的回合应被跳过'
    assert room.state == 'rock_paper_scissors', '跳过后直接重新猜拳（新大回合）'


def test_end_turn_blocked_while_chain_pending(room):
    """连锁未结算时不允许结束回合 —— 否则卡牌效果会在换人后才生效。"""
    room.attack_order = [P1, P2]
    room.current_attacker = P1
    room.current_phase = 'end'
    room.attacks_remaining = 0
    room.chain = [ChainItem(P1, card('Freezing！'), {}, 0)]
    room.chain_waiting = True

    res = server.end_turn({'room_id': room.id, 'player_id': P1})
    assert res['status'] == 'error', '连锁挂起时结束回合应被拒绝'
    assert room.current_attacker == P1

    # 连锁结算完之后恢复正常
    room.chain = []
    room.chain_waiting = False
    res = server.end_turn({'room_id': room.id, 'player_id': P1})
    assert res['status'] == 'success', res
    assert room.current_attacker == P2


# ---------------------------------------------------------------------------
# 回光返照
# ---------------------------------------------------------------------------
def test_huiguang_reset_board_and_lose_on_damage(room):
    """清空棋盘重摆6艘；本大回合内被对方造成伤害则直接判负"""
    room.players[P1].ships = [ship((0, 0))]
    room.players[P1].remaining_ships = 1
    res = apply(room, P1, '回光返照')
    assert res.success is True
    assert room.players[P1].ships == []
    assert room.players[P1].needs_reset is True
    assert room.game_effects['last_chance']['caster'] == P1

    # 对方重新摆好船的 P1 造成伤害 => P1 判负（对方在自己的战斗阶段攻击）
    room.players[P1].ships = [ship((2, 2))]
    room.players[P1].remaining_ships = 1
    room.players[P1].needs_reset = False
    room.current_attacker = P2
    room.current_phase = 'battle'
    # ★ 2026-09-20：回光返照现在会让施法者进入 `placing_ships`，并把
    # `attacks_remaining` 清零（摆放期间本就没有攻击，与败者食尘同一口径）。
    # 对手若此时正在自己的战斗阶段，其攻击额度是**他自己的**，不该被这次重摆影响。
    # 夹具原先靠"房间初始的 6 次"顺带成立，这里显式给出，让用例表达的东西不变。
    room.attacks_remaining = room.players[P2].remaining_ships or 6
    attack(room, P2, 2, 2)
    assert room.state == 'game_over'
    assert room.winner == P2


def test_huiguang_requires_first_player(room):
    room.attack_order = [P2, P1]
    res = apply(room, P1, '回光返照')
    assert res.success is False


# ---------------------------------------------------------------------------
# 明智埋葬
# ---------------------------------------------------------------------------
def test_mingzhi_bury_and_draw(room):
    """选一张牌堆中的卡埋掉，再摸一张"""
    give_deck(room, ['轰炸', '冻结'])
    res = apply(room, P1, '明智埋葬')
    assert res.success is True
    assert res['temp_data_id'] == 'bury_choice'
    # 候选里应含牌堆的两张
    sources = [c['source'] for c in res['cards']]
    assert sources.count('deck') == 2

    ok = server.handle_magic_target({
        'room_id': room.id, 'player_id': P1,
        'temp_data_id': 'bury_choice',
        'target_data': {'card_index': 0, 'source': 'deck'}
    })
    assert ok['status'] == 'success'
    # 轰炸被埋进弃牌堆
    assert any(c.name == '轰炸' for c in room.magic_discard)
    # 自己摸到了剩下的那张
    assert any(c.name == '冻结' for c in room.players[P1].magic_hand)


def test_mingzhi_can_bury_opponent_hand(room):
    """可以埋葬对方手牌中的卡"""
    give_deck(room, ['轰炸'])
    give_hand(room.players[P2], ['冻结'])

    res = apply(room, P1, '明智埋葬')
    assert res.success is True
    # 候选中应含对方手牌
    assert any(c['source'] == 'opponent_hand' for c in res['cards'])

    ok = server.handle_magic_target({
        'room_id': room.id, 'player_id': P1,
        'temp_data_id': 'bury_choice',
        'target_data': {'card_index': 0, 'source': 'opponent_hand'}
    })
    assert ok['status'] == 'success'
    # 对方的冻结被埋掉了
    assert not any(c.name == '冻结' for c in room.players[P2].magic_hand)
    assert any(c.name == '冻结' for c in room.magic_discard)


def test_mingzhi_fails_when_nothing_to_bury(room):
    """牌堆与对方手牌都空时不可发动"""
    room.magic_deck = []
    room.players[P1].magic_hand = []
    room.players[P2].magic_hand = []
    res = apply(room, P1, '明智埋葬')
    assert res.success is False


# ---------------------------------------------------------------------------
# 火力全开
# ---------------------------------------------------------------------------
def test_huoli_double_attacks_in_battle_phase(room):
    """本大回合攻击阶段攻击次数翻倍（准备阶段打出 → 进战斗时翻倍）"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 1))]
    room.players[P1].remaining_ships = 2
    # 必须在【准备阶段】出牌：2026-09-14 起，战斗阶段打出会当场翻倍并消费标记
    # （否则速阶1在战斗阶段打出时，enter_battle_phase 早已过去，标记永远没人读）
    room.current_phase = 'preparation'
    room.attacks_remaining = 2
    apply(room, P1, '火力全开')
    assert room.players[P1].effect_flags.double_attacks is True, '准备阶段只挂标记'
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert room.attacks_remaining == 4
    assert room.players[P1].effect_flags.double_attacks is False


def test_huoli_in_battle_phase_doubles_immediately(room):
    """战斗阶段打出火力全开 → 当场翻倍，不能等一个永远不会再来的阶段转换。

    实测缺陷（2026-09-14 修复前）：战斗阶段打出后 attacks 仍是 6 不翻倍，
    标记一直挂着没人读，玩家白扔一张牌还以为生效了。
    """
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3
    room.current_phase = 'preparation'      # 必须先处于准备阶段，enter_battle_phase 才会执行
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert room.current_phase == 'battle'
    # 进战斗阶段无条件按当前规则重算：3 艘活船 = 3 次
    assert room.attacks_remaining == 3

    res = apply(room, P1, '火力全开')
    assert res.success is True
    assert room.attacks_remaining == 6, '战斗阶段打出应立即翻倍'
    assert room.players[P1].effect_flags.double_attacks is False, '标记应已消费'


# ---------------------------------------------------------------------------
# 加百列之光
# ---------------------------------------------------------------------------
def test_jiabaili_negates_field_when_no_chain(room):
    """没有连锁栈时：加百列之光主动拆掉场上的场地魔法。

    2026-09-14 规则修正（作者裁定）：有连锁栈就康连锁项，没有则拆场地 —— 二选一。
    这让"场地早贴上了、过了一会想反悔"有解（旧实现在无连锁时只回退历史记录，
    场上那张场地反而拆不掉）。
    """
    room.magic_history = [{'card': card('轰炸'), 'caster': P2}]
    room.field_magic = card('禁忌果实')
    res = apply(room, P1, '加百列之光')
    assert res.success is True
    assert room.field_magic is None, '场地应被拆掉'
    # 无连锁时不再顺带康历史里那张（二选一口径）
    assert len(room.magic_history) == 1, '历史不该被清（那条不是本次的目标）'


def test_jiabaili_negates_chain_item_when_present(room):
    """有连锁栈时：康连锁项（此时不额外拆场地）。"""
    room.chain = [ChainItem(P2, card('轰炸'), {}, 0)]
    res = apply(room, P1, '加百列之光')
    assert res.success is True
    assert getattr(res, 'negate_target', False) is True, '应标记无效化连锁项'


# ---------------------------------------------------------------------------
# 仁王之盾
# ---------------------------------------------------------------------------
def test_renwang_shields_up_to_three(room):
    """至多3艘船获得盾牌，抵挡一次伤害"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2)), ship((3, 3))]
    room.players[P1].remaining_ships = 4
    res = apply(room, P1, '仁王之盾')
    assert res.success is True
    assert res['temp_data_id'] == 'shield_choice'

    ok = server.handle_magic_target({
        'room_id': room.id, 'player_id': P1,
        'temp_data_id': 'shield_choice',
        'target_data': {'ship_indices': [0, 1, 2, 3]}  # 只能生效3艘
    })
    assert ok['status'] == 'success'
    assert sum(1 for s in room.players[P1].ships if s.shield) == 3

    # 盾牌抵挡一次伤害
    room.current_attacker = P2
    attack(room, P2, 0, 0)
    assert room.players[P1].remaining_ships == 4
    assert room.players[P1].ships[0].shield is False


# ---------------------------------------------------------------------------
# 钢筋铁骨
# ---------------------------------------------------------------------------
def test_gangjin_sacrifice_then_invincible(room):
    """牺牲一艘船，其余所有船进入无敌"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3
    res = apply(room, P1, '钢筋铁骨')
    assert res.success is True
    assert room.players[P1].remaining_ships == 2
    assert all(s.invincible for s in room.players[P1].ships)


def test_gangjin_requires_two_ships(room):
    room.players[P1].ships = [ship((0, 0))]
    res = apply(room, P1, '钢筋铁骨')
    assert res.success is False


# ---------------------------------------------------------------------------
# 神机妙算
# ---------------------------------------------------------------------------
def test_shenji_declare_prediction(room):
    """宣言数目x并登记初始船数用于结束阶段校验"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 1))]
    room.players[P1].remaining_ships = 2
    room.magic_temp_data = {'prediction': 2}
    res = apply(room, P1, '神机妙算')
    assert res.success is True
    assert room.players[P1].effect_flags.prediction == 2
    # 修正后存初始快照（船数+沉船数+已沉船的 id 快照），用沉船差值校验
    snap = room.game_effects[f'prediction_initial_{P1}']
    assert snap['ships'] == 2
    assert snap['sunken'] == 0
    # sunken_ids：结算时靠它区分"本大回合新沉的船"与旧沉船
    # （不能按 sunken_ships 的排列位置切分 —— 那个顺序不保证等于沉没先后）
    assert snap['sunken_ids'] == []


def test_shenji_requires_declaration(room):
    res = apply(room, P1, '神机妙算')
    # 新流程：未宣言时请求玩家宣言（不再直接失败）
    assert res.temp_data_id == 'shenji_declare'
    assert room.magic_temp_data.get('pending_shenji', {}).get('caster') == P1


# ---------------------------------------------------------------------------
# 灵气复苏
# ---------------------------------------------------------------------------
def test_lingqi_adjust_ship_count(room):
    """双方船数调整为x，并在原有位置重新部署"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3
    room.players[P2].ships = [ship((4, 4))]
    room.players[P2].remaining_ships = 1

    res = apply(room, P1, '灵气复苏')
    assert res.success is True
    assert room.magic_temp_data['max_ships'] == 3

    ok = server.confirm_magic_target({
        'room_id': room.id, 'player_id': P1,
        'temp_data_id': 'lingqi_choice',
        'target_data': {'target_ships': 2}
    })
    assert ok['status'] == 'success'
    assert room.players[P1].max_ships == 2
    assert room.players[P2].max_ships == 2
    assert room.state == 'placing_ships'


def _replay_lingqi(room, caster, n):
    """出牌 → 选船数 → 双方重新摆放，走真实入口。"""
    room.players[caster].magic_hand = [card('灵气复苏')]
    server.apply_magic_effect(room, caster, card('灵气复苏'), {})
    server.confirm_magic_target({
        'room_id': room.id, 'player_id': caster,
        'temp_data_id': 'lingqi_choice',
        'target_data': {'target_ships': n}
    })
    for p in (P1, P2):
        ships = [{'positions': [{'x': i, 'y': 0}], 'hits': []} for i in range(n)]
        server.handle_place_ships({'room_id': room.id, 'player_id': p, 'ships': ships})


def test_lingqi_preserves_turn_and_phase(room):
    """重新摆放后不重新猜拳：先后手、阶段、回合数按原对局继续。"""
    room.current_attacker = P2
    room.current_phase = 'preparation'
    room.attack_order = [P1, P2]
    room.round = 4
    for p, n in ((P1, 3), (P2, 4)):
        room.players[p].ships = [ship((i, 0)) for i in range(n)]
        room.players[p].remaining_ships = n

    _replay_lingqi(room, P2, 2)

    assert room.state == 'attacking', '不应停在猜拳阶段'
    assert room.current_attacker == P2, '先后手应保持原样'
    assert room.current_phase == 'preparation', '阶段应保持原样'
    assert room.attack_order == [P1, P2]
    assert room.round == 4
    assert room.players[P1].remaining_ships == 2
    assert room.players[P2].remaining_ships == 2


def test_lingqi_recalcs_attacks_in_preparation(room):
    """准备阶段：攻击次数按新船数重算。"""
    room.current_attacker = P1
    room.current_phase = 'preparation'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 5
    room.players[P1].ships = [ship((i, 0)) for i in range(3)]
    room.players[P1].remaining_ships = 3

    _replay_lingqi(room, P1, 2)

    assert room.current_phase == 'preparation'
    assert room.attacks_remaining == 2, '准备阶段应按新船数(2)重算'


def test_lingqi_keeps_attacks_in_battle_phase(room):
    """战斗阶段：保留原本剩余攻击次数，不凭空增加。"""
    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 1
    room.players[P1].ships = [ship((i, 0)) for i in range(3)]
    room.players[P1].remaining_ships = 3
    room.players[P2].ships = [ship((i, 5)) for i in range(3)]   # 对手也要有船，否则判 game_over
    room.players[P2].remaining_ships = 3

    _replay_lingqi(room, P1, 4)

    assert room.state == 'attacking'
    assert room.current_phase == 'battle'
    assert room.attacks_remaining == 1, '战斗阶段不应凭空补满攻击次数'


def test_lingqi_clears_its_own_flags(room):
    """标记用完即清，避免影响后续对局。"""
    room.current_attacker = P1
    room.attack_order = [P1, P2]
    room.players[P1].ships = [ship((0, 0))]
    room.players[P1].remaining_ships = 1

    _replay_lingqi(room, P1, 1)

    assert not getattr(room, 'lingqi_resurgence_applied', False)
    assert not getattr(room, 'lingqi_saved_state', None)


def test_normal_placement_still_goes_to_rps(room):
    """没有灵气复苏标记时，正常开局仍应进入猜拳。"""
    room.state = 'placing_ships'
    room.players[P1].ships = []
    room.players[P2].ships = []
    for p in (P1, P2):
        ships = [{'positions': [{'x': i, 'y': 0}], 'hits': []} for i in range(6)]
        server.handle_place_ships({'room_id': room.id, 'player_id': p, 'ships': ships})
    assert room.state == 'rock_paper_scissors'


# ---------------------------------------------------------------------------
# 败者食尘
# ---------------------------------------------------------------------------
def test_baizhe_reset_gameboard_targets_sid_not_player_key(room, events):
    """败者食尘的 reset_gameboard 必须发给 player.sid。

    room.players 的 key 在自定义房 / 人机房里是 user_id（≠ socket sid）。
    以前写成 to=p_id，事件根本送不到 —— 玩家界面毫无反应、只能手动刷新游戏
    才会开始重新摆船。游客恰好 p_id == sid，所以这个 bug 只在登录用户身上出现。
    """
    room.players[P1].ships = [ship((0, 0)), ship((1, 1))]
    room.players[P1].remaining_ships = 2
    room.players[P2].ships = [ship((4, 4))]
    room.players[P2].remaining_ships = 1

    apply(room, P1, '败者食尘')

    targets = sorted(t for (e, _d, t, _r) in events if e == 'reset_gameboard')
    assert targets == ['sid-p1', 'sid-p2'], f'应发给两个 sid，实际 {targets}'
    assert P1 not in targets and P2 not in targets, '不能把玩家 key 当成 sid 用'


def test_lingqi_reset_gameboard_targets_sid_not_player_key(room, events):
    """灵气复苏走的是同一段发放逻辑，同样必须发到 sid。"""
    room.magic_temp_data = {'type': 'lingqi_choice', 'max_ships': 6}
    events.clear()

    server.confirm_magic_target({
        'room_id': room.id, 'player_id': P1,
        'temp_data_id': 'lingqi_choice', 'target_data': {'target_ships': 3}})

    targets = sorted(t for (e, _d, t, _r) in events if e == 'reset_gameboard')
    assert targets == ['sid-p1', 'sid-p2'], f'应发给两个 sid，实际 {targets}'
    assert P1 not in targets and P2 not in targets, '不能把玩家 key 当成 sid 用'


# 当前生效效果角标：服务端每次变化都要把「真相」推给本人
def test_active_effects_broadcast_tracks_flag_lifecycle(room, events):
    """百亿补贴的角标必须随真实状态出现 / 消失（以前前端只加不删，看着像永久）。

    ⚠️ 推送形状已改成按收件人视角的 {self, opponent}：
    作者要求「双方都可见正在生效的效果」，所以对手现在【能看到】我的角标
    （通过他自己的 opponent 字段），与旧断言「对手不该看到我的角标」相反。
    """
    events.clear()
    server._emit_active_effects(room)
    got = [d for (e, d, _t, _r) in events if e == 'active_effects']
    assert got and all(d['self'] == [] and d['opponent'] == [] for d in got), '没效果时两边都应为空'

    # 打出百亿补贴 → 角标出现
    events.clear()
    apply(room, P1, '百亿补贴')
    server._emit_active_effects(room)
    by_self = {t: [b['name'] for b in d['self']] for (e, d, t, _r) in events if e == 'active_effects'}
    by_opp = {t: [b['name'] for b in d['opponent']] for (e, d, t, _r) in events if e == 'active_effects'}
    assert '百亿补贴' in by_self.get('sid-p1', []), '施法者自己的列表里要有'
    assert '百亿补贴' not in by_self.get('sid-p2', []), '它不是对手自己的效果'
    assert '百亿补贴' in by_opp.get('sid-p2', []), '★ 对手应该能看到我挂着什么（双方可见）'

    # 回合切换会清掉 subsidy → 角标必须跟着消失
    room.players[P1].effect_flags.__dict__ = {
        k: v for k, v in room.players[P1].effect_flags.__dict__.items()
        if k in ['holy_heart']}
    events.clear()
    server._emit_active_effects(room)
    by_self = {t: [b['name'] for b in d['self']] for (e, d, t, _r) in events if e == 'active_effects'}
    by_opp = {t: [b['name'] for b in d['opponent']] for (e, d, t, _r) in events if e == 'active_effects'}
    assert '百亿补贴' not in by_self.get('sid-p1', []), '标记被清后角标要消失'
    assert '百亿补贴' not in by_opp.get('sid-p2', []), '对手那边也要跟着消失'


def test_active_effects_sent_to_both_players_by_sid(room, events):
    """角标按 sid 直发本人（同样是 player.sid，不能拿玩家 key 当 sid）。"""
    events.clear()
    server._emit_active_effects(room)
    targets = sorted(t for (e, _d, t, _r) in events if e == 'active_effects')
    assert targets == ['sid-p1', 'sid-p2'], f'实际 {targets}'


def test_baizhe_restart_keep_hands(room):
    """重启对局但保留手牌；生效大回合内攻击次数为0"""
    give_hand(room.players[P1], ['轰炸'])
    give_hand(room.players[P2], ['冻结'])
    room.players[P1].ships = [ship((0, 0)), ship((1, 1)), ship((2, 2))]
    room.players[P1].remaining_ships = 3
    room.players[P2].ships = [ship((4, 4)), ship((5, 5))]
    room.players[P2].remaining_ships = 2

    res = apply(room, P1, '败者食尘')
    assert res.success is True
    assert room.state == 'placing_ships'
    assert room.attacks_remaining == 0
    # 手牌保留
    assert len(room.players[P1].magic_hand) == 1
    assert len(room.players[P2].magic_hand) == 1
    # 棋盘清空
    assert room.players[P1].ships == []
    assert room.players[P2].ships == []
    # 「重启正常对局」= 双方一律回到默认 6 艘，不是交换双方船数
    # （2026-09-14 修正：旧实现把 max_ships 互换，与卡面不符）
    assert room.players[P1].max_ships == 6
    assert room.players[P2].max_ships == 6


# ---------------------------------------------------------------------------
# 场地魔法替换 / 场地卡实战流程（handle_use_magic_card 会预先把 field_magic 设为卡对象）
# ---------------------------------------------------------------------------
def test_field_magic_replacement(room):
    apply(room, P1, '恶魔契约')
    res = apply(room, P2, '禁忌果实')
    assert room.field_magic.name == '禁忌果实'


def test_field_card_real_flow_crash(room):
    """复现实战：先按 use_magic_card 的逻辑预设 field_magic 再结算效果"""
    give_hand(room.players[P1], ['禁忌果实'])
    played = card('禁忌果实')
    room.field_magic = played  # handle_use_magic_card 第2302行的行为
    apply(room, P1, '禁忌果实')
    assert room.field_magic.name == '禁忌果实'


# ---------------------------------------------------------------------------
# 出牌阶段规则（前端发起 use_magic_card 时的服务端校验）
# ---------------------------------------------------------------------------
def test_speed3_playable_anytime(room):
    room.current_attacker = P2
    room.current_phase = 'end'
    assert server.can_play_magic_card(room, P1, card('失灵！')) is True


def test_speed12_require_own_turn(room):
    room.current_attacker = P2
    room.current_phase = 'battle'
    assert server.can_play_magic_card(room, P1, card('冻结')) is False
    room.current_attacker = P1
    assert server.can_play_magic_card(room, P1, card('冻结')) is True


def test_no_magic_in_end_phase(room):
    room.current_phase = 'end'
    assert server.can_play_magic_card(room, P1, card('冻结')) is False


# ---------------------------------------------------------------------------
# 前后端卡牌数据一致性（magic_cards.js vs magic_card.json）
# ---------------------------------------------------------------------------
def test_frontend_card_data_matches_backend():
    """前端 magic_cards.js 的卡名/速度/类型必须与后端 magic_card.json 一致"""
    import re
    from file import read_json

    backend = read_json('./static/magic_card.json')
    with open('./static/magic_cards.js', encoding='utf-8') as f:
        js_text = f.read()

    pattern = re.compile(
        r'name:\s*"([^"]+)",\s*speed:\s*(\d+),\s*type:\s*"([^"]+)"')
    frontend = [(m.group(1), int(m.group(2)), m.group(3))
                for m in pattern.finditer(js_text)]
    backend_seq = [(c['name'], int(c['speed']), c['type']) for c in backend]
    assert frontend == backend_seq


# ---------------------------------------------------------------------------
# 神之宣告的发动条件（2026-09-19 从 `<2` 收紧为 `<=2`）
# ---------------------------------------------------------------------------
def test_shenzhixuanga_refuses_when_two_ships_or_fewer(room):
    """★ 船数 ≤ 2 时不许发动，并**直接报出**「您的船数不足」。

    判据若仍是 `< 2`，2 艘那一档会被静默放行 —— 牺牲两艘后自己剩 0 艘、紧接着被判负，
    那不是玩家想要的取舍（作者明确要求拦掉）。这里顺带断言"一艘都没被牺牲"：
    只要有一艘被送掉，就说明拦的位置太晚（已经动过棋盘了）。
    """
    for n in (2, 1, 0):
        room.players[P1].ships = [ship((i, 0)) for i in range(n)]
        room.players[P1].remaining_ships = n
        res = apply(room, P1, '神之宣告', {'effect_choice': 1})
        assert res.success is False, f'{n} 艘时不该发动成功'
        assert res.message == '您的船数不足，无法使用神之宣告', res.message
        assert len(room.players[P1].ships) == n, f'{n} 艘时一艘都不该被牺牲'


def test_shenzhixuanga_still_works_with_three_ships(room):
    """3 艘是新的边界：可以发动，牺牲 2 艘后剩 1 艘（别改回 `<2`）。"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 0)), ship((2, 0))]
    room.players[P1].remaining_ships = 3
    room.players[P2].ships = [ship((3, 3))]
    room.players[P2].remaining_ships = 1
    room.magic_temp_data = {'effect_choice': 2}          # 跳过对方回合，免去"等对方点选"
    res = apply(room, P1, '神之宣告', {'effect_choice': 2})
    assert res.success is True, res.message
    assert room.players[P1].remaining_ships == 1, room.players[P1].remaining_ships


# ---------------------------------------------------------------------------
# 重摆棋盘必须终止「持续生效的范围效果」（2026-09-19 作者实测报的 bug）
#
# 原来的形状：四处重摆只调了 `_discard_excluded_ships()`（丢"神威除外船"），
# 却没人清「神威扣掉的区域」→ 棋盘换了新船，那片区域**继续挡攻击**（玩家："神威一直生效"）。
# 冻结的那片区域同理。现在统一走 `server._clear_board_effects()`。
# ---------------------------------------------------------------------------
def _shenwei_on(room, caster, victim, area):
    """让 `caster` 对 `victim` 的棋盘打神威！，返回结果（洞与除外船都记在 victim 名下）。"""
    res = apply(room, caster, '神威！', {'target_area': area})
    assert res.success is True, res.message
    assert server._cell_in_shenwei_hole(room, victim, area['x1'], area['y1']) is True
    return res


def test_clear_board_effects_only_touches_the_given_players(room, events):
    """★ 收口函数只清**指定玩家**名下的状态（回光返照不该越权清对方棋盘的标记）。

    两块棋盘各留一个洞：P2 打 P1 的棋盘、P1 打 P2 的棋盘，然后只清 P1。
    """
    room.players[P1].ships = [ship((0, 0)), ship((5, 5))]
    room.players[P1].remaining_ships = 2
    room.players[P2].ships = [ship((3, 3)), ship((0, 0))]
    room.players[P2].remaining_ships = 2
    _shenwei_on(room, P2, P1, {'x1': 0, 'x2': 2, 'y1': 0, 'y2': 2})
    _shenwei_on(room, P1, P2, {'x1': 3, 'x2': 5, 'y1': 3, 'y2': 5})

    events.clear()
    server._clear_board_effects(room, [P1], '单测')

    assert server._cell_in_shenwei_hole(room, P1, 1, 1) is False, '自己棋盘上的洞要清'
    assert server._cell_in_shenwei_hole(room, P2, 4, 4) is True, '不该动对方的棋盘'
    restored = [e for e in events if e[0] == 'shenwei_hole_restored']
    assert [(e[1] or {}).get('player') for e in restored] == [P1], restored


def test_lingqi_resurgence_clears_shenwei_holes_and_excluded_ships(room, events):
    """★ 灵气复苏（双方重摆）→ 神威扣掉的区域与除外船都必须终止。"""
    # ⚠️ 施法者自己也必须有船：`神威！`结算时会检查"己方棋盘是否被清空"，
    #    0 艘会被判负 → state 变 game_over → 后面的写操作全被 `_require_live_room` 挡掉。
    room.players[P1].ships = [ship((5, 5))]
    room.players[P1].remaining_ships = 1
    room.players[P2].ships = [ship((0, 0)), ship((1, 1)), ship((4, 4)), ship((5, 5))]
    room.players[P2].remaining_ships = 4
    _shenwei_on(room, P1, P2, {'x1': 0, 'x2': 2, 'y1': 0, 'y2': 2})
    assert room.game_effects.get('excluded_ships'), '神威应当留下了除外的船'

    room.magic_temp_data = {'max_ships': 6}
    events.clear()
    out = server.confirm_magic_target({
        'room_id': room.id, 'player_id': P1, 'temp_data_id': 'lingqi_choice',
        'target_data': {'target_ships': 6},
    })
    assert out.get('status') == 'success', out

    assert server._cell_in_shenwei_hole(room, P2, 1, 1) is False, '重摆后那片区域不该还挡攻击'
    assert not room.game_effects.get('excluded_ships'), '重摆后不该还留着除外船'
    assert any(e[0] == 'shenwei_hole_restored' for e in events), '必须通知前端恢复区域'


def test_afterglow_clears_only_the_casters_board_effects(room, events):
    """★ 回光返照只重摆**自己**的棋盘 → 只清自己那片（对方的洞留在对方棋盘上）。"""
    room.players[P1].ships = [ship((0, 0))]
    room.players[P1].remaining_ships = 1
    room.players[P2].ships = [ship((3, 3)), ship((4, 4))]
    room.players[P2].remaining_ships = 2
    _shenwei_on(room, P2, P1, {'x1': 0, 'x2': 2, 'y1': 0, 'y2': 2})     # 洞在 P1 棋盘
    _shenwei_on(room, P1, P2, {'x1': 3, 'x2': 5, 'y1': 3, 'y2': 5})     # 洞在 P2 棋盘

    room.attack_order = [P1, P2]        # 回光返照只能在自己先手时发动
    events.clear()
    res = apply(room, P1, '回光返照')
    assert res.success is True, res.message

    assert server._cell_in_shenwei_hole(room, P1, 1, 1) is False, '自己棋盘的洞要清'
    assert server._cell_in_shenwei_hole(room, P2, 4, 4) is True, '对方棋盘的洞不许被顺手清掉'


def test_frozen_area_cleared_when_that_board_is_rebuilt(room, events):
    """★ 冻结的那片区域也是"持续生效的范围"：重摆被冻的那块棋盘时必须终止。"""
    room.players[P2].ships = [ship((0, 0)), ship((1, 1))]
    room.players[P2].remaining_ships = 2
    apply(room, P1, '冻结', {'target_area': {'x1': 0, 'x2': 2, 'y1': 0, 'y2': 2}})
    assert (room.game_effects.get('frozen_area') or {}).get('owner') == P2, room.game_effects

    room.attack_order = [P2, P1]
    events.clear()
    res = apply(room, P2, '回光返照')
    assert res.success is True, res.message

    assert room.game_effects.get('frozen_area') is None, '重摆之后冻结区域不该还在生效'
    assert any(e[0] == 'frozen_area' and (e[1] or {}).get('cleared') for e in events), \
        '必须通知前端把那片区域清掉'


def test_last_stand_clears_own_holes_and_excluded_ships(room):
    """★ 绝处逢生同样是"重摆自己棋盘"：除外船必须丢掉。

    ⚠️ 少这一句的后果不是"区域还亮着"那么轻：除外的船到期会以**幽灵船**身份 append 回来
    （本项目实测过 6 艘变 8 艘，突破上限且坐标与现有船重叠）。
    这里只验"清理钩子跑过"，不验绝处逢生自己的放置流程（那是另一批的事）。
    """
    room.players[P1].ships = [ship((0, 0)),
                              ship((3, 3)), ship((4, 4)), ship((5, 5))]
    room.players[P1].remaining_ships = 4
    room.players[P2].ships = [ship((0, 0)), ship((1, 1)),
                              ship((3, 3)), ship((4, 4)), ship((5, 5))]
    room.players[P2].remaining_ships = 5
    _shenwei_on(room, P1, P2, {'x1': 0, 'x2': 2, 'y1': 0, 'y2': 2})
    assert room.game_effects.get('excluded_ships')

    apply(room, P2, '绝处逢生', {})

    assert server._cell_in_shenwei_hole(room, P2, 1, 1) is False, '自己棋盘上的洞要清'
    assert not room.game_effects.get('excluded_ships'), '除外船必须丢掉（否则会变幽灵船）'
