# -*- coding: utf-8 -*-
"""区域选择魔法卡：**双方连锁预览**的守卫（2026-09-27 批）。

规格：`docs/superpowers/specs/2026-09-27-area-preview-design.md`（作者已批准，§4 采方案 A）。

## 这一批做了什么

连锁结算期间，双方都要能看到**每个已确认的连锁节点作用在哪几格、在哪块棋盘上、
是哪张卡**，而且只含公开信息。落地方式：

1. `spectate.AREA_TARGET_BOARDS` —— 「卡名 → 棋盘归属」的**服务端权威表**
   （`self` / `opponent` / `choice`），`static/game.js` 的 `MAGIC_TARGET_DESCRIPTORS`
   是它的**只读镜像**（本文件第 1 节把它钉死）；
2. `server._sanitize_magic_targets(targets, card_name)` 在归一化时**校验/写回** `board`
   —— 缺归属或非法归属一律**拒绝**，绝不兜底（教训 #2）；
3. `spectate.sanitize_preview_item` 把链项**白名单重建**成
   `{card, seat, negated, preview}`；
4. `server._spectate_chain_payload` 是**唯一**的连锁公开 payload 构造点，
   对局广播 / 重连快照 / 观战快照三处共用。

## 本文件的守卫

| 用例 | 守的是什么 |
| --- | --- |
| `test_frontend_mirror_matches_server` | 前端那张表与服务端镜像表**逐卡一致**（教训 #1） |
| `test_frontend_call_sites_exist_for_every_mirror_card` | 每张登记卡在 `game.js` 里真的有 `confirmMagicTarget` 调用点 |
| `test_all_region_cards_are_covered` | 服务端**实际读**区域/行列/连续格的卡，一张不漏地有归属登记 |
| `test_cards_that_do_not_use_the_chain_target_channel_are_excluded` | 选船类（神之宣告 / 仁王之盾）**明确不纳入**及理由 |
| `test_normalization_rejects_missing_or_invalid_board` | 非法 / 缺失 `board` **被拒**且给出明确报错 |
| `test_normalization_writes_the_authoritative_board` | 固定归属由**服务端写回**，客户端的值改变不了它 |
| `test_preview_cells_for_every_region_card` | 全部公开区域卡的实际选区 → 格子集合与 `board` |
| `test_shenwei_choice_maps_to_both_boards` | 神威！选己方 / 对方各画在哪块棋盘 |
| `test_multi_node_chain_keeps_every_area` | 同一连锁里多个待结算区域**并存**、各带自己的归属与卡名 |
| `test_cleanup_on_resolve_and_on_negation` | 结算 / 被康 → 预览随之消失 |
| `test_snapshot_uses_the_same_contract_as_live_stream` | 重连快照与实时流**同一构造函数、同一字段集合** |
| `test_preview_never_leaks_private_fields` | 隐藏字段不泄漏（逐键白名单 + 私密值不出现） |
| `test_preview_is_idempotent` | 净化**幂等**（观众那一路要过两次，座位不许退化成 unknown） |
| `test_no_unconfirmed_selection_is_ever_broadcast` | 选区**未确认不广播**（预览只从 `room.chain` 派生） |
| `test_frontend_renders_before_response_prompt` | 前端预览**先于**响应窗口就绪，且清理点齐备 |
"""
import io
import json
import os
import re

import pytest

import server
import spectate
from server import ChainItem, GameRoom, MagicCard, Player, PlayerShip, Position
from spectate import spectate_room_id

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_JS = os.path.join(ROOT, 'static', 'game.js')
SERVER_PY = os.path.join(ROOT, 'server.py')

# 座位 key：用**匹配房的约定**（key = socket sid）—— 最容易出问题的那一套，
# 而且 `seat_label` 的结果与自定义房（user_id）无关，两种约定下都是 p1/p2。
SID_A, SID_B = 'areaprev-sid-a', 'areaprev-sid-b'

# 前端 `MAGIC_TARGET_DESCRIPTORS` 的条目：`'卡名': { ... 一行 ... },`
_JS_ENTRY = re.compile(
    r"""^\s*(?:'([^']+)'|"([^"]+)")\s*:\s*\{(.*?)\}\s*,?\s*(?://.*)?$""", re.M)
_JS_BOARD = re.compile(r"""board\s*:\s*'([^']+)'""")
_JS_TYPE = re.compile(r"""type\s*:\s*'([^']+)'""")

# 服务端 `apply_magic_effect` 里"哪些卡在读哪种目标形状"的**源码扫描**结果，
# 由 `test_all_region_cards_are_covered` 现算（不硬编码结论）。
#
# ⚠️ 这张表必须**穷举**全部目标形状 key：漏一个就会把那张卡判成"没读目标"
#    （本文件第一版就漏了 `selected_cells`，于是「神之宣告」被判成不存在 ——
#     那种假绿正是"守卫没在守"的典型）。
_SERVER_SHAPE_KEYS = {
    'target_area': 'area',
    'target_line': 'line',
    'target_cells': 'cells',
    'selected_cells': 'cells',
    # 单格：克苏鲁之眼走 `_pick_cell_from_target`
    '_pick_cell_from_target': 'single',
    # 多选自己的船（仁王之盾那类）——**不是**区域，用来把这类卡认出来而非当成区域
    'ship_indices': 'ships',
}
# 这些形状算"区域类"（要登记归属、要能画预览）
_REGION_SHAPES = ('area', 'line', 'cells')


# 前端描述符的 `type` ↔ 服务端预览的 `shape`。
# 只有 `continuous`（自由连选，硫磺火焰）两边叫法不同：前端叫"连续选择模式"，
# 服务端归一化之后是"一组格子"（`cells`）。`shenwei` 是前端的两段式入口，
# 提交上去就是 `target_area` ⇒ 预览层看到的是 `area`。
# `own_ships`（神之宣告）**没有** shape：它是"选自己的船"，不是区域，
# 按设计不画（理由见 `_NOT_PREVIEWED_BY_DESIGN`）—— 用 None 显式表态，
# 不允许"忘了映射"与"故意不映射"长得一样。
_JS_TYPE_TO_SHAPE = {
    'area': 'area',
    'line': 'line',
    'continuous': 'cells',
    'single': None,        # 克苏鲁之眼选择隐藏船位，结算前不得公开
    'shenwei': 'area',
    'own_ships': None,     # 选船类：不是区域，不画（也不登记归属）
}

# 前端有选择器、但**明确不纳入**区域预览的卡（理由见
# `test_cards_that_do_not_use_the_chain_target_channel_are_excluded`）。
_NOT_PREVIEWED_BY_DESIGN = ('神之宣告', '克苏鲁之眼')


def _read(path):
    with io.open(path, encoding='utf-8') as f:
        return f.read()


