# -*- coding: utf-8 -*-
"""★★ 第 7 处玩家可见缺陷：`轰炸` / `硫磺火焰` 打出的格子在回放里**一个标记都没有**。

## 症状（作者实报，与"看不到已打过的格"同族）

回放里被这几张卡打过的那一整行 / 整列画成"**没挨过炮的海面**"，
只有"恰好把船打沉的那一格"会以沉没 ✕ 出现（那是 `ships` 时间线兜的，不是标记）。
⇒ 一份**残缺的棋盘** —— 本项目最怕的"看着对、其实少东西"。

## 根因（教训 #1 的老形状：同一件事两份数据源）

| 数据源 | 是什么 | 谁在读 |
| --- | --- | --- |
| `Player.attacks` | **权威动作记录**（逐格写、逐格 `emit('attack_result')`） | 实战前端画"我已轰过的格"、观战棋盘帧（`_spectate_player_cells`） |
| `game_logs` 里 `type='attack'` 的日志 | **只有普通炮击**会写（`handle_attack`） | 回放（改动前：`replayComputeFrame` 第 ③ 段按 `step.kind === 'attack'` 反推） |

`轰炸` / `硫磺火焰`（以及本批一并查出来的【溅射】【雷达子弹】【探测雷达】）
只写前一份 ⇒ 观战**看得出**这些格子、回放**看不出**。

## 修法（本批）

**把回放的棋盘标记收敛到与观战同一份权威数据源**：新增一条**稀疏 + 增量**的
`attacks` 时间线（`{step, p1?: [{x,y,hit?,sunk?}], p2?: [...]}`，只带这一步**新增**的格），
数据源 = `Player.attacks`；前端按侧**累加**，再被 `board_resets` 按侧擦除。

⚠️ **明确不做**的两件事（也是本文件的守卫在钉的）：
1. **不给每一格补一条 `add_game_log(type='attack')`** —— 那会让**游戏内日志面板**
   凭空多出 6 条一行一行的行（改一个既有玩家可见功能来绕开问题）。
   判据：`EXPECTED_ADD_GAME_LOG_SITES`（`tests/test_replay_guards.py`）一个点都不许变。
2. **不在回放里留两份标记来源**（日志一份 + 时间线一份）—— 那只是把教训 #1
   从"观战/回放之间"搬到"回放内部"。判据：`replayComputeFrame` 的标记只由
   `payload.attacks` 产生（源码级），且 `frame.marks` 的写入点**只有一处**。

⚠️ **必须保住**的两条既有语义（本文件各有专门的用例）：
* **步进**：第 k 帧只看得到 `step ≤ k` 的标记（这是本功能的核心）；
* **`board_resets` 仍要能擦掉标记**：重置之前的炮消失、之后的还在（方向不许写反）。

真浏览器 / 真 `game.js` 的**逐格字形**证据在 `tools/dom_replay_frame_check.mjs` 的 I 组
（本文件断言的是后端产出的 payload 形状 + 记录器语义，两侧分工与前几批一致）。
"""
import ast
import io
import os
import uuid

import pytest

import replay
import server
from server import GameRoom, MagicCard, Player, PlayerShip, Position, room_manager

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_JS = os.path.join(ROOT, 'static', 'game.js')
SERVER_PY = os.path.join(ROOT, 'server.py')

# ⚠️ 座位 key 与 `Player.sid` 保持同一个串（人机房 / 自定义房就是同一套）。
P1, P2 = 'bombmark-p1', 'bombmark-p2'
SIDE1, SIDE2 = 'p1', 'p2'          # 回放时间线里的座位代号（不是原始 pid）
RAW1, RAW2 = P1, P2


def _read(path):
    with io.open(path, encoding='utf-8') as fh:
        return fh.read()


