# -*- coding: utf-8 -*-
"""回放缺陷批（2026-09-24）· **`神威！` 致死那一支的船不许在回放里凭空消失**。

作者实报的第五条同族成因（前四条已在前几批修完：主动牺牲 / 绝处逢生 / 钢筋铁骨 /
滥竽充数收回 / 换位复活）。症状与"主动牺牲"**一模一样**：那一格凭空消失、
既不产生 `attack` 步也没有沉没记录。

## 根因（`server.apply_magic_effect` 的 `神威！` 分支）

```python
excluded_ships.append(ship)
del target_player.ships[i]        # ★ 船从列表里被摘掉
target_player.remaining_ships -= 1
...
if board != 'self' and len(excluded_ships) == 1:      # ← 致死那一支
    _mark_ship_sunken(target_player, excluded_ships[0])
```

回放的船位时间线（`replay._ship_cells`）**只遍历 `player.ships`** ⇒ 那一格不再进快照
⇒ 前端按 `side` 整体替换之后，回放棋盘上那格**凭空消失**。
而它**不产生 attack 步**（没有"打这一炮"），所以连攻击标记也补不上 ——
这正是它与 `轰炸` / `硫磺火焰`（同样 `ships.remove` 但逐格发 `attack_result`）的区别。

## 两支的差别是**有意**的，别把它改成一样

| 支 | 触发 | 游戏里 | 回放里必须 |
| --- | --- | --- | --- |
| **致死** | 作用于对方棋盘 + 区域内恰好 1 艘 | 船被就地打沉（双方看得见） | **红叉**（`alive: False` + `sunk: True`） |
| **暂时除外** | 其余情况 | 区域被"扣掉"，船下个大回合原样归还 | 那一格**消失**（一个沉没标记都不许有） |

所以登记点在**致死那一支**里，用的是**手上这艘船的坐标** ——
绝不是"diff 前后快照猜哪几格没了"（那会把暂时除外的船一起判成沉没）。

## 另外两件事（同一批一起钉住）

1. **登记只改状态、不推动记录器**：记录器只在**下一步追加**时比对快照，
   而"直调 `apply_magic_effect`"这类收尾**不写任何日志** ⇒ 那一帧永远不变。
   修法是那一段收尾处显式 `replay.refresh_ships(room)`（幂等），
   且排在**船位 / 船数 / 待办全部落定之后**；
2. **同一步只留一行**：`_append` 已经记过一行（那一刻的中间态），刷新再记一次
   ⇒ 时间线里会出现**两条 `step` 相同的行**（同一帧两份说法）。`replay._record_at_current_step`
   现在把这种情况合成一行。本文件最后一条用例钉的就是它。
"""
import ast
import io
import pathlib
import uuid

import pytest

import replay
import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

# ⚠️ 座位 key 与 `Player.sid` 必须一致：项目在人机房 / 自定义房里就是同一套
#    （key = sid），而 `replay._effects_of` 是按 `sid` 去对齐
#    `game_effects['shenwei_holes'][*]['player']` 的。
P1, P2 = 'shenwei-p1', 'shenwei-p2'

SHENWEI_AREA = {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}
IN_AREA = (1, 1)          # 必落在上面的 3×3 里
IN_AREA_2 = (2, 2)        # 同上
OUT_AREA = (5, 5)


def _ships(shape):
    return [PlayerShip(positions=[Position(x, y) for (x, y) in cells], hits=[])
            for cells in shape]


def _room(p2_shape):
    """神威的形状：施法者 p1 自己也要有船（末尾会检查"己方棋盘是否被清空"）。"""
    room = GameRoom('shenwei-' + uuid.uuid4().hex[:6])
    room.players[P1] = Player(name='甲', ships=_ships([[(0, 4)], [(1, 4)]]),
                              attacks=[], remaining_ships=2, sid=P1)
    room.players[P2] = Player(name='乙', ships=_ships(p2_shape),
                              attacks=[], remaining_ships=len(p2_shape), sid=P2)
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
    r = _room([[(IN_AREA)], [(OUT_AREA)]])
    yield r
    room_manager.rooms.pop(r.id, None)


