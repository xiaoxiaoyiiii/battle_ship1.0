# -*- coding: utf-8 -*-
"""仁王之盾「破盾」与绝处逢生「候选格」的回归测试（2026-09-14）。

作者反馈：

1. 仁王之盾 —— 「攻击到带盾的船之后那个格子会直接变成红叉叉 不能再次攻击了就
   改成一个特殊一点的格子样式 能看出来是带盾牌的船被破盾了
   然后在同一回合内还是可以再次攻击这个地方的」

2. 绝处逢生 —— 「这一方使用绝处逢生通过之后 让原本有船的六个格子高亮标给对方
   然后不要是红叉叉 不然的话打不了」

两者的病灶是同一个：**把"这一格已经打过了"当成铁律记下来**。
`attacks` 数组同时决定「前端画不画叉」和「这一格还能不能点」，
于是一次没造成任何伤害/一次本来就没打过的交互，被永久/整回合锁死了。
"""
import pytest

import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def events(monkeypatch):
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    monkeypatch.setattr(server.socketio, 'start_background_task', lambda t, *a, **k: None)
    monkeypatch.setattr(server, '_schedule_chain_timeout', lambda *a, **k: None)
    monkeypatch.setattr(server, '_schedule_priority_timeout', lambda *a, **k: None)
    monkeypatch.setattr(server, '_has_request_context', lambda: False)
    return captured


def make_room():
    room = GameRoom('shield-laststand-room')
    room.players[P1] = Player(name='p1',
                              ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(6)],
                              attacks=[], remaining_ships=6, sid='sid-p1')
    room.players[P2] = Player(name='p2',
                              ships=[PlayerShip(positions=[Position(i, 5)], hits=[]) for i in range(6)],
                              attacks=[], remaining_ships=6, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 5
    room.magic_deck = [MagicCard(n) for n in ['冻结', '疗愈', '仁王之盾', '绝处逢生']]
    room_manager.rooms[room.id] = room
    return room


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def attack(room, x, y, attacker=P1):
    return server.handle_attack({'room_id': room.id, 'player_id': attacker, 'x': x, 'y': y})


def attack_results(events):
    """attack_result 广播的是 AttackResult 实例（emit 时才序列化），这里统一成 dict。"""
    out = []
    for e, d, _t, _r in events:
        if e != 'attack_result':
            continue
        out.append(d.to_dict() if hasattr(d, 'to_dict') else d)
    return out


def attacked_cells(room, player=P1):
    return sorted((a.x, a.y) for a in room.players[player].attacks)


# ===========================================================================
# 仁王之盾：破盾的那一格不算「已攻击」，同一回合还能再打
# ===========================================================================
def shield_p2_ship_at(room, x, y):
    ship = next(s for s in room.players[P2].ships if s.positions[0].x == x)
    ship.positions = [Position(x, y)]
    ship.hits = []
    ship.shield = True
    return ship


def test_shielded_hit_is_marked_as_shield_blocked(room, events):
    """★ 被盾挡下的那一炮要在 attack_result 里标出来，前端才能画"破盾"而不是命中叉。"""
    shield_p2_ship_at(room, 3, 5)

    resp = attack(room, 3, 5)

    assert resp['status'] == 'success'
    res = attack_results(events)[-1]
    assert res['shield_blocked'] is True, res
    assert res['ship_sunk'] is False
    assert room.players[P2].ships[[s.positions[0].x for s in room.players[P2].ships].index(3)].shield is False


def test_shield_blocked_cell_is_not_recorded_as_attacked(room, events):
    """★ 核心：破盾的那一格不能进 attacks —— 否则前端画叉 + 不绑点击，整回合打不了。"""
    shield_p2_ship_at(room, 3, 5)

    attack(room, 3, 5)

    assert (3, 5) not in attacked_cells(room), \
        f'破盾格不该算已攻击，实际 attacks={attacked_cells(room)}'


def test_can_attack_the_same_cell_again_in_the_same_turn(room, events):
    """★ 破盾之后同一回合还能再打这一格，而且这一炮真的造成伤害。"""
    ship = shield_p2_ship_at(room, 3, 5)

    first = attack(room, 3, 5)
    assert first['status'] == 'success'
    assert ship.hits == [], '第一炮只该破盾，不该造成伤害'

    second = attack(room, 3, 5)

    assert second['status'] == 'success', f'第二炮必须能打（{second}）'
    assert len(ship.hits) == 1, '第二炮要真的打中'
    res = attack_results(events)[-1]
    assert res['shield_blocked'] is False, '第二次不该再被盾挡'
    assert res['hit'] is True


def test_shield_blocked_shot_still_costs_an_attack(room, events):
    """盾挡掉的是一发炮弹：攻击次数照扣（只是格子不算"已打过"）。"""
    shield_p2_ship_at(room, 3, 5)
    before = room.attacks_remaining

    attack(room, 3, 5)

    assert room.attacks_remaining == before - 1


def test_second_shot_on_the_broken_shield_cell_is_recorded(room, events):
    """破盾后真正打中的那一炮，才把这一格记进 attacks（此后前端正常画叉）。"""
    shield_p2_ship_at(room, 3, 5)
    attack(room, 3, 5)          # 破盾
    attack(room, 3, 5)          # 真打中

    assert (3, 5) in attacked_cells(room)


def test_normal_attacks_are_still_recorded(room, events):
    """反证：没有盾的普通攻击照旧记账（否则"同一格打两次"就没人拦了）。"""
    attack(room, 2, 5)

    assert (2, 5) in attacked_cells(room)
    dup = attack(room, 2, 5)
    assert dup['status'] == 'error' and '已经攻击过' in dup['message'], dup


def test_forced_kill_still_goes_through_a_shield(room, events):
    """余音绕梁（强制击杀）本来就无视盾牌 —— 别被这次改动带坏。"""
    ship = shield_p2_ship_at(room, 3, 5)
    room.players[P1].effect_flags.forced_kill = 1

    attack(room, 3, 5)

    res = attack_results(events)[-1]
    assert res['ship_sunk'] is True
    assert res['shield_blocked'] is False, '强制击杀不该被盾挡下'
    assert (3, 5) in attacked_cells(room)


# ===========================================================================
# 绝处逢生：候选格公开高亮，且不是红叉（对方照样能打）
# ===========================================================================
def last_stand_cells_events(events):
    return [d for e, d, _t, _r in events if e == 'last_stand_cells']


def play_last_stand(room, events):
    """让 P1 走真实结算打出绝处逢生（速阶3，可随时使用）。"""
    room.players[P1].remaining_ships = 4
    room.players[P1].ships = room.players[P1].ships[:4]
    room.players[P1].magic_hand = [MagicCard('绝处逢生')]
    return server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '绝处逢生'}, 'targets': {},
    })