def _js_descriptors():
    """解析 `static/game.js` 的 `MAGIC_TARGET_DESCRIPTORS`。

    ⚠️ 不解析"函数体里的 map"—— 那张表是模块级 const（见它上面的注释），
       解析器只认 `const NAME = { ... };`，格式变了就直接断言失败，
       而不是静默返回空表（那样就没在测任何东西了）。
    """
    src = _read(GAME_JS)
    m = re.search(r'const\s+MAGIC_TARGET_DESCRIPTORS\s*=\s*\{(.*?)\n\};', src, re.S)
    assert m, 'game.js 里找不到模块级的 `const MAGIC_TARGET_DESCRIPTORS = { ... };`'
    out = {}
    for line in m.group(1).splitlines():
        em = _JS_ENTRY.match(line)
        if not em:
            continue
        name = em.group(1) or em.group(2)
        body = em.group(3)
        tm = _JS_TYPE.search(body)
        out[name] = {
            'type': tm.group(1) if tm else None,
            'board': (_JS_BOARD.search(body).group(1)
                      if _JS_BOARD.search(body) else None),
        }
    assert out, 'game.js 的 MAGIC_TARGET_DESCRIPTORS 解析为空（格式变了？）'
    return out


def _server_region_branches():
    """扫描 `apply_magic_effect`：`{卡名: [读到的目标形状 key, ...]}`。

    这是"**服务端**哪些卡真的在用区域/行列/连续格/单格目标通道"的机器判据
    —— 不靠人肉记，也不靠硬编码轰炸与冻结（那正是本批要避免的做法）。

    ⚠️ 两个坑都实测踩过：
      ① 第一张卡的分支是 `if card.name == 'X':`，其余是 `elif` —— 只扫 elif
         会把第一张卡整个漏掉；
      ② **必须把扫描窗口限死在 `apply_magic_effect` 里面** —— 别处（如
         `confirm_magic_target` 的 `shield_choice`）也有关键字，不限窗口会
         把它们算到最后一个卡牌分支头上（实测：仁王之盾的 `ship_indices`
         被算成了「神之宣告」的）。
    """
    src = _read(SERVER_PY)
    start = src.index('def apply_magic_effect(')
    nxt = src.find('\ndef ', start + 10)
    assert nxt > start, '找不到 apply_magic_effect 的结尾'
    src = src[start:nxt]
    marks = [(mm.start(), mm.group(1))
             for mm in re.finditer(r"(?:el)?if card\.name == '([^']+)':", src)]
    assert len(marks) > 20, '没扫到卡牌分支（正则过期了？扫到 %d 个）' % len(marks)
    out = {}
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(src)
        blk = src[pos:end]
        found = sorted(k for k in _SERVER_SHAPE_KEYS if k in blk)
        if found:
            out[name] = found
    return out


def _frontend_confirm_call_sites():
    """`game.js` 里全部 `confirmMagicTarget(` 的**行号 + 行内容**（真选择器调用点）。"""
    src = _read(GAME_JS)
    sites = []
    for i, line in enumerate(src.splitlines(), 1):
        # 跳过函数定义本身
        if 'function confirmMagicTarget' in line:
            continue
        if 'confirmMagicTarget(' in line:
            sites.append((i, line.strip()))
    return sites


def _make_room():
    room = GameRoom('areaprev-' + os.urandom(4).hex())
    for sid, name in ((SID_A, '甲'), (SID_B, '乙')):
        room.players[sid] = Player(name=name, ships=[], attacks=[],
                                   remaining_ships=6, sid=sid)
    room.state = 'attacking'
    room.current_phase = 'battle'
    room.current_attacker = SID_A
    room.attack_order = [SID_A, SID_B]
    room.attacks_remaining = 5
    room.game_logs = []
    server.room_manager.rooms[room.id] = room
    return room


@pytest.fixture
def room():
    r = _make_room()
    yield r
    server.room_manager.rooms.pop(r.id, None)


def _make_and_register():
    """临时房间（用完请自己 `server.room_manager.rooms.pop(...)`）。

    与 `room` fixture 同一份实现 —— 需要在一个用例里造**多个**房间时用它。
    """
    return _make_room()


def _arm(room, card_name, targets, player_id=SID_A):
    """走**真入口**把一张卡打进连锁：归一化 → 压栈 → 广播，返回 (payload, 错误)。

    ⚠️ 不往 `magic_hand` 里塞卡：卡名合法性由卡表校验，而这里要测的是
       "已确认目标 → 公开预览"这一段，手牌与它无关（放进去只会引入无关失败）。
    """
    targets, err = server._sanitize_magic_targets(dict(targets), card_name)
    if err:
        return None, err
    card = MagicCard(name=card_name, speed=1, type='普通', description='')
    room.chain.append(ChainItem(player_id, card, targets, 0.0))
    return server._spectate_chain_payload(room), None


# ===========================================================================
# 1. 镜像表同步（教训 #1：同一个判断两份实现必然漂移）
# ===========================================================================
def test_frontend_mirror_matches_server():
    """★ `static/game.js` 的 `MAGIC_TARGET_DESCRIPTORS` ↔ `spectate.AREA_TARGET_BOARDS`。

    只比"卡名 → 作用棋盘"这一列（形状在前端是渲染用的，服务端不读）。
    前端缺登记 ⇒ 玩家点不了 / 服务端拒绝；服务端缺登记 ⇒ 预览画不出来。
    两种情况都**不报错**，所以必须用这条用例钉住（先例 `test_ship_pick_mirror.py`）。

    ⚠️ `神之宣告` 在前端有选择器、但**故意不登记**（它把 `selected_cells` 当
       "要牺牲哪两艘自己的船"，位置是私密的，画出来是泄漏 —— 见下面那条用例）。
       所以比对时先把"按设计排除"的卡剔掉，且**断言剔除名单只有它**，
       防止有人顺手往排除名单里塞新卡。
    """
    js = {name: d['board'] for name, d in _js_descriptors().items()}
    js_only = {k: v for k, v in js.items() if k not in _NOT_PREVIEWED_BY_DESIGN}
    assert set(js) - set(js_only) == set(_NOT_PREVIEWED_BY_DESIGN)
    py = dict(spectate.AREA_TARGET_BOARDS)
    # `None`（前端没写 board）== `'choice'`（服务端记法：玩家当场二选一）
    normalised = {k: (v if v is not None else 'choice') for k, v in js_only.items()}
    assert normalised == py, (
        '前端 MAGIC_TARGET_DESCRIPTORS 与服务端 AREA_TARGET_BOARDS 不一致\n'
        '  只在服务端: %s\n  只在前端:   %s\n  值不同:     %s' % (
            sorted(set(py) - set(normalised)), sorted(set(normalised) - set(py)),
            {k: (normalised[k], py[k]) for k in set(py) & set(normalised)
             if normalised[k] != py[k]}))


def test_frontend_call_sites_exist_for_every_mirror_card():
    """镜像表里的每张卡在 `game.js` 里都要**真的有**选择器调用点。

    防的是"表里登记了、实际没有选择器"——那种卡点了没反应、且不报错（教训 #32）。
    神威！的两次提交走 `Object.assign({board:...}, areaObj)` 包一层，
    所以对它在**整个文件**里查（卡名 + 两个归属字符串）。
    """
    sites = _frontend_confirm_call_sites()
    assert len(sites) >= 6, 'confirmMagicTarget 的调用点少得可疑：%r' % (sites,)
    whole = _read(GAME_JS)
    missing = []
    for name in spectate.AREA_TARGET_BOARDS:
        if any(name in line for _, line in sites):
            continue
        # 神威！：卡名只出现在它自己的两段式选择器里，两个归属都提交过即可
        if name == '神威！':
            ok = ("board: 'self'" in whole and "board: 'opponent'" in whole)
        else:
            ok = sites and name in whole
        if not ok:
            missing.append(name)
    assert not missing, '这些卡登记在镜像表里，却找不到选择器调用点：%s' % missing


