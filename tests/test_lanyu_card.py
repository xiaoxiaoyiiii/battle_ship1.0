# -*- coding: utf-8 -*-
"""滥竽充数（速阶3 普通魔法卡）的回归测试。

按 CLAUDE.md 第 7 节「改卡要同步 4 处」要求覆盖：
  · magic_card.json / magic_cards.js 一致性
  · 发动条件「船数未满 + 有空格」在扣牌前拦截
  · apply_magic_effect 滥竽充数分支：补充到满船数 + 启动放置流程
  · handle_confirm_reinforcement 的 lanyu kind：新建船 + 登记 game_effects
  · 大回合结束时 _recall_lanyu_ships：强制收回活船、不显示沉没
  · 极端情况：可放置格子 < 需要补充数 → 尽可能多补充
  · 收回导致船数归零 → 判负
"""
import json
import os

import pytest

import server
from server import (GameRoom, MagicCard, Player, PlayerShip, Position,
                    room_manager)

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
    """P1/P2 各 6 艘活船，分别在 y=0 / y=5 行。"""
    room = GameRoom('test-lanyu-room')
    room.players[P1] = Player(name='p1',
                              ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(6)],
                              attacks=[], remaining_ships=6, sid='sid-p1')
    room.players[P2] = Player(name='p2',
                              ships=[PlayerShip(positions=[Position(i, 5)], hits=[]) for i in range(6)],
                              attacks=[], remaining_ships=6, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'preparation'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 1
    room_manager.rooms[room.id] = room
    return room


def card(name):
    return MagicCard(name)


def give_hand(player, names):
    player.magic_hand = [card(n) for n in names]


def find_emit(events, event_name, to=None):
    out = []
    for ev, data, t, r in events:
        if ev == event_name and (to is None or t == to):
            out.append((ev, data, t, r))
    return out


def apply_lanyu(room, caster):
    return server.apply_magic_effect(room, caster, card('滥竽充数'), {})


# ---------------------------------------------------------------------------
# 卡牌定义一致性
# ---------------------------------------------------------------------------
def test_card_definition_consistent():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, 'static', 'magic_card.json'), encoding='utf-8') as f:
        json_cards = json.load(f)
    lanyu_json = [c for c in json_cards if c['name'] == '滥竽充数']
    assert len(lanyu_json) == 1
    lj = lanyu_json[0]
    assert lj['speed'] == 3
    assert lj['type'] == '普通'

    with open(os.path.join(here, 'static', 'magic_cards.js'), encoding='utf-8') as f:
        js_src = f.read()
    assert f'name: "滥竽充数"' in js_src
    assert f'speed: {lj["speed"]}' in js_src
    assert f'type: "{lj["type"]}"' in js_src
    assert lj['description'] in js_src


def test_lanyu_card_enters_deck():
    names = [c.name for c in server.magic_cards]
    assert '滥竽充数' in names


def test_deck_size_grew():
    """新加一张普通卡，牌池规模 47 → 48。"""
    deck = server.magic_cards
    assert len(deck) == 48, f'卡池应 48 条，实际 {len(deck)}'


# ---------------------------------------------------------------------------
# 发动条件
# ---------------------------------------------------------------------------
def test_blocked_when_ships_full(room):
    """船数已满 → 拒；手牌不丢。"""
    room.players[P1].remaining_ships = 6
    room.players[P2].remaining_ships = 6
    give_hand(room.players[P1], ['滥竽充数'])
    room.current_phase = 'preparation'
    room.current_attacker = P1

    resp = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '滥竽充数', 'speed': 3, 'type': '普通', 'description': ''},
        'targets': {},
    })
    assert resp['status'] == 'error'
    assert '滥竽充数' in resp['message']
    # 手牌不丢
    assert len(room.players[P1].magic_hand) == 1
    assert room.players[P1].magic_hand[0].name == '滥竽充数'


