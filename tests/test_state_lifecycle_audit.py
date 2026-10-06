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






# ---------------------------------------------------------------------------
# B. 伊甸园被拆除后必须重算
# ---------------------------------------------------------------------------


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
    # ⚠️ 例外：绝处逢生是【两个】标记。last_stand（锁卡）只持续本回合，
    # 但 last_stand_win（击杀即胜）必须跨回合、活到对局结束 ——
    # 此前两者合成一个，于是击杀即胜跟着锁卡一起过期，只在发动当回合有效。
    assert 'last_stand_win' in keep, '绝处逢生的击杀即胜必须跨小回合保留'
    assert 'last_stand_win' in server.FLAGS_KEEP_ACROSS_ROUND, '也要跨大回合'


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
    """余音绕梁在教皇旨意的新流程下要生效（弃卡换次数 → 普通攻击能打穿无敌船）。

    ⚠️ 教皇旨意已改版：弃卡只负责「攻击次数 +2」，攻击本身走普通 attack 通道。
    所以这里先弃卡、再用 handle_attack 打那一炮。
    """
    setup_papal(room)
    room.players[P2].ships = [PlayerShip(positions=[Position(5, 5)], hits=[])]
    room.players[P2].ships[0].invincible = True
    room.players[P2].remaining_ships = 1
    room.players[P1].effect_flags.forced_kill = 2
    room.players[P1].magic_hand = [card('轰炸'), card('冻结')]

    server.handle_papal_discard({
        'room_id': room.id, 'player_id': P1, 'discard_card_index': 0,
    })
    assert room.attacks_remaining == 2, '弃卡应换来 2 次攻击'
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 5, 'y': 5})
    assert room.players[P2].remaining_ships == 0, '无敌船应被强制击杀'






# ---------------------------------------------------------------------------
# F. 火力全开在战斗阶段打出必须当场翻倍
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# G. resolve_chain 收尾补全推送
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# 盾挡下一击：不能让前端画成普通"命中"
# ---------------------------------------------------------------------------
