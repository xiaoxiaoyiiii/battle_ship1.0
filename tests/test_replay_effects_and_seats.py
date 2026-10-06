# -*- coding: utf-8 -*-
"""回放缺陷修复批（2026-09-23 晚）· **效果时间线 + `you_are` 座位口径**。

作者实报四条里的两条只有后端能钉住：

* **缺陷 ③**（看不到护盾格 / 神威洞 / 冻结区 / 绝处逢生候选格）—— 后端
  `replay.py` 根本没有这些字段，所以前端无从画起。本批加了一条
  `effects` 时间线，口径**照抄** `_build_spectate_snapshot` 的公开效果段
  （教训 #1：同一件事不许有两套字段名）。
* **缺陷 ④**（`（你）`标在了对手身上）—— `replay.you_are` 原来按
  "胜者 ⇒ p1、败者 ⇒ p2" 算代号，而 `p1` / `p2` 是**入座顺序**
  （与胜负毫无关系）。这是一个**方向写反**型 bug（教训 #7）：
  既有的 `test_participant_can_read_and_gets_you_are` 全绿，因为它的夹具里
  **恰好** `winner == p1`（对称局面测不出方向）。

⚠️ 每条都按"能红"写：把修复改回去，这些用例必须红。
"""
import json
import uuid

import pytest

import db as db_module
import replay
import server
from server import GameRoom, Player, PlayerShip, Position, room_manager

SID_A, SID_B = 'eff-sid-a', 'eff-sid-b'
EFFECT_FIELDS = ('shield', 'shenwei_holes', 'frozen_area',
                 'last_stand_cells', 'last_stand_owner')


def _ships(shape):
    return [PlayerShip(positions=[Position(x, y) for (x, y) in cells], hits=[])
            for cells in shape]


def _account():
    uid = db_module.create_user('effrep-%s' % uuid.uuid4().hex[:10], 'x' * 12)
    assert uid
    return uid


def _room(p1_uid=None, p2_uid=None):
    """匹配房形状的房间：key = sid，真人 uid 在 `Player.user_id` 上。"""
    room = GameRoom('effrep-' + uuid.uuid4().hex[:6])
    room.players[SID_A] = Player(name='甲', ships=_ships([((0, 0),), ((1, 0),)]),
                                 attacks=[], remaining_ships=2, sid=SID_A,
                                 user_id=p1_uid if p1_uid is not None else _account())
    room.players[SID_B] = Player(name='乙', ships=_ships([((0, 5),), ((1, 5),)]),
                                 attacks=[], remaining_ships=2, sid=SID_B,
                                 user_id=p2_uid if p2_uid is not None else _account())
    room.state = 'attacking'
    room.current_phase = 'battle'
    room.current_attacker = SID_A
    room.attack_order = [SID_A, SID_B]
    room.attacks_remaining = 2
    room.round = 3
    room.game_logs = []
    room.game_effects = {}
    room_manager.rooms[room.id] = room
    return room


@pytest.fixture
def room():
    r = _room()
    yield r
    room_manager.rooms.pop(r.id, None)


def _note(room, text='打了一炮'):
    """喂一步（走真实入口 `replay.note`，与 `add_game_log` 末尾那一次同形）。"""
    replay.note(room, {'type': 'attack', 'text': text,
                       'detail': {'attacker': SID_A, 'target': {'x': 0, 'y': 0},
                                  'hit': True, 'ship_sunk': False}})


def _effects(room):
    return replay.build(room)['effects']


# ===========================================================================
# 1. 形状契约：每个座位每条都带**全部**五个字段
# ===========================================================================
def test_effects_row_carries_every_field_on_the_changed_side(room):
    """★ 形状：`effects[i] = {step, p1|p2: {...}}`，那一侧带**全部**五个字段。

    字段名照抄 `_build_spectate_snapshot` 的公开效果段（教训 #1）。
    """
    room.players[SID_A].ships[0].shield = True
    _note(room)
    rows = _effects(room)
    assert len(rows) == 1, rows
    assert rows[0]['step'] == 0
    assert 'p1' in rows[0], '甲那一侧有变化 ⇒ 必须出现 p1：%s' % rows[0]
    assert sorted(rows[0]['p1'].keys()) == sorted(EFFECT_FIELDS), \
        '字段名必须与观战公开效果段逐个一致：%s' % sorted(rows[0]['p1'].keys())
    # ⚠️ 另一侧不许出现（增量语义：只带变了的座位）
    assert 'p2' not in rows[0], '没变化的那一侧不许出现：%s' % rows[0]