def test_every_frontend_selector_card_is_accounted_for():
    """前端那张表里的卡**每一张都要有交代**：要么进镜像表，要么在排除名单里。

    防"新加一张选择器卡、忘了登记归属"（教训 #9：改共用表先 grep 全部调用点、
    按 kind 逐个表态）。
    """
    js = _js_descriptors()
    accounted = set(spectate.AREA_TARGET_BOARDS) | set(_NOT_PREVIEWED_BY_DESIGN)
    unaccounted = sorted(set(js) - accounted)
    assert not unaccounted, (
        '这些卡在前端有目标选择器，却既没登记归属也没说明为什么排除：%s' % unaccounted)


# ===========================================================================
# 2. 完整覆盖：真实选择器 ↔ 服务端校验，两边交叉验证
# ===========================================================================
def test_all_region_cards_are_covered():
    """★ 服务端**实际**读区域/行列/连续格/单格的卡，一张不漏地有归属登记。

    判据来自源码扫描（`_server_region_branches`），不硬编码轰炸与冻结 ——
    新加一张区域卡而忘了登记归属时，这条会红。
    """
    branches = _server_region_branches()
    # 8 张卡真的在读目标（实测：神威！/冻结/轰炸/硫磺火焰/探测雷达/克苏鲁之眼/
    # 仁王之盾/神之宣告）—— 少于这个数就是扫描器瞎了，那比没有测试更坏。
    assert len(branches) >= 8, '源码扫描只认出了 %d 张卡：%r' % (len(branches), branches)
    all_cards = {name: keys for name, keys in branches.items()
                 if any(_SERVER_SHAPE_KEYS[k] in _REGION_SHAPES for k in keys)}
    assert all_cards, '源码扫描没扫到任何区域卡分支（正则过期了？）'
    # 「神之宣告」读的是 `selected_cells`（两张要牺牲的自己的船），形状上确实是
    # "一组格子"，但**按设计不登记**（位置私密，见下面那条用例）——
    # 所以"漏登记"的判据要把它排除，且这条排除必须**白纸黑字**。
    region_cards = {k: v for k, v in all_cards.items()
                    if k not in _NOT_PREVIEWED_BY_DESIGN}
    unregistered = sorted(set(region_cards) - set(spectate.AREA_TARGET_BOARDS))
    assert not unregistered, (
        '这些卡真的在读区域/行列/连续格目标，却没登记棋盘归属（预览会画不出来）：%s\n'
        '  扫到的形状：%r' % (unregistered, {k: region_cards[k] for k in unregistered}))
    # 排除名单里的卡确实是在读区域类形状的（防"把不相干的卡塞进排除名单逃过检查"）
    for name in _NOT_PREVIEWED_BY_DESIGN:
        if name in all_cards:
            assert any(_SERVER_SHAPE_KEYS[k] in _REGION_SHAPES for k in all_cards[name]), \
                '%s 不在读区域形状，不该出现在排除名单里' % name

    # 反向：登记了就必须真的在用那条通道（防"登记了一张不相干的卡"）
    not_region = sorted(set(spectate.AREA_TARGET_BOARDS) - set(branches))
    assert not not_region, '这些卡登记了归属，但服务端根本没读目标：%s' % not_region


def test_cards_that_do_not_use_the_chain_target_channel_are_excluded():
    """★ 私密目标卡不公开预览，理由必须明确。

    实测（源码扫描，不是推测）：

    * `神之宣告` —— 前端 `own_ships` 选两艘自己的船，提交 `selected_cells`，
      服务端分支读的也是 `selected_cells`（`server.py` 的
      `elif card.name == '神之宣告':` 那一段），**确实走 `_sanitize_magic_targets`**。
      但这几个格子是"我马上要牺牲哪两艘" —— **位置本身是私密的**：
      船位只有在挨过炮或自己揭示之后才是公开的。把它登记进归属表，
      预览就会把这两艘船的坐标直接画到对方棋盘上 = **白送两个船位**。
      所以：走同一通道，但**按设计不登记** ⇒ 预览为 `None`（不画）。
    * `克苏鲁之眼` —— 虽然走区域目标通道，但选择的是自己隐藏的船位；
      结算前公开会直接泄漏位置，因此不登记归属、不画预览。
    * `仁王之盾` —— 走的是 `select_magic_target` + `confirm_magic_target`
      的 `ship_indices` 临时通道（`temp_data_id == 'shield_choice'`），
      **根本不经过 `room.chain`**，预览层唯一的数据源拿不到它。同理不登记。
    """
    branches = _server_region_branches()
    # 神之宣告确实读 selected_cells（与前端的 own_ships 是同一批格子）
    assert '神之宣告' in branches and 'selected_cells' in branches['神之宣告'], branches.get('神之宣告')
    assert '神之宣告' not in spectate.AREA_TARGET_BOARDS, (
        '神之宣告不许登记归属 —— 那两艘船的坐标是私密的，画出来就是白送船位')
    assert '克苏鲁之眼' not in spectate.AREA_TARGET_BOARDS
    assert '仁王之盾' not in spectate.AREA_TARGET_BOARDS
    # 仁王之盾确实走的是另一条通道（源码级：它在 confirm_magic_target 的
    # shield_choice 分支里读 ship_indices，不在 room.chain 上）
    src = _read(SERVER_PY)
    assert "'target_data': {'ship_indices': indices[:3]}" in src, \
        '仁王之盾的提交点变了 —— 请重新确认它是否已改走连锁目标通道'
    shield = src.index("temp_data_id == 'shield_choice'")
    assert "target_data.get('ship_indices')" in src[shield:shield + 400], \
        '仁王之盾的读取点变了（不再走 ship_indices 临时通道）'
    # 不登记的后果必须是"不画"，而不是"用默认值画到对方棋盘上"
    r = _make_and_register()
    try:
        payload, err = _arm(r, '神之宣告',
                            {'selected_cells': [{'x': 5, 'y': 5}, {'x': 4, 'y': 4}]})
        assert err is None
        assert payload['chain'][0]['preview'] is None, \
            '神之宣告的牺牲目标被画成预览了 —— 那是私密的船位，会泄漏给对方'
    finally:
        server.room_manager.rooms.pop(r.id, None)

    r = _make_and_register()
    try:
        payload, err = _arm(r, '克苏鲁之眼',
                            {'target_area': {'x1': 2, 'y1': 2, 'x2': 2, 'y2': 2}})
        assert err is None
        assert payload['chain'][0]['preview'] is None, \
            '克苏鲁之眼的隐藏船位不能在连锁结算前公开'
    finally:
        server.room_manager.rooms.pop(r.id, None)