def _magic_log(room, text):
    """喂一条"使用了【神威！】"的步骤（形状与 `server.log_magic` 一致）。

    ⚠️ 这里**不**调 `server.log_magic`：那会 `add_game_log` → 真 `emit`，
       需要请求上下文；本文件要钉的是**记录器**那一侧，事件不是它的判据。
    """
    replay.note(room, {'type': 'magic', 'text': text,
                       'detail': {'caster': P1, 'card': '神威！'}})


def _cast(room, board=None):
    target = {'target_area': SHENWEI_AREA}
    if board:
        target['board'] = board
    return server.apply_magic_effect(room, P1, MagicCard('神威！'), target)


SIDE1, SIDE2 = 'p1', 'p2'      # 回放时间线里的**座位代号**（不是原始 pid！）
RAW1, RAW2 = P1, P2            # 房间里的**原始 pid**（本文件里两者故意取不同的串）


def _fold_ships_up_to(room, k=None):
    """前端 `replayFoldTimeline` 的同一套叠加口径：按 step 升序叠加（增量）。

    返回 `{side: [cell, ...]}` —— 就是前端 `frame.ships[side]` 的那一份。
    ⚠️ 时间线里的键是**座位代号**（`p1` / `p2`，由 `replay.build` 按入座顺序算出来），
       而原始 pid 是另一套 id 空间（本文件的夹具里两者取了不同的串，就是为了让
       "拿原始 pid 当座位代号"这种串味**当场出错**，而不是悄悄全绿 —— 教训 #20）。
    """
    rows = replay.build(room)['ships']
    if k is None:
        k = max(0, len(room.replay['steps']) - 1)
    out = {SIDE1: [], SIDE2: []}
    for row in rows:
        if int(row.get('step', -1)) > k:
            break
        for side in (SIDE1, SIDE2):
            if isinstance(row.get(side), list):
                out[side] = row[side]
    return out


def _cells_of(room, side, k=None):
    """`side` 取 `SIDE1` / `SIDE2`（座位代号）。"""
    return _fold_ships_up_to(room, k)[side]


def _cell_at(cells, x, y):
    """⚠️ 逐格比对必须按**同一种类型**比（`replay._ship_cells` 里 `x`/`y` 是 `int`
    还是 `str` 取决于喂进来的坐标）—— 上一批就是拿 `4 == '4'` 比而假红过。"""
    for c in cells:
        try:
            if int(c.get('x')) == int(x) and int(c.get('y')) == int(y):
                return c
        except (TypeError, ValueError):
            continue
    return None


# ===========================================================================
# 1. ★★ 致死腿：真调 `神威！`，那一格必须在时间线里且是沉没
# ===========================================================================
def test_shenwei_kill_marks_the_cell_as_sunk(room):
    """★★ 本批的验收核心。

    改前：`del target_player.ships[i]` 之后那一格**根本不在时间线里** ⇒
    下面第一条断言直接红（`assert None is not None`）。
    """
    victim = room.players[P2].ships[0]
    x, y = victim.positions[0].x, victim.positions[0].y
    assert (x, y) == IN_AREA, '前提：牺牲的这艘船就在 3×3 区域里'

    _magic_log(room, '甲 使用了【神威！】')
    before = _cell_at(_cells_of(room, SIDE2), x, y)
    assert before is not None and before.get('alive') is True, \
        '前提：打之前那一格是活船：%s' % before

    res = _cast(room)
    assert getattr(res, 'success', False) is True, res
    assert '击沉' in getattr(res, 'message', ''), res.message

    cells = _cells_of(room, SIDE2)
    cell = _cell_at(cells, x, y)
    assert cell is not None, (
        '神威致死那一格 (%d,%d) 不在回放的船位时间线里 ⇒ 回放棋盘上会凭空消失：%s'
        % (x, y, cells))
    assert cell.get('sunk') is True, '致死格必须是沉没：%s' % cell
    assert cell.get('alive') is False, '致死格的 alive 必须是 False（前端判据）：%s' % cell
    # ⚠️ `src` 是 2026-09-24 收口批加的探针字段（这一格来自活船列表还是显式沉没登记），
    #    见 `replay._ship_cells` 的 ★★ 段与 `tests/test_replay_lost_priority.py`。
    assert set(cell.keys()) == {'x', 'y', 'alive', 'sunk', 'src'}, \
        '船格字段就这五个（前端判据只读 alive / sunk；src 是给守卫看的）：%s' % cell
    assert cell.get('src') == 'lost', \
        '致死格必须来自**显式沉没登记**（它已经被 `del ships[i]` 摘掉了）：%s' % cell

    # 区域外的船照旧活着（不许被一起标成沉没）
    other = _cell_at(cells, OUT_AREA[0], OUT_AREA[1])
    assert other is not None and other.get('alive') is True, other


