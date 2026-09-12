# -*- coding: utf-8 -*-
"""2026-09-13 全量实测审计批：缺陷修复回归。

覆盖本轮修掉的问题：
  1. 对局已结束（game_over）后仍可布船/结束回合/出牌/投降 —— 门禁缺失
  2. rps_choice 非法出拳 —— handler 抛 KeyError 卡死 / 非法方直接获胜
  3. 连锁响应窗口开着时仍可继续攻击（与 end_turn 口径不一致）
  4. 桃园结义「对方再选一张」被忽略
  5. 已沉没的战舰仍留在 ships 列表 → 钢筋铁骨/神之宣告/绝处逢生 重复计数
  6. 建了但一直没人入座的房间永不回收
  7. 重连快照缺「对手打在我棋盘上的格」
"""
import time

import pytest

import server
from server import (ChainItem, GameRoom, MagicCard, Player, PlayerShip,
                    Position, room_manager)

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def events(monkeypatch):
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append((event, data, to, room))

    monkeypatch.setattr(server, 'emit', fake_emit)
    return captured


def ship(*cells):
    return PlayerShip(positions=[Position(x, y) for x, y in cells], hits=[])


def card(name):
    return MagicCard(name)


def make_room(ships1=6, ships2=6):
    r = GameRoom('defect-room')
    r.players[P1] = Player(name='p1', ships=[ship((i, 0)) for i in range(ships1)],
                           attacks=[], remaining_ships=ships1, sid='sid-p1', user_id='u1')
    r.players[P2] = Player(name='p2', ships=[ship((i, 1)) for i in range(ships2)],
                           attacks=[], remaining_ships=ships2, sid='sid-p2', user_id='u2')
    r.state = 'attacking'
    r.current_attacker = P1
    r.current_phase = 'battle'
    r.attack_order = [P1, P2]
    r.attacks_remaining = ships1
    r.round = 1
    room_manager.rooms[r.id] = r
    return r


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)
    room_manager.match_queue = []


def six_ships():
    return [{'positions': [{'x': i, 'y': i}], 'hits': []} for i in range(6)]


# ---------------------------------------------------------------------------
# 1. 终局门禁
# ---------------------------------------------------------------------------
def test_place_ships_rejected_after_game_over(room):
    """终局后重新布船曾把 game_over 倒回 rock_paper_scissors（对局复活）。"""
    room.state = 'game_over'
    room.winner = P1
    res = server.handle_place_ships({'room_id': room.id, 'player_id': P1, 'ships': six_ships()})
    assert res['status'] == 'error'
    assert room.state == 'game_over', '对局不得被布船复活'
    assert room.winner == P1


def test_end_turn_rejected_after_game_over(room):
    room.state = 'game_over'
    room.current_phase = 'end'
    res = server.end_turn({'room_id': room.id, 'player_id': P1})
    assert res['status'] == 'error'
    assert room.current_attacker == P1, '终局后不得再切换攻击方'


def test_enter_end_phase_rejected_after_game_over(room):
    room.state = 'game_over'
    room.attacks_remaining = 0
    res = server.handle_enter_end_phase({'room_id': room.id, 'player_id': P1})
    assert res['status'] == 'error'


def test_use_magic_card_rejected_after_game_over(room):
    room.state = 'game_over'
    room.players[P1].magic_hand = [card('无中生有')]
    res = server.handle_use_magic_card({
        'room_id': room.id, 'player_id': P1,
        'card': {'name': '无中生有', 'speed': 1, 'type': '普通'}, 'targets': {}})
    assert res['status'] == 'error'


def test_surrender_rejected_after_game_over(room):
    """胜者在结算界面再点一次投降，曾把已经记过账的胜负翻转。"""
    room.state = 'game_over'
    room.winner = P1
    res = server.handle_surrender({'room_id': room.id, 'player_id': P1})
    assert res['status'] == 'error'
    assert room.winner == P1, '终局后投降不得改写胜负'


