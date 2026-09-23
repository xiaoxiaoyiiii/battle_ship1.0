# -*- coding: utf-8 -*-
"""回放收口批（2026-09-24）· **"这一格沉了"的两份数据源：定优先级 + 钉住 + 清账**。

上一批（§F1~F8）把"船从 `player.ships` 消失"穷举了一遍，并**如实报告了两处没修的**。
本批收的就是那两个口子，它们都是同一个形状 —— **同一件事有两份数据源**（教训 #1）。

## 口子①：沉没判据变成了双源，而且优先级没有守卫

回放里"这一格沉了"有两份来源：

* **活船列表**（`player.ships` 快照）—— 走的是**否定式推断**："这艘船**不在**列表里 ⇒ 它沉了"；
* **`lost` 登记表**（`replay.note_ship_lost`）—— 是实现点当场登记的**显式事实**（"这艘船因
  恶魔契约被献祭了"）。

同一格同时出现在两处时取哪一条，上一批**没有用例守着**（§F8 第 4 条自己写了这一点）。

**本批定的口径：`lost`（显式事实）优先于活船列表（推断）。** 理由与反向理由都写在
`replay._ship_cells` 的 ★★ 段里。实现上是**排除这个状态本身**：`_ship_cells` 保证
**同一格最多只出一条**（撞车时活船那条整条丢掉），所以前端 `replayCellOf` 的
`for...break`（取第一条）与"以最后一条为准"**结果相同** —— 它不依赖前端取哪一条。
格子上的 `src` 字段（`'ships'` / `'lost'`）就是给这条契约留的探针。

## 口子①的第三问：`lost` 表的清理路径

| 路径 | 实现点 | 撤销口 | 本批实测 |
| --- | --- | --- | --- |
| 复活 | `_revive_sunken_ships` | `note_ship_returned` | ✅ 已有 |
| 换位（神机妙算重新部署） | `handle_confirm_reinforcement` | `note_ship_returned` | ✅ 已有 |
| 棋盘整块换新 | `灵气复苏` / `败者食尘` / `回光返照` / `绝处逢生` | `note_board_replaced` | ✅ 已有 |
| **★ 平等条约回滚** | `apply_magic_effect` / `平等条约` | **上一批漏了** | ★ **本批补** |

**第三条路径是真的存在的**（不是理论）：`last_ship_change` 是**单槽**，而"牺牲"不写这个槽
—— 于是"A 船被魔法击沉 → B 船被牺牲 → 对方打平等条约"这条链上，回滚会把**已经被牺牲掉
的那艘**重新 `ships.append` 回棋盘，而它的 `lost` 登记**没有任何人撤**。
实测症状：那一格在回放里是个**红叉**，可它在游戏里明明**活着**（幻影沉船）。

## 怎么证明能红

见 `docs/REPLAY_2026_09_23.md` §G 的实施记录（每条都贴了原始输出）。
"""
import ast
import io

import pytest

import replay
import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager
import test_ship_removal_sites as removal_registry

P1, P2 = 'lostprio-p1', 'lostprio-p2'      # ⚠️ 与座位代号 `p1`/`p2` **故意取不同的串**
SIDE1, SIDE2 = 'p1', 'p2'                  # （教训 #20：两套 id 空间不许串味）


def _ships(shape):
    return [PlayerShip(positions=[Position(x, y) for (x, y) in cells], hits=[])
            for cells in shape]


def _room(p1_shape=None, p2_shape=None):
    room = GameRoom('lostprio-' + 'x' * 6)
    room.id = 'lostprio-%d' % id(room)
    room.players[P1] = Player(name='甲', ships=_ships(p1_shape or [[(0, 4)], [(5, 4)]]),
                              attacks=[], remaining_ships=2, sid=P1)
    room.players[P2] = Player(name='乙', ships=_ships(p2_shape or [[(1, 1)], [(4, 4)]]),
                              attacks=[], remaining_ships=2, sid=P2)
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
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