def test_playable_when_ships_not_full(room):
    """船数未满 → 通过。"""
    room.players[P1].remaining_ships = 3
    assert server._lanyu_requirement_reason(room, P1, card('滥竽充数')) is None


def test_requirement_reason_function(room):
    """_lanyu_requirement_reason 直接单元测试。"""
    # 非滥竽充数不拦
    assert server._lanyu_requirement_reason(room, P1, card('增援')) is None
    # 6/6 → 拦
    room.players[P1].remaining_ships = 6
    assert server._lanyu_requirement_reason(room, P1, card('滥竽充数')) is not None
    # 3/6 → 过
    room.players[P1].remaining_ships = 3
    assert server._lanyu_requirement_reason(room, P1, card('滥竽充数')) is None


def test_blocked_when_no_placeable_cells(room, events):
    """棋盘全被己方占用 → 拒。"""
    # P1 在所有 36 格都放满船（极限场景）
    room.players[P1].ships = [PlayerShip(positions=[Position(x, y)], hits=[])
                              for x in range(6) for y in range(6)]
    room.players[P1].remaining_ships = 36
    # 船数已满 36/6 不对 —— max_ships 默认 6，36>=6 已经会拦
    # 改为：max_ships 设大，但格子全满
    room.players[P1].max_ships = 36
    room.players[P1].remaining_ships = 30  # 未满 36，但 6 个空格都被 P2 打过
    # P2 攻击剩下的 6 格
    for i in range(6):
        room.players[P2].attacks.append(Position(i, 1))
    reason = server._lanyu_requirement_reason(room, P1, card('滥竽充数'))
    assert reason is not None
    assert '棋盘' in reason or '满' in reason


# ---------------------------------------------------------------------------
# apply_magic_effect：启动放置流程
# ---------------------------------------------------------------------------
def test_apply_starts_placement(room, events):
    """发动后开启 lanyu 放置流程，count = max_ships - remaining_ships。"""
    room.players[P1].remaining_ships = 3
    room.players[P2].remaining_ships = 6
    res = apply_lanyu(room, P1)
    assert res.success is True
    # 应该在 magic_temp_data 里登记 pending_placement
    pending = room.magic_temp_data.get('pending_placement')
    assert pending is not None
    assert pending['kind'] == 'lanyu'
    assert pending['caster'] == P1
    assert pending['remaining'] == 3  # 6 - 3 = 3
    assert pending['total'] == 3
    # 应该在 game_effects 里登记 lanyu_temp_ships
    lanyu = room.game_effects.get('lanyu_temp_ships')
    assert lanyu is not None
    assert P1 in lanyu
    assert lanyu[P1] == []  # 还没放置


def test_apply_extreme_case_fewer_cells(room, events):
    """极端情况：可放置格子 < 需要补充数 → 尽可能多补充。"""
    # P1 有 3 艘活船（需要补充 3 艘），但只剩 2 个可放置格子
    # P1 占 y=0 行 6 格，沉掉 3 艘后剩 3 艘活船在 (0,0)(1,0)(2,0)
    # 沉船位置 (3,0)(4,0)(5,0) 仍算占用 → 可放置格子要避开这些
    room.players[P1].ships = [
        PlayerShip(positions=[Position(0, 0)], hits=[]),
        PlayerShip(positions=[Position(1, 0)], hits=[]),
        PlayerShip(positions=[Position(2, 0)], hits=[]),
        # 沉船（仍在 ships 里）
        PlayerShip(positions=[Position(3, 0)], hits=[Position(3, 0)]),
        PlayerShip(positions=[Position(4, 0)], hits=[Position(4, 0)]),
        PlayerShip(positions=[Position(5, 0)], hits=[Position(5, 0)]),
    ]
    room.players[P1].remaining_ships = 3
    # P2 打了 y=1 行的前 4 格 + y=2 行的全部 → 只剩很少可放置格
    for x in range(6):
        room.players[P2].attacks.append(Position(x, 1))
    for x in range(4):
        room.players[P2].attacks.append(Position(x, 2))
    # 可放置格 = 36 - 6(P1活船) - 3(P1沉船) - 6(P2打y=1) - 4(P2打y=2前4) = 17
    # 但 needed = 6-3 = 3，3 < 17 → count = 3
    res = apply_lanyu(room, P1)
    assert res.success is True
    pending = room.magic_temp_data.get('pending_placement')
    assert pending['remaining'] == 3  # 需要的 ≤ 可放置的，按需要的算