# ===========================================================================
# 2. 四项效果的来源与归属（逐个钉住"画在哪块棋盘上"）
# ===========================================================================
def test_shield_cells_come_from_the_ship_objects(room):
    """★★ 护盾的**真实来源是 `PlayerShip.shield`**（不是 `game_effects`）。

    实测（server.py 的'仁王之盾'与'卧薪尝胆'两个分支）：两张卡都是逐艘
    `ship.shield = True`。所以这里断言"从船对象取"，并且**一格不落地**取全
    （一艘船的每一格都算护盾格）。沉船 / 取消的盾必须跟着消失（它读的是当前状态）。
    """
    room.players[SID_A].ships[0].shield = True
    _note(room)
    got = _effects(room)
    assert got[-1]['p1']['shield'] == [[0, 0]], \
        '甲的第一艘船在 (0,0)，护盾坐标对必须是 [[0,0]]：%s' % got[-1]['p1']['shield']

    # 把盾挪到第二艘船 ⇒ 必须**跟着变**（不是"一旦有过就永远记着"）
    room.players[SID_A].ships[0].shield = False
    room.players[SID_A].ships[1].shield = True
    _note(room)
    rows = _effects(room)
    assert len(rows) == 2, rows
    assert rows[-1]['p1']['shield'] == [[1, 0]], rows[-1]['p1']['shield']
    assert rows[-1]['step'] == 1

    # 盾被挡掉之后清零 ⇒ 必须记成空表（前端据此把盾的画法撤掉）
    room.players[SID_A].ships[1].shield = False
    _note(room)
    rows = _effects(room)
    assert rows[-1]['p1']['shield'] == [], \
        '盾消失后必须记成空表（否则前端会把盾一直画着）：%s' % rows[-1]['p1']['shield']


def test_shenwei_holes_are_attributed_to_the_owner_board(room):
    """★★ 神威洞：只算**记在这位玩家身上**的那些，且 → 他那一侧的代号。

    `game_effects['shenwei_holes']` 是 `{'player': <原始 pid>, ...}`。
    ⚠️ 归属写反 = 洞画到对手棋盘上（与作者 2026-09-16 实报的绝处逢生那次同族）。
    """
    room.game_effects['shenwei_holes'] = [
        {'player': SID_B, 'x1': 2, 'y1': 4, 'x2': 4, 'y2': 5, 'return_turn': 9},
    ]
    _note(room)
    rows = _effects(room)
    assert rows[-1]['p2']['shenwei_holes'] == [{'x1': 2, 'y1': 4, 'x2': 4, 'y2': 5}], \
        '洞属于乙 ⇒ 必须落在 p2 那一侧：%s' % rows[-1]
    assert rows[-1].get('p1', {}).get('shenwei_holes', []) == [], \
        '甲那一侧不许有洞：%s' % rows[-1].get('p1')

    # 归属反过来 ⇒ 必须跟着翻到另一侧（反向腿：防止"永远记在 p2"）
    room.game_effects['shenwei_holes'] = [
        {'player': SID_A, 'x1': 0, 'y1': 0, 'x2': 1, 'y2': 1, 'return_turn': 9},
    ]
    _note(room)
    rows = _effects(room)
    assert rows[-1]['p1']['shenwei_holes'] == [{'x1': 0, 'y1': 0, 'x2': 1, 'y2': 1}], rows[-1]
    assert rows[-1]['p2']['shenwei_holes'] == [], \
        '甲那一侧的洞换了归属后，乙那一侧必须变成空表（不是沿用上一条）'


def test_frozen_area_is_only_recorded_on_the_victim_board(room):
    """★★ 冻结区：`owner` = 那片区域在**谁**的棋盘上（2026-09-16 的约定）。

    归错棋盘会让玩家看到"我这块被冻了"而其实是对面 —— 与实战屏同族的误导。
    """
    room.game_effects['frozen_area'] = {
        'x1': 3, 'y1': 0, 'x2': 5, 'y2': 2, 'owner': SID_B, 'caster': SID_A,
        'frozen': 2, 'until_round': 4,
    }
    _note(room)
    rows = _effects(room)
    frozen = rows[-1]['p2']['frozen_area']
    assert frozen and frozen['x1'] == 3 and frozen['y1'] == 0, \
        '冻结区必须落在受害者乙那一侧：%s' % rows[-1]
    assert 'p1' not in rows[-1], '甲那一侧没有变化 ⇒ 不许出现（增量语义）：%s' % rows[-1]
    # 只带**观战那一份**的字段（多带 `caster` / `until_round` 会让前端多一套口径）
    assert sorted(frozen.keys()) == ['frozen', 'owner', 'x1', 'x2', 'y1', 'y2'], sorted(frozen)