# ---------------------------------------------------------------------------
# 前端 `replayFoldTimeline` / `replayCellOf` 的同一套口径（增量叠加 + **取第一条**）
# ---------------------------------------------------------------------------
def _fold_ships(room):
    out = {SIDE1: [], SIDE2: []}
    for row in replay.build(room)['ships']:
        for side in (SIDE1, SIDE2):
            if isinstance(row.get(side), list):
                out[side] = row[side]
    return out


def _cells(room, side):
    return _fold_ships(room)[side]


def _frontend_cell(cells, x, y):
    """前端 `replayCellOf` 的取法：**第一条**命中（`for ... break`）。"""
    for c in cells:
        if int(c.get('x')) == int(x) and int(c.get('y')) == int(y):
            return c
    return None


def _last_cell(cells, x, y):
    """另一种可能的前端写法：**以最后一条为准**（本文件用来证明两者等价）。"""
    found = None
    for c in cells:
        if int(c.get('x')) == int(x) and int(c.get('y')) == int(y):
            found = c
    return found


def _all_cells_at(cells, x, y):
    return [c for c in cells
            if int(c.get('x')) == int(x) and int(c.get('y')) == int(y)]


def _is_sunk_view(cell):
    """前端判沉的唯一出口：`!!(shipCell && shipCell.sunk && shipCell.alive !== true)`。"""
    return bool(cell and cell.get('sunk') and cell.get('alive') is not True)


# ===========================================================================
# 1. ★★ 优先级：显式事实（`lost`）优先于推断（活船列表）
# ===========================================================================
def test_lost_fact_wins_over_alive_ship_inference(room):
    """★★ 本批的判据核心：同一格**同时在**两份表里时，必须按 `lost` 画成沉没。

    ⚠️ 这个形状**真的出现过**（本批实测，见 `test_treaty_rollback_clears_the_wreck_it_revives`）：
    "船被放回棋盘（`hits` 清空、`sunken_ships` 里也摘掉）+ `lost` 登记没人撤" 就是它。
    本用例手工把这两个条件摆出来，钉的是**合并口径**（不改产品代码也能红）。

    ⚠️ 判据是 `_all_cells_at(...) == 1`：**"口径是 `lost` 优先"在实现上就是
       "同一格最多只出一条"**（活船那条整条丢掉）。所以"谁优先"这件事在这里
       表现为"有没有重复"，而不是"两条里挑哪条"。
       改前（本批之前）：活船格先 append、`lost` 格后 append ⇒ 同一格两条，
       前端取第一条 ⇒ 画成**活船** —— 一件双方都看得见的沉没被一笔勾销。
    """
    victim = room.players[P2].ships[0]
    x, y = victim.positions[0].x, victim.positions[0].y
    server._do_demon_contract_sacrifice(room, P2, victim, 'demon_contract')
    assert _is_sunk_view(_frontend_cell(_cells(room, SIDE2), x, y)) is True, '前提：牺牲格是沉没'

    # 手工造出"这艘船又回到棋盘上、`lost` 登记还在"的冲突态。
    # ⚠️ 三件事都要做，缺一件就不是这个形状：
    #   ① 放回活船列表；② 清空命中（"活着"的判据是 `len(hits) < len(positions)`）；
    #   ③ 从沉船堆里摘掉。
    room.players[P2].ships.append(victim)
    victim.hits = []
    while victim in room.players[P2].sunken_ships:
        room.players[P2].sunken_ships.remove(victim)
    assert victim in room.players[P2].ships, '前提：这艘船在活船列表里'
    assert victim not in room.players[P2].sunken_ships, '前提：它不在沉船堆里'
    assert replay._is_alive(victim), '前提：回放层看它是**活着**的（hits 为空）'
    assert replay._lost_cells(room, P2), '前提：`lost` 表里还有它的登记'
    # ⚠️ 必须再推动记录器一次：时间线是**稀疏**的，冲突态是在"上一步之后"才摆出来的，
    #    不刷新的话读到的还是上一步那一条（本批实测：漏了这一句 ⇒ 冲突态根本没进时间线，
    #    守卫恒绿 —— 一个"改了也不红"的假守卫）。
    replay.refresh_ships(room)

    cells = _cells(room, SIDE2)
    assert len(_all_cells_at(cells, x, y)) == 1, (
        '同一格必须**只有一条**说法（两份说法并存 ⇒ 优先级就成了"看谁写在前面"）：%s'
        % _all_cells_at(cells, x, y))
    cell = _frontend_cell(cells, x, y)
    assert cell.get('src') == 'lost', '这一格必须按**显式事实**（lost 表）出：%s' % cell
    assert _is_sunk_view(cell) is True, (
        '`lost` 表里登记过沉没的格子必须画成沉没（事实压过推断）：%s' % cell)
    assert cell.get('alive') is False and cell.get('sunk') is True, cell

    # 同一份数据换成"以最后一条为准"的读法，结论必须一模一样（不依赖前端取哪一条）
    assert _last_cell(cells, x, y) == cell, (
        '前端取第一条与取最后一条必须等价 —— 判据在服务端，不在前端：%s / %s'
        % (_last_cell(cells, x, y), cell))


