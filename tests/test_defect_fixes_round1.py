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














# ---------------------------------------------------------------------------
# 2. rps_choice 非法值
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# 3. 连锁窗口内不得继续攻击
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 4. 桃园结义：对方自选那张必须生效
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# 5. 已沉船不得被重复牺牲 / 重复入沉船堆
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# 6. 未开局房间回收
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# 7. 重连快照：对手打在我棋盘上的格
# ---------------------------------------------------------------------------

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
    # ⚠️ 待选战舰自 2026-09-20 起在**房间级优先队列**里（`server._request_ship_pick`），
    #    不再写 `magic_temp_data['pending_sacrifice']` —— 写旧键这条用例就失去意义了。
    server._request_ship_pick(room, P2, 'demon_contract', 'm')
    assert server.get_magic_temp_data({'room_id': room.id, 'player_id': P2})['status'] == 'success'
    assert server.get_magic_temp_data({'room_id': room.id, 'player_id': P1})['status'] == 'error'

# ---------------------------------------------------------------------------
# 9. 排行榜分页参数
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 10. 区域魔法造成的船数变化也能被平等条约无效化（并与普通攻击共用副作用）
#
# ★ 2026-09-24 改版更正：平等条约改成**连锁无效化**（目标 = 栈中正下方那一项），
#   原来那套"船数变化快照"整条删除。本节三条对着快照写的用例随之删除：
#     · test_area_kills_record_treaty_snapshot   —— 测的是"区域魔法必须写快照"，
#       快照已不存在；它真正想守的"区域魔法击沉能被平等条约无效化"改由
#       `tests/test_pingdeng_tiaoyue_chain.py::test_liuhuang_kills_alive_ship`
#       （真连锁：硫磺火焰被康掉、一艘都不沉）覆盖。
#     · test_treaty_rolls_back_area_kill         —— 测的是"回滚把船放回棋盘"，
#       回滚机制整个不存在；同上由那条连锁用例覆盖。
#     · test_ordinary_attack_still_records_treaty_snapshot —— 测的是"普通攻击
#       也要写快照"；普通攻击与区域魔法**共用 `_on_ship_destroyed`** 这件事，
#       现由 `tests/test_pingdeng_tiaoyue_chain.py` 的三条副作用用例
#       （百亿补贴 / 无瑕圣心 / 守株待兔）与本节的 `test_area_kill_interrupts_holy_heart`
#       共同覆盖。
#   下面这一条**与快照无关**（无瑕圣心中断），原样保留。
# ---------------------------------------------------------------------------
def _apply(room, pid, name, targets=None):
    return server.apply_magic_effect(room, pid, card(name), targets or {})


def test_area_kill_interrupts_holy_heart(room, events):
    """区域魔法击沉此前只把 no_damage 置 False，无暇圣心既没中断也没广播。"""
    room.game_effects['holy_heart'] = {'caster': P1, 'rounds_left': 2, 'no_damage': True}
    room.players[P2].ships = [ship((0, 0))]
    room.players[P2].remaining_ships = 1

    _apply(room, P1, '硫磺火焰', {'target_cells': [{'x': i, 'y': 0} for i in range(6)]})

    assert 'holy_heart' not in room.game_effects
    assert any(e[0] == 'holy_heart_interrupted' for e in events)



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