# ⚠️ 座位形状的讲究（本批实测踩过）：p2 **至少要有两艘船**，否则"打沉一艘"就
#    `remaining_ships <= 0` ⇒ 多出一条 `game_over` 步、行号与帧号全乱。
#    另外**别把 p2 的船排成一条与轰炸同一行的竖列** —— 那会被一炮全清。
#    下面这套形状：第 1 行三艘（轰炸命中）+ 第 4/5 行各一艘（保证打不完）。
P2_SHAPE_BOMB_ROW = [[(0, 1)], [(2, 1)], [(4, 1)], [(0, 4)], [(3, 5)]]
# 同上，但三艘都在**第 1 列**（给【硫磺火焰】那一列用）。
P2_SHAPE_SULFUR_COL = [[(1, 0)], [(1, 2)], [(1, 4)], [(0, 4)], [(3, 5)]]


def _ships(shape):
    return [PlayerShip(positions=[Position(x, y) for (x, y) in cells], hits=[])
            for cells in shape]


def _room(p2_shape, p1_shape=[[(0, 0)]]):
    room = GameRoom('bombmark-' + uuid.uuid4().hex[:6])
    room.players[P1] = Player(name='甲', ships=_ships(list(p1_shape)), attacks=[],
                              remaining_ships=len(p1_shape), sid=P1)
    room.players[P2] = Player(name='乙', ships=_ships(p2_shape), attacks=[],
                              remaining_ships=len(p2_shape), sid=P2)
    room.state = 'attacking'
    room.current_attacker = P1
    room.current_phase = 'battle'
    room.attack_order = [P1, P2]
    room.attacks_remaining = 6
    room.round = 3
    room.game_logs = []
    room.game_effects = {}
    room.magic_temp_data = {}
    room_manager.rooms[room.id] = room
    return room


@pytest.fixture
def room():
    r = _room(P2_SHAPE_BOMB_ROW)
    yield r
    room_manager.rooms.pop(r.id, None)


def _magic_step(r, card_name):
    """喂一条"使用了【X】"的步骤（形状与 `server.log_magic` 一致）。

    ⚠️ 这里**不**调 `server.log_magic`：那会 `add_game_log` → 真 `emit`，需要请求上下文。
       本文件要钉的是**记录器与打包**那一侧，事件不是它的判据。
       但**用户可见的游戏内日志一行都不加**是本批的硬要求 —— 由
       `test_no_card_adds_a_game_log_row` 用源码级断言单独钉住。
    """
    replay.note(r, {'type': 'magic', 'text': '第3回合 · 甲 使用了【%s】' % card_name,
                    'detail': {'caster': P1, 'card': card_name}})


def _fold(payload, side, k):
    """**前端 `replayComputeFrame` 第 ③ 段的同一套口径**（独立复算，用来做数据判据）：

    ① 把 `attacks` 时间线里 `step ≤ k` 的条目按侧**累加**（同一格**后写的赢**）；
    ② 再丢掉 `step ≤ 该侧最后一次重置` 的那些（`board_resets` 擦除）。

    ⚠️ 这里**不许**读 `steps` 里的 attack 步 —— 那正是本批修掉的那条第二数据源。
    ⚠️ "同一格后写的赢"复刻的是实战前端"逐条覆盖同一个键"：真对局里约 3/10 局会出现
       "某一格先被炮击打沉、又被【轰炸】补一条落空"（服务端那一格本来就有两条）。
    """
    rows = payload.get('attacks') or []
    resets = [int(r['step']) for r in (payload.get('board_resets') or [])
              if r.get('side') == side and int(r['step']) <= k]
    last_reset = max(resets) if resets else -1
    acc = {}                      # (x, y) -> [(step, cell), ...]（按出现顺序）
    for row in rows:
        step = int(row.get('step', -1))
        if step < 0 or step > k:
            continue
        for cell in (row.get(side) or []):
            acc.setdefault((int(cell['x']), int(cell['y'])), []).append((step, cell))
    out = []
    for (x, y), marks in sorted(acc.items()):
        step, cell = marks[-1]            # ★ 后写的赢（与前端同一口径）
        if step <= last_reset:
            continue
        out.append('%d,%d%s' % (x, y, '(沉)' if cell.get('sunk') else ''))
    return out


def _truth(player):
    """`caster.attacks` 的**真值表**：`['x,y', 'x,y(沉)', ...]`（同一格后写的赢）。"""
    latest = {}
    for a in player.attacks:
        latest[(a.x, a.y)] = '(沉)' if getattr(a, 'ship_sunk', False) else ''
    return ['%d,%d%s' % (x, y, mark) for (x, y), mark in sorted(latest.items())]


