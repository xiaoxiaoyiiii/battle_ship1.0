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