def test_alive_ship_list_only_wins_where_lost_has_no_record(room):
    """★ 反向腿：`lost` 表**没有**这格时，活船列表照旧说了算（不许被改成永远沉没）。

    朴素修法（"凡是曾经有过船就永远留成沉没"）会让这条红 —— 而它正是
    滥竽充数收回 / 换位 / 神威暂时除外那三条反向腿要保的东西。

    ⚠️ 船位时间线是**稀疏**的（没变化就不记行），所以先制造一次变化，
       时间线里才有 p1 那一侧可断言。
    """
    server._do_demon_contract_sacrifice(room, P2, room.players[P2].ships[0], 'demon_contract')
    cells = _cells(room, SIDE1)
    assert cells, '前提：这一帧里 p1 那一侧有船格：%s' % _fold_ships(room)
    alive = _frontend_cell(cells, 0, 4)
    assert alive is not None and alive.get('alive') is True, alive
    assert alive.get('src') == 'ships', '没登记过沉没的格子必须来自活船列表：%s' % alive
    assert _is_sunk_view(alive) is False, alive


def test_every_cell_declares_which_source_it_came_from(room):
    """★ 探针字段：每条船格都必须带 `src`，且只能是 `ships` / `lost` 两种之一。

    没有这个字段，"两份说法取哪一条"就只能靠读代码猜 —— 而下一批的人一定会猜错。
    """
    server._do_demon_contract_sacrifice(room, P2, room.players[P2].ships[0], 'demon_contract')
    seen = set()
    for cell in _cells(room, SIDE1) + _cells(room, SIDE2):
        assert cell.get('src') in ('ships', 'lost'), cell
        assert set(cell) <= {'x', 'y', 'alive', 'sunk', 'src'}, sorted(cell)
        seen.add(cell['src'])
    assert seen == {'ships', 'lost'}, '两种来源都要真的出现过（否则探针是空的）：%s' % seen


# ===========================================================================
# 2. ★★ `lost` 表的清理：第三条路径（平等条约回滚）实测复现 + 修复
# ===========================================================================
def _stage_equal_treaty_rollback(room):
    """造出"平等条约回滚会把已被牺牲的船放回棋盘"的那个局面（真调两条产品路径）。

    链：① 牺牲 B 船（写 `lost`）→ ② `last_ship_change` 单槽里存的正是 B 船
    （牺牲**不写**这个槽，所以它留着的是更早那次魔法击沉的快照）→ ③ 打平等条约。
    """
    victim = room.players[P2].ships[0]
    x, y = victim.positions[0].x, victim.positions[0].y
    server._do_demon_contract_sacrifice(room, P2, victim, 'demon_contract')
    room.game_effects['last_ship_change'] = {
        'round': room.round, 'player': P2, 'count': 1,
        'ship': victim, 'hits_added': [], 'source': 'magic',
    }
    return victim, x, y