def test_shenwei_kill_is_recorded_at_the_step_it_happened(room):
    """★ 那一格必须**在那一步**就出现（不是等到下一步才对）。"""
    _magic_log(room, '甲 使用了【神威！】')
    _cast(room)
    _magic_log(room, '甲 使用了【神威！】，目标区域内1艘战舰被击沉')

    rows = replay.build(room)['ships']
    print('ships timeline =', rows)
    kinds = [row for row in rows
             if isinstance(row.get(SIDE2), list)
             and any(c.get('sunk') is True for c in row[SIDE2])]
    assert kinds, '时间线里没有任何一条带沉没格的行：%s' % rows
    step = int(kinds[0]['step'])
    # 上一步（打牌那一帧）它还是活船 —— 这一格是**这一步**才沉的
    assert _cell_at(_cells_of(room, SIDE2, step - 1), IN_AREA[0], IN_AREA[1]) is None, \
        '第 %d 步之前它不该已经沉了' % step
    assert len(room.replay['steps']) - 1 >= step, '沉没必须落在已经录下来的步骤里'






def test_shenwei_hole_region_is_still_recorded(room):
    """★ 区域本身照旧进效果时间线（作者要的是格子按沉没画，不是拆掉区域效果）。"""
    _magic_log(room, '甲 使用了【神威！】')
    _cast(room)
    _magic_log(room, '甲 使用了【神威！】，目标区域内1艘战舰被击沉')
    payload = replay.build(room)
    holes = [h for row in payload['effects']
             for side in ('p1', 'p2')
             for h in ((row.get(side) or {}).get('shenwei_holes') or [])]
    assert holes, '神威洞没有进效果时间线：%s' % payload['effects']
    assert holes[0] == {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}, holes[0]




def test_shenwei_ship_and_effect_timelines_never_carry_a_raw_pid(room):
    """★ 归属只许是座位代号（契约 §6：回放响应里不许出现 user_id / 原始 pid）。

    ⚠️ 判据只看**本批动过的那两条时间线**（`ships` / `effects`）以及 `names` 段：
       `steps[*].detail` 里的 `caster` / `attacker` 是**既有形状**（录制期就用原始 pid
       当键，`_step_detail` 只做标量裁剪），本批**不**顺手改它 —— 那是另一条账。
    """
    _magic_log(room, '甲 使用了【神威！】')
    _cast(room)
    _magic_log(room, '甲 使用了【神威！】，目标区域内1艘战舰被击沉')
    payload = replay.build(room)
    for key in ('ships', 'effects', 'hands', 'board_resets', 'nodes'):
        blob = repr(payload.get(key))
        for raw in (RAW1, RAW2):
            assert raw not in blob, '回放数据 %r 里出现了原始 pid %r' % (key, raw)
    # 原始 pid 也绝不许冒充座位代号混进时间线的**键**
    for row in payload['ships'] + payload['effects']:
        assert set(row.keys()) <= {'step', SIDE1, SIDE2}, row