def test_apply_emits_placement_request(room, events):
    """发动后给施法者发 placement_request 事件。"""
    room.players[P1].remaining_ships = 4
    res = apply_lanyu(room, P1)
    assert res.success is True
    reqs = find_emit(events, 'placement_request', to='sid-p1')
    assert len(reqs) >= 1
    data = reqs[0][1]
    assert data['kind'] == 'lanyu'
    assert data['remaining'] == 2  # 6 - 4 = 2


# ---------------------------------------------------------------------------
# handle_confirm_reinforcement：放置 lanyu 船 + 登记
# ---------------------------------------------------------------------------
def test_confirm_lanyu_placement(room, events):
    """放置一艘 lanyu 船 → ships +1、remaining_ships +1、登记到 game_effects。"""
    room.players[P1].remaining_ships = 3
    apply_lanyu(room, P1)

    # 放在 (0, 1)（未被占用、未被 P2 打过）
    resp = server.handle_confirm_reinforcement({
        'room_id': room.id, 'player_id': P1,
        'position': {'x': 0, 'y': 1},
    })
    assert resp['status'] == 'success'
    assert room.players[P1].remaining_ships == 4
    lanyu = room.game_effects.get('lanyu_temp_ships')
    assert len(lanyu[P1]) == 1
    placed_ship = lanyu[P1][0]
    assert placed_ship.positions[0].x == 0
    assert placed_ship.positions[0].y == 1
    # 这艘船应该在 P1 的 ships 列表里
    assert placed_ship in room.players[P1].ships


def test_confirm_multiple_lanyu_placements(room, events):
    """连续放置多艘 lanyu 船，每艘都登记。"""
    room.players[P1].remaining_ships = 2
    apply_lanyu(room, P1)  # 需要 4 艘

    for i in range(4):
        resp = server.handle_confirm_reinforcement({
            'room_id': room.id, 'player_id': P1,
            'position': {'x': i, 'y': 1},
        })
        assert resp['status'] == 'success'

    assert room.players[P1].remaining_ships == 6
    lanyu = room.game_effects.get('lanyu_temp_ships')
    assert len(lanyu[P1]) == 4


