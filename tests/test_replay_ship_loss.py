# -*- coding: utf-8 -*-
"""回放缺陷批（2026-09-23 深夜）· **主动牺牲的船必须在回放里变成沉没格**。

作者实报：
> 主动牺牲的船会在回放的棋盘中直接消失掉 而不是变成红色叉叉

## 根因

回放的船位时间线（`replay._ship_cells`）**只遍历 `player.ships`**，而"牺牲一艘船"的
唯一实现点 `server._do_demon_contract_sacrifice` 第一件事就是 `player.ships.remove(ship)`
（`demon_contract` / `divine_decree` / `dice_sacrifice` / `trap_sacrifice` 四种 reason
全部汇到这里）。船被摘掉之后快照里那一格**没了** ⇒ 回放棋盘上那格凭空消失。

而**数据本来就有**：同一条 `add_game_log` 的 `detail.positions` 里带着这艘船的坐标，
`emit('ship_sacrificed', ...)` 也是公开广播给双方的（代码注释原文：
「公开广播：自己与对手都能看到这艘船被划掉」）。

## 修法（本文件钉住的口径）

在牺牲那个**唯一实现点**上把"这几格沉了"记成一个**显式事实**
（`replay.note_ship_lost(room, player_id, positions)`），记录器把这批格子以
**`alive: False` + `sunk: True`** 的形态**留在**船位时间线里；
船真的回到棋盘时由 `replay.note_ship_returned` 撤掉，棋盘整块换新时由
`replay.note_board_replaced` 撤掉。

⚠️ **四条腿必须同时钉住**（这是本条最容易修坏的地方 —— 同一格"不再有船"至少有四种成因，
   只有"主动牺牲"该画成沉没）：

| 腿 | 成因 | 回放里必须 |
| --- | --- | --- |
| ★ 牺牲 | 恶魔契约 / 神之宣告 / 命运骰子 6 点 / 守株待兔 | **留在时间线里且 `sunk`**（要修的） |
| 滥竽充数 | 临时船回合末被强制收回（卡面明写"不会显示沉没"） | **不在时间线里**（不许变成沉没） |
| 换位 | 增援 / 神机妙算 / 回光返照 / 灵气复苏 / 死者苏生 | 旧格**不许**留假红叉 |
| 复活 | 疗愈 / 复活 | 红叉**必须消失**、船重新画出来 |

⚠️ 本文件**没有**去"diff 前后快照、猜哪几格消失了" —— 那是从表象反推，
   会把滥竽充数一起误判成沉没（因果来源必须单一：牺牲点手上的 `positions`）。
"""
import uuid

import pytest

import db as db_module
import replay
import server
from server import GameRoom, Player, PlayerShip, Position, room_manager

SID_A, SID_B = 'loss-sid-a', 'loss-sid-b'
P1, P2 = 'p1', 'p2'


def _ships(shape):
    return [PlayerShip(positions=[Position(x, y) for (x, y) in cells], hits=[])
            for cells in shape]


def _account():
    uid = db_module.create_user('lossrep-%s' % uuid.uuid4().hex[:10], 'x' * 12)
    assert uid
    return uid


def _room(p1_ships=None, p2_ships=None):
    """人机房形状的房间：key = sid，真人 uid 在 `Player.user_id` 上。"""
    room = GameRoom('lossrep-' + uuid.uuid4().hex[:6])
    room.players[SID_A] = Player(
        name='甲', ships=_ships(p1_ships or [((2, 2),), ((3, 3),)]),
        attacks=[], remaining_ships=2, sid=SID_A, user_id=_account())
    room.players[SID_B] = Player(
        name='乙', ships=_ships(p2_ships or [((0, 0),), ((5, 5),)]),
        attacks=[], remaining_ships=2, sid=SID_B, user_id=None)
    room.state = 'attacking'
    room.current_phase = 'battle'
    room.current_attacker = SID_A
    room.attack_order = [SID_A, SID_B]
    room.attacks_remaining = 2
    room.round = 3
    room.game_logs = []
    room.game_effects = {}
    room.magic_temp_data = {}
    room_manager.rooms[room.id] = room
    return room


@pytest.fixture
def room():
    r = _room()
    yield r
    room_manager.rooms.pop(r.id, None)


def _ships_rows(room):
    return replay.build(room)['ships']


def _fold_ships(rows):
    """前端 `replayFoldTimeline` 的同一套叠加口径：按 step 升序把两侧叠上去。

    ⚠️ 时间线是**增量**（每条只带变了的座位），所以不能只取最后一条。
    """
    out = {P1: [], P2: []}
    for row in rows:
        for side in (P1, P2):
            if isinstance(row.get(side), list):
                out[side] = row[side]
    return out