def test_last_stand_publishes_candidate_cells(room, events):
    """★ 打出绝处逢生的那一刻就要把"原本有船的格子"公开出去。"""
    play_last_stand(room, events)

    got = last_stand_cells_events(events)
    assert got, '必须下发 last_stand_cells'
    cells = {(c['x'], c['y']) for c in got[-1]['cells']}
    assert cells == {(0, 0), (1, 0), (2, 0), (3, 0)}, cells
    # 公开信息：发给房间内所有人（前端两侧都要高亮）
    targets = [r for e, _d, _t, r in events if e == 'last_stand_cells']
    assert targets and targets[-1] == room.id, '应广播给双方'


def test_candidate_cells_survive_until_next_big_round(room, events):
    """候选格在换大回合时要清掉（下个回合再亮着就是过期线索）。"""
    play_last_stand(room, events)
    assert room.game_effects.get('last_stand_cells')

    # 让回合走到大回合边界：P2 结束回合 → next_index 绕回 0
    room.current_attacker = P2
    room.current_phase = 'end'
    events.clear()
    server.end_turn({'room_id': room.id, 'player_id': P2})

    assert not room.game_effects.get('last_stand_cells'), '大回合开始应清掉候选格'
    cleared = last_stand_cells_events(events)
    assert cleared and cleared[-1]['cells'] == [], '要明确下发"清空"，否则前端一直亮着'


def test_room_sync_carries_candidate_cells(room, events):
    """重连快照要带上候选格，否则回来高亮没了、又以为那几格不能打。"""
    play_last_stand(room, events)

    sync = server._build_room_sync(room, P1)

    cells = {(c['x'], c['y']) for c in sync['last_stand_cells']}
    assert cells == {(0, 0), (1, 0), (2, 0), (3, 0)}, sync['last_stand_cells']


def test_candidate_cell_is_attackable_after_placement(room, events):
    """★ 核心：唯一一艘新船落在其中一格之后，对方必须能打那一格。"""
    play_last_stand(room, events)
    pending = room.magic_temp_data.get('pending_placement')
    assert pending and pending['kind'] == 'last_stand', pending

    # 施法者把唯一一艘放在 (1,0)
    resp = server.handle_confirm_reinforcement({
        'room_id': room.id, 'player_id': P1, 'position': {'x': 1, 'y': 0},
    })
    assert resp['status'] == 'success', resp
    assert room.players[P1].remaining_ships == 1

    # 换 P2 来打这一格
    room.current_attacker = P2
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6

    res = attack(room, 1, 0, attacker=P2)

    assert res['status'] == 'success', f'对方必须能打绝处逢生落点（{res}）'
    assert (1, 0) in attacked_cells(room, P2)