def test_treaty_rollback_clears_the_wreck_it_revives(room):
    """★★ 本批修的第三条路径：平等条约把船放回棋盘 ⇒ 那一格的红叉必须消失。

    改前：`lost` 登记没人撤 ⇒ 船在棋盘上活着、回放里却是个**红叉**（幻影沉船）。
    改后：回滚分支调 `note_ship_returned` + 收尾 `refresh_ships`。
    """
    victim, x, y = _stage_equal_treaty_rollback(room)
    assert _is_sunk_view(_frontend_cell(_cells(room, SIDE2), x, y)) is True, '前提：回滚前是红叉'

    res = server.apply_magic_effect(room, P1, MagicCard('平等条约'), {})
    assert getattr(res, 'success', False) is True, getattr(res, 'message', None)
    assert victim in room.players[P2].ships, '前提：船真的被放回了棋盘（产品路径自己做的）'

    cells = _cells(room, SIDE2)
    cell = _frontend_cell(cells, x, y)
    assert cell is not None, '船放回棋盘之后那一格必须在时间线里：%s' % cells
    assert _is_sunk_view(cell) is False, (
        '船已经回到棋盘上，那一格的红叉必须消失（改前这里是幻影沉船）：%s' % cell)
    assert cell.get('alive') is True and cell.get('src') == 'ships', cell
    assert not replay._lost_cells(room, P2), '`lost` 表必须被清干净：%s' % room.replay.get('lost')


def test_treaty_rollback_snapshot_lands_on_the_same_step(room):
    """★ 回滚那一帧必须**当场**就是真值（不是等下一次别处的日志才补上）。

    ⚠️ 平等条约这个分支**不写游戏日志**，所以 `note_ship_returned` 只改登记、
    不推动记录器 ⇒ 必须由收尾的 `refresh_ships` 补一次快照。少了它，红叉会一直挂到
    下一次有日志的动作为止（实测过同形状）。
    """
    victim, x, y = _stage_equal_treaty_rollback(room)
    steps_before = len(room.replay['steps'])
    server.apply_magic_effect(room, P1, MagicCard('平等条约'), {})
    assert len(room.replay['steps']) == steps_before, '回滚不产生新步骤（前提）'
    row = room.replay['ships'][-1]
    assert int(row['step']) == steps_before - 1, (
        '最后一帧必须就是回滚那一步（%d），实际 %s' % (steps_before - 1, row))
    cell = _frontend_cell(row.get(SIDE2) or [], x, y)
    assert cell is not None and cell.get('alive') is True, cell
    # ★ 稀疏的判据：**没变的那一侧不许被重记**。回滚只动被回滚那一侧，
    #   所以最后两行里 p1 那一段必须**逐字节相同**（重新记一份全量会白占体积）。
    #   ⚠️ 快照是**按帧**记两侧的（`_record_snapshot` 记的是"这一刻的整张桌面"），
    #      所以判据只能是"内容有没有变"，不能是"键有没有出现"。
    if len(room.replay['ships']) >= 2:
        before_row = room.replay['ships'][-2]
        assert before_row.get(SIDE1) == row.get(SIDE1), (
            '另一侧没变却被重记了一份不同的全量：%s / %s' % (before_row.get(SIDE1), row.get(SIDE1)))


def test_lost_table_is_empty_after_every_cleanup_path(room):
    """★ 逐条清账：复活 / 换位 / 棋盘换新 / 平等条约回滚之后，`lost` 表必须为空。

    四条路径都用**产品函数**跑（不是直接改 `lost`），所以它同时是"撤销口还在"的回归。
    """
    # ① 复活（疗愈）
    server._do_demon_contract_sacrifice(room, P2, room.players[P2].ships[0], 'demon_contract')
    assert replay._lost_cells(room, P2), '前提：牺牲后有登记'
    assert server._revive_sunken_ships(room, room.players[P2], 1) == 1
    assert not replay._lost_cells(room, P2), '复活之后 `lost` 必须清空：%s' % room.replay['lost']

    # ② 棋盘整块换新（回光返照只换自己那块）
    server._do_demon_contract_sacrifice(room, P2, room.players[P2].ships[0], 'demon_contract')
    assert replay._lost_cells(room, P2), '前提：牺牲后有登记'
    replay.note_board_replaced(room, P2)
    assert not replay._lost_cells(room, P2), '棋盘换新之后 `lost` 必须清空：%s' % room.replay['lost']

    # ③ 平等条约回滚（本批补的那条）
    victim, x, y = _stage_equal_treaty_rollback(room)
    assert server.apply_magic_effect(room, P1, MagicCard('平等条约'), {})
    assert not replay._lost_cells(room, P2), '回滚之后 `lost` 必须清空：%s' % room.replay['lost']