def _cells_of(room, side):
    """这一侧**最后一帧**的船格（前端 `frame.ships[side]` 的那一份）。"""
    return _fold_ships(_ships_rows(room))[side]


def _cell_at(cells, x, y):
    for c in cells:
        if c.get('x') == x and c.get('y') == y:
            return c
    return None


def _note_attack(room, x, y, sunk=False):
    replay.note(room, {'type': 'attack', 'text': '打了一炮',
                       'detail': {'attacker': SID_A, 'target': {'x': x, 'y': y},
                                  'hit': True, 'ship_sunk': sunk}})


# ===========================================================================
# 1. ★★ 牺牲腿：真调用 `_do_demon_contract_sacrifice`，那几格必须**在**且是**沉没**
# ===========================================================================
@pytest.mark.parametrize('reason', ['demon_contract', 'divine_decree',
                                    'dice_sacrifice', 'trap_sacrifice'])
def test_sacrificed_ship_cells_stay_in_the_timeline_as_sunk(room, reason):
    """★★ 本批的验收核心：四种 reason 的牺牲都必须留下**沉没**格。

    改前：`_do_demon_contract_sacrifice` 把船从 `player.ships` 摘掉 ⇒ 快照里那格**消失**
    ⇒ 这条断言「格子在时间线里」直接红（`assert None is not None`）。
    """
    victim = room.players[SID_A].ships[0]
    x, y = victim.positions[0].x, victim.positions[0].y

    server._do_demon_contract_sacrifice(room, SID_A, victim, reason)

    assert victim not in room.players[SID_A].ships, '前提：船确实被摘掉了'
    assert victim in room.players[SID_A].sunken_ships, '前提：船确实登记进沉船堆'

    cells = _cells_of(room, P1)
    cell = _cell_at(cells, x, y)
    assert cell is not None, (
        '牺牲的船格 (%d,%d) 不在回放的船位时间线里 ⇒ 回放棋盘上会凭空消失：%s' % (x, y, cells))
    assert cell.get('sunk') is True, '牺牲格必须是沉没：%s' % cell
    assert cell.get('alive') is False, '牺牲格的 alive 必须是 False（前端判据）：%s' % cell

    # 没被牺牲的那艘船照旧活着（不许被误标成沉没）
    other = _cell_at(cells, 3, 3)
    assert other is not None and other.get('alive') is True, other


def test_sacrifice_row_is_recorded_exactly_once_and_sparsely(room):
    """★ 稀疏：牺牲只记**一条**涉及该座位的船位行；后续无变化的步不再记。

    线上只有 777 MB 可用（契约 §1），牺牲格不许变成"每步一份全量快照"。
    """
    _note_attack(room, 0, 3)                     # 与船位无关的一步
    rows_before = len(_ships_rows(room))
    server._do_demon_contract_sacrifice(room, SID_A, room.players[SID_A].ships[0],
                                        'demon_contract')
    rows_after = len(_ships_rows(room))
    assert rows_after == rows_before + 1, (
        '牺牲应该只新增一条船位行（%d → %d）：%s' % (rows_before, rows_after, _ships_rows(room)))

    for i in range(5):
        _note_attack(room, i, 4)
    assert len(_ships_rows(room)) == rows_after, \
        '没有船位变化却记了新行（每步全量快照）：%s' % _ships_rows(room)


def test_sacrificed_cell_is_marked_sunk_not_just_alive_false(room):
    """★ 口径：`sunk` 与 `alive` **两个字段都要有**，且方向一致。

    `alive: False` 但没有 `sunk` ⇒ 前端 `replayCellOf` 的
    `!!(shipCell && shipCell.sunk && shipCell.alive !== true)` 为假 ⇒ **不画红叉**，
    只是把这一格从"有船"变成"空"（还是消失）。反过来 `sunk: True` + `alive: True`
    也会被前端判成不沉。所以两个字段必须同时正确。
    """
    victim = room.players[SID_A].ships[1]
    x, y = victim.positions[0].x, victim.positions[0].y
    server._do_demon_contract_sacrifice(room, SID_A, victim, 'demon_contract')
    cell = _cell_at(_cells_of(room, P1), x, y)
    assert cell is not None, '牺牲格不在时间线里'
    # ⚠️ `src` 是 2026-09-24 收口批加的探针字段（这一格来自活船列表还是显式沉没登记），
    #    见 `replay._ship_cells` 的 ★★ 段与 `tests/test_replay_lost_priority.py`。
    assert set(cell.keys()) == {'x', 'y', 'alive', 'sunk', 'src'}, \
        '船格字段就这五个（前端判据只读 alive / sunk；src 是给守卫看的）：%s' % cell
    assert cell.get('src') == 'lost', \
        '牺牲格必须来自**显式沉没登记**（不是从"船不在 ships 里"推出来的）：%s' % cell


