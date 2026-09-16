# -*- coding: utf-8 -*-
"""桃园取消卡死 / 冻结区域指示 / 疗愈透视 / 调试门禁 的回归测试（2026-09-16）。

作者一次提的四件事：

  ① 桃园结义自己取消选择后，对手直接卡死在等待界面
  ② 冻结在棋盘上没有任何"区域"指示（只有被冻者自己的船上有雪花）
  ③ 疗愈原地复活要显形给对手（防止对方忘记哪里原本有沉船）
  ④ F8 开发者调试面板（服务端门禁：开关 + 账号白名单）
"""
import pytest

import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

P1, P2 = 'p1', 'p2'


@pytest.fixture(autouse=True)
def events(monkeypatch):
    captured = []

    def fake_emit(event, data, to=None, room=None):
        captured.append({'event': event, 'data': data, 'to': to, 'room': room})

    monkeypatch.setattr(server, 'emit', fake_emit)
    monkeypatch.setattr(server.socketio, 'start_background_task', lambda target, *a, **k: None)
    monkeypatch.setattr(server, '_schedule_chain_timeout', lambda *a, **k: None)
    monkeypatch.setattr(server, '_schedule_shenji_declare_timeout', lambda *a, **k: None,
                        raising=False)
    yield captured
    captured.clear()


@pytest.fixture
def room():
    r = make_room()
    yield r
    room_manager.rooms.pop(r.id, None)


def make_room():
    room = GameRoom('cancel-freeze-heal')
    room.players[P1] = Player(
        name='p1', ships=[PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(6)],
        attacks=[], remaining_ships=6, sid='sid-p1')
    room.players[P2] = Player(
        name='p2', ships=[PlayerShip(positions=[Position(i, 5)], hits=[]) for i in range(6)],
        attacks=[], remaining_ships=6, sid='sid-p2')
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 1
    room_manager.rooms[room.id] = room
    return room


def card(name):
    return MagicCard(name)


def apply(room, caster, name, target=None):
    return server.apply_magic_effect(room, caster, card(name), target or {})


def pick(events, name):
    return [e for e in events if e['event'] == name]


# ===========================================================================
# ① 桃园取消必须通知对手（否则对手的全屏等待浮层永不消失）
# ===========================================================================
def test_taoyuan_cancel_notifies_opponent(room, events):
    """★ 取消桃园结义 → 对手必须收到 taoyuan_complete（前端靠它撤掉全屏浮层）。"""
    room.magic_deck = [card('轰炸'), card('疗愈')]
    room.players[P1].remaining_ships = 2
    apply(room, P1, '桃园结义')
    assert room.magic_temp_data.get('type') == 'taoyuan_choice'
    events.clear()

    res = server.handle_cancel_magic_selection({'room_id': room.id, 'player_id': P1})
    assert res['status'] == 'success', res

    done = pick(events, 'taoyuan_complete')
    assert done, f'取消后对手收不到任何事件，会永久卡在等待浮层：{events}'
    assert done[-1]['data'].get('cancelled') is True, done[-1]['data']
    assert done[-1]['to'] == 'sid-p2', '只发给对手（施法者自己另有一条提示）'
    assert room.magic_temp_data == {}


def test_taoyuan_cancel_returns_cards_to_deck(room, events):
    """取消后抽出来的牌要放回牌堆（沿用既有行为，别在改动里弄丢）。"""
    room.magic_deck = [card('轰炸'), card('疗愈')]
    room.players[P1].remaining_ships = 2
    apply(room, P1, '桃园结义')
    drawn = list(room.magic_temp_data.get('cards') or [])
    assert drawn

    server.handle_cancel_magic_selection({'room_id': room.id, 'player_id': P1})

    names = [c.name for c in room.magic_deck]
    for c in drawn:
        assert c.name in names, f'{c.name} 没有被放回牌堆'