# ===========================================================================
# ★★ 守卫 1（本批验收核心）：真调两张卡 ⇒ 那一行 / 列的格子在帧里**逐格一致**
# ===========================================================================
@pytest.mark.parametrize('card_name,target,expect_sunk,expect_miss', [
    ('轰炸', {'target_line': {'type': 'row', 'index': 1}},
     [(0, 1), (2, 1), (4, 1)], [(1, 1), (3, 1), (5, 1)]),
    ('硫磺火焰', {'target_cells': [{'x': y, 'y': y} for y in range(6)]},
     None, None),        # 硫磺火焰那一列：船在 x=1 那一列，形状见下
])
def test_bomb_and_sulfur_marks_reach_the_replay_frame(room, card_name, target,
                                                      expect_sunk, expect_miss):
    """★★ 真调 `apply_magic_effect`：那一行 / 列的 6 格必须**逐格**出现在帧里。

    **改前必红**：`attacks` 时间线不存在 ⇒ `_fold` 返回 `[]`（这正是作者看到的
    "没挨过炮的海面"）。改后与 `caster.attacks` 真值表**逐格一致**。
    """
    if card_name == '硫磺火焰':
        # 硫磺火焰那一列：p2 的船在 (1,0) (1,2) (1,4) ⇒ 那一列全部 6 格挨过炮
        room = _room(P2_SHAPE_SULFUR_COL)
        target = {'target_cells': [{'x': 1, 'y': y} for y in range(6)]}
        expect_sunk = [(1, 0), (1, 2), (1, 4)]
        expect_miss = [(1, 1), (1, 3), (1, 5)]

    _magic_step(room, card_name)
    result = server.apply_magic_effect(room, P1, MagicCard(card_name), target)
    assert getattr(result, 'success', True) is not False, result
    # ⚠️ 这两张卡**不写**任何游戏日志 ⇒ 必须由收尾的刷新把这一步记下来
    replay.refresh_ships(room)

    payload = replay.build(room)
    k = len(payload['steps']) - 1
    assert len(payload['attacks']) >= 1, (
        '★ 改前必红：`attacks` 时间线是空的 ⇒ 回放里那一行一个标记都没有（本批修的缺陷）')

    # ① 与**真值表**（`caster.attacks`）逐格一致 —— 一格不多、一格不少
    assert _fold(payload, SIDE1, k) == sorted(_truth(room.players[P1])), (
        '帧标记必须与 `caster.attacks` 真值表逐格相等。\n'
        '  帧：%s\n  真值表：%s' % (_fold(payload, SIDE1, k), sorted(_truth(room.players[P1]))))

    # ② 击沉的那几格带 `sunk`、落空的那几格不带（字形由它决定）
    marks = {}
    for row in payload['attacks']:
        for cell in (row.get(SIDE1) or []):
            marks[(int(cell['x']), int(cell['y']))] = cell
    for (x, y) in expect_sunk:
        assert marks.get((x, y), {}).get('sunk') is True, \
            '(%d,%d) 是被打沉的那一格，帧标记必须带 sunk：%s' % (x, y, marks.get((x, y)))
    for (x, y) in expect_miss:
        assert (x, y) in marks, '(%d,%d) 挨过炮却不在帧标记里' % (x, y)
        assert not marks[(x, y)].get('sunk'), '(%d,%d) 是落空，不许带 sunk' % (x, y)
        assert not marks[(x, y)].get('hit'), '(%d,%d) 是落空，不许带 hit' % (x, y)

    # ③ 只落在**对手**那块棋盘上（自己那块一格都不许有）
    assert _fold(payload, SIDE2, k) == [], '这一炮打在对手棋盘上，自己那块不许有标记'


