# -*- coding: utf-8 -*-
"""Coverage 缺口第一回合填补（2026-09-14）。

本文件锁定 coverage 报告中缺失但业务价值高的函数 ——
这些函数要么是核心模块（神威扣洞、弃牌堆查询、结束游戏入口），
要么是边界校验逻辑（身份认证、去重、安全位置查找），
回归风险高且此前完全没有单测覆盖。

覆盖范围：
  · _shenwei_holes / _add_shenwei_hole / _clear_due_shenwei_holes
    / _discard_excluded_ships           —— 神威扣洞管理 + 棋盘重摆清理
  · find_safe_position                  —— 找安全位置（边界：全被打过时）
  · get_discard_pile                    —— 弃牌堆查询（身份校验 + 去重逻辑）
  · _finish_game                        —— 统一结算入口
  · switch_turn_after_end_phase          —— 回合切换（含冻结/补贴计算）
  · _do_demon_contract_sacrifice         —— 恶魔契约牺牲船（边界：无效输入）
"""
import pytest

import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'


# ============================================================
# Fixtures
# ============================================================
@pytest.fixture(autouse=True)
def events(monkeypatch):
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    monkeypatch.setattr(server.socketio, 'start_background_task',
                        lambda target, *a, **k: target(*a, **k))
    monkeypatch.setattr(server, '_schedule_chain_timeout', lambda *a, **k: None)
    monkeypatch.setattr(server, '_schedule_priority_timeout', lambda *a, **k: None)
    monkeypatch.setattr(server, '_has_request_context', lambda: False)
    # switch_turn_after_end_phase 里有 time.sleep(2) —— mock 掉
    monkeypatch.setattr(server.time, 'sleep', lambda *_a, **_k: None)
    return captured


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def make_room(n_p1=6, n_p2=6):
    room = GameRoom('test-room')
    room.players[P1] = Player(
        name='p1',
        ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(n_p1)],
        attacks=[], remaining_ships=n_p1, sid='sid-p1', user_id='u1')
    room.players[P2] = Player(
        name='p2',
        ships=[PlayerShip(positions=[Position(i, 5)], hits=[]) for i in range(n_p2)],
        attacks=[], remaining_ships=n_p2, sid='sid-p2', user_id='u2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'preparation'
    room.attack_order = [P1, P2]
    room.attacks_remaining = n_p1
    room.round = 3
    room_manager.rooms[room.id] = room
    return room


def ship_of(room, player_id, index=0):
    return room.players[player_id].ships[index]


# ============================================================
# 1. 神威扣洞系列
# ============================================================
class TestShenweiHoles:
    def test_shenwei_holes_default_empty(self, room):
        """首次访问 game_effects.shenwei_holes 应自动初始化为空列表。"""
        holes = server._shenwei_holes(room)
        assert holes == []
        assert room.game_effects['shenwei_holes'] is holes

    def test_add_shenwei_hole_records_area(self, room):
        """_add_shenwei_hole 应把区域参数原样记录。"""
        area = {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}
        server._add_shenwei_hole(room, P2, area, return_turn=5)
        holes = server._shenwei_holes(room)
        assert len(holes) == 1
        assert holes[0]['player'] == P2
        assert holes[0]['x1'] == 0 and holes[0]['x2'] == 2
        assert holes[0]['y1'] == 0 and holes[0]['y2'] == 2
        assert holes[0]['return_turn'] == 5

    def test_clear_due_shenwei_holes_removes_expired(self, room):
        """return_turn <= current_round 的扣洞应被清除，并返回被清除的列表。"""
        server._add_shenwei_hole(room, P1, {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}, return_turn=2)
        server._add_shenwei_hole(room, P2, {'x1': 3, 'y1': 3, 'x2': 5, 'y2': 5}, return_turn=10)
        room.round = 3

        cleared = server._clear_due_shenwei_holes(room, room.round)
        assert len(cleared) == 1
        assert cleared[0]['player'] == P1
        # 未到期的还在
        remaining = server._shenwei_holes(room)
        assert len(remaining) == 1
        assert remaining[0]['player'] == P2

    def test_clear_all_holes_when_all_due(self, room):
        """所有扣洞到期时，shenwei_holes 应被清空。"""
        server._add_shenwei_hole(room, P1, {'x1': 0, 'y1': 0, 'x2': 1, 'y2': 1}, return_turn=1)
        server._add_shenwei_hole(room, P2, {'x1': 3, 'y1': 3, 'x2': 5, 'y2': 5}, return_turn=2)
        server._clear_due_shenwei_holes(room, current_round=5)
        assert server._shenwei_holes(room) == []


# ============================================================
# 2. _discard_excluded_ships —— 棋盘重摆时清理除外列表
# ============================================================
class TestDiscardExcludedShips:
    def test_discard_no_entries_is_silent(self, room):
        """excluded_ships 不存在时，不应抛错、不应新增 key。"""
        server._discard_excluded_ships(room)
        assert 'excluded_ships' not in room.game_effects

    def test_discard_all_when_player_none(self, room):
        """player_id=None 时应清空所有除外条目（败者食尘等双方重摆场景）。"""
        room.game_effects['excluded_ships'] = [
            {'player': P1, 'ships': [ship_of(room, P1)]},
            {'player': P2, 'ships': [ship_of(room, P2)]},
        ]
        server._discard_excluded_ships(room, player_id=None)
        assert 'excluded_ships' not in room.game_effects

    def test_discard_one_player_preserves_other(self, room):
        """只清理某一方时，另一方条目应保留。"""
        room.game_effects['excluded_ships'] = [
            {'player': P1, 'ships': [ship_of(room, P1)]},
            {'player': P2, 'ships': [ship_of(room, P2)]},
        ]
        server._discard_excluded_ships(room, player_id=P1)
        remaining = room.game_effects['excluded_ships']
        assert len(remaining) == 1
        assert remaining[0]['player'] == P2

    def test_discard_last_player_removes_key(self, room):
        """只清理一方，且清理后列表为空时，应把 excluded_ships 键也移除。"""
        room.game_effects['excluded_ships'] = [
            {'player': P1, 'ships': [ship_of(room, P1)]},
        ]
        server._discard_excluded_ships(room, player_id=P1)
        assert 'excluded_ships' not in room.game_effects


# ============================================================
# 3. find_safe_position —— 找安全位置（边界：全被打过）
# ============================================================
class TestFindSafePosition:
    def test_returns_first_untouched(self, room):
        """正常情况应返回第一个未被对方攻击过的格子。"""
        room.players[P2].attacks = [Position(0, 0), Position(1, 0)]
        pos = server.find_safe_position(room, P1)
        assert pos is not None
        # P1 棋盘 (y=0), 被打过的是 (0,0),(1,0), 下一个是 (2,0)
        assert pos == {'x': 2, 'y': 0}

    def test_returns_none_when_everything_hit(self, room):
        """极端边界：6x6 全部格子都被对方打过 → 返回 None。"""
        room.players[P2].attacks = [Position(x, y) for x in range(6) for y in range(6)]
        pos = server.find_safe_position(room, P1)
        assert pos is None

    def test_skips_to_next_row(self, room):
        """某一行全被打过时，应跳到下一行找。"""
        room.players[P2].attacks = [Position(x, 0) for x in range(6)]
        pos = server.find_safe_position(room, P1)
        assert pos == {'x': 0, 'y': 1}


# ============================================================
# 4. get_discard_pile —— 弃牌堆查询
# ============================================================
class TestGetDiscardPile:
    def test_identity_rejected_for_outsider(self, room):
        """非房间玩家查询 → 返回 error。"""
        res = server.get_discard_pile({
            'room_id': room.id, 'player_id': 'stranger',
        })
        assert res['status'] == 'error'

    def test_missing_room_or_player_is_error(self, room):
        res = server.get_discard_pile({'room_id': 'no-such', 'player_id': P1})
        assert res['status'] == 'error'

    def test_deduplicates_normal_cards(self, room):
        """重复的非「失灵！」卡牌应去重，但各「失灵！」应保留多张。"""
        room.magic_discard = [
            MagicCard('冻结'), MagicCard('冻结'), MagicCard('冻结'),
            MagicCard('轰炸'), MagicCard('轰炸'),
            MagicCard('失灵！'), MagicCard('失灵！'), MagicCard('失灵！'),
            MagicCard('疗愈'),
        ]
        res = server.get_discard_pile({'room_id': room.id, 'player_id': P1})
        assert res['status'] == 'success'
        names = [c['name'] for c in res['discard_pile']]
        # 「失灵！」保留 3 张
        assert names.count('失灵！') == 3
        # 其它每张只出现一次
        assert names.count('冻结') == 1
        assert names.count('轰炸') == 1
        assert names.count('疗愈') == 1
        assert len(res['discard_pile']) == 3 + 3  # 3 张失灵 + 3 种非失灵

    def test_empty_discard_returns_empty_list(self, room):
        room.magic_discard = []
        res = server.get_discard_pile({'room_id': room.id, 'player_id': P1})
        assert res['status'] == 'success'
        assert res['discard_pile'] == []


# ============================================================
# 5. _finish_game —— 统一结算入口
# ============================================================
class TestFinishGame:
    def test_sets_game_over_state_and_winner(self, room, events):
        """调用后房间应进入 game_over 状态，记录胜利者与原因，并广播 game_over。"""
        server._finish_game(room, winner_id=P1, loser_id=P2, reason='sunk_all')

        assert room.state == 'game_over'
        assert room.winner == P1
        # 必须有 game_over 广播
        game_overs = [e for e, _d, _t, _r in events if e == 'game_over']
        assert len(game_overs) >= 1
        last = game_overs[-1]
        assert last is not None
        # 校验 payload
        game_over_event = next((d for e, d, _t, _r in events if e == 'game_over'), None)
        assert game_over_event is not None
        assert game_over_event['winner'] == P1
        assert game_over_event['reason'] == 'sunk_all'

    def test_log_result_entry_created(self, room):
        """_finish_game 应往 game_logs 追加一条 result 类型日志。"""
        server._finish_game(room, winner_id=P2, loser_id=P1, reason='disconnect')
        result_logs = [l for l in room.game_logs if l['type'] == 'result']
        assert len(result_logs) == 1
        assert result_logs[0]['detail']['winner'] == P2


# ============================================================
# 6. switch_turn_after_end_phase —— 回合切换
# ============================================================
class TestSwitchTurnAfterEndPhase:
    def test_switches_attacker_and_phase(self, room, events):
        """回合切换：当前攻击者变对手，阶段重置为 preparation。"""
        room.current_attacker = P1
        server.switch_turn_after_end_phase(room, opponent_id=P2)

        assert room.current_attacker == P2
        assert room.current_phase == 'preparation'
        assert room.players[P2].damage_dealt_this_turn == 0

        turn_changes = [d for e, d, _t, _r in events if e == 'turn_change']
        assert len(turn_changes) == 1
        assert turn_changes[0]['current_attacker'] == P2

    def test_attacks_reduced_by_frozen(self, room, events):
        """对方有被冻结的船 → attacks_remaining 应扣除冻结数。"""
        frozen_ship = ship_of(room, P2, 0)
        frozen_ship.frozen = True
        room.players[P2].remaining_ships = 6  # 6 艘，其中 1 艘冻结

        server.switch_turn_after_end_phase(room, opponent_id=P2)
        # 6 存活 - 1 冻结 = 5
        assert room.attacks_remaining == 5

    def test_attacks_never_negative(self, room, events):
        """全部船都冻结时，attacks_remaining 应为 0（不负数）。"""
        for s in room.players[P2].ships:
            s.frozen = True
        server.switch_turn_after_end_phase(room, opponent_id=P2)
        assert room.attacks_remaining == 0


# ============================================================
# 7. _do_demon_contract_sacrifice —— 恶魔契约牺牲船
# ============================================================
class TestDemonContractSacrifice:
    def test_ignores_ship_not_in_player(self, room):
        """传入一艘不属于该玩家的船 → 应静默返回，不能动对手的船。"""
        before_p1 = len(room.players[P1].ships)
        before_p2 = len(room.players[P2].ships)
        alien_ship = ship_of(room, P2, 0)  # P2 的船传给 P1 去"牺牲"
        server._do_demon_contract_sacrifice(room, P1, alien_ship)
        assert len(room.players[P1].ships) == before_p1
        assert len(room.players[P2].ships) == before_p2

    def test_ignores_none_ship(self, room):
        """ship=None → 静默返回。"""
        before = len(room.players[P1].ships)
        server._do_demon_contract_sacrifice(room, P1, None)
        assert len(room.players[P1].ships) == before

    def test_ignores_none_player(self, room):
        """player 为 None（room.players 没这个 key）→ 静默。"""
        before = len(room.players[P1].ships)
        server._do_demon_contract_sacrifice(room, 'ghost', ship_of(room, P1, 0))
        assert len(room.players[P1].ships) == before

    def test_reason_defaults_to_demon_contract(self, room, events):
        """不传 reason 时日志应为 '恶魔契约'。"""
        victim = ship_of(room, P1, 0)
        server._do_demon_contract_sacrifice(room, P1, victim)
        # 广播 ship_sacrificed
        sacrifices = [d for e, d, _t, _r in events if e == 'ship_sacrificed']
        assert len(sacrifices) == 1
        assert sacrifices[0]['reason'] == 'demon_contract'
        # 船数扣减
        assert room.players[P1].remaining_ships == 5

    def test_divine_decree_reason(self, room, events):
        """reason='divine_decree' 时日志应写 '神之宣告'。"""
        victim = ship_of(room, P1, 0)
        server._do_demon_contract_sacrifice(room, P1, victim, reason='divine_decree')
        sacrifices = [d for e, d, _t, _r in events if e == 'ship_sacrificed']
        assert len(sacrifices) == 1
        assert sacrifices[0]['reason'] == 'divine_decree'