# ===========================================================================
# 2. ★★ 滥竽充数反向腿：临时船被收回后**不许**变成沉没
# ===========================================================================
def test_temporary_lanyu_ship_never_leaves_a_sunk_cell(room):
    """★★ 最重要的一条反向腿：日志里明写"临时船收回**不会显示沉没**"。

    判据写成"凡是曾在该格出现过船就永远留成沉没"的**朴素修法**会让这条**红**：
    临时船被收回之后那几格会留在时间线里、还带着 `sunk: True` ⇒ 回放里凭空多出沉船。
    """
    player = room.players[SID_A]
    temp = PlayerShip(positions=[Position(x=1, y=1)], hits=[])
    player.ships.append(temp)
    player.remaining_ships += 1
    replay.note(room, {'type': 'system', 'text': '滥竽充数：临时战舰登场'})

    assert _cell_at(_cells_of(room, P1), 1, 1) is not None, '登场那一刻必须在时间线里'

    # 大回合结束：临时船被强制收回（server `_recall_lanyu_ships` 就是 ships.remove）
    player.ships.remove(temp)
    player.remaining_ships -= 1
    replay.note(room, {'type': 'system', 'text': '滥竽充数：临时战舰已收回'})

    cells = _cells_of(room, P1)
    cell = _cell_at(cells, 1, 1)
    assert cell is None or cell.get('sunk') is not True, (
        '临时船收回**不是沉没**（卡面/代码注释明写"不会显示沉没"），'
        '却在那格留下了沉没标记 ⇒ 回放里出现幻影沉船：%s' % cell)


def test_lanyu_recall_code_path_is_not_a_sacrifice(room):
    """★★ 源码级钉住：滥竽充数的收回**不许**走 `note_ship_lost`。

    这条防的是"把登记写进共用的移除函数里"那种改法 —— 那样临时船、
    除外船、换位船全都会变成沉船。回收点只认 `ships.remove`，不认沉没。
    """
    import ast
    import io
    import pathlib
    src = io.open(pathlib.Path(server.__file__), encoding='utf-8').read()
    tree = ast.parse(src)
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, 'id', None)
        if name not in ('note_ship_lost',):
            continue
        if not (isinstance(fn, ast.Attribute)
                and getattr(fn.value, 'id', None) == 'replay'):
            continue
        cur = parent.get(node)
        while cur is not None and not isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cur = parent.get(cur)
        hits.append(cur.name if cur is not None else '<module>')
    assert sorted(hits) == ['_do_demon_contract_sacrifice',
                            'apply_magic_effect', 'apply_magic_effect',
                            'apply_magic_effect'], (
        '「记成沉没」只允许出现在**主动牺牲 / 自牺牲**的实现点（唯一实现点 1 处 + '
        '`apply_magic_effect` 里 绝处逢生 / 钢筋铁骨 / `神威！`致死 三处），'
        '别的地方（临时船收回 / 神威**除外** / 换位重摆）一律不许：%s' % sorted(hits))
    assert hits.count('apply_magic_effect') == 3, \
        '`apply_magic_effect` 里应当**恰好三处**（绝处逢生 / 钢筋铁骨 / 神威致死）：%s' % hits