def test_lingqi_cancel_notifies_opponent(room, events):
    """灵气复苏同样是"等对方选"，取消时也一并通知（虽然它只是 toast，不挡屏）。"""
    room.magic_temp_data = {'type': 'lingqi_choice', 'caster': P1}
    events.clear()

    server.handle_cancel_magic_selection({'room_id': room.id, 'player_id': P1})

    assert pick(events, 'lingqi_complete'), events


def test_other_choice_cancel_does_not_fake_taoyuan_event(room, events):
    """反证：明智埋葬等其它选择取消时不该发出桃园/灵气的事件（避免误报"对方取消了桃园"）。"""
    room.magic_temp_data = {'type': 'bury_choice', 'caster': P1}
    events.clear()

    server.handle_cancel_magic_selection({'room_id': room.id, 'player_id': P1})

    assert not pick(events, 'taoyuan_complete')
    assert not pick(events, 'lingqi_complete')


# ===========================================================================
# ② 冻结区域（区域属于受害者棋盘；双方都要看得到）
# ===========================================================================
def test_freeze_records_area_with_owner(room, events):
    room.players[P2].ships = [PlayerShip(positions=[Position(1, 1)], hits=[])]
    room.players[P2].remaining_ships = 1

    apply(room, P1, '冻结', {'target_area': {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}})

    fa = room.game_effects.get('frozen_area')
    assert fa, '没有记录冻结区域 → 前端无处可画'
    assert (fa['x1'], fa['y1'], fa['x2'], fa['y2']) == (0, 0, 2, 2), fa
    assert fa['owner'] == P2, '区域在被冻者的棋盘上，owner 必须是受害者'
    assert fa['caster'] == P1 and fa['frozen'] == 1, fa


def test_freeze_area_broadcast_to_room(room, events):
    """★ 必须发给双方：施法方原先什么都收不到，过一会儿就忘了冻的是哪片。"""
    room.players[P2].ships = [PlayerShip(positions=[Position(1, 1)], hits=[])]
    room.players[P2].remaining_ships = 1
    events.clear()

    apply(room, P1, '冻结', {'target_area': {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}})

    sent = pick(events, 'frozen_area')
    assert sent, f'没有广播冻结区域：{events}'
    assert sent[-1]['room'] == room.id, '要发给整个房间，不能只发受害者'
    assert sent[-1]['data']['owner'] == P2


def test_freeze_area_in_room_sync(room):
    room.players[P2].ships = [PlayerShip(positions=[Position(1, 1)], hits=[])]
    room.players[P2].remaining_ships = 1
    apply(room, P1, '冻结', {'target_area': {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}})

    sync = server._build_room_sync(room, P2)
    assert sync.get('frozen_area'), '重连快照没带冻结区域 → 重连后又忘了冻的是哪片'


def test_board_reset_clears_frozen_area(room):
    room.players[P2].ships = [PlayerShip(positions=[Position(1, 1)], hits=[])]
    room.players[P2].remaining_ships = 1
    apply(room, P1, '冻结', {'target_area': {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}})

    room.game_effects['frozen_area']['until_round'] = 0    # 假装已过期
    room.current_attacker = P2
    room.current_phase = 'end'
    room.round = 5
    server.end_turn({'room_id': room.id, 'player_id': P2})

    assert 'frozen_area' not in room.game_effects, '解冻后区域记录残留 → 棋盘一直挂着斜纹'