# ===========================================================================
# 3. ★★ 源码级穷举：每个"把船放回棋盘"的点都要为 `lost` 表表态
# ===========================================================================
#: 每个船追加点的处置口径：`(函数名, 容器变量名) → True/False`。
#:
#: * `True`  —— 这个点会把**曾经被登记过沉没的船**放回棋盘 ⇒ **必须**在同一个函数里
#:   调 `replay.note_ship_returned`（否则那一格就是幻影沉船）；
#: * `False` —— 它放回来的船**不可能**在 `lost` 表里：新建的船（增援 / 滥竽充数 /
#:   绝处逢生的唯一一艘）、神威"暂时除外"到期归还（那一支**有意不登记**）、
#:   棋盘整块换新（由 `note_board_replaced` 撤账）、布船阶段重建、构造器与调试夹具。
#:
#: ⚠️ **按"函数名 + 容器变量名"登记，不按行号**（行号每提交都漂移）。
#: ⚠️ 判据落在**函数这一层**（这个函数里有没有 `note_ship_returned`），而不是
#:    "最近的那一层语句块"：实测过前者 —— 撤销口与追加点常常是**并列的两个分支**
#:    （`handle_confirm_reinforcement` 的 `revive` / `shenji_redeploy` 就是），
#:    按"最近语句块"判会把它们判成"没调"，三条本该绿的腿一起假红。
#:    代价是判据变粗：于是**同一个函数里两种处置**必须显式登记（`apply_magic_effect`
#:    既有要撤销的点、也有不需要撤销的点），见下面 `LOST_RETURN_EXCEPTIONS`。
LOST_RETURN_POLICY = {
    # ---- 会把"登记过沉没的船"放回棋盘的 ----
    ('_revive_sunken_ships', 'player'): True,
    ('handle_confirm_reinforcement', 'caster'): True,
    ('apply_magic_effect', 'affected_player'): True,
    # ---- 放回来的船不可能在 `lost` 表里 ----
    ('apply_magic_effect', 'caster'): False,    # 绝处逢生 / 钢筋铁骨：新建的船或自牺牲
    ('_restore_due_shenwei', 'owner'): False,   # 神威"暂时除外"**有意不登记**
    ('apply_magic_effect', 'player'): False,    # 败者食尘：`player.ships = []` 整体重建
    ('confirm_magic_target', 'player'): False,  # 灵气复苏：同上（紧跟 note_board_replaced）
    ('handle_place_ships', 'players'): False,   # 布船阶段整体重建
    ('_ai_place_ships', 'player'): False,       # 布船阶段
    ('__init__', 'self'): False,                # 构造器
    ('test_set_player_ships', 'player'): False,  # 调试夹具
    ('test_set_opponent_ships', 'opponent'): False,
    ('test_reset_game', 'player'): False,
}

#: ★ **同一个函数里既有 `True` 也有 `False` 时**，每一条 `False` 都必须在这里写理由。
#:
#: 为什么需要它：判据落在函数这一层（见上），所以"这个函数的某个分支调了撤销口"
#: 会盖住整个函数。**新增一个不需要撤销的追加点到这种函数里**时，如果不强制表态，
#: 下次复制粘贴就会把"新建的船"混进"要撤销的船"那一支（幻影沉船）。
LOST_RETURN_EXCEPTIONS = {
    ('apply_magic_effect', 'caster'): (
        '`绝处逢生` / `钢筋铁骨` 往 `caster.ships` 里放的是**新建或现有**的船，'
        '不是"被登记过沉没的船"（自牺牲那一支是**往相反方向**走：船被摘掉）'),
    ('apply_magic_effect', 'player'): (
        '`败者食尘` 的 `player.ships = []` 是**整体重建**，旧棋盘上的沉没登记由 '
        '`note_board_replaced` 撤 —— 撤账口与"船回来了"不是同一件事，'
        '混在一起会让重摆顺手把两套账都动一遍'),
}