def test_the_same_cards_write_zero_attack_steps():
    """★ 把"改前的数据判据"钉在源码级：这两张卡**一条 attack 步都不写**。

    判据：`轰炸` / `硫磺火焰` 两个分支的源码段里没有 `add_game_log(..., 'attack', ...)`
    也没有 `log_attack`。它是"为什么必须加时间线"的理由 —— 有人哪天给这两张卡补了
    attack 日志（那会污染游戏内日志面板），这条会红、逼他先来读这段。
    """
    src = _read(SERVER_PY)
    tree = ast.parse(src)
    for card in ('轰炸', '硫磺火焰'):
        branch = _card_branch_source(src, tree, card)
        assert branch, '找不到 %s 的分支（改名/搬家了？）' % card
        assert "'attack'" not in branch.replace('"attack"', "'attack'"), (
            '%s 里出现了 type="attack" 的游戏日志 —— 那会让游戏内日志面板凭空多几行'
            '（本批明确不做这条改法）' % card)
    # 反向校准：普通炮击**确实**写 attack 日志（否则上面那条判据是空转的）
    assert "'attack'" in _func_source(src, tree, 'handle_attack'), \
        'handle_attack 不再写 attack 日志了？那本文件的整条理由都要重写'


def _func_source(src, tree, name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ''
    return ''


def _card_branch_source(src, tree, card_name):
    """`apply_magic_effect` 里 `card.name == '<卡名>'` 那一支的源码段（下一个 `elif` 前）。"""
    body = _func_source(src, tree, 'apply_magic_effect')
    if not body:
        return ''
    marker = "card.name == '%s'" % card_name
    idx = body.find(marker)
    if idx < 0:
        return ''
    nxt = body.find('elif card.name ==', idx + len(marker))
    return body[idx:nxt if nxt > 0 else len(body)]


# ===========================================================================
# ★ 守卫 2（回归腿）：普通炮击的标记**一个字节都没变**
# ===========================================================================
def test_single_shot_marks_are_unchanged(room):
    """★ 单格炮击仍然一格标记、且 hit/sunk 与改动前逐格相同。

    判据含"改前那条路径也会给出同一格"：一炮既有 attack 步、又有 `caster.attacks`，
    所以新旧两条路径在**普通炮击**上必须给出同一个答案（这正是"收敛数据源"的
    前提：收敛**不许**改变已经正确的那一类）。
    """
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 2, 'y': 1})
    payload = replay.build(room)
    k = len(payload['steps']) - 1

    # ① 普通炮击**确实**产出了 attack 步（这是它与那两张卡的区别，别丢掉）
    atk_steps = [s for s in payload['steps'] if s['kind'] == 'attack']
    assert len(atk_steps) == 1, atk_steps
    detail = atk_steps[0]['detail']
    assert (detail['target']['x'], detail['target']['y']) == (2, 1)
    assert detail['hit'] is True and detail['ship_sunk'] is True

    # ② 帧标记与真值表一致（与回放改前逐格相同）
    assert _fold(payload, SIDE1, k) == sorted(_truth(room.players[P1])) == ['2,1(沉)']
    assert _fold(payload, SIDE2, k) == [], 'p1 没打过 p2 那块棋盘，它一格标记都不许有'
    # ③ `attacks` 时间线里那一格也带 sunk（前端据此画 ✕ 而不是 ○）
    cells = [c for row in payload['attacks'] for c in (row.get(SIDE1) or [])]
    assert cells == [{'x': 2, 'y': 1, 'hit': True, 'sunk': True}], cells
    room_manager.rooms.pop(room.id, None)


def test_a_miss_keeps_hit_and_sunk_absent(room):
    """★ 落空那一格**不带** `hit` / `sunk` 两个键（体积与"缺省即未命中"的口径）。

    别为了"字段整齐"补上 `hit: False` —— 时间线是逐格写的，补上会让每一格胖 20 字节左右，
    而且会让"缺省"与"显式假"两种写法同时存在（同一件事两份表达）。
    """
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 5, 'y': 5})
    payload = replay.build(room)
    cells = [c for row in payload['attacks'] for c in (row.get(SIDE1) or [])]
    assert cells == [{'x': 5, 'y': 5}], cells
    room_manager.rooms.pop(room.id, None)