def test_region_preview_shapes_are_the_documented_ones():
    """每张区域卡：前端**选择器形状**与服务端**预览形状**都要与表一致。

    ⚠️ 两者**不是同一个名字空间**（前端 `single`/`shenwei`/`continuous` 是入口形态，
       服务端 `shape` 是归一化后的形状），所以有一张显式的映射表 `_JS_TYPE_TO_SHAPE`；
       它同时也是"前端那一侧认得出的形状都在服务端有人处理"的判据。
    """
    js = _js_descriptors()
    expect = {           # 卡名 → (前端 type, 服务端 shape)
        '冻结': ('area', 'area'),
        '探测雷达': ('area', 'area'),
        '轰炸': ('line', 'line'),
        '硫磺火焰': ('continuous', 'cells'),
        '神威！': ('shenwei', 'area'),
    }
    for name, (js_type, shape) in expect.items():
        got = js.get(name, {}).get('type')
        assert got == js_type, '%s 的前端描述符形状应是 %r，实际 %r' % (name, js_type, got)
        assert _JS_TYPE_TO_SHAPE.get(js_type) == shape, (
            '前端形状 %r 应映射到预览 shape %r，实际 %r' % (
                js_type, shape, _JS_TYPE_TO_SHAPE.get(js_type)))
    # 反向：前端表里出现的选择器形状都要**显式**表态
    #（新加一种入口却不表态 = 静默不画，正是教训 #13 那个形状）
    unmapped = sorted({v.get('type') for v in js.values()} - set(_JS_TYPE_TO_SHAPE))
    assert not unmapped, '这些前端选择器形状没有映射到预览 shape：%s' % unmapped
    # 映射到 `None` 的（选船类）必须正好是排除名单里的那些 ——
    # 否则就是"故意不映射"与"忘了映射"混在了一起。
    none_typed = {name for name, v in js.items()
                  if _JS_TYPE_TO_SHAPE.get(v.get('type')) is None}
    assert none_typed == set(_NOT_PREVIEWED_BY_DESIGN), (
        '映射为 None 的卡应是 %s，实际 %s' % (
            sorted(_NOT_PREVIEWED_BY_DESIGN), sorted(none_typed)))


# ===========================================================================
# 3. 非法的目标 / 归属一律拒绝（教训 #2：绝不兜底）
# ===========================================================================
def test_fixed_board_card_rejects_a_contradicting_client_board():
    """固定归属的卡：客户端提交的 `board` 与卡不符 ⇒ **拒绝**（并写明理由）。

    静默采用任意一侧都会让"预览画在哪块棋盘"这个判据失去唯一来源（教训 #1/#2）。
    """
    for card_name, board in (('冻结', 'self'), ('探测雷达', 'self'), ('轰炸', 'self'),
                             ('硫磺火焰', 'self')):
        targets = {'target_area': {'x1': 0, 'y1': 0, 'x2': 1, 'y2': 1}, 'board': board}
        _, err = server._sanitize_magic_targets(dict(targets), card_name)
        assert err, '%s 提交 board=%r 竟然被放行（静默采用一侧 = 预览可能画反）' % (
            card_name, board)
        assert card_name in err and ('己方' in err or '对方' in err), err


@pytest.mark.parametrize('board', ['', 'both', 'enemy', 'SELF', 1, None, ['self']])
def test_shenwei_rejects_missing_or_invalid_board(board):
    """★ 神威！：归属由玩家当场二选一 —— 缺失或非法**一律拒绝**，绝不默认成对方。

    这正是 CLAUDE.md 教训 #2 的形状（旧的 `target_data.get('board', 'opponent')`
    就是"漏传即静默按对方处理"）。
    """
    targets = {'target_area': {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}}
    if board is not None:
        targets['board'] = board
    _, err = server._sanitize_magic_targets(dict(targets), '神威！')
    assert err, '神威！ board=%r 竟然被放行' % (board,)
    assert '棋盘' in err


def test_shenwei_accepts_both_valid_boards():
    for board in spectate.BOARD_SIDES:
        targets = {'target_area': {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}, 'board': board}
        out, err = server._sanitize_magic_targets(dict(targets), '神威！')
        assert err is None and out['board'] == board


@pytest.mark.parametrize('targets,expect', [
    ({'target_area': {'x1': 0, 'y1': 0, 'x2': 6, 'y2': 2}, 'board': 'opponent'},
     '超出棋盘范围'),
    ({'target_area': {'x1': 0, 'y1': 0, 'x2': 2}, 'board': 'opponent'}, '参数缺失'),
    ({'target_area': {'x1': 'a', 'y1': 0, 'x2': 2, 'y2': 2}, 'board': 'opponent'},
     '坐标非法'),
    ({'target_line': {'type': 'diag', 'index': 1}}, '行列参数非法'),
    ({'target_line': {'type': 'row', 'index': 9}}, '超出棋盘范围'),
    ({'target_cells': [{'x': 7, 'y': 0}]}, '超出棋盘范围'),
])
def test_existing_coordinate_validation_is_unchanged(targets, expect):
    """坐标校验的既有口径不许因为本批改动而松动。"""
    _, err = server._sanitize_magic_targets(dict(targets), '冻结')
    assert err and expect in err, '期望含 %r 的报错，实际 %r' % (expect, err)


def test_normalization_writes_the_authoritative_board():
    """固定归属由**服务端写回** targets —— 预览只认这里写下的值。"""
    out, err = server._sanitize_magic_targets(
        {'target_area': {'x1': 3, 'y1': 3, 'x2': 5, 'y2': 5}}, '冻结')
    assert err is None and out['board'] == 'opponent'


def test_unregistered_card_is_left_untouched():
    """没登记归属的卡：既有行为完全不变（不因为本批而对它做新校验）。"""
    targets = {'target_area': {'x1': 0, 'y1': 0, 'x2': 1, 'y2': 1}}
    out, err = server._sanitize_magic_targets(dict(targets), '无中生有')
    assert err is None and 'board' not in out


# ===========================================================================
# 4. 覆盖表逐张：真实选区 → 格子集合与棋盘归属
# ===========================================================================
# ⚠️ 这里的 cells 是**写死的期望值**（不是用被测函数算出来的）：用被测函数的输出
#    自比等于没有断言。`board` 与形状都属于对外契约，改契约就该改这里。
_CASES = [
    ('冻结', {'target_area': {'x1': 1, 'y1': 2, 'x2': 3, 'y2': 4}},
     'opponent', 'area', 9, [(1, 2), (3, 2), (1, 4), (3, 4)]),
    ('探测雷达', {'target_area': {'x1': 4, 'y1': 0, 'x2': 5, 'y2': 1}},
     'opponent', 'area', 4, [(4, 0), (5, 0), (4, 1), (5, 1)]),
    ('轰炸', {'target_line': {'type': 'row', 'index': 2}},
     'opponent', 'line', 6, [(0, 2), (5, 2)]),
    ('轰炸', {'target_line': {'type': 'col', 'index': 3}},
     'opponent', 'line', 6, [(3, 0), (3, 5)]),
    ('硫磺火焰', {'target_cells': [{'x': i, 'y': 5} for i in range(6)]},
     'opponent', 'cells', 6, [(0, 5), (5, 5)]),
]