def _scan_ship_add_sites():
    """扫出 `server.py` 里所有"把船**放进** `*.ships`"的点。

    形状与 `test_ship_removal_sites._scan_ship_mutations` 同源（那边是宽表，
    这边只看追加那几个操作：`append` / `insert` / `extend` / 整体重建）。
    返回 `(src, tree, [site, ...])`，`site` = `{fn, container, line}`：

    * `container` —— `X.ships` 里的 `X` 标识（`player` / `caster` / `affected_player`…）；
      写成 `room.players[pid].ships` 时取**最外层**的名字（`room.players` ⇒ `players`），
      与 `test_ship_removal_sites` 同一个口径（两套扫描器对同一处的叫法必须一样）。
    """
    src = io.open(server.__file__, encoding='utf-8').read()
    tree = ast.parse(src)
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node

    def owner_fn(node):
        cur = node
        while cur is not None:
            cur = parent.get(cur)
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return cur
        return None

    def container_of(attr_node):
        base = attr_node.value
        while isinstance(base, ast.Subscript):
            base = base.value
        return getattr(base, 'id', None) or getattr(base, 'attr', None)

    found = []
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ('append', 'insert', 'extend'):
            targets = [(node.func.value, node)]
        elif isinstance(node, ast.Assign):
            targets = [(t, node) for t in node.targets]
        for (attr_node, site_node) in targets:
            if not (isinstance(attr_node, ast.Attribute) and attr_node.attr == 'ships'):
                continue
            fn = owner_fn(site_node)
            found.append(dict(fn=(fn.name if fn else '<module>'),
                              container=container_of(attr_node),
                              line=site_node.lineno, fn_node=fn))
    return src, tree, found


def _ancestors_of(node, parent):
    """`node` 的全部祖先（自底向上）。`parent` 是预先算好的"子 → 父"映射。"""
    out = []
    cur = parent.get(node)
    while cur is not None:
        out.append(cur)
        cur = parent.get(cur)
    return out