# ===========================================================================
# ★ 守卫 3（步进语义）：第 k 帧只含 `step ≤ k` 的标记
# ===========================================================================
def test_step_semantics_only_marks_at_or_before_k(room):
    """★★ 步进：第 k 帧只看得到 `step ≤ k` 的格（本功能的核心，不许退化成"一次全给"）。"""
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 2, 'y': 1})   # step 0
    _magic_step(room, '轰炸')                                                     # step 1
    server.apply_magic_effect(room, P1, MagicCard('轰炸'),
                              {'target_line': {'type': 'row', 'index': 1}})
    replay.refresh_ships(room)

    payload = replay.build(room)
    assert len(payload['steps']) == 2, payload['steps']
    # 第 0 帧：只有第一炮那一格
    assert _fold(payload, SIDE1, 0) == ['2,1(沉)'], _fold(payload, SIDE1, 0)
    # 第 1 帧：那一行 6 格（含第一炮）全在
    # ⚠️ (2,1) 是**先被打沉、又被轰炸补了一条落空**的那一格（服务端那一格本来就有两条，
    #    见 `_fold` 的说明）⇒ 帧里它按**后写的那条**画（不带"沉"）。这种格子真对局里
    #    约 3/10 局会出现一处，本批实测过（`.tmp/dbg_dupcell.py`）。
    want = sorted(['0,1(沉)', '1,1', '2,1', '3,1', '4,1(沉)', '5,1'])
    assert _fold(payload, SIDE1, 1) == want, _fold(payload, SIDE1, 1)
    # 时间线本身也必须是**两条**（第一炮一步、轰炸一步），不是"开局一条全量"
    assert [r['step'] for r in payload['attacks']] == [0, 1], payload['attacks']
    room_manager.rooms.pop(room.id, None)


# ===========================================================================
# ★ 守卫 4（`board_resets` 语义）：重置之前的标记消失、之后的还在
# ===========================================================================
def test_board_reset_still_erases_the_earlier_marks(room):
    """★★ 重置**之前**的炮必须消失、**之后**的必须还在（上一批刚修过方向，别弄回去）。

    ⚠️ **重置落点用的是 `len(steps)`（= 它之后的那一步）** —— 这是既有的既有语义
       （`replay.note_board_reset`），本批**一个字都没动**：真实卡片那一支里
       `add_game_log` 先长了一步、再调它，落点正好是刚刚那一步；直调时落点是"下一步"。
       本用例要让重置精确落在**第 0 步之后的某一步**，所以走 `replay.note_board_reset`
       的同一条出口（同一个函数、同一个形状），只在**调用时机**上取准 —— 判据本身
       （之前消失 / 之后还在）与落点取法无关。

    构造：step 0 打一炮 → 切条三炮 → 重置（记为 step 1）→ step 2 再打一炮。
    第 0 帧看得到第一炮，第 1 帧起它消失，第 2 帧只剩最后那一格。
    """
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 0})   # step 0
    assert _fold(replay.build(room), SIDE1, 0) == ['0,0']
    # ⚠️ 记的是 **P1**（= 打出去那一侧）：`board_resets[].side` 与 `attacks` 行的键
    #    走的是同一套 `_side_label`，闸门也按同一侧配对 —— 真实卡片（灵气复苏 /
    #    败者食尘）本来就是双方各记一条，所以这里记哪一侧都在口径内。
    replay.note_board_reset(room, P1)          # 记在 `len(steps)` = 1（见上面那段说明）
    assert [r['step'] for r in replay.build(room)['board_resets']] == [1], \
        replay.build(room)['board_resets']
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 2, 'y': 0})   # step 1
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 3, 'y': 0})   # step 2

    payload = replay.build(room)
    assert _fold(payload, SIDE1, 0) == ['0,0'], (
        '重置**之前**那一帧该看得见 step 0 的那一格：%s' % _fold(payload, SIDE1, 0))
    assert _fold(payload, SIDE1, 1) == [], (
        '重置那一帧起、"重置之前"的标记必须已经消失（这一步也打了一炮，它同样在重置点上）：%s'
        % _fold(payload, SIDE1, 1))
    assert _fold(payload, SIDE1, 2) == ['3,0'], (
        '重置**之后**的那一炮必须还在（这是"擦干净之后还继续挨炮"的那一半）：%s'
        % _fold(payload, SIDE1, 2))
    # 反向腿：这一侧被重置**不影响另一侧** —— `attacks` 行里 `p2` 那个键自始至终
    # 一个都不许出现（本局 p2 没打过炮），而 `p1`（= 被重置那一侧）里只剩重置之后的。
    assert all(SIDE2 not in row for row in payload['attacks']), payload['attacks']
    assert _fold(payload, SIDE2, 2) == [], '另一侧一格标记都不许有'
    room_manager.rooms.pop(room.id, None)