@pytest.mark.parametrize('card_name,targets,board,shape,count,spot', _CASES)
def test_preview_cells_for_every_region_card(room, card_name, targets, board, shape,
                                             count, spot):
    """★ 全部实际区域卡：服务端归一化 → 公开预览，格子/归属/形状逐张核对。"""
    payload, err = _arm(room, card_name, targets)
    assert err is None, err
    assert payload['chain_len'] == 1
    node = payload['chain'][0]
    assert node['card'] == card_name
    assert node['seat'] == 'p1'
    pv = node['preview']
    assert pv is not None, '%s 的预览是空的（区域卡必须能画）' % card_name
    assert pv['board'] == board
    assert pv['shape'] == shape
    assert pv['card'] == card_name
    cells = [(c['x'], c['y']) for c in pv['cells']]
    assert len(cells) == count
    for want in spot:
        assert want in cells, '%s 的格子少了 %r（实际 %r）' % (card_name, want, cells)
    # 0..5 的整数对，且不重复
    assert len(set(cells)) == len(cells)
    assert all(isinstance(x, int) and isinstance(y, int) and 0 <= x <= 5 and 0 <= y <= 5
               for x, y in cells)


def test_shenwei_choice_maps_to_both_boards(room):
    """★ 神威！选己方 / 选对方 → 预览分别落在两块棋盘上（坐标按对应棋盘映射）。"""
    boards = []
    for board in ('self', 'opponent'):
        r = _make_room()
        try:
            payload, err = _arm(r, '神威！', {
                'target_area': {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}, 'board': board})
            assert err is None, err
            pv = payload['chain'][0]['preview']
            assert pv['board'] == board
            assert len(pv['cells']) == 9
            boards.append(pv['board'])
        finally:
            server.room_manager.rooms.pop(r.id, None)
    assert sorted(boards) == ['opponent', 'self'], '两种归属必须都能画出来'


def test_preview_coordinates_are_identical_for_both_seats(room):
    """双方收到的是**同一份公开 payload**（同一格在两块屏幕上指的是同一格）。

    ⚠️ 这里刻意不写"按座位翻转"：区域坐标是**棋盘内坐标**，前端按 `board`
    选棋盘、按 `x/y` 选格子 —— 两块棋盘各自的 `.cell[data-x][data-y]` 就是那一格。
    服务端只保证"归一化后的坐标"就这一个（`_preview_cells` 是唯一派生点）。
    """
    payload, err = _arm(room, '冻结', {'target_area': {'x1': 1, 'y1': 1, 'x2': 3, 'y2': 3}},
                        player_id=SID_B)
    assert err is None
    node = payload['chain'][0]
    assert node['seat'] == 'p2', '施法者是乙，座位标签必须是 p2'
    assert node['preview']['board'] == 'opponent', \
        '冻结固定打**对方**棋盘 —— 施法者是乙时，"对方"仍是乙的对手那一块'
    # 同一份 payload 发给双方：链路里没有 per-player 分支
    assert json.dumps(payload, ensure_ascii=False) == json.dumps(
        server._spectate_chain_payload(room), ensure_ascii=False)


# ===========================================================================
# 5. 多节点并存
# ===========================================================================
def test_multi_node_chain_keeps_every_area(room):
    """★ 同一连锁里多个待结算区域**同时存在**、各带自己的卡名与归属。"""
    card_a = MagicCard(name='冻结', speed=1, type='普通', description='')
    card_b = MagicCard(name='轰炸', speed=3, type='普通', description='')

    t1, e1 = server._sanitize_magic_targets(
        {'target_area': {'x1': 0, 'y1': 0, 'x2': 1, 'y2': 1}}, '冻结')
    t2, e2 = server._sanitize_magic_targets(
        {'target_line': {'type': 'col', 'index': 5}}, '轰炸')
    assert not (e1 or e2)

    room.chain = [ChainItem(SID_A, card_a, t1, 0.0),
                  ChainItem(SID_B, card_b, t2, 0.0)]

    payload = server._spectate_chain_payload(room)
    assert payload['chain_len'] == 2
    got = [(n['card'], n['seat'], n['preview']['board'], n['preview']['shape'])
           for n in payload['chain']]
    assert got == [
        ('冻结', 'p1', 'opponent', 'area'),
        ('轰炸', 'p2', 'opponent', 'line'),
    ], got
    # 两块区域必须互不相同（否则"并存"看不出来）
    ids = [n['preview']['id'] for n in payload['chain']]
    assert len(set(ids)) == 2, '两个节点的区域标识必须互不相同：%r' % (ids,)
    # 重叠情形：冻结与轰炸可在同一格上——
    # 这里显式构造一次重叠并断言"两边都画得出来"（前端按节点各画一层）。
    assert ('opponent', 'area') in [(n['preview']['board'], n['preview']['shape'])
                                    for n in payload['chain']]


def test_overlapping_areas_are_both_representable(room):
    """★ 重叠区域要能区分来源：同一格同时属于两个节点时，两份预览都还在。"""
    t1, _ = server._sanitize_magic_targets(
        {'target_area': {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}}, '冻结')
    t2, _ = server._sanitize_magic_targets(
        {'target_area': {'x1': 1, 'y1': 1, 'x2': 3, 'y2': 3}}, '探测雷达')
    room.chain = [
        ChainItem(SID_A, MagicCard(name='冻结', speed=1, type='普通', description=''),
                  t1, 0.0),
        ChainItem(SID_B, MagicCard(name='探测雷达', speed=1, type='普通', description=''),
                  t2, 0.0),
    ]
    payload = server._spectate_chain_payload(room)
    cells_a = {(c['x'], c['y']) for c in payload['chain'][0]['preview']['cells']}
    cells_b = {(c['x'], c['y']) for c in payload['chain'][1]['preview']['cells']}
    overlap = cells_a & cells_b
    assert overlap, '这个用例的前提是两块区域重叠'
    # 重叠格在两个节点里都在（前端据此同时挂两个类 + 两个角标 ⇒ 来源可辨）
    for cell in overlap:
        assert cell in cells_a and cell in cells_b
    assert payload['chain'][0]['preview']['card'] != payload['chain'][1]['preview']['card']


# ===========================================================================
# 6. 清理：结算 / 被康 / 出栈
# ===========================================================================
def test_cleanup_on_resolve_and_on_negation(room):
    """★ 结算 / 被失灵无效化 / 移出连锁 → 预览随之消失（只有一个数据源 `room.chain`）。"""
    payload, err = _arm(room, '冻结', {'target_area': {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}})
    assert err is None and payload['chain'][0]['preview'] is not None

    # ① 被康：`resolve_chain` 会先给链项打标记；标记之后预览照样在（还在栈上、要显示）
    room.chain[-1].negated = True
    room.chain[-1].negated_by = '失灵！'
    mid = server._spectate_chain_payload(room)
    assert mid['chain'][0]['negated'] is True
    assert mid['chain'][0]['preview'] is not None, '还没出栈就清预览 = 玩家看不到它要打哪'

    # ② 出栈（任何一条结算路径最后都会清空 room.chain）→ 预览随之消失
    room.chain = []
    after = server._spectate_chain_payload(room)
    assert after['chain'] == [] and after['chain_len'] == 0
    assert after.get('targets_dropped') == 0