# ===========================================================================
# 3. ★ 换位反向腿：船换位置之后旧格**不许**留假红叉
# ===========================================================================
def test_redeployed_ship_leaves_no_fake_wreck_at_the_old_cell(room):
    """★ 换位（神机妙算）：船换位置之后旧格是"空"，不是"沉"。

    真的先牺牲一艘（于是 (2,2) 登记成沉没），再走**真实入口**
    `handle_confirm_reinforcement` 的 `shenji_redeploy` 分支把它部署到 (4,1) ——
    这正是"船回到棋盘上"那一支，旧格的红叉必须消失、新格必须是活着。
    """
    victim = room.players[SID_A].ships[0]
    server._do_demon_contract_sacrifice(room, SID_A, victim, 'demon_contract')
    assert _cell_at(_cells_of(room, P1), 2, 2) is not None

    room.game_effects['shenji_redeploy_ships'] = [victim]
    room.game_effects['shenji_redeploy_cells'] = [[2, 2]]
    room.magic_temp_data['pending_placement'] = {
        'caster': SID_A, 'kind': 'shenji_redeploy',
        'remaining': 1, 'total': 1, 'placed': 0,
    }
    resp = server.handle_confirm_reinforcement({
        'room_id': room.id, 'player_id': SID_A, 'position': {'x': 4, 'y': 1}})
    assert resp.get('status') == 'success', resp
    assert victim in room.players[SID_A].ships, '前提：船真的回到棋盘上'

    cells = _cells_of(room, P1)
    assert _cell_at(cells, 2, 2) is None, \
        '船搬到 (4,1) 之后，旧格 (2,2) 不许再留着沉船标记：%s' % cells
    new = _cell_at(cells, 4, 1)
    assert new is not None and new.get('alive') is True, \
        '重新部署后的新格必须是活着：%s' % new


def test_board_replace_drops_the_previous_wrecks(room):
    """★ 棋盘整块换新（灵气复苏 / 败者食尘 / 回光返照）：旧棋盘上的沉船一起作废。"""
    victim = room.players[SID_A].ships[0]
    server._do_demon_contract_sacrifice(room, SID_A, victim, 'demon_contract')
    assert _cell_at(_cells_of(room, P1), 2, 2) is not None

    # 重摆自己棋盘：船清空 + 新船摆到别处
    player = room.players[SID_A]
    player.ships = _ships([((0, 4),)])
    player.remaining_ships = 1
    replay.note_board_replaced(room, SID_A)
    replay.note(room, {'type': 'system', 'text': '重新摆放完成'})

    cells = _cells_of(room, P1)
    assert _cell_at(cells, 2, 2) is None, \
        '棋盘重摆之后旧棋盘上的沉船格不许残留：%s' % cells
    assert _cell_at(cells, 0, 4) is not None


# ===========================================================================
# 4. ★ 复活反向腿：红叉必须消失、船重新画出来
# ===========================================================================
def test_revived_ship_loses_the_wreck_mark_and_comes_back(room):
    """★ 死者苏生 / 复活：走进真实入口 `handle_confirm_reinforcement`（kind='revive'）。"""
    victim = room.players[SID_A].ships[0]
    server._do_demon_contract_sacrifice(room, SID_A, victim, 'demon_contract')
    cell = _cell_at(_cells_of(room, P1), 2, 2)
    assert cell is not None and cell.get('sunk') is True, '前提：牺牲格是沉没'

    # 复活到 (4,4)：这是 handle_confirm_reinforcement 的 'revive' 分支
    if victim not in room.players[SID_A].sunken_ships:
        room.players[SID_A].sunken_ships.append(victim)
    room.magic_temp_data['pending_placement'] = {
        'caster': SID_A, 'kind': 'revive',
        'remaining': 1, 'total': 1, 'placed': 0,
    }
    resp = server.handle_confirm_reinforcement({
        'room_id': room.id, 'player_id': SID_A, 'position': {'x': 4, 'y': 4}})
    assert resp.get('status') == 'success', resp

    cells = _cells_of(room, P1)
    assert _cell_at(cells, 2, 2) is None, \
        '复活之后旧格 (2,2) 的红叉必须消失：%s' % cells
    back = _cell_at(cells, 4, 4)
    assert back is not None and back.get('alive') is True, \
        '复活后的船必须重新画出来（alive=True）：%s' % back


def test_heal_revive_helper_also_clears_the_wreck(room):
    """★ 疗愈走的是 `_revive_sunken_ships`（原地复活）—— 同一格的红叉也要消失。"""
    victim = room.players[SID_A].ships[0]
    server._do_demon_contract_sacrifice(room, SID_A, victim, 'demon_contract')
    assert _cell_at(_cells_of(room, P1), 2, 2) is not None

    player = room.players[SID_A]
    if victim not in player.sunken_ships:
        player.sunken_ships.append(victim)
    revived = server._revive_sunken_ships(room, player, 1)
    assert revived == 1, '前提：真的复活了一艘'
    replay.note(room, {'type': 'system', 'text': '疗愈：一艘战舰复活'})

    cells = _cells_of(room, P1)
    cell = _cell_at(cells, 2, 2)
    assert cell is not None, '原地复活的那一格必须在时间线里'
    assert cell.get('alive') is True and cell.get('sunk') is not True, \
        '复活之后那一格必须画成船、不能再是红叉：%s' % cell