def test_only_one_mark_source_in_the_frontend():
    """★★★ 回放里**只有一份**标记来源（教训 #1 不许从观战/回放之间搬进回放内部）。

    判据（源码级，因为"两份来源"的症状是**多画/少画几格**、不会报错）：
      ① `replayComputeFrame` 里标记只由 `payload.attacks` 产生；
      ② 整个函数体里**不许**再出现 `kind === 'attack'` 那种"从日志步反推标记"的痕迹；
      ③ `frame.marks[` 的**写入点全项目只有一处**（`frame.marks = ...` 的初始化不算）。
    """
    src = _read(GAME_JS)
    frame_fn = _js_function_body(src, 'function replayComputeFrame(')
    assert frame_fn, '找不到 replayComputeFrame（改名了？）'

    assert 'payload.attacks' in frame_fn, \
        '标记的数据源必须是 `payload.attacks` 这条时间线'
    assert "kind !== 'attack'" not in frame_fn and 'step.kind' not in frame_fn, (
        '`replayComputeFrame` 里又出现了"从 attack 步反推标记"的写法 —— 那正是本批修掉的'
        '缺陷（只有普通炮击写 attack 步，那五张卡打出的格会整片消失）')

    writes = [ln.strip() for ln in src.split('\n')
              if 'frame.marks[' in ln and '] =' in ln]
    assert len(writes) == 1, (
        '`frame.marks[...] = ...` 的写入点必须**只有一处**（两份来源 = 一定漂移）：%s' % writes)
    # ③ 反向校准：`steps` 仍然被用来判"这一帧到哪了"，别把整段删空
    assert 'steps.length - 1' in frame_fn, '帧解算仍然要靠 steps 的长度定位最后一帧'


def test_cards_do_not_add_a_game_log_row():
    """★★ 本批**不许**给那几张卡补 `type='attack'` 的游戏日志（既有玩家可见功能不改）。

    判据：`add_game_log` 的调用点清单（`tests/test_replay_guards.py`）一个点都不能变，
    而且 `apply_magic_effect` 里那张 5 个点的表**也不许涨** —— 这条是它的本地化版本。
    """
    src = _read(SERVER_PY)
    tree = ast.parse(src)
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    tally = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, 'id', None) != 'add_game_log':
            continue
        cur = parent.get(node)
        while cur is not None and not isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            cur = parent.get(cur)
        name = cur.name if cur is not None else '<module>'
        tally[name] = tally.get(name, 0) + 1
    assert tally.get('apply_magic_effect') == 5, (
        '`apply_magic_effect` 里的 add_game_log 调用点必须是 5（本批一个字都不加）：%s'
        % tally.get('apply_magic_effect'))
    assert sum(tally.values()) == 38, 'add_game_log 调用点总数必须仍是 38：%s' % sum(tally.values())


# ===========================================================================
# ★ 守卫 5：记录器侧 —— 时间线是**稀疏 + 增量**，且"某格不再算打过"不在这里记账
# ===========================================================================
def test_the_attacks_timeline_is_sparse_and_incremental(room):
    """★★ 只记**这一步新增的格**（不是"整份列表再记一次"）。"""
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 1})
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 1, 'y': 1})
    payload = replay.build(room)
    assert [r['step'] for r in payload['attacks']] == [0, 1], payload['attacks']
    assert len(payload['attacks'][0][SIDE1]) == 1, payload['attacks'][0]
    assert len(payload['attacks'][1][SIDE1]) == 1, (
        '第 2 步只该带**新打的那一格**，不是"两格再来一份"：%s' % payload['attacks'][1])
    # 两条加起来 == 真值表的格集（不多不少）
    assert _fold(payload, SIDE1, 1) == sorted(_truth(room.players[P1]))
    room_manager.rooms.pop(room.id, None)