def test_resolve_chain_clears_the_preview_source(room):
    """走**真的** `resolve_chain`：栈被清空 ⇒ 后续任何 payload 都不再带预览。

    ⚠️ 这里只用"空目标"的卡（`无中生有`），避免把整局状态机拖进来 ——
    本用例要证明的是"预览的来源被清掉了"，不是某个卡的效果。
    """
    fake = MagicCard(name='无中生有', speed=1, type='普通', description='')
    room.players[SID_A].magic_hand.append(fake)
    room.chain = [ChainItem(SID_A, fake, [], 0.0)]
    assert server._spectate_chain_payload(room)['chain_len'] == 1
    server.resolve_chain(room)
    assert room.chain == []
    assert server._spectate_chain_payload(room)['chain'] == []


def test_frontend_preview_layer_is_independent_and_non_blocking():
    """★ 前端预览层的三条硬要求都落在源码上（本批不用无头浏览器时的机器守卫）。

    1. **两块棋盘各一个预览层**：按 `preview.board` 选 `gamePlayerBoard` / `opponentBoard`，
       坐标按对应棋盘的 `.cell[data-x][data-y]` 映射；
    2. **多区域并存 + 重叠可分**：按链项序号给不同的类与颜色变量，格子上还记
       `data-chain-preview`（同一格属于多张卡时都能看出来）；
    3. **不遮挡响应交互**：`.cell.chain-preview` 与卡名角标在 CSS 里都
       `pointer-events: none`，且只动不参与布局的属性（box-shadow / background-image）。
    """
    js = _read(GAME_JS)
    assert 'function renderChainPreview' in js
    body = js[js.index('function renderChainPreview'):]
    body = body[:body.index('\n// 更新连锁UI显示')]
    # ① 两块棋盘各画各的
    assert 'node.board === \'self\' ? gamePlayerBoard' in body
    assert 'opponentBoard' in body
    assert "board.querySelector(`.cell[data-x=" in body, \
        '预览没有按"对应棋盘的格子"映射坐标'
    # ② 多区域并存 + 重叠可辨
    assert 'chain-preview--' in body and 'CHAIN_PREVIEW_COLORS' in body
    assert 'setProperty(' in body, '颜色变量必须用 setProperty 设（拼字符串最容易改坏）'
    assert 'data-chain-preview' in body, '格子上没有记"这格属于哪张卡"，重叠时分不出来'
    assert 'chain-preview-badge' in body, '没有卡名角标'
    # ③ 页面里引用到的 id 都必须真实存在（教训 #32：null 被 if 兜掉 = 点了没反应）
    css = _read(os.path.join(ROOT, 'static', 'style.css'))
    for cls in ('.cell.chain-preview', '.chain-preview-badge', '.chain-preview-badge--2',
                '.chain-preview--1', '.chain-preview--4'):
        assert cls in css, 'CSS 里缺 %s（样式丢了功能还在，检查工具也不报错）' % cls
    assert re.search(r'\.cell\.chain-preview\s*\{[^}]*pointer-events:\s*none', css), \
        '.cell.chain-preview 没设 pointer-events: none —— 会挡住响应/棋盘点击'
    assert re.search(r'\.chain-preview-badge\s*\{[^}]*pointer-events:\s*none', css), \
        '.chain-preview-badge 没设 pointer-events: none'
    # 只动不参与布局的属性（不许出现尺寸声明）—— CLAUDE.md §11.6
    for block in re.findall(r'\.cell\.chain-preview[^{]*\{([^}]*)\}', css):
        for bad in ('width:', 'height:', 'padding:', 'margin:', 'font-size:'):
            assert bad not in block, '预览层动了盒模型（%s）：%r' % (bad, block)


def test_frontend_preview_consumes_the_server_contract_verbatim():
    """前端读的字段名必须与服务端**发出去的**字段名逐字一致。

    （教训 #1 的另一半：契约两侧各写一遍名字，改一边不报错。）
    """
    js = _read(GAME_JS)
    body = js[js.index('function renderChainPreview'):]
    body = body[:body.index('\n// 更新连锁UI显示')]
    for field in ('preview', 'board', 'shape', 'cells'):
        assert field in body, '前端预览层没有读 `%s`' % field
    # 服务端实际发的键（从净化函数现取，不硬编码）
    node = spectate.sanitize_preview_item(
        {'card': {'name': '冻结'}, 'seat': 'p1', 'negated': False, 'player_id': SID_A,
         'targets': {'target_area': {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2},
                     'board': 'opponent'}},
        room=None)
    assert node is not None
    assert set(node) == {'card', 'seat', 'negated', 'preview'}
    assert set(node['preview']) == {'id', 'card', 'seat', 'board', 'shape', 'cells'}
    for field in ('board', 'shape', 'cells', 'card'):
        assert field in body, '服务端发了 `%s`，前端却没读' % field


def test_frontend_clears_preview_on_resolve_and_game_over():
    """前端清理点齐备（源码级）：结算、对局结束、重连快照三处都要能清。

    ⚠️ 判据是"**调用点存在**"而不是"某一毫秒的 DOM 里没有"（教训 #15）。
    ⚠️ `game.js` 里有**两个** `chain_resolved` 处理器：先注册的是观战屏那个
       （它只清观战快照），对局屏那个在后面。这里必须查**对局屏**那个。
    """
    src = _read(GAME_JS)
    assert 'function clearChainPreview' in src
    handlers = [m.start() for m in re.finditer(r"socket\.on\('chain_resolved'", src)]
    assert len(handlers) >= 2, 'chain_resolved 的处理器比预期少：%r' % handlers
    play_block = src[handlers[-1]:handlers[-1] + 900]
    assert 'updateChainUI' in play_block, \
        '对局屏的 chain_resolved 里没有走 updateChainUI（预览不会清）'
    # 对局结束那一条
    over = src.index("socket.on('game_over'")
    assert 'clearChainPreview' in src[over:over + 4000], \
        'game_over 里没有清预览层（结算屏上会还画着某卡的区域）'
    # updateChainUI 必须先刷预览、**不能**被 `#chain-display` 的存在性挡住
    ui = src.index('function updateChainUI')
    head = src[ui:ui + 700]
    assert head.index('renderChainPreview') < head.index("getElementById('chain-display')"), \
        ('updateChainUI 先取 #chain-display 再刷预览 —— 那个元素在 index.html 里\n'
         '       并不存在（提前 return），预览会跟着一起"不存在"且**不报错**')