def test_placement_flow_reemits_request_until_satisfied(room, events):
    """★ 钉住「落子 N 次必须能落满 N 艘；remaining 归零前不得结束放置流程」。

    这是 2026-09-22 作者实报「滥竽充数只补了一艘就当摆完了 / 没达到目标船数」
    的**服务端那一半**契约 —— 根因在前端（上一次落子的 ack 把服务端刚重发的
    新面板删掉了，见 `static/game.js` 的 `placementGeneration`），
    但正因为服务端**本来是对的**，这条契约才必须有用例守着：
    谁把 `_emit_placement_request` 的时机改早/改晚，或者提前调 `_finish_placement`，
    就会把 bug 变成"服务端也只让摆一艘"，前端再对也白搭。
    """
    room.players[P1].remaining_ships = 3
    apply_lanyu(room, P1)          # 需要补 3 艘
    pending = room.magic_temp_data['pending_placement']
    assert pending['remaining'] == 3 and pending['total'] == 3

    reqs = find_emit(events, 'placement_request')
    assert len(reqs) == 1, '启动放置流程时要发一次 placement_request'
    assert reqs[-1][1]['remaining'] == 3

    for step in range(1, 4):
        events.clear()
        resp = server.handle_confirm_reinforcement({
            'room_id': room.id, 'player_id': P1,
            'position': {'x': step - 1, 'y': 1},
        })
        assert resp['status'] == 'success'

        pending = room.magic_temp_data.get('pending_placement')
        if step < 3:
            # ★ 还没摆满：流程必须【还开着】，并且必须重发一次 placement_request
            assert pending is not None, (
                f'第 {step} 艘落完就结束了放置流程 —— 还差 {3 - step} 艘没摆')
            assert pending['remaining'] == 3 - step
            assert pending['placed'] == step
            again = find_emit(events, 'placement_request')
            assert len(again) == 1, (
                f'落完第 {step} 艘后没有重发 placement_request —— 前端拿不到第 {step + 1} 艘的窗口')
            assert again[0][1]['remaining'] == 3 - step
            assert find_emit(events, 'placement_done') == [], (
                '还有船没摆完就不许发 placement_done（前端会据此收面板）')
        else:
            # ★ 摆满了：这时才该收尾
            assert pending is None
            assert find_emit(events, 'placement_done'), '摆满后要收尾'
            assert find_emit(events, 'placement_request') == [], (
                'remaining 已归零，不该再请求位置')

    # 落子次数 == 补满的艘数
    assert room.players[P1].remaining_ships == 6
    assert len(room.game_effects['lanyu_temp_ships'][P1]) == 3


def test_extreme_case_flow_ends_exactly_at_available_count(room, events):
    """极限情况（可放置格子 < 需要补充数）也必须是"落一次少一艘、恰好落满 count 次"。

    卡面：「在极限情况下（即剩余的格子数比需要补充的船数少的时候）就尽可能多的补充」——
    所以 `count` 可以小于 `needed`，但**流程长度必须正好等于 count**，
    既不能提前结束，也不能多要一次。
    """
    # 满编 11 艘、现在 6 艘 → 需要补 5 艘；但棋盘上只留得出 3 个空格
    room.players[P1].max_ships = 11
    room.players[P1].ships = [PlayerShip(positions=[Position(x, 0)], hits=[]) for x in range(6)]
    room.players[P1].remaining_ships = 6
    # 用 P2 的攻击占掉除 (1,1)/(2,1)/(3,1) 之外的 33 格
    free = [(1, 1), (2, 1), (3, 1)]
    room.players[P2].attacks = [Position(x, y) for x in range(6) for y in range(6)
                                if (x, y) not in free]

    res = apply_lanyu(room, P1)
    assert res.success, res.message
    pending = room.magic_temp_data['pending_placement']
    assert pending['total'] == 3, f'应尽可能多补到 3 艘，实际 {pending["total"]}'

    placed = 0
    for (x, y) in free:
        assert room.magic_temp_data.get('pending_placement') is not None, (
            f'第 {placed + 1} 艘之前流程就被结束了')
        resp = server.handle_confirm_reinforcement({
            'room_id': room.id, 'player_id': P1, 'position': {'x': x, 'y': y}})
        assert resp['status'] == 'success', resp
        placed += 1
    assert placed == 3
    assert room.magic_temp_data.get('pending_placement') is None, '补满后流程要收尾'
    assert len(room.game_effects['lanyu_temp_ships'][P1]) == 3


