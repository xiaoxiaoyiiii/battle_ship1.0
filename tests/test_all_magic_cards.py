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


def test_zengyuan_full_board_rejected(room):
    room.players[P1].ships = [ship((i, 0)) for i in range(6)]
    room.players[P1].remaining_ships = 6
    res = apply(room, P1, '增援')
    assert res.success is False


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
    assert room.magic_temp_data['pending_sacrifice']['player'] == P1


def test_demon_contract_sacrifice_requires_own_ship(room):
    """恶魔契约的牺牲必须点自己船所在格，选空格要被拒。"""
    apply(room, P1, '恶魔契约')
    room.players[P1].ships = [ship((4, 4)), ship((5, 5))]
    room.players[P1].remaining_ships = 2
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1
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
def test_pingdeng_negates_ship_change(room):
    """使船数改变的攻击无效化（恢复船只）"""
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1
    attack(room, P1, 0, 0)
    assert room.players[P2].remaining_ships == 0

    res = apply(room, P1, '平等条约')
    assert res.success is True
    assert room.players[P2].remaining_ships == 1
    assert len(room.players[P2].ships) == 1


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
    pending = room.magic_temp_data.get('pending_sacrifice')
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
    room.players[P1].ships = [ship((0, 0)), ship((1, 1))]
    room.players[P1].remaining_ships = 2
    room.magic_temp_data = {'effect_choice': 2}
    apply(room, P1, '神之宣告')
    # 修正后存玩家ID（与 end_turn 的比较语义一致）
    assert room.skip_opponent_turn == P2


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
    pending = room.magic_temp_data.get('pending_sacrifice')
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
def test_wuxian_plus_three_when_no_damage(room):
    """本回合未造成伤害则攻击次数+3"""
    room.players[P1].damage_dealt_this_turn = 0
    before = room.attacks_remaining
    res = apply(room, P1, '五险一金')
    assert res.success is True
    assert room.attacks_remaining == before + 3


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
    # 卡面要求"击中对方后"才能使用
    room.last_attack = {'attacker': P1, 'x': 0, 'y': 0, 'hit': True}
    apply(room, P1, '饮血')
    assert room.players[P1].effect_flags.vampire is True

    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1
    attack(room, P1, 0, 0)
    assert any(c.name == '轰炸' for c in room.players[P1].magic_hand)


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
    pending = room.magic_temp_data.get('pending_sacrifice')
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
    """全链路：结束阶段出牌 → 结束回合 → 对手回合被跳过"""
    room.attack_order = [P1, P2]
    room.current_attacker = P1
    room.current_phase = 'end'
    room.attacks_remaining = 0
    room.players[P1].damage_dealt_this_turn = 0

    res = _play_freezing(room, P1)
    assert res['status'] == 'success', res
    assert room.skip_opponent_turn == P2

    server.end_turn({'room_id': room.id, 'player_id': P1})
    assert room.current_attacker == P1, 'P2 的回合应被跳过'
    assert room.current_phase == 'preparation'


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

    server.end_turn({'room_id': room.id, 'player_id': P1})
    assert room.current_attacker == P1, 'P2 的回合应被跳过'
    assert room.current_phase == 'preparation'


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
    """本大回合攻击阶段攻击次数翻倍"""
    room.players[P1].ships = [ship((0, 0)), ship((1, 1))]
    room.players[P1].remaining_ships = 2
    apply(room, P1, '火力全开')
    room.current_phase = 'preparation'
    room.attacks_remaining = 2
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert room.attacks_remaining == 4
    assert room.players[P1].effect_flags.double_attacks is False


# ---------------------------------------------------------------------------
# 加百列之光
# ---------------------------------------------------------------------------
def test_jiabaili_negates_last_and_field(room):
    """无效化对方上一张魔法卡和当前场地魔法"""
    room.magic_history = [{'card': card('轰炸'), 'caster': P2}]
    room.field_magic = card('禁忌果实')
    res = apply(room, P1, '加百列之光')
    assert res.success is True
    assert room.magic_history == []
    assert room.field_magic is None


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
    # 修正后存初始快照（船数+沉船数），用沉船差值校验
    assert room.game_effects[f'prediction_initial_{P1}'] == {'ships': 2, 'sunken': 0}


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
    # 船数限制互换
    assert room.players[P1].max_ships == 2
    assert room.players[P2].max_ships == 3


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