def test_frontend_renders_before_response_prompt():
    """★ 预览必须在**响应按钮可用之前**就绪。

    服务端次序：`handle_use_magic_card` 先把净化后的 `magic_chain_updated` 广播出去，
    之后才 `_advance_chain_window` 发 `chain_request`（响应窗口）。
    前端两个处理器各走各的（预览在 `magic_chain_updated` 里画）⇒ 天然就绪在先。
    """
    src = _read(SERVER_PY)
    body = src.index('def handle_use_magic_card')
    block = src[body:body + 8000]
    emit_at = block.index("emit('magic_chain_updated'")
    # 响应窗口那一行在 `_advance_chain_window` 定义之后，所以块要开得够大；
    # 找不到就是顺序被改动了，直接判红（不许静默跳过）。
    window_at = block.index('_advance_chain_window(room, opponent_id)')
    assert emit_at < window_at, \
        '先开响应窗口、后广播连锁 = 响应按钮出现时预览还没到（作者明确要求不许这样）'
    # 前端：预览画在 magic_chain_updated 处理器里，不需要等 chain_request。
    # ⚠️ 这个事件有**两个**处理器（先注册的是观战屏那个），对局屏的在后面。
    js = _read(GAME_JS)
    hs = [m.start() for m in re.finditer(r"socket\.on\('magic_chain_updated'", js)]
    assert len(hs) >= 2, 'magic_chain_updated 的处理器比预期少：%r' % hs
    assert 'updateChainUI()' in js[hs[-1]:hs[-1] + 700], \
        '对局屏的 magic_chain_updated 处理器里没有刷连锁/预览'


# ===========================================================================
# 7. 重连快照：同一契约
# ===========================================================================
def test_snapshot_uses_the_same_contract_as_live_stream(room):
    """★ `_build_room_sync` 的 `chain` 与实时流**逐字节同构**（同一构造函数）。

    形状必须自带 `preview` —— 否则"重连回来的玩家看不到别人打哪儿"
    （旧实现手拼 `{card, caster, negated}`，就是这个问题）。
    """
    payload, err = _arm(room, '探测雷达', {'target_area': {'x1': 2, 'y1': 2, 'x2': 3, 'y2': 3}})
    assert err is None
    snap = server._build_room_sync(room, SID_A)
    assert snap['chain'] == payload, (
        '重连快照里的 chain 与实时流不是同一份：\n  快照: %r\n  实时: %r'
        % (snap['chain'], payload))
    assert snap['chain']['chain'][0]['preview']['board'] == 'opponent'
    # 观战快照也走同一个函数（第三处消费方）
    spec = server._build_spectate_snapshot(room)
    assert spec['chain'] == payload


def test_room_sync_snapshot_still_has_what_the_frontend_needs(room):
    """重连快照的 chain 不能为了加预览而丢掉前端要用的东西。"""
    _arm(room, '冻结', {'target_area': {'x1': 0, 'y1': 0, 'x2': 2, 'y2': 2}})
    snap = server._build_room_sync(room, SID_A)
    item = snap['chain']['chain'][0]
    for key in ('card', 'seat', 'negated', 'preview'):
        assert key in item, '重连快照的链项丢了 %r' % key
    assert snap['chain_waiting'] in (True, False)
    assert 'chain_window' in snap


# ===========================================================================
# 8. 隐藏字段不泄漏（以别人身份直读 + 两侧都断言）
# ===========================================================================
_PRIVATE_KEYS = ('targets', 'ships', 'positions', 'hits', 'sunk_positions',
                 'revealed_positions', 'hand', 'magic_hand', 'ship_positions',
                 'affected_positions', 'player_id', 'effect_flags')


def _all_keys(node, out=None):
    """递归收一个 JSON 结构里的**全部键名**。"""
    out = set() if out is None else out
    if isinstance(node, dict):
        for k, v in node.items():
            out.add(k)
            _all_keys(v, out)
    elif isinstance(node, list):
        for v in node:
            _all_keys(v, out)
    return out


def test_preview_never_leaks_private_fields(room):
    """★ 预览只含白名单字段；私密键名一个都不出现。

    判据分两侧（教训 #12：隐私过滤只有服务端拦得住，前端断言会假绿）：
      · **键名侧**：递归扫全部键 ⇒ 不许命中 `FORBIDDEN_PAYLOAD_KEYS` / `SNAPSHOT_FORBIDDEN_KEYS`；
      · **值侧**：给房间塞上私密值（船位 / 命中 / 手牌 / 揭示坐标 / 一份"额外参数"），
        断言它们在 payload 的文本里**一个字节都不出现**。
    """
    # —— 值侧：塞私密数据 ——
    secret_cells = [(5, 4), (4, 5)]
    room.players[SID_A].ships = [
        PlayerShip(positions=[Position(x, y) for (x, y) in secret_cells], hits=[])]
    room.players[SID_A].revealed_positions = [Position(1, 0)]
    # ⚠️ 手牌用一张**真实存在**的卡：卡名合法性由卡表校验，编一个名字会抛 ValueError。
    room.players[SID_A].magic_hand = [
        MagicCard(name=server.magic_cards[0].name, speed=1, type='普通', description='')]
    hand_name = server.magic_cards[0].name
    payload, err = _arm(room, '冻结', {
        'target_area': {'x1': 0, 'y1': 0, 'x2': 0, 'y2': 0},
        # 客户端多塞一个私密参数：净化是**白名单重建**，它必须整条消失
        'secret_extra': 'PER-ATTR-SECRET',
    })
    assert err is None

    keys = _all_keys(payload)
    forbidden = set(spectate.FORBIDDEN_PAYLOAD_KEYS) | set(spectate.SNAPSHOT_FORBIDDEN_KEYS)
    hit = keys & forbidden
    assert not hit, '连锁 payload 里出现了禁字段：%s' % sorted(hit)
    assert not (keys & set(_PRIVATE_KEYS)), \
        '连锁 payload 里出现了私密键：%s' % sorted(keys & set(_PRIVATE_KEYS))
    # 白名单：链项与预览的键集合都不许多
    assert set(payload['chain'][0]) == {'card', 'seat', 'negated', 'preview'}
    assert set(payload['chain'][0]['preview']) == {
        'id', 'card', 'seat', 'board', 'shape', 'cells'}

    blob = json.dumps(payload, ensure_ascii=False)
    assert 'PER-ATTR-SECRET' not in blob, '客户端多塞的私密参数被原样透传了'
    assert hand_name not in blob, '手牌内容泄漏（%r）' % hand_name
    assert SID_A not in blob and SID_B not in blob, '原始座位 sid 泄漏'
    # 私密船位（(5,4)/(4,5) 从没挨过炮）不许出现在预览里
    preview_cells = {(c['x'], c['y']) for c in payload['chain'][0]['preview']['cells']}
    assert not (preview_cells & set(secret_cells)), '未挨过炮的船位出现在了预览里'


