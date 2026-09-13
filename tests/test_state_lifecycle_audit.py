# -*- coding: utf-8 -*-
"""「状态生效/失效写在单一路径」类缺陷的系统性回归（2026-09-14 深度审计）。

这轮由三个并行审计（effect_flags 配对 / game_effects 与场地配对 / 前后端同步）
产出 10 个已实测复现的缺陷，本文件锁定其中可在后端单测覆盖的部分。

统一根因：某个状态的【设置】与【清除/消费】写在不同的代码路径里，
而该状态可以从多条路径被引入 —— 总有一条路径漏掉另一半。

已单独成文件的（不在这里重复）：
  · 教皇旨意归零         → test_papal_decree_zero_attacks.py
  · 饮血流程             → test_yinxue_flow_fix.py
  · 败者食尘重启         → test_chain_hand_and_baizhe_fix.py
  · 多级连锁无效化       → test_multilevel_chain_negation.py

本文件覆盖：
  A. 拆场地后攻击次数不纠正（含 preparation 相位整段被跳过）
  B. 伊甸园被拆后不重算（白拿攻击次数）
  C. 神威除外 + 棋盘重摆 → 幽灵船突破 6 艘上限
  D. 三张"持续型"标记在小回合切换被误清（应活到本大回合结束）
  E. 教皇旨意弃卡攻击：余音绕梁不生效 / 伤害统计不记（Freezing！被误放行）
  F. 火力全开在战斗阶段打出 = 静默失效
  G. resolve_chain 收尾不补 ships / phase（护盾、钢筋铁骨、回光返照）
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


def make_room(n_p1=6):
    room = GameRoom('test-room')
    room.players[P1] = Player(name='p1', ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(n_p1)],
                              attacks=[], remaining_ships=n_p1, sid='sid-p1')
    room.players[P2] = Player(name='p2', ships=[PlayerShip(positions=[Position(i, 5)], hits=[]) for i in range(6)],
                              attacks=[], remaining_ships=6, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'preparation'
    room.attack_order = [P1, P2]
    room.attacks_remaining = n_p1
    room.round = 5
    room_manager.rooms[room.id] = room
    return room


def card(name):
    return MagicCard(name)


def use(room, caster, name):
    return server.handle_use_magic_card({
        'room_id': room.id, 'player_id': caster,
        'card': {'name': name}, 'targets': {},
    })


# ---------------------------------------------------------------------------
# A. 拆场地后攻击次数必须纠正（含 preparation 相位）
# ---------------------------------------------------------------------------
def test_papal_removed_in_preparation_restores_attacks(room):
    """准备阶段打出教皇旨意 → 拆场地 → 次数必须恢复（6 艘船 = 6）。"""
    room.players[P1].magic_hand = [card('教皇旨意')]
    use(room, P1, '教皇旨意')
    assert room.attacks_remaining == 0

    server._clear_field_magic_effects(room)
    assert room.attacks_remaining == 6, (
        f'准备阶段拆场也要恢复，实际 {room.attacks_remaining}')


def test_papal_removed_in_preparation_then_battle_can_attack(room):
    """★ 完整卡死路径：准备阶段打 → 拆 → 进战斗阶段 → 必须能开炮。

    修复前：attacks 停在 0，玩家 6 艘船一发都打不出去。
    """
    room.players[P1].magic_hand = [card('教皇旨意')]
    use(room, P1, '教皇旨意')
    server._clear_field_magic_effects(room)
    room.field_magic = None
    room.field_magic_owner = None

    assert server.enter_battle_phase({'room_id': room.id, 'player_id': P1})['status'] == 'success'
    assert room.attacks_remaining == 6
    res = server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 5, 'y': 5})
    assert res.get('status') == 'success', f'应能开炮，实际 {res}'


def test_enter_battle_phase_recalculates_unconditionally(room):
    """进战斗阶段无条件按当前场地规则重算（不再只处理两个特例）。"""
    room.attacks_remaining = 99          # 故意给个错值
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert room.attacks_remaining == 6, '应按存活船数重算'


# ---------------------------------------------------------------------------
# B. 伊甸园被拆除后必须重算
# ---------------------------------------------------------------------------
def test_eden_removed_recalculates_attacks(room):
    """2 艘船 + 伊甸园 = 4 次；拆掉后应回到 2 次（不能白拿）。"""
    room.players[P1].ships = [PlayerShip(positions=[Position(0, 0)], hits=[]),
                              PlayerShip(positions=[Position(1, 0)], hits=[])]
    room.players[P1].remaining_ships = 2
    room.field_magic = card('伊甸园')
    room.field_magic_owner = P1
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert room.attacks_remaining == 4

    server._clear_field_magic_effects(room)
    assert room.attacks_remaining == 2, (
        f'伊甸园离场后应回到存活船数，实际 {room.attacks_remaining}')


def test_eden_replaced_by_other_field_recalculates(room):
    """伊甸园被别的场地顶替（_place_field_magic 路径）也要重算。"""
    room.players[P1].ships = [PlayerShip(positions=[Position(0, 0)], hits=[]),
                              PlayerShip(positions=[Position(1, 0)], hits=[])]
    room.players[P1].remaining_ships = 2
    room.field_magic = card('伊甸园')
    room.field_magic_owner = P1
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert room.attacks_remaining == 4

    # 顶替成禁忌果实
    server._place_field_magic(room, P1, card('禁忌果实'))
    assert room.attacks_remaining == 2, (
        f'顶替后应重算，实际 {room.attacks_remaining}')


def test_other_field_untouched(room):
    """反证：拆除与攻击次数无关的场地（恶魔契约）不该动次数。"""
    room.players[P1].magic_hand = [card('恶魔契约')]
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    before = room.attacks_remaining

    room.game_effects['demon_contract'] = True
    server._clear_field_magic_effects(room)
    assert room.attacks_remaining == before, '恶魔契约不影响攻击次数'
    assert room.game_effects.get('demon_contract') is None, '但标记必须清掉'


# ---------------------------------------------------------------------------
# C. 神威除外 + 棋盘重摆 = 幽灵船
# ---------------------------------------------------------------------------
def setup_excluded(room, player_id, n=2):
    excluded = []
    for sh in list(room.players[player_id].ships)[:n]:
        room.players[player_id].ships.remove(sh)
        room.players[player_id].remaining_ships -= 1
        excluded.append(sh)
    room.game_effects.setdefault('excluded_ships', []).append({
        'player': player_id, 'ships': excluded, 'return_turn': room.round + 1,
    })
    return excluded


def test_ghost_ship_after_huiguang_reset(room):
    """神威除外 → 回光返照重摆 → 到期不得凭空多出船（原来是 6 变 8）。"""
    setup_excluded(room, P2, 2)
    room.attack_order = [P2, P1]          # 回光返照要求先手
    server.apply_magic_effect(room, P2, card('回光返照'), {})

    # 重新摆放 6 艘
    room.players[P2].ships = [PlayerShip(positions=[Position(i, 3)], hits=[]) for i in range(6)]
    room.players[P2].remaining_ships = 6

    room.round += 1
    server._restore_due_shenwei(room, room.round)
    assert len(room.players[P2].ships) == 6, (
        f'重摆后不该有幽灵船，实际 {len(room.players[P2].ships)} 艘')
    assert room.players[P2].remaining_ships == 6


def test_ghost_ship_after_lingqi_reset(room):
    """神威除外 → 灵气复苏重摆（上限 3）→ 到期不得突破上限。"""
    setup_excluded(room, P2, 2)
    room.players[P1].magic_hand = [card('灵气复苏')]
    server.apply_magic_effect(room, P1, card('灵气复苏'), {})
    server.confirm_magic_target({
        'room_id': room.id, 'player_id': P1, 'temp_data_id': 'lingqi_choice',
        'target_data': {'target_ships': 3},
    })
    assert not room.game_effects.get('excluded_ships'), '重摆后除外名单应清空'

    room.round += 1
    server._restore_due_shenwei(room, room.round)
    assert len(room.players[P2].ships) <= 3, (
        f'不得超过新上限，实际 {len(room.players[P2].ships)} 艘')


def test_ghost_ship_after_baizhe_reset(room):
    """神威除外 → 败者食尘重摆 → 除外名单清空。"""
    setup_excluded(room, P2, 2)
    room.players[P1].magic_hand = [card('败者食尘')]
    server.apply_magic_effect(room, P1, card('败者食尘'), {})
    assert not room.game_effects.get('excluded_ships')


def test_normal_shenwei_return_still_works(room):
    """反证：正常的「神威除外 → 到期原地归还」必须仍然工作。"""
    setup_excluded(room, P2, 2)
    assert len(room.players[P2].ships) == 4
    room.round += 1
    server._restore_due_shenwei(room, room.round)
    assert len(room.players[P2].ships) == 6, '正常归还不能被误伤'
    assert room.players[P2].remaining_ships == 6


# ---------------------------------------------------------------------------
# D. 持续型标记的生命周期（本大回合，不是本小回合）
# ---------------------------------------------------------------------------
def test_persistent_flags_survive_turn_switch():
    """百亿补贴 / 饮血 / 八方来财 应活到本大回合结束，不在小回合切换时被清。"""
    keep = server.FLAGS_KEEP_ACROSS_TURN
    for name in ('subsidy', 'subsidy_bonus', 'vampire', 'treasure_hunter'):
        assert name in keep, f'{name} 应跨小回合保留'
    # 只持续本回合的不能进白名单
    for name in ('battle_spirit', 'wuxian', 'double_attacks', 'last_stand'):
        assert name not in keep, f'{name} 只持续本回合，不该保留'


def test_prune_effect_flags_keeps_whitelist(room):
    """_prune_effect_flags 只按白名单裁剪，且对双方都生效。"""
    room.players[P1].effect_flags.subsidy = True
    room.players[P1].effect_flags.subsidy_bonus = 9
    room.players[P1].effect_flags.vampire = True
    room.players[P1].effect_flags.battle_spirit = True
    room.players[P2].effect_flags.treasure_hunter = True

    server._prune_effect_flags(room, server.FLAGS_KEEP_ACROSS_TURN)

    f1 = room.players[P1].effect_flags
    assert f1.subsidy is True and f1.subsidy_bonus == 9 and f1.vampire is True
    assert f1.battle_spirit is False, '只持续本回合的应被清'
    assert room.players[P2].effect_flags.treasure_hunter is True


def test_prune_effect_flags_returns_whether_changed(room):
    """返回值用于判断是否需要刷新角标。"""
    assert server._prune_effect_flags(room, server.FLAGS_KEEP_ACROSS_TURN) is False
    room.players[P1].effect_flags.battle_spirit = True
    assert server._prune_effect_flags(room, server.FLAGS_KEEP_ACROSS_TURN) is True


def test_prune_to_empty_round_whitelist_clears_all(room):
    """大回合结束时（白名单为空）所有标记清空。"""
    room.players[P1].effect_flags.subsidy = True
    room.players[P1].effect_flags.vampire = True
    server._prune_effect_flags(room, server.FLAGS_KEEP_ACROSS_ROUND)
    assert room.players[P1].effect_flags.subsidy is False
    assert room.players[P1].effect_flags.vampire is False


# ---------------------------------------------------------------------------
# E. 教皇旨意弃卡攻击：余音绕梁 + 伤害统计
# ---------------------------------------------------------------------------
def setup_papal(room):
    """把房间调整到"教皇旨意生效 + 处于战斗阶段"，可以直接弃卡攻击。"""
    room.game_effects['papal_edict'] = True
    room.field_magic = card('教皇旨意')
    room.field_magic_owner = P1
    room.attacks_remaining = 0        # 教皇旨意下常规攻击次数恒为 0（全局字段）
    room.current_phase = 'battle'      # 弃卡攻击要求处于战斗阶段


def test_papal_attack_respects_forced_kill(room):
    """余音绕梁在弃卡攻击路径也要生效（能打穿无敌船）。"""
    setup_papal(room)
    room.players[P2].ships = [PlayerShip(positions=[Position(5, 5)], hits=[])]
    room.players[P2].ships[0].invincible = True
    room.players[P2].remaining_ships = 1
    room.players[P1].effect_flags.forced_kill = 2
    room.players[P1].magic_hand = [card('轰炸'), card('冻结')]

    server.handle_papal_attack({
        'room_id': room.id, 'player_id': P1, 'x': 5, 'y': 5, 'discard_card_index': 0,
    })
    assert room.players[P2].remaining_ships == 0, '无敌船应被强制击杀'


def test_papal_attack_records_damage(room):
    """弃卡攻击击沉后必须记 damage_dealt_this_turn。

    否则 Freezing！ 会被误判为"本回合没让对方减船"而放行，
    白送一个跳过对方整回合的效果。
    """
    setup_papal(room)
    room.players[P1].magic_hand = [card('轰炸'), card('Freezing！')]
    before = room.players[P2].remaining_ships
    server.handle_papal_attack({
        'room_id': room.id, 'player_id': P1, 'x': 5, 'y': 5, 'discard_card_index': 0,
    })
    assert room.players[P2].remaining_ships < before, '这一炮应该击沉了船'
    assert room.players[P1].damage_dealt_this_turn > 0, '伤害统计必须记录'


def test_papal_attack_battle_spirit(room):
    """越战越勇在弃卡攻击路径也要生效（+1 次攻击）。"""
    setup_papal(room)
    room.players[P1].effect_flags.battle_spirit = True
    room.players[P1].magic_hand = [card('轰炸'), card('冻结')]
    # 让对手只有 1 艘船，保证第一炮就击沉
    room.players[P2].ships = [PlayerShip(positions=[Position(5, 5)], hits=[])]
    room.players[P2].remaining_ships = 1

    server.handle_papal_attack({
        'room_id': room.id, 'player_id': P1, 'x': 5, 'y': 5, 'discard_card_index': 0,
    })
    assert room.attacks_remaining == 1, f'越战越勇应 +1，实际 {room.attacks_remaining}'


# ---------------------------------------------------------------------------
# F. 火力全开在战斗阶段打出必须当场翻倍
# ---------------------------------------------------------------------------
def test_huoli_in_battle_phase_doubles_immediately(room):
    """战斗阶段打出 → 当场翻倍（阶段转换不会再发生）。"""
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert room.attacks_remaining == 6

    room.players[P1].magic_hand = [card('火力全开')]
    res = server.apply_magic_effect(room, P1, card('火力全开'), {})
    assert res.success is True
    assert room.attacks_remaining == 12, '应立即翻倍'
    assert room.players[P1].effect_flags.double_attacks is False, '标记应已消费'


def test_huoli_in_preparation_defers_to_battle_phase(room):
    """准备阶段打出 → 只挂标记，进战斗阶段时才翻（那时才知道最终次数）。"""
    room.players[P1].magic_hand = [card('火力全开')]
    server.apply_magic_effect(room, P1, card('火力全开'), {})
    assert room.players[P1].effect_flags.double_attacks is True, '准备阶段只挂标记'

    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    assert room.attacks_remaining == 12
    assert room.players[P1].effect_flags.double_attacks is False


def test_huoli_emits_attacks_updated(room, events):
    """战斗阶段当场翻倍后要广播。"""
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})
    room.players[P1].magic_hand = [card('火力全开')]
    server.apply_magic_effect(room, P1, card('火力全开'), {})
    updates = [d for e, d, to, r in events if e == 'attacks_updated']
    assert updates and updates[-1]['attacks_remaining'] == 12


# ---------------------------------------------------------------------------
# G. resolve_chain 收尾补全推送
# ---------------------------------------------------------------------------
def test_resolve_chain_emits_ships_and_phase(room, events):
    """结算收尾必须补推 ships / 自己的棋盘 / phase。

    护盾（仁王之盾）、钢筋铁骨、回光返照三个分支自己一个 emit 都没有，
    全靠收尾兜底 —— 漏了它们前端就永远看不到。
    """
    room.chain = [ChainItem(P1, card('无中生有'), {}, 0)]
    server.resolve_chain(room)

    kinds = [e for e, d, to, r in events]
    assert 'ships_updated' in kinds, '必须补推船数'
    assert 'player_ships_updated' in kinds, '必须补推各自的棋盘'
    assert 'phase_updated' in kinds, '必须补推阶段'
    # 双方都要收到自己的棋盘
    owners = {to for e, d, to, r in events if e == 'player_ships_updated'}
    assert owners == {'sid-p1', 'sid-p2'}


def test_player_ships_payload_includes_shield_and_invincible(room, events):
    """己方棋盘必须带 shield / invincible，否则前端画不出这两种状态。"""
    room.players[P1].ships[0].shield = True
    room.players[P1].ships[1].invincible = True
    server._emit_player_ships(room, P1)

    payload = [d for e, d, to, r in events if e == 'player_ships_updated'][-1]
    ships = payload['ships']
    assert ships[0]['shield'] is True
    assert ships[0]['invincible'] is False
    assert ships[1]['invincible'] is True
    # 既有字段不能被挤掉
    assert 'frozen' in ships[0] and 'alive' in ships[0]


def test_renwang_shield_choice_emits_player_ships(room, events):
    """仁王之盾加盾后必须把己方棋盘推给本人（原来零 emit）。"""
    room.magic_temp_data['temp_data_id'] = 'shield_choice'
    res = server.confirm_magic_target({
        'room_id': room.id, 'player_id': P1, 'temp_data_id': 'shield_choice',
        'target_data': {'ship_indices': [0, 1]},
    })
    assert res.get('status') == 'success', res
    assert room.players[P1].ships[0].shield is True

    payloads = [d for e, d, to, r in events if e == 'player_ships_updated']
    assert payloads, '加盾后必须推送己方棋盘'
    assert payloads[-1]['ships'][0]['shield'] is True


# ---------------------------------------------------------------------------
# 盾挡下一击：不能让前端画成普通"命中"
# ---------------------------------------------------------------------------
def test_shield_absorb_broadcasts_event(room, events):
    """盾挡下一击要有专门的 shield_absorbed 事件。"""
    room.players[P2].ships = [PlayerShip(positions=[Position(5, 5)], hits=[])]
    room.players[P2].ships[0].shield = True
    room.players[P2].remaining_ships = 1
    server.enter_battle_phase({'room_id': room.id, 'player_id': P1})

    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 5, 'y': 5})

    absorbed = [d for e, d, to, r in events if e == 'shield_absorbed']
    assert absorbed, '盾挡下时必须广播，否则前端只会画成一次普通命中'
    assert absorbed[-1]['player'] == P2
    assert room.players[P2].ships[0].shield is False, '盾应被消耗'
    assert room.players[P2].ships[0].hits == [], '船毫发无伤'


def test_papal_attack_shield_absorb_broadcasts(room, events):
    """教皇旨意弃卡攻击路径同样要广播盾挡下。

    注意弃卡攻击会打两次：第一发被盾挡下（船毫发无伤），
    第二发盾已消耗，所以会真的命中。这里只断言"盾被消耗 + 有广播"，
    不给第二发的结果下断言（那是既有规则）。
    """
    setup_papal(room)
    room.players[P2].ships = [PlayerShip(positions=[Position(5, 5)], hits=[])]
    room.players[P2].ships[0].shield = True
    room.players[P2].remaining_ships = 1
    room.players[P1].magic_hand = [card('轰炸'), card('冻结')]

    server.handle_papal_attack({
        'room_id': room.id, 'player_id': P1, 'x': 5, 'y': 5, 'discard_card_index': 0,
    })
    absorbed = [d for e, d, to, r in events if e == 'shield_absorbed']
    assert absorbed, '弃卡攻击路径也要广播盾挡下'
    assert room.players[P2].ships[0].shield is False, '盾应被消耗'