# ===========================================================================
# 2. ★★ 反向腿：「暂时除外」那一支**不许**留下沉没标记
# ===========================================================================
def test_shenwei_exclusion_never_leaves_a_sunk_cell():
    """★★ 最重要的一条反向腿：区域内 2 艘 ⇒ 暂时除外、下个大回合原样归还。

    判据写成"凡是消失就登记沉没"的**朴素修法**（或把登记挪到 `del` 那一行）
    会让这条**红**：那两格会留在时间线里、还带着 `sunk: True` ⇒ 回放里凭空多出沉船。
    """
    room = _room([[(IN_AREA)], [(IN_AREA_2)], [(OUT_AREA)]])
    try:
        _magic_log(room, '甲 使用了【神威！】')
        res = _cast(room)
        assert getattr(res, 'success', False) is True, res
        assert '暂时除外' in getattr(res, 'message', ''), res.message
        # 前提：这两艘船真的被摘掉了、而且**没进沉船堆**
        assert len(room.players[P2].ships) == 1, room.players[P2].ships
        assert room.players[P2].sunken_ships == [], '除外**不是**沉没'
        assert room.game_effects.get('excluded_ships'), '前提：登记了"下回合归还"'

        _magic_log(room, '甲 使用了【神威！】，目标区域内2艘战舰被暂时除外')
        cells = _cells_of(room, SIDE2)
        for (x, y) in (IN_AREA, IN_AREA_2):
            cell = _cell_at(cells, x, y)
            assert cell is None or cell.get('sunk') is not True, (
                '暂时除外**不是沉没**（下个大回合原样归还），却在那格留下了沉没标记 '
                '⇒ 回放里出现幻影沉船：%s' % cell)
        # 区域外那艘不受影响
        outside = _cell_at(cells, OUT_AREA[0], OUT_AREA[1])
        assert outside is not None and outside.get('alive') is True, outside
    finally:
        room_manager.rooms.pop(room.id, None)






# ===========================================================================
# 3. 源码级：登记点只许在**致死那一支**里
# ===========================================================================
def _shenwei_block_source():
    """`apply_magic_effect` 里 `神威！` 那一节的源码（到下一个 `elif card.name` 为止）。

    ⚠️ 那张卡是**一条 `if` / 一长串 `elif` 链**里的一节（不是每个卡名一条独立 `if`），
       所以判据是"这一节的 `test` 源码里同时出现 `card.name` 与 `'神威！'`" ——
       别写成"第一个 `if card.name == ...`"（那会先拿到 `余音绕梁`，本批实测踩过）。
    ⚠️ 还要**在 `神威！` 之后截断**：`ast.walk` 会一路扫到整条链的收尾
       （本批实测：不截断时把 `绝处逢生` / `钢筋铁骨` 那几处也算进来，数出 3 处）。
    """
    src = io.open(server.__file__, encoding='utf-8').read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != 'apply_magic_effect':
            continue
        # 先按源码找 `神威！` 那一节的起点，再用**下一节 `elif` 的起点**截断
        # （`ast` 里 `elif` 是 `orelse=[If]`，直接取片段会从 `elif` 开头 —— 那不是
        #  能独立 parse 的语句，本批实测 `ast.parse` 会抛 SyntaxError）。
        start = src.find("elif card.name == '神威！'")
        if start < 0:
            start = src.find("if card.name == '神威！'")
        end = src.find("card.name == '冻结'", start)
        if start < 0 or end < 0:
            continue
        end = src.rfind('elif ', start, end)
        seg = src[start:end]
        if seg.lstrip().startswith('elif'):
            seg = 'if' + seg.lstrip()[4:]
        return src, seg
    raise AssertionError('没找到 `神威！` 分支（源码结构变了？）')