# ===========================================================================
# ③ 疗愈原地复活 → 显形给对手（带 kind，前端据此做专属标记与悬停说明）
# ===========================================================================
def test_heal_reveals_revived_cell_to_opponent(room, events):
    """★ 疗愈后对手要能看见"船又回到这一格"，且带 kind='heal' 以便区分雷达显形。

    ⚠️ 构造沉船必须把 hits 填成与 positions 相同 —— 否则 _revive_sunken_ships 的
    "幽灵记录"守卫（船在 ships 里且 _is_ship_alive 为真）会 continue 跳过，
    船根本没复活，测试会以"没有显形"的形式假红。
    """
    sunk = PlayerShip(positions=[Position(2, 2)], hits=list([Position(2, 2)]))
    room.players[P1].ships = [sunk]
    room.players[P1].sunken_ships = [sunk]
    room.players[P1].remaining_ships = 0
    events.clear()

    res = apply(room, P1, '疗愈')
    assert res.success is True, res.message
    assert room.players[P1].remaining_ships == 1, '前置条件不成立：船没有真的复活'

    revealed = pick(events, 'revealed_positions')
    assert revealed, f'疗愈没有向对手显形：{events}'
    last = revealed[-1]
    assert last['to'] == 'sid-p2', '要发给对手'
    assert last['data'].get('kind') == 'heal', last['data']
    assert {'x': 2, 'y': 2} in last['data']['positions'], last['data']
    assert any(p.x == 2 and p.y == 2 for p in room.players[P2].revealed_positions), \
        '对手的持久显形记录里也该有这一格（重连后仍要看得到）'


def test_new_position_cards_do_not_reveal(room, events):
    """反证：死者苏生/增援放的是玩家自选的新位置，绝不能显形给对手（会泄露新船位）。"""
    room.magic_deck = [card('冻结')]
    room.players[P1].ships = [PlayerShip(positions=[Position(i, 0)], hits=[]) for i in range(5)]
    room.players[P1].remaining_ships = 5
    apply(room, P1, '增援')
    events.clear()

    server.handle_confirm_reinforcement(
        {'room_id': room.id, 'player_id': P1, 'position': {'x': 3, 'y': 3}})

    for e in pick(events, 'revealed_positions'):
        assert e['to'] != 'sid-p2', f'自选新位置不该显形给对手：{e}'


# ===========================================================================
# ④ 调试面板门禁（开关 + 账号白名单）
# ===========================================================================
def test_debug_status_reflects_switch(monkeypatch):
    monkeypatch.setattr(server, 'ENABLE_TEST_EVENTS', False)
    assert server.handle_debug_status({}) == {'enabled': False, 'allowed': False, 'allowlist': False}

    monkeypatch.setattr(server, 'ENABLE_TEST_EVENTS', True)
    monkeypatch.setattr(server, 'DEBUG_ADMIN_USER_IDS', set())
    assert server.handle_debug_status({})['allowed'] is True, '没配白名单时沿用旧行为'


def test_debug_allowlist_blocks_others(monkeypatch, room):
    """★ 配了白名单之后：白名单内的账号放行，其余（含无身份的调用）一律拒绝。"""
    monkeypatch.setattr(server, 'ENABLE_TEST_EVENTS', True)
    monkeypatch.setattr(server, 'DEBUG_ADMIN_USER_IDS', {'owner-uid'})

    monkeypatch.setattr(server, 'session', {'user_id': 'owner-uid'})
    assert server.handle_debug_status({})['allowed'] is True
    assert server.test_add_all_magic_cards({'room_id': room.id, 'player_id': P1})['status'] == 'success'

    monkeypatch.setattr(server, 'session', {'user_id': 'someone-else'})
    assert server.handle_debug_status({})['allowed'] is False
    res = server.test_add_all_magic_cards({'room_id': room.id, 'player_id': P1})
    assert res['status'] == 'error' and '未对你的账号开放' in res['message'], res


def test_debug_switch_off_refuses_everything(monkeypatch, room):
    monkeypatch.setattr(server, 'ENABLE_TEST_EVENTS', False)
    monkeypatch.setattr(server, 'DEBUG_ADMIN_USER_IDS', set())
    res = server.test_win_game({'room_id': room.id, 'player_id': P1})
    assert res['status'] == 'error' and '未启用' in res['message'], res
    assert not room.winner, '开关关着时绝不能真的判胜'   # winner 初值是 ''