def test_removing_marks_is_the_board_reset_timeline_s_job(room):
    """★★ "某格不再算打过"（疗愈复活 / 换位共用的 `_clear_attacks_on_cells`）
    **不写进 `attacks` 时间线**，而是由同一个失效点上的 `board_resets` 擦掉。

    判据：清掉 `Player.attacks` 之后时间线里**没有任何"删除行"**（增量只记新增），
    但配上 `note_board_reset` 之后帧里那些格就消失了 —— 一条时间线只做一件事。
    """
    # `note_board_reset` 用的是**调用那一刻**的 `len(steps)` ⇒ 它必须在"要在它之后
    # 出现的那一步"之前调用（真实卡片里它紧跟在 `add_game_log` 后面）。这里先打完两炮、
    # 再记重置（记在 step 2），随后再打的那一炮落在 step 2 之后。
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 1, 'y': 0})   # step 1
    room.players[P1].attacks = []
    replay.note_board_reset(room, P1)               # 记在 step 2
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 0})   # step 1
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 4, 'y': 0})   # step 2

    after = replay.build(room)
    rows = after['attacks']
    assert [r['step'] for r in rows] == [0, 1, 2], rows
    for row in rows:
        assert all(0 <= int(c['x']) <= 5 for c in (row.get(SIDE1) or [])), \
            '时间线里不许有"删除行"（删除是 board_resets 的活）'
    assert _fold(after, SIDE1, 1) == [], (
        '换新之后那两格必须已经不在了：%s' % _fold(after, SIDE1, 1))
    assert _fold(after, SIDE1, 3) == ['4,0'], (
        '重置点之后打的那一格必须还在：%s' % _fold(after, SIDE1, 3))
    assert after['board_resets'], '擦除必须由 board_resets 这条时间线负责'
    room_manager.rooms.pop(room.id, None)


def test_offboard_coordinates_are_dropped(room):
    """★ 出界坐标一律丢掉（前端也丢）：`探测雷达` 的 `target_area` 由前端自由传入，
    服务端那一支没有范围校验 —— 照原样写进时间线就是画不出来的键（白占体积）。"""
    _magic_step(room, '轰炸')               # step 0：时间线要有"当前这一步"才记
    _magic_step(room, '硫磺火焰')           # step 1
    room.players[P1].attacks.append(Position(x=9, y=-1, hit=True))
    room.players[P1].attacks.append(Position(x=2, y=3, hit=False))
    replay.refresh_ships(room)
    payload = replay.build(room)
    cells = [c for row in payload['attacks'] for c in (row.get(SIDE1) or [])]
    assert cells == [{'x': 2, 'y': 3}], cells
    room_manager.rooms.pop(room.id, None)


def test_same_step_rows_are_merged_for_both_timelines(room):
    """★ 同一步只留一行：`ships` **和** `attacks` 两条时间线都要合并。

    它们都是"同一帧的增量说法"，谁漏了谁就会在时间线里留下两条 `step=k` 的行
    （任何按 step 去重的消费者都会算错）。
    """
    _magic_step(room, '轰炸')                       # step 0
    server.apply_magic_effect(room, P1, MagicCard('轰炸'),
                              {'target_line': {'type': 'row', 'index': 1}})
    replay.refresh_ships(room)
    replay.refresh_ships(room)                      # 再来一次（幂等，不许长出第二行）
    payload = replay.build(room)
    for key in ('ships', 'attacks'):
        steps = [r['step'] for r in payload[key]]
        assert len(steps) == len(set(steps)), '%s 时间线里有重复的同 step 行：%s' % (key, steps)
    room_manager.rooms.pop(room.id, None)


# ===========================================================================
# ★ 守卫 6：前端源码级的"第二份实现"扫描
# ===========================================================================
def _js_function_body(src, header):
    """从 `header` 起按花括号配平取出函数体（与 `tests/test_replay_frontend.py` 同款）。"""
    start = src.index(header)
    i = src.index('{', start)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == '{':
            depth += 1
        elif src[j] == '}':
            depth -= 1
            if depth == 0:
                return src[start:j + 1]
    raise AssertionError('花括号不配平：%s' % header)