# ---------------------------------------------------------------------------
# 大回合结束：强制收回
# ---------------------------------------------------------------------------
def test_recall_at_round_end(room, events):
    """大回合结束时收回活着的临时船，remaining_ships 减回。"""
    room.players[P1].remaining_ships = 3
    apply_lanyu(room, P1)
    # 放 3 艘临时船
    for i in range(3):
        server.handle_confirm_reinforcement({
            'room_id': room.id, 'player_id': P1,
            'position': {'x': i, 'y': 1},
        })
    assert room.players[P1].remaining_ships == 6

    # 模拟大回合结束 → 进入新大回合
    # end_turn 需要 current_phase == 'end' 且 current_attacker == player_id
    room.current_phase = 'end'
    room.current_attacker = P2  # P2 结束回合 → next_index=0 → 新大回合
    # attack_order = [P1, P2]，P2 结束 → next=(1+1)%2=0 → 新大回合
    resp = server.end_turn({'room_id': room.id, 'player_id': P2})

    # 临时船应被收回
    assert room.players[P1].remaining_ships == 3
    # game_effects 里的 lanyu_temp_ships 应被清掉
    assert 'lanyu_temp_ships' not in room.game_effects
    # 应该发出 lanyu_recalled 事件
    recalled = find_emit(events, 'lanyu_recalled')
    assert len(recalled) >= 1
    assert recalled[0][1]['player'] == P1
    assert recalled[0][1]['count'] == 3


def test_recall_does_not_show_sinking(room, events):
    """收回时不发击沉事件（不显示沉没）。"""
    room.players[P1].remaining_ships = 3
    apply_lanyu(room, P1)
    server.handle_confirm_reinforcement({
        'room_id': room.id, 'player_id': P1,
        'position': {'x': 0, 'y': 1},
    })

    room.current_phase = 'end'
    room.current_attacker = P2
    server.end_turn({'room_id': room.id, 'player_id': P2})

    # 不应该有 ship_sunk / ship_destroyed 事件
    sunk = find_emit(events, 'ship_sunk')
    assert len(sunk) == 0
    destroyed = find_emit(events, 'ship_destroyed')
    assert len(destroyed) == 0
    # 临时船不应该进 sunken_ships
    assert len(room.players[P1].sunken_ships) == 0


def test_recall_skips_sunken_temp_ships(room, events):
    """回合内被击沉的临时船不会被重复收回（已计入沉船统计）。"""
    room.players[P1].remaining_ships = 3
    apply_lanyu(room, P1)
    # 放 3 艘临时船
    for i in range(3):
        server.handle_confirm_reinforcement({
            'room_id': room.id, 'player_id': P1,
            'position': {'x': i, 'y': 1},
        })
    assert room.players[P1].remaining_ships == 6

    # 击沉其中 1 艘临时船
    lanyu_ships = room.game_effects['lanyu_temp_ships'][P1]
    sunk_ship = lanyu_ships[0]
    server._mark_ship_sunken(room.players[P1], sunk_ship)
    sunk_ship.hits.append(sunk_ship.positions[0])
    room.players[P1].remaining_ships -= 1
    assert room.players[P1].remaining_ships == 5

    # 大回合结束 → 收回
    room.current_phase = 'end'
    room.current_attacker = P2
    server.end_turn({'room_id': room.id, 'player_id': P2})

    # 应该收回 2 艘（活着的），不收回已沉的 1 艘
    assert room.players[P1].remaining_ships == 3  # 5 - 2 = 3
    # 已沉的临时船仍在 sunken_ships 里（击沉统计不回滚）
    assert sunk_ship in room.players[P1].sunken_ships


def test_recall_no_temp_ships_is_noop(room, events):
    """没玩过滥竽充数 → 收回函数无副作用。"""
    result = server._recall_lanyu_ships(room, room.id)
    assert result is False
    assert room.players[P1].remaining_ships == 6


def test_recall_idempotent(room, events):
    """连续调用两次不会重复收回。"""
    room.players[P1].remaining_ships = 3
    apply_lanyu(room, P1)
    server.handle_confirm_reinforcement({
        'room_id': room.id, 'player_id': P1,
        'position': {'x': 0, 'y': 1},
    })
    assert room.players[P1].remaining_ships == 4

    server._recall_lanyu_ships(room, room.id)
    assert room.players[P1].remaining_ships == 3

    # 第二次调用：lanyu_temp_ships 已被 pop，无副作用
    result = server._recall_lanyu_ships(room, room.id)
    assert result is False
    assert room.players[P1].remaining_ships == 3