def test_spectator_gets_the_same_sanitized_shape(room):
    """★ 以**观众**身份直读那一路：净化结果仍是同一份白名单形状。"""
    payload, err = _arm(room, '硫磺火焰',
                        {'target_cells': [{'x': i, 'y': 1} for i in range(6)]})
    assert err is None
    # 观众那一路（`emit` 的第三条腿）拿到的是**已经净化过**的 payload，再过一次净化
    again = spectate.sanitize_event('magic_chain_updated', payload, room=room)
    assert again['chain'] == payload['chain'], '观众看到的结构与对局双方不一致'
    assert set(again['chain'][0]) == {'card', 'seat', 'negated', 'preview'}
    # ⚠️ 别用 `'targets' not in blob`：净化结果里**有一项就叫 `targets_dropped`**。
    #    要判的是 `ChainItem.targets` 那个**字段**有没有被带出来 —— 逐项看键名。
    for item in again['chain']:
        assert 'targets' not in item
    assert 'targets' not in again['chain'][0]['preview']


def test_preview_is_idempotent(room):
    """★ 净化**幂等**：观众那一路要过两次，第二次不许把座位退化成 unknown。

    这是本批**实测踩到**的真缺陷：对局广播发的是已净化的 payload，
    而 `emit()` 复制给观战通道时又净化一次 —— 第一遍已把 `player_id` 换成 `seat`，
    第二遍按 `player_id=None` 重算就得到 `unknown`（观众看到的座位标签全是 unknown）。
    """
    payload, _ = _arm(room, '轰炸', {'target_line': {'type': 'row', 'index': 4}},
                      player_id=SID_B)
    once = payload
    twice = spectate.sanitize_event('magic_chain_updated', once, room=room)
    thrice = spectate.sanitize_event('magic_chain_updated', twice, room=room)
    assert once == twice == thrice
    assert twice['chain'][0]['seat'] == 'p2'
    assert twice['chain'][0]['preview']['seat'] == 'p2'


def test_no_unconfirmed_selection_is_ever_broadcast(room):
    """★ 选区**未确认时绝不广播**：预览只有一个数据源 —— `room.chain`。

    判据（源码级）：`magic_chain_updated` 的构造点只有 `_spectate_chain_payload`，
    而后者只读 `room.chain`；不存在"读客户端鼠标位置 / 读临时选区"的路径。
    """
    src = _read(SERVER_PY)
    builders = re.findall(r"_spectate_chain_payload\(room", src)
    assert len(builders) >= 3, '连锁 payload 的构造点变少了（快照或实时流被绕开了？）'
    # 除了这个函数本身，任何地方都不许再手拼 chain 广播
    raw = re.findall(r"emit\('magic_chain_updated',\s*\{\s*'chain'", src)
    assert not raw, '还有地方在**原样转发** room.chain（绕过净化）：%d 处' % len(raw)
    # `_spectate_chain_payload` 只从 room.chain 派生
    fn = src.index('def _spectate_chain_payload')
    body = src[fn:src.index('def _build_spectate_snapshot')]
    assert "getattr(room, 'chain'" in body
    for bad in ('magic_temp_data', 'pending_', 'selecting'):
        assert bad not in body, '预览的构造读了 %r（可能是未确认的选区）' % bad


def _strip_strings_and_comments(src):
    """去掉源码里的字符串字面量与 `#` 注释 —— 只留下真正会执行的代码。

    源码级守卫必须这么做：本项目的中文注释里经常**引用**被禁的写法
    （"别用 `room.players[...]`"），不剥掉的话守卫会把注释当代码判红
    —— 那种假红会让人直接把守卫删掉。
    """
    src = re.sub(r'"""[\s\S]*?"""', '', src)
    src = re.sub(r"'''[\s\S]*?'''", '', src)
    out = []
    for line in src.splitlines():
        # 粗略剥字符串（这些函数体里没有带引号的 # 或转义引号）
        line = re.sub(r'"[^"\n]*"', '""', line)
        line = re.sub(r"'[^'\n]*'", "''", line)
        out.append(line.split('#')[0])
    return '\n'.join(out)


def test_preview_derivation_never_calls_effect_logic():
    """★ 不许调用效果逻辑"试算"区域（规格 §5 硬约束）。

    `preview_node` / `_preview_cells` / `sanitize_preview_item` **只**做
    "已确认目标 → 格子"，不许碰局面（船位、命中、手牌、临时选区），也不许跑效果。
    """
    src = _read(os.path.join(ROOT, 'spectate.py'))
    start = src.index('def _preview_cells')
    end = src.index('def _pub_magic_chain')
    block = _strip_strings_and_comments(src[start:end])
    for bad in ('apply_magic_effect', 'room.players', '.ships', '.hits',
                'magic_temp_data', 'pending_', 'revealed_positions',
                'resolve_chain', 'sendMagic'):
        assert bad not in block, '预览的派生逻辑里出现了 %r' % bad
    # room 的唯一用途是座位标签；页面级字段一律不许读
    for line in block.splitlines():
        if 'room' in line:
            assert 'seat_label(' in line or 'room=room' in line or 'room=None' in line \
                or 'room,' in line or 'room)' in line, \
                '预览逻辑里出现了非座位用途的 room：%r' % line.strip()


# ===========================================================================
# 9. 源码级守卫：把"看起来做了"变成"改坏了就红"
# ===========================================================================
def test_area_target_boards_is_the_only_source_of_truth():
    """卡名归属只在 `spectate.AREA_TARGET_BOARDS` 里声明一次（教训 #1）。

    防的是"顺手在 server.py 里再抄一张表" —— 两张表必然漂移。
    """
    src = _read(SERVER_PY)
    assert 'spectate.AREA_TARGET_BOARDS' in src
    for name in spectate.AREA_TARGET_BOARDS:
        # 服务端不许再出现"卡名 → 归属字符串"的第二次声明
        pat = re.compile(r"'%s'\s*:\s*'(self|opponent|choice)'" % re.escape(name))
        assert not pat.search(src), 'server.py 里又抄了一份 %s 的归属表' % name


def test_preview_keys_have_no_intersection_with_forbidden_tables():
    """白名单与两张禁字段表**不许有交集**（教训 #10）—— 也由 spectate._validate 兜底。"""
    allowed = set(spectate.PREVIEW_KEYS)
    assert not (allowed & set(spectate.FORBIDDEN_PAYLOAD_KEYS))
    assert not (allowed & set(spectate.SNAPSHOT_FORBIDDEN_KEYS))
    # 预览内部的字段同样不许
    inner = {'id', 'card', 'seat', 'board', 'shape', 'cells'}
    assert not (inner & set(spectate.FORBIDDEN_PAYLOAD_KEYS))


def test_spectate_validate_rejects_a_broken_board_table(monkeypatch):
    """★ 元测试：把归属表改坏（非法取值）⇒ `_validate()` 必须报错。

    防"守卫永远绿"（教训 #34：兜底 except + 零报错制造假象）。
    """
    broken = dict(spectate.AREA_TARGET_BOARDS)
    broken['冻结'] = 'opponentt'
    monkeypatch.setattr(spectate, 'AREA_TARGET_BOARDS', broken)
    with pytest.raises(ValueError) as exc:
        spectate._validate()
    assert 'AREA_TARGET_BOARDS' in str(exc.value)


def test_spectator_room_id_is_not_a_game_room(room):
    """本批的 payload 仍然只通过 `emit` 的对局广播与观战通道流转（不新开出口）。"""
    assert spectate_room_id(room.id) != room.id
    assert room.id in server.room_manager.rooms