# ===========================================================================
# 溅射：盾挡下的目标格不应进 attacks（同普通攻击路径）
# ===========================================================================
def apply_splash(room, events):
    """用 apply_magic_effect 直接结算溅射，绕过出牌/选卡链路。"""
    return server.apply_magic_effect(room, P1, MagicCard('溅射'), {})


def make_splash_room(extra_last_attack=None):
    room = GameRoom('splash-shield-room')
    room.players[P1] = Player(name='p1',
                              ships=[PlayerShip(positions=[Position(3, 3)], hits=[])],
                              attacks=[], remaining_ships=1, sid='sid-p1')
    room.players[P2] = Player(name='p2',
                              ships=[PlayerShip(positions=[Position(3, 2)], hits=[])],
                              attacks=[], remaining_ships=1, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 5
    room.last_attack = {'attacker': P1, 'x': 3, 'y': 3, 'hit': True}
    if extra_last_attack:
        room.last_attack.update(extra_last_attack)
    room_manager.rooms[room.id] = room
    return room


def test_splash_shielded_cell_not_recorded_in_attacks(events):
    """★ 溅射路径：盾挡下的格子不能进 attacks（和普通攻击路径保持一致）。"""
    room = make_splash_room()
    try:
        ship = room.players[P2].ships[0]
        ship.shield = True  # 溅射方向 up=(3,2) 正好命中此船

        apply_splash(room, events)

        assert ship.shield is False, '盾应被消耗'
        assert ship.hits == [], '盾挡下后不应造成伤害'
        assert (3, 2) not in attacked_cells(room), \
            f'盾挡下的溅射格不该进 attacks，实际 {attacked_cells(room)}'
    finally:
        room_manager.rooms.pop(room.id, None)


def test_splash_shield_absorbed_event_is_broadcast(events):
    """溅射路径：盾挡下时也要广播 shield_absorbed 事件。"""
    room = make_splash_room()
    try:
        ship = room.players[P2].ships[0]
        ship.shield = True

        apply_splash(room, events)

        absorbed = [e for e in events if e[0] == 'shield_absorbed']
        assert absorbed, '溅射盾挡下必须广播 shield_absorbed'
    finally:
        room_manager.rooms.pop(room.id, None)


def test_splash_can_target_shielded_cell_again_after_turn(events):
    """溅射消耗盾后，同一回合后续可以用普通攻击打这格（位置未被锁死）。"""
    room = make_splash_room()
    try:
        ship = room.players[P2].ships[0]
        ship.shield = True

        apply_splash(room, events)
        # 盾已消耗但格子未被标记"已攻击" —— 校验直接看 attacks 列表
        assert (3, 2) not in attacked_cells(room)
        # 重置攻击次数让后续炮击能通过次数校验（测试目的是验证位置不被锁）
        room.attacks_remaining = 3
        res = attack(room, 3, 2, attacker=P1)
        assert res['status'] == 'success', f'(3,2) 不应被锁死（盾已消耗），但收到 {res}'
    finally:
        room_manager.rooms.pop(room.id, None)


# ===========================================================================
# 轰炸：护盾应该能挡下（卡面没说"强制击杀/无视盾"，和硫磺火焰区分开）
# ===========================================================================
def make_bomb_room():
    room = GameRoom('bomb-shield-room')
    room.players[P1] = Player(name='p1',
                              ships=[PlayerShip(positions=[Position(0, 2)], hits=[])],
                              attacks=[], remaining_ships=1, sid='sid-p1')
    room.players[P2] = Player(name='p2',
                              ships=[PlayerShip(positions=[Position(1, 2), Position(2, 2)], hits=[])],
                              attacks=[], remaining_ships=1, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 5
    room_manager.rooms[room.id] = room
    return room


def test_bomb_respects_shield(events):
    """★ 轰炸不能直接炸沉有盾的船（卡面没说无视盾，盾能挡一次）。"""
    room = make_bomb_room()
    try:
        ship = room.players[P2].ships[0]
        ship.shield = True

        result = server.apply_magic_effect(
            room, P1, MagicCard('轰炸'),
            {'target_line': {'type': 'row', 'index': 2}}
        )

        assert result.success is True
        # 盾被消耗但船存活
        assert ship.shield is False, '盾应被消耗'
        assert len(room.players[P2].ships) == 1, '有盾船不应被炸沉'
        assert room.players[P2].remaining_ships == 1
    finally:
        room_manager.rooms.pop(room.id, None)


def test_bomb_shielded_cells_not_recorded_in_attacks(events):
    """★ 轰炸+盾：被盾挡下的格子不应进 attacks（和普通攻击/溅射一致）。"""
    room = make_bomb_room()
    try:
        ship = room.players[P2].ships[0]
        ship.shield = True

        server.apply_magic_effect(
            room, P1, MagicCard('轰炸'),
            {'target_line': {'type': 'row', 'index': 2}}
        )

        # 盾挡下的格子不能被标记为"已攻击"
        attacks_set = {(a.x, a.y) for a in room.players[P1].attacks}
        shielded_positions = {(1, 2), (2, 2)}  # 这艘船在轰炸行上的格子
        assert attacks_set.isdisjoint(shielded_positions), \
            f'盾挡下的轰炸格不该进 attacks，有交集: {attacks_set & shielded_positions}'
    finally:
        room_manager.rooms.pop(room.id, None)


def test_bomb_shield_absorbed_event_is_broadcast(events):
    """轰炸盾挡下也要广播 shield_absorbed 事件。"""
    room = make_bomb_room()
    try:
        ship = room.players[P2].ships[0]
        ship.shield = True

        server.apply_magic_effect(
            room, P1, MagicCard('轰炸'),
            {'target_line': {'type': 'row', 'index': 2}}
        )

        absorbed = [e for e in events if e[0] == 'shield_absorbed']
        assert absorbed, '轰炸盾挡下必须广播 shield_absorbed'
    finally:
        room_manager.rooms.pop(room.id, None)


def test_bomb_sunk_ship_positions_are_still_recorded(events):
    """反证：没有盾的船被炸沉后，它的格子仍然要进 attacks。"""
    room = make_bomb_room()
    try:
        # 把 P2 的船改成无盾
        ship = room.players[P2].ships[0]
        ship.shield = False

        server.apply_magic_effect(
            room, P1, MagicCard('轰炸'),
            {'target_line': {'type': 'row', 'index': 2}}
        )

        assert len(room.players[P2].ships) == 0, '无盾船应被炸沉'
        attacks_set = {(a.x, a.y) for a in room.players[P1].attacks}
        assert {(1, 2), (2, 2)}.issubset(attacks_set), \
            f'被击沉船的格子必须进 attacks，缺少: {(1,2),(2,2)} - attacks={attacks_set}'
    finally:
        room_manager.rooms.pop(room.id, None)


def test_bomb_mixed_shielded_and_unshielded(events):
    """混合场景：轰炸行上有一艘有盾船和一艘无盾船。"""
    room = GameRoom('bomb-mixed-room')
    room.players[P1] = Player(name='p1',
                              ships=[PlayerShip(positions=[Position(0, 2)], hits=[])],
                              attacks=[], remaining_ships=1, sid='sid-p1')
    # P2 有两艘船：一艘有盾（格 1,2），一艘无盾（格 3,2），都在第 2 行
    s_shielded = PlayerShip(positions=[Position(1, 2)], hits=[])
    s_shielded.shield = True
    s_normal = PlayerShip(positions=[Position(3, 2)], hits=[])
    room.players[P2] = Player(name='p2',
                              ships=[s_shielded, s_normal],
                              attacks=[], remaining_ships=2, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 5
    room_manager.rooms[room.id] = room

    try:
        result = server.apply_magic_effect(
            room, P1, MagicCard('轰炸'),
            {'target_line': {'type': 'row', 'index': 2}}
        )

        # 有盾船存活但盾被消耗
        assert len(room.players[P2].ships) == 1, '有盾船应存活，无盾船应被炸沉'
        remaining_ship = room.players[P2].ships[0]
        assert remaining_ship.positions == [Position(1, 2)], '应该是有盾船存活'
        assert remaining_ship.shield is False, '盾应被消耗'
        assert room.players[P2].remaining_ships == 1

        # 记录里只有无盾船的格子，盾挡的不应出现
        attacks_set = {(a.x, a.y) for a in room.players[P1].attacks}
        assert (3, 2) in attacks_set, '无盾船被炸沉，格子应进 attacks'
        assert (1, 2) not in attacks_set, '盾挡的格子不该进 attacks'
    finally:
        room_manager.rooms.pop(room.id, None)