def test_chain_response_rejected_after_game_over(room):
    room.state = 'game_over'
    res = server.chain_response({
        'room_id': room.id, 'player_id': P2, 'chain': False})
    assert res['status'] == 'error'


def test_gating_does_not_touch_normal_play(room):
    """门禁只针对 game_over：进行中的对局一切照旧。"""
    assert server.handle_place_ships(
        {'room_id': room.id, 'player_id': P1, 'ships': six_ships()})['status'] == 'success'
    assert room.state != 'game_over'


# ---------------------------------------------------------------------------
# 2. rps_choice 非法值
# ---------------------------------------------------------------------------
def test_rps_choice_rejects_invalid_value(room):
    room.state = 'rock_paper_scissors'
    room.rps_choices = {}
    room.rps_processed = False
    res = server.handle_rps_choice({'room_id': room.id, 'player_id': P1, 'choice': 'gun'})
    assert res['status'] == 'error'
    assert 'gun' not in room.rps_choices, '非法出拳不得写进 rps_choices'


def test_rps_choice_settlement_survives_invalid_second_choice(room):
    """此前 players[0] 合法 + players[1] 非法 → determine_rps_winner KeyError，
    结算 handler 抛异常、双方都拿不到 rps_result。"""
    room.state = 'rock_paper_scissors'
    room.rps_choices = {}
    room.rps_processed = False
    assert server.handle_rps_choice(
        {'room_id': room.id, 'player_id': P1, 'choice': 'rock'})['status'] == 'success'
    bad = server.handle_rps_choice(
        {'room_id': room.id, 'player_id': P2, 'choice': 'gun'})
    assert bad['status'] == 'error'
    # 补一个合法出拳后必须能正常结算（不再卡死）
    ok = server.handle_rps_choice(
        {'room_id': room.id, 'player_id': P2, 'choice': 'scissors'})
    assert ok['status'] == 'success'
    assert room.current_attacker == P1, 'rock 应胜 scissors，且非法值不得左右胜负'


def test_determine_rps_winner_no_keyerror_on_garbage():
    """即使有人绕过 handler 直接塞进非法值，也不能抛 KeyError。"""
    r = GameRoom('rps-room')
    r.players[P1] = Player(name='p1', ships=[], attacks=[], remaining_ships=0, sid='sid-p1')
    r.players[P2] = Player(name='p2', ships=[], attacks=[], remaining_ships=0, sid='sid-p2')
    r.rps_choices = {P1: 'gun', P2: 'rock'}
    result = server.determine_rps_winner(r)
    assert result.status in ('win', 'tie')