def test_effects_ownership_flips_with_the_caster(room):
    """★ 反向腿：`last_stand_owner` 换成乙 ⇒ 归属必须整条翻过去。"""
    room.game_effects['last_stand_cells'] = [(4, 4)]
    room.game_effects['last_stand_owner'] = SID_A
    _note(room)
    room.game_effects['last_stand_owner'] = SID_B
    _note(room)
    rows = _effects(room)
    assert rows[-1]['p2']['last_stand_cells'] == [[4, 4]] and \
        rows[-1]['p2']['last_stand_owner'] == 'p2', rows[-1]
    assert rows[-1]['p1']['last_stand_cells'] == [] and \
        rows[-1]['p1']['last_stand_owner'] is None, rows[-1]['p1']








def test_effects_never_leak_a_raw_pid(room):
    """★★ 效果行里**只许出现 `p1` / `p2` 代号**，绝不许出现原始 pid / user_id。

    原始 pid 在匹配房里就是入座 sid —— 直接下发等于把"谁是谁"送出去
    （契约 §6：response 里不许有 user_id）。
    """
    room.players[SID_B].ships[0].shield = True
    room.game_effects['shenwei_holes'] = [
        {'player': SID_B, 'x1': 0, 'y1': 5, 'x2': 2, 'y2': 5, 'return_turn': 9}]
    room.game_effects['frozen_area'] = {
        'x1': 1, 'y1': 1, 'x2': 3, 'y2': 3, 'owner': SID_B, 'caster': SID_A,
        'frozen': 1, 'until_round': 5}
    room.game_effects['last_stand_cells'] = [(0, 5)]
    room.game_effects['last_stand_owner'] = SID_B
    _note(room)
    dumped = json.dumps(_effects(room), ensure_ascii=False)
    for raw in (SID_A, SID_B):
        assert raw not in dumped, '效果行里带出了原始 pid（%s）：%s' % (raw, dumped)
    for uid in (room.players[SID_A].user_id, room.players[SID_B].user_id):
        assert uid and uid not in dumped, '效果行里带出了 user_id：%s' % dumped
    assert 'p2' in dumped




# ===========================================================================
# 3. `you_are`：代号口径 = **入座顺序**，不是胜负（缺陷 ④ 的后端根因）
# ===========================================================================
def _replay_blob(payload_seats, p1_name='甲', p2_name='乙'):
    return {'version': replay.REPLAY_VERSION,
            'p1_name': p1_name, 'p2_name': p2_name,
            'seats': payload_seats,
            'started_at': 0, 'steps': [], 'ships': [], 'hands': [], 'effects': [],
            'board_resets': [], 'nodes': [], 'truncated': None}


def test_you_are_uses_seats_not_winner_status():
    """★★★ 缺陷 ④ 的**根因**：代号必须按 `seats`（入座顺序）算。

    构造作者实报的那个场景：查看者**坐在 p2、并且他赢了**
    （截图里 `p1_name='AI'`、`p2_name='小小弈11'`，而登录的就是小小弈11）。
    旧口径"胜者 ⇒ p1"会返回 `'p1'` ⇒ 前端把 `（你）` 标到 **AI** 那一侧。
    """
    uid_win = 'u-小小弈11'
    uid_lose = 'u-aoi'
    row = {'winner_user_id': uid_win, 'loser_user_id': uid_lose}
    blob = _replay_blob({uid_lose: 'p1', uid_win: 'p2'}, p1_name='AI', p2_name='小小弈11')

    assert replay.you_are(blob, row, uid_win) == 'p2', \
        '赢的那位坐在 p2 ⇒ 必须返回 p2（旧口径会返回 p1，于是（你）标到 AI 上）'
    assert replay.you_are(blob, row, uid_lose) == 'p1', \
        '输的那位坐在 p1 ⇒ 必须返回 p1'

    # 反向腿：把胜负与座位**对调**（赢家坐在 p1），两边的答案必须跟着对调
    blob2 = _replay_blob({uid_win: 'p1', uid_lose: 'p2'})
    assert replay.you_are(blob2, row, uid_win) == 'p1'
    assert replay.you_are(blob2, row, uid_lose) == 'p2'


def test_you_are_returns_none_for_a_stranger_even_with_seats():
    """★★ 旁观者必须拿 `None`（不许被算成某一侧）。

    反向腿同在：同一份 `seats` 下，两个真参与者都必须拿到自己的代号 ——
    否则"拒掉"可能只是因为整个函数坏了（空转绿，教训 #12）。
    """
    row = {'winner_user_id': 'u-a', 'loser_user_id': 'u-b'}
    blob = _replay_blob({'u-a': 'p1', 'u-b': 'p2'})
    assert replay.you_are(blob, row, 'u-stranger') is None
    assert replay.you_are(blob, row, 'u-a') == 'p1'
    assert replay.you_are(blob, row, 'u-b') == 'p2'