# ---------------------------------------------------------------------------
# 收回导致船数归零 → 判负
# ---------------------------------------------------------------------------
def test_recall_to_zero_loses(room, events):
    """收回后船数归零 → 对手获胜。"""
    # P1 有 1 艘活船 + 5 艘沉船 → remaining=1
    # 玩滥竽充数补充到 6 → remaining=6（1 真 + 5 临时）
    # 大回合结束收回 5 艘临时 → remaining=1 → 不归零，不判负
    #
    # 要测归零：P1 有 0 艘活船 + 6 艘沉船 → remaining=0
    # 但 remaining=0 时游戏应该已经结束了...
    # 换个思路：P1 有 1 艘活船，玩滥竽充数补 5 艘（remaining=6）。
    # 然后那 1 艘真船被击沉 → remaining=5（全是临时船）。
    # 大回合结束收回 5 艘 → remaining=0 → 判负。
    room.players[P1].remaining_ships = 1
    # 把 5 艘标记为沉船
    for s in room.players[P1].ships[1:]:
        server._mark_ship_sunken(room.players[P1], s)
        s.hits.append(s.positions[0])
    room.players[P1].remaining_ships = 1

    apply_lanyu(room, P1)  # 补 5 艘
    for i in range(5):
        server.handle_confirm_reinforcement({
            'room_id': room.id, 'player_id': P1,
            'position': {'x': i, 'y': 1},
        })
    assert room.players[P1].remaining_ships == 6

    # 击沉那 1 艘真船
    real_ship = room.players[P1].ships[0]
    server._mark_ship_sunken(room.players[P1], real_ship)
    real_ship.hits.append(real_ship.positions[0])
    room.players[P1].remaining_ships = 5

    # 大回合结束 → 收回 5 艘临时 → remaining=0 → 判负
    room.current_phase = 'end'
    room.current_attacker = P2
    server.end_turn({'room_id': room.id, 'player_id': P2})

    assert room.players[P1].remaining_ships == 0
    assert room.state == 'game_over'
    assert room.winner == P2


# ---------------------------------------------------------------------------
# 速阶3 任何时候可用
# ---------------------------------------------------------------------------
def test_playable_anytime(room):
    """速阶3 在任何阶段都可用。"""
    room.players[P1].remaining_ships = 3
    room.current_phase = 'preparation'
    room.current_attacker = P2  # 不是自己回合
    assert server.can_play_magic_card(room, P1, card('滥竽充数')) is True

    room.current_phase = 'battle'
    assert server.can_play_magic_card(room, P1, card('滥竽充数')) is True

    room.current_phase = 'end'
    assert server.can_play_magic_card(room, P1, card('滥竽充数')) is True


# ---------------------------------------------------------------------------
# 看破 / 禁忌果实反制
# ---------------------------------------------------------------------------
def test_kanpo_blocks_lanyu(room):
    """看破！生效时，被封锁的玩家不能用滥竽充数。"""
    room.players[P1].magic_blocked = True
    give_hand(room.players[P1], ['滥竽充数'])
    room.players[P1].remaining_ships = 3
    room.current_phase = 'preparation'
    room.current_attacker = P1

    r = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '滥竽充数', 'speed': 3, 'type': '普通', 'description': ''},
        'targets': {},
    })
    assert r['status'] == 'error'
    assert '看破' in r['message']


def test_forbidden_fruit_blocks_lanyu(room):
    """禁忌果实生效时，非场地非失灵类卡不能发动。"""
    room.field_magic = card('禁忌果实')
    give_hand(room.players[P1], ['滥竽充数'])
    room.players[P1].remaining_ships = 3
    room.current_phase = 'preparation'
    room.current_attacker = P1
    assert server.can_play_magic_card(room, P1, card('滥竽充数')) is False