# ---------------------------------------------------------------------------
# 3. 连锁窗口内不得继续攻击
# ---------------------------------------------------------------------------
def test_attack_rejected_while_chain_window_open(room):
    room.chain = [ChainItem(P1, card('无中生有'), [], time.time())]
    res = server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 1})
    assert res['status'] == 'error'
    assert '连锁' in res['message']
    # 窗口关掉后恢复
    room.chain = []
    room.chain_waiting = False
    assert server.handle_attack(
        {'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 1})['status'] == 'success'


# ---------------------------------------------------------------------------
# 4. 桃园结义：对方自选那张必须生效
# ---------------------------------------------------------------------------
def test_taoyuan_honours_opponent_choice(room):
    cards = [card('溅射'), card('雷达子弹'), card('冻结')]
    room.magic_temp_data = {'cards': cards}
    res = server.confirm_magic_target({
        'room_id': room.id, 'player_id': P1,
        'temp_data_id': 'taoyuan_choice',
        'target_data': {'caster_choice': 0, 'opponent_choice': 2},
    })
    assert res['status'] == 'success'
    assert [c.name for c in room.players[P1].magic_hand] == ['溅射']
    assert [c.name for c in room.players[P2].magic_hand] == ['冻结'], \
        '对方自己挑的那张必须给他'
    assert '雷达子弹' in [c.name for c in room.magic_deck]


def test_taoyuan_falls_back_when_choice_missing(room):
    cards = [card('溅射'), card('雷达子弹'), card('冻结')]
    room.magic_temp_data = {'cards': cards}
    res = server.confirm_magic_target({
        'room_id': room.id, 'player_id': P1,
        'temp_data_id': 'taoyuan_choice',
        'target_data': {'caster_choice': 0},
    })
    assert res['status'] == 'success'
    assert len(room.players[P2].magic_hand) == 1


# ---------------------------------------------------------------------------
# 5. 已沉船不得被重复牺牲 / 重复入沉船堆
# ---------------------------------------------------------------------------
def test_steel_body_sacrifices_a_live_ship(room):
    """普通击沉不会把船移出 ships 列表，钢筋铁骨曾 pop 到已经沉掉的船
    （零代价发动 + 沉船堆重复条目）。"""
    alive_a, alive_b, sunk_c = ship((4, 4)), ship((3, 3)), ship((5, 5))
    room.players[P1].ships = [alive_a, alive_b, sunk_c]
    room.players[P1].remaining_ships = 2
    room.players[P1].sunken_ships = [sunk_c]   # c 已经沉了，但仍在 ships 列表里

    server.apply_magic_effect(room, P1, card('钢筋铁骨'), {})

    assert sunk_c in room.players[P1].ships, '已沉的船本来就不该被移除'
    assert room.players[P1].sunken_ships.count(sunk_c) == 1, '沉船堆不得出现重复条目'
    sacrificed = [sh for sh in (alive_a, alive_b) if sh in room.players[P1].sunken_ships]
    assert len(sacrificed) == 1, '应当牺牲一艘还活着的船'
    assert room.players[P1].remaining_ships == 1


def test_last_stand_does_not_duplicate_sunken_ships(room):
    a, b, c = ship((0, 0)), ship((1, 1)), ship((2, 2))
    room.players[P1].ships = [a, b, c]
    room.players[P1].remaining_ships = 3
    room.players[P1].sunken_ships = [b]        # b 已经沉了

    server.apply_magic_effect(room, P1, card('绝处逢生'), {})

    assert room.players[P1].sunken_ships.count(b) == 1, '已沉的船不得重复入堆'
    assert room.players[P1].remaining_ships == 0


def test_divine_decree_never_picks_sunken_ships(room):
    alive1, alive2, sunk = ship((0, 0)), ship((1, 1)), ship((2, 2))
    room.players[P1].ships = [alive1, alive2, sunk]
    room.players[P1].remaining_ships = 2
    room.players[P1].sunken_ships = [sunk]

    server.apply_magic_effect(room, P1, card('神之宣告'),
                              {'effect_choice': 2})   # 2 = 跳过对方回合，不需要对方再选

    assert sunk not in room.players[P1].sunken_ships[1:], '不得重复牺牲已沉船'
    assert room.players[P1].sunken_ships.count(sunk) == 1


# ---------------------------------------------------------------------------
# 6. 未开局房间回收
# ---------------------------------------------------------------------------
def test_reaper_removes_stale_waiting_rooms():
    r = GameRoom('waiting-room')
    r.players[P1] = Player(name='p1', ships=[], attacks=[], remaining_ships=0, sid='sid-p1')
    r.state = 'waiting'
    room_manager.rooms[r.id] = r
    try:
        # 首次（未超时）不回收
        assert r.id not in server._reap_ended_rooms(now=r.created_at + 1)
        # 超过 TTL 回收
        reaped = server._reap_ended_rooms(now=r.created_at + server._WAITING_ROOM_TTL + 1)
        assert r.id in reaped
        assert r.id not in room_manager.get_all_rooms()
    finally:
        room_manager.rooms.pop(r.id, None)


def test_reaper_keeps_fresh_waiting_rooms():
    r = GameRoom('fresh-room')
    r.state = 'waiting'
    room_manager.rooms[r.id] = r
    try:
        assert server._reap_ended_rooms(now=time.time()) == []
        assert r.id in room_manager.get_all_rooms()
    finally:
        room_manager.rooms.pop(r.id, None)


# ---------------------------------------------------------------------------
# 7. 重连快照：对手打在我棋盘上的格
# ---------------------------------------------------------------------------
def test_room_sync_includes_opponent_attacks(room):
    room.players[P2].attacks = [Position(x=0, y=0, hit=True), Position(x=3, y=2)]
    sync = server._build_room_sync(room, P1)
    assert 'opponent_attacks' in sync
    got = sorted((a['x'], a['y']) for a in sync['opponent_attacks'])
    assert got == [(0, 0), (3, 2)]
    # 自己打出去的仍然在 attacks 里，两者互不混淆
    assert sync['attacks'] == []

# ---------------------------------------------------------------------------
# 8. 临时选择数据只发给当事人
# ---------------------------------------------------------------------------
def test_temp_data_not_leaked_to_opponent(room):
    """桃园结义抽出的候选牌对对方不可见（卡面明写），此前任何房内玩家
    手动 emit 一次 get_magic_temp_data 就能读到全部候选。"""
    room.magic_temp_data = {'caster': P1, 'cards': [{'name': '冻结'}]}
    mine = server.get_magic_temp_data({'room_id': room.id, 'player_id': P1})
    assert mine['status'] == 'success'
    assert mine['data']['cards'][0]['name'] == '冻结'

    theirs = server.get_magic_temp_data({'room_id': room.id, 'player_id': P2})
    assert theirs['status'] == 'error'
    assert 'cards' not in theirs


def test_temp_data_respects_pending_owner(room):
    room.magic_temp_data = {'pending_sacrifice': {'player': P2, 'count': 1}}
    assert server.get_magic_temp_data({'room_id': room.id, 'player_id': P2})['status'] == 'success'
    assert server.get_magic_temp_data({'room_id': room.id, 'player_id': P1})['status'] == 'error'

# ---------------------------------------------------------------------------
# 9. 排行榜分页参数
# ---------------------------------------------------------------------------
def test_leaderboard_respects_limit(monkeypatch):
    """/api/leaderboard 此前硬编码 100，?limit= 被完全忽略。"""
    seen = {}

    def fake_get_leaderboard(limit=10):
        seen['limit'] = limit
        return []

    monkeypatch.setattr(server.db, 'get_leaderboard', fake_get_leaderboard)
    client = server.app.test_client()

    assert client.get('/api/leaderboard?limit=2').status_code == 200
    assert seen['limit'] == 2, '应把 limit 透传给数据层'

    client.get('/api/leaderboard?limit=abc')
    assert seen['limit'] == 100, '非法值回退默认'

    client.get('/api/leaderboard?limit=9999')
    assert seen['limit'] == 100, '上限钳制到 100'

    client.get('/api/leaderboard?limit=0')
    assert seen['limit'] == 1, '下限钳制到 1'

# ---------------------------------------------------------------------------
# 10. 区域魔法造成的船数变化也能被平等条约无效化（并与普通攻击共用副作用）
# ---------------------------------------------------------------------------
def _apply(room, pid, name, targets=None):
    return server.apply_magic_effect(room, pid, card(name), targets or {})


def test_area_kills_record_treaty_snapshot(room):
    """硫磺火焰/轰炸此前各自内联结算、不写 last_ship_change，
    导致平等条约报「没有可无效化的船数改变效果」。"""
    victim = ship((2, 0))
    room.players[P2].ships = [victim]
    room.players[P2].remaining_ships = 1
    cells = [{'x': i, 'y': 0} for i in range(6)]

    _apply(room, P1, '硫磺火焰', {'target_cells': cells})

    change = room.game_effects.get('last_ship_change')
    assert change, '区域魔法击沉也必须写平等条约快照'
    assert change['player'] == P2 and change['ship'] is victim
    assert change['round'] == room.round


def test_treaty_rolls_back_area_kill(room):
    victim = ship((2, 0))
    room.players[P2].ships = [victim]
    room.players[P2].remaining_ships = 1
    _apply(room, P1, '硫磺火焰', {'target_cells': [{'x': i, 'y': 0} for i in range(6)]})
    assert room.players[P2].remaining_ships == 0

    _apply(room, P2, '平等条约')

    assert room.players[P2].remaining_ships == 1, '平等条约应能回滚区域魔法造成的船数变化'
    assert victim in room.players[P2].ships, '被击沉的船要回到棋盘'
    assert victim not in room.players[P2].sunken_ships


def test_area_kill_interrupts_holy_heart(room, events):
    """区域魔法击沉此前只把 no_damage 置 False，无暇圣心既没中断也没广播。"""
    room.game_effects['holy_heart'] = {'caster': P1, 'rounds_left': 2, 'no_damage': True}
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1

    _apply(room, P1, '硫磺火焰', {'target_cells': [{'x': i, 'y': 0} for i in range(6)]})

    assert 'holy_heart' not in room.game_effects
    assert any(e[0] == 'holy_heart_interrupted' for e in events)


def test_ordinary_attack_still_records_treaty_snapshot(room):
    """普通攻击路径改为复用同一个 helper 后，行为必须保持不变。"""
    victim = ship((3, 3))
    room.players[P2].ships = [victim]
    room.players[P2].remaining_ships = 1
    room.current_phase = 'battle'
    room.attacks_remaining = 6

    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 3, 'y': 3})

    change = room.game_effects.get('last_ship_change')
    assert change and change['ship'] is victim and change['player'] == P2
    assert change['hits_added'], '普通攻击要记录命中的格，回滚时撤销该命中'