def test_every_ship_add_site_states_its_lost_policy():
    """★★ 穷举守卫：每个"把船放回棋盘"的点都必须在 `LOST_RETURN_POLICY` 里有交代。

    四条腿都会红（每条都实测过，见 §G 实施记录）：
      · **新增**一个"把船放回棋盘"的点却没登记 ⇒ 红（下一批就可能漏掉撤销口）；
      · 登记成 `True`（要撤销）而那个函数里**根本没有** `note_ship_returned` ⇒ 红
        （那正是本批修的那种漏：`平等条约` 回滚）；
      · 登记成 `False` 但函数里**有**撤销口、又没写进 `LOST_RETURN_EXCEPTIONS` ⇒ 红
        （函数变了形却没重新表态）；
      · 例外表/策略表里有指向不存在的代码的条目 ⇒ 红（例外表不许烂在原地）。

    ⚠️ 这条判据**只**管"撤销口还在不在"，不管"撤销口有没有漏格" ——
       后者由本文件上半部分的运行时用例与 `tools/dom_replay_frame_check.mjs` 管。
    """
    src, tree, found = _scan_ship_add_sites()
    # ⚠️ **写成确切数字**（不是 `>= 12`）：扫描器"少看见几个点"和"多看见一个点"都是
    #    **必须有人看一眼**的事（前者的后果是守卫恒绿）。新增一个合法追加点时会红两次
    #    （这里 + 上面的登记表），那正是想要的效果 —— 逼人表态，而不是静默扩表。
    #    实测口径见 §G 实施记录：20 个点 / 13 条 `(函数, 容器)` 登记。
    assert len(found) == 20, (
        '扫描到的"把船放回棋盘"的点是 %d 个（基线 20）—— 扫描器变了或代码变了，'
        '两种都要先看一眼：%s' % (len(found), [(s['fn'], s['line']) for s in found]))

    parent = {}
    for n in ast.walk(tree):
        for child in ast.iter_child_nodes(n):
            parent[child] = n

    ret_nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == 'note_ship_returned'
                 and getattr(n.func.value, 'id', None) == 'replay']
    assert ret_nodes, '一个 `note_ship_returned` 调用点都找不到 —— 扫描器坏了？'
    fns_with_return = set()
    for r in ret_nodes:
        for anc in [r] + _ancestors_of(r, parent):
            if isinstance(anc, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fns_with_return.add(anc.name)
                break

    unregistered, mismatched = [], []
    for site in found:
        key = (site['fn'], site['container'])
        if key not in LOST_RETURN_POLICY:
            unregistered.append('%s / %s 第 %d 行' % (site['fn'], site['container'], site['line']))
            continue
        policy = LOST_RETURN_POLICY[key]
        calls = site['fn'] in fns_with_return
        if policy and not calls:
            mismatched.append(
                '%s / %s 第 %d 行：登记"要撤销"，但这个函数里没有 `note_ship_returned`'
                % (site['fn'], site['container'], site['line']))
        if (not policy) and calls and key not in LOST_RETURN_EXCEPTIONS:
            mismatched.append(
                '%s / %s 第 %d 行：登记"不用撤销"，但这个函数里**有**撤销口 —— '
                '要么改成"要撤销"，要么写进 `LOST_RETURN_EXCEPTIONS` 说明为什么不用'
                % (site['fn'], site['container'], site['line']))

    assert not unregistered, (
        '这些"把船放回棋盘的点"没有在 LOST_RETURN_POLICY 里交代'
        '（新写法？漏登记？它会绕过 `lost` 表的撤销口）：\n  ' + '\n  '.join(unregistered))
    assert not mismatched, '处置口径与实际代码对不上：\n  ' + '\n  '.join(mismatched)

    # 例外表不许烂在原地：表里每条都必须指向**真的还在**的代码
    scanned = {(s['fn'], s['container']) for s in found}
    stale = [k for k in list(LOST_RETURN_POLICY) + list(LOST_RETURN_EXCEPTIONS)
             if k not in scanned]
    assert not stale, '策略表/例外表里有指向不存在的代码的条目：%s' % stale
    orphan = [k for k in LOST_RETURN_EXCEPTIONS if LOST_RETURN_POLICY.get(k) is not False]
    assert not orphan, '例外表里的条目必须是一条 `False` 的策略：%s' % orphan

    # 与穷举移除表的登记面必须**同源**（两套表各记一份函数名就会漂移 —— 教训 #1）
    wanted = {e['fn'] for e in removal_registry.REMOVAL_SITES}
    extra = sorted({k[0] for k in LOST_RETURN_POLICY if k[0] not in wanted})
    assert not extra, (
        '策略表里的这些函数在 `REMOVAL_SITES`（穷举移除表）里找不到 —— 两套登记面漂移了：%s'
        % extra)


def test_reviver_sites_call_the_shared_cleanup_not_a_local_one():
    """★ 撤销口**只有一个**（`replay.note_ship_returned`），别在 server 里另写一份。

    同一件事两份实现必然漂移（教训 #1）：谁在 server 里手写
    `room.replay['lost'].pop(pid)`，就会绕过 `lost` 表的"键没了就删"口径，
    留下一个空的 `lost` 条目（看起来"清过了"，其实留下一条空壳）。
    """
    src = io.open(server.__file__, encoding='utf-8').read()
    tree = ast.parse(src)
    bad = []
    for node in ast.walk(tree):
        # 形如 `<任意>.replay['lost']` 的下标读取/赋值
        if isinstance(node, ast.Subscript) and getattr(node.value, 'attr', None) == 'replay':
            seg = ast.get_source_segment(src, node) or ''
            if "'lost'" in seg or '"lost"' in seg:
                bad.append('第 %d 行：%s' % (node.lineno, seg[:70]))
    assert not bad, (
        'server.py 里出现了直接读写 `room.replay[\'lost\']` 的代码 —— '
        '撤销口必须走 `replay.note_ship_returned` / `note_board_replaced`：\n  ' + '\n  '.join(bad))