def test_payload_field_list_matches_the_backend():
    """★★ 前端认识的 `attacks` 字段必须**真的**在后端 `build()` 里。

    这条防的是"前端加了一段读 `payload.attacks`、后端忘了产出它"（那就永远空）——
    表现是"一片海面"、零报错、零异常，正是本批这个缺陷的形状。
    """
    payload = {}
    room = _room([[(0, 1)]])
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 1})
    payload = replay.build(room)
    assert 'attacks' in payload, 'replay.build() 没有产出 attacks 时间线'
    assert isinstance(payload['attacks'], list) and payload['attacks']
    first = payload['attacks'][0]
    assert set(first) <= {'step', SIDE1, SIDE2}, first
    cell = (first.get(SIDE1) or [])[0]
    assert set(cell) <= {'x', 'y', 'hit', 'sunk'}, cell
    room_manager.rooms.pop(room.id, None)


def test_the_timeline_key_is_the_shooters_side_label(room):
    """★★★ 时间线的键 = **打出这一炮那个座位**的代号，而且必须**就是**
    `replay._side_label` 算出来的那一个（不许在别处再算一套）。

    为什么单列一条：这份数据的键会决定"这一格画在哪块棋盘上"。同一份数据的两处取键
    一旦漂移，症状是"标记画到对调的那块棋盘上"—— 不抛异常、不报错
    （第 6 批观战批的原病根；CLAUDE.md 教训 #20：判据的输入必须来自同一套 id 空间）。

    ⚠️ 顺带把"键是谁"这件事**写进断言**：前端 `renderReplayBoards` 让
    `#replay-board-1`（第一位玩家的棋盘）画 `frame.marks[座位 1]`，所以键 = 座位。
    """
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 0, 'y': 0})
    payload = replay.build(room)
    row = payload['attacks'][0]
    assert list(row) == ['step', replay._side_label(room, P1)], (
        '行的键必须正好是 `_side_label(room, 打出去那个座位)`：%s' % row)
    room_manager.rooms.pop(room.id, None)


def test_a_cell_written_twice_keeps_the_last_write(room):
    """★★ 同一格被写两次（先沉后落空）时，时间线与 `caster.attacks` 都取**后写的那条**。

    真对局里约 3/10 局会出现一处（`tools/headless_game.py` 10 局实测 3 局，见文档 §H）：
    普通炮击打沉某格之后，【轰炸】/【硫磺火焰】会给同一格补一条 `hit=False` 的落空
    （卡里那句过滤只按"这次真的摘掉了哪些船"，已经沉过的船不在候选表里）。
    实战前端逐条覆盖同一个键 ⇒ 玩家看到的是后写的那条 ⇒ 回放必须一致。
    """
    server.handle_attack({'room_id': room.id, 'player_id': P1, 'x': 2, 'y': 1})   # 击沉
    _magic_step(room, '轰炸')                                                     # step 1
    server.apply_magic_effect(room, P1, MagicCard('轰炸'),
                              {'target_line': {'type': 'row', 'index': 1}})
    replay.refresh_ships(room)
    truth = _truth(room.players[P1])
    assert '2,1(沉)' not in truth, '这一格最终是落空（后写的那条）:%s' % truth
    payload = replay.build(room)
    k = len(payload['steps']) - 1
    assert _fold(payload, SIDE1, k) == sorted(truth), (
        '帧必须与"后写的那条"逐格一致：\n  帧：%s\n  真值表：%s'
        % (_fold(payload, SIDE1, k), sorted(truth)))
    # 时间线里那一格必须有**两条**（step 0 的沉 + step 1 的落空），前端后写的赢
    marks = [c for row in payload['attacks'] for c in (row.get(SIDE1) or [])
             if (int(c['x']), int(c['y'])) == (2, 1)]
    assert len(marks) == 2 and marks[0].get('sunk') is True and not marks[1].get('sunk'), marks
    room_manager.rooms.pop(room.id, None)