# ---------------------------------------------------------------------------
# 11. 冻结状态必须能传到玩家自己的棋盘上
# ---------------------------------------------------------------------------
def test_freeze_notifies_victim_with_frozen_flag(room, events):
    """冻结的船不提供攻击次数，此前棋盘上完全看不出哪几艘被冻住了。"""
    victim = ship((1, 1))
    room.players[P2].ships = [victim, ship((5, 5))]
    room.players[P2].remaining_ships = 2

    _apply(room, P1, '冻结', {'target_area': {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}})

    assert victim.frozen == room.round + 1
    updates = [e for e in events if e[0] == 'player_ships_updated']
    assert updates, '冻结后必须把状态推送给被冻结的一方'
    payload = updates[-1][1]['ships']
    assert any(sh['frozen'] for sh in payload), '被冻住的船要带上 frozen 标记'
    assert any(not sh['frozen'] for sh in payload), '没被冻住的船不能误标'


def test_freeze_outside_area_untouched(room, events):
    outside = ship((5, 5))
    room.players[P2].ships = [outside]
    room.players[P2].remaining_ships = 1

    _apply(room, P1, '冻结', {'target_area': {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}})

    assert not getattr(outside, 'frozen', None)
    updates = [e for e in events if e[0] == 'player_ships_updated']
    assert not updates or not any(sh['frozen'] for sh in updates[-1][1]['ships']), \
        '一艘都没冻住时不应把船标成冻结'


def test_room_sync_carries_frozen_flag(room):
    frozen_ship = ship((2, 2))
    frozen_ship.frozen = room.round + 1
    room.players[P1].ships = [frozen_ship, ship((3, 3))]

    sync = server._build_room_sync(room, P1)

    flags = [sh['frozen'] for sh in sync['ships']]
    assert flags == [True, False], '重连快照要带上冻结状态，否则重连后看不见'
