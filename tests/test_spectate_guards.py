# -*- coding: utf-8 -*-
"""观战地基的两条**穷举守卫**（以及把它们钉住的元测试）。

## 为什么需要"穷举"

观战最大的风险不是"功能没做出来"，而是**漏一个事件 = 透视漏洞**：
房间级广播里有几个 payload 带**整船坐标**（设计上对双方就是公开的），
原样转给观众就等于把双方船位白送出去。

本项目已经栽过同形状的跟头（CLAUDE.md 第 10 节第 1 条、教训 #38）：
"改共用函数先 grep 出全部调用点、逐个表态" —— 靠人肉记名单必然漂移。
所以这里把"表态"变成**机器穷举**：

1. `test_every_emit_site_is_classified` —— 扫 `server.py` 源码里**全部** `emit(...)`
   调用点，每一个事件名必须落在 `spectate.SPECTATE_EVENTS`（给观众，附净化函数）
   或 `spectate.NOT_FOR_SPECTATORS`（不给，附理由）里；
2. `test_no_position_leak_in_any_spectator_payload` —— 造一个**船位已知**的房间，
   对表里每一个"给观众"的事件构造**真实形状**的 payload 走净化，
   断言净化结果里不含任何**未被轰过的**船坐标、也不含 `ships`/`positions`/`hits`；
   并且**反向断言**动作信息没被砍掉（防"为了安全把该给的也砍了"）。

## 这两条守卫自己也必须"能抓到问题"

教训 #34：只看"没报错"等于没验。所以各配一条**元测试**，
把源码/payload 故意改坏，断言守卫真的变红：

* `test_guard_a_actually_catches_a_new_token` —— 往源码副本里插一个没登记的事件名；
* `test_guard_b_actually_catches_a_raw_position_payload` —— 让净化函数原样放行坐标。
"""
import ast
import io
import pathlib

import pytest

import server
import spectate

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER_PY = REPO_ROOT / 'server.py'


# ===========================================================================
# 规范的"事件全集" —— 加事件的人必须在这里 + spectate.py 里同时表态
# ===========================================================================
# 这张表与 `spectate.py` 的两张表合起来才是完整分类：
#   KNOWN_EVENTS ⊆ (SPECTATE_EVENTS ∪ NOT_FOR_SPECTATORS)
#
# 数字来自 2026-09-22 第 2 批后的实际扫描：`server.py` 共 196 处 emit/semit 调用点、
# 78 个静态字面量事件名、7 处名字是算出来的（其中 6 处由下面两张登记表逐个表态，
# `_MULTITURN_EFFECTS` 那处走变量、在第 4 步被逐个断言）、
# 另有若干 `socketio.emit` 直调（大厅/观战通道，不走 `emit`）。
KNOWN_EVENTS = frozenset({
    # —— 对局动作与状态 ——
    'attack_result', 'attacks_updated', 'turn_change', 'turn_skipped', 'phase_updated',
    'game_state', 'game_log', 'game_message', 'game_over', 'game_canceled',
    'chain_resolved', 'magic_chain_updated', 'chain_request',
    'chat_message', 'quick_chat', 'message', 'rps_result',
    # —— 按座位下发的私有事件 ——
    'hand_updated', 'ships_updated', 'player_ships_updated', 'board_attacks_updated',
    'revealed_positions', 'active_effects', 'room_sync', 'resume_game',
    'reconnect_token', 'reconnect_warning',
    'sacrifice_request', 'sacrifice_cancelled', 'placement_request', 'placement_done',
    'reset_gameboard', 'dice_discard_request',
    'priority_request', 'priority_waiting', 'priority_waiting_end',
    'priority_setting_updated',
    'taoyuan_complete', 'taoyuan_choice', 'taoyuan_waiting',
    'lingqi_complete', 'lingqi_waiting',
    'wangyang_complete',
    'shenji_waiting', 'shenji_waiting_end',
    # —— 魔法 / 棋盘效果 ——
    'field_magic_updated', 'last_stand_cells', 'shenwei_hole', 'shenwei_hole_restored',
    'frozen_area', 'lanyu_recalled', 'ship_sacrificed',
    'shields_added', 'shield_absorbed', 'trap_set', 'trap_triggered', 'trap_expired',
    'dice_rolled', 'dice_discard_complete',
    'reinforcement_activated', 'reinforcement_turn_updated', 'reinforcement_cleared',
    'holy_heart_activated', 'holy_heart_interrupted', 'holy_heart_turn_updated',
    'holy_heart_cleared', 'demon_contract_cleared',
    # —— 掉线 ——
    'opponent_disconnected', 'opponent_reconnected',
    # —— 结算播报（发往玩家自己的 sid，见 spectate.py 的分类说明）——
    'achievements_unlocked', 'xp_gained', 'rank_changed',
    # —— 匹配 / 大厅 ——
    'match_queued', 'match_canceled',
    'lobby_state', 'lobby_hello', 'lobby_chat', 'lobby_chat_history',
    # —— 观战通道自己的一套（第 2 批：快照 / 人数 / 结束）——
    'spectate_sync', 'spectate_count_changed', 'spectate_ended',
    # —— 观战通道自己的一套（第 4 批：名单 / 进出 / 聊天 / "我是谁"）——
    # 前四个走后门：`spectate_roster` / `spectate_joined` / `spectate_left` /
    # `spectate_chat` 都由 `_spectate_broadcast_*` / handler 里的 **`socketio.emit`**
    # 直接发进 `spectate:<room_id>`（不经 `emit` 的第三条腿，也就不会被"只转发
    # 对局房间号"的门禁挡掉）。只有 `spectate_you` 走 `emit(..., to=sid)` 单发。
    'spectate_roster', 'spectate_joined', 'spectate_left', 'spectate_chat',
    'spectate_you',
    # —— 错误提示 ——
    'error',
})

# `emit(<计算出来的名字>)` 的**逐处登记表**：源码片段 → (解析出的事件名, 理由)。
#
# ⚠️ **按内容登记，不按行号** —— 行号每次提交都会漂（CLAUDE.md 开头就写着
#    "行号只当线索"），拿行号当契约的守卫会在别人只是加了几行注释时莫名其妙变红。
#    每条都写明"它长什么样"，扫描函数按样子去找；找不到 = 写法变了，必须重新表态。
_DYNAMIC_EMIT_SITES = (
    (
        "emit(event_name, {'reason': why}",
        'table',
        ('holy_heart_cleared', 'reinforcement_cleared', 'demon_contract_cleared'),
        '_clear_multiturn_effects：名字来自 _MULTITURN_EFFECTS 表（不是在 emit 行里写死的），'
        '表本身在下面第 4 步被逐个断言',
    ),
    (
        "'taoyuan_complete' if cancelled_kind",
        'literals',
        ('taoyuan_complete', 'lingqi_complete'),
        'handle_cancel_magic_selection 里的三元表达式：取消的选牌类型决定事件名',
    ),
)

# `emit(...)` 的表达式里**不是事件名**的字符串字面量：逐个写明它是什么。
#
# ⚠️ 扫描函数把 emit 表达式里**所有**字符串字面量都揪出来要求表态（这一条是本批的
#    真实收获：`emit('A' if kind == 'X' else 'B')` 里 `'X'` 也是字面量）。
#    它们不是事件名，但必须显式声明 —— 否则下一个"长得像事件名的判据值"
#    就会混进 KNOWN_EVENTS，让那张表慢慢失真。
_NON_EVENT_STRING_LITERALS = {
    'taoyuan_choice': 'handle_cancel_magic_selection 里的**判据值**（magic_temp_data 的 kind），'
                      '真正的两个事件名是同行的 taoyuan_complete / lingqi_complete',
}


def _string_constants(node):
    """递归取出一个表达式里出现的全部字符串字面量。

    三元表达式 `'a' if cond else 'b'` 两侧的名字都要被要求表态 ——
    只取 `node.args[0]` 的 value 会漏掉它们（那是真正的盲区）。
    """
    return {n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _emit_sites(src: str, path_label: str = '<source>'):
    """从源码字符串里取出全部 `emit(...)` / `semit(...)` 调用点的事件名。

    返回 `(事件名集合, 计算出来的名字列表)`。用 AST 而不是正则 ——
    正则会被字符串里的 `emit(`、跨行调用、以及三元表达式骗到。
    """
    tree = ast.parse(src)
    lines = src.splitlines()
    names = set()
    computed = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        fname = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
        if fname not in ('emit', 'semit'):
            continue
        if not node.args:
            raise AssertionError('%s:%d emit() 没有事件名' % (path_label, node.lineno))
        arg0 = node.args[0]
        if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
            names.add(arg0.value)
        else:
            literals = _string_constants(arg0)
            names |= literals
            computed.append((node.lineno, lines[node.lineno - 1].strip(), sorted(literals)))
    return names, computed


def _registries():
    return set(spectate.SPECTATE_EVENTS) | set(spectate.NOT_FOR_SPECTATORS)


# ===========================================================================
# 守卫 (a)：事件分类穷举
# ===========================================================================

def test_event_registries_are_complete_and_disjoint():
    """三张名单必须自洽：`KNOWN_EVENTS` 全覆盖、白名单黑名单零交集、理由非空。"""
    allowed = set(spectate.SPECTATE_EVENTS)
    denied = set(spectate.NOT_FOR_SPECTATORS)

    both = allowed & denied
    assert not both, '这些事件既给观众又不给观众（自相矛盾）：%s' % sorted(both)

    uncovered = KNOWN_EVENTS - allowed - denied
    assert not uncovered, (
        '这些事件没有表态（既不在 SPECTATE_EVENTS 也不在 NOT_FOR_SPECTATORS）：%s\n'
        '新加事件必须逐个表态：给观众就在 SPECTATE_EVENTS 登记净化函数，'
        '不给就在 NOT_FOR_SPECTATORS 写明理由。' % sorted(uncovered)
    )

    stale = (allowed | denied) - KNOWN_EVENTS
    assert not stale, (
        '这些事件登记了却不在 KNOWN_EVENTS 里（要么是死代码，要么是忘了同步本表）：%s'
        % sorted(stale)
    )

    for event, reason in spectate.NOT_FOR_SPECTATORS.items():
        assert isinstance(reason, str) and reason.strip(), \
            'NOT_FOR_SPECTATORS[%r] 的理由是空的 —— 写不出理由就是没想清楚' % event


def test_every_emit_site_is_classified():
    """★ 守卫 (a)：`server.py` 源码里每一个 emit 事件名都必须已分类。

    这是本批的核心价值：把"漏一个事件 = 透视漏洞"从人肉约定变成机器穷举。
    """
    src = io.open(SERVER_PY, encoding='utf-8').read()
    names, computed = _emit_sites(src, 'server.py')
    registries = _registries()

    # 1) 源码里出现的所有字面量事件名必须全部已分类
    unclassified = names - registries - set(_NON_EVENT_STRING_LITERALS)
    assert not unclassified, (
        'server.py 里这些 emit 事件名没有分类（默认拒绝会静默不发观众）：%s\n'
        '（如果它不是事件名，请登记进 _NON_EVENT_STRING_LITERALS 并说明它是什么）'
        % sorted(unclassified)
    )

    # 2) 反向：源码里出现的事件名不许超出 KNOWN_EVENTS
    #    （少了这一条，KNOWN_EVENTS 就是一张没人维护的摆设清单）
    unknown = names - KNOWN_EVENTS - set(_NON_EVENT_STRING_LITERALS)
    assert not unknown, (
        'server.py 里出现了 KNOWN_EVENTS 没登记的事件名：%s\n'
        '（加事件的人要同步 KNOWN_EVENTS + spectate 的表）' % sorted(unknown)
    )

    # 3) 计算出来的事件名必须逐个显式登记
    #
    # ⚠️ 判据取的是**同一个 AST 节点**解析出的字面量（不是按行去 parse 源码片段 ——
    #    像 `emit('A' if c else 'B', ...)` 这种跨行调用按行 parse 会 SyntaxError）。
    by_literals = {}
    for _lineno, _line, literals in computed:
        for literal in literals:
            by_literals.setdefault(literal, []).append(_lineno)

    for needle, kind, expected, why in _DYNAMIC_EMIT_SITES:
        assert why, '动态事件名 %r 的登记项没写理由' % needle
        assert kind in ('table', 'literals'), '未知的登记类型 %r' % kind
        for name in expected:
            assert name in registries, '动态事件名 %r（登记项 %r）没分类' % (name, needle)
            if kind == 'literals':
                assert by_literals.get(name), (
                    '登记表称 %r 是源码里写死的事件名，但 AST 里没扫到它 —— 写法变了' % name
                )

    # 4) `_MULTITURN_EFFECTS` 表里的事件名也必须都被覆盖
    #    （它们是通过 `emit(event_name, ...)` 发的，AST 只抓得到变量名）
    for entry in server._MULTITURN_EFFECTS:
        event_name = entry[1]
        assert event_name in registries, '_MULTITURN_EFFECTS 里的 %r 没有分类' % event_name
        assert event_name in src, \
            '_MULTITURN_EFFECTS 里的 %r 在源码里根本没出现（表过期了？）' % event_name
        assert event_name not in names, (
            '%r 既是表驱动的事件名、又在别处被写死成字面量 —— 两处定义迟早漂移，'
            '请统一到 _MULTITURN_EFFECTS' % event_name
        )


def test_guard_a_actually_catches_a_new_token():
    """★ 元测试：证明守卫 (a) **真的能抓到**漏网事件（教训 #34）。

    做法：把真实 `server.py` 复制一份，往里插一行**没登记过**的 emit，
    再跑同一个扫描函数 —— 必须报出那个假事件名。

    ⚠️ 两个方向都断言：干净副本扫不出问题 + 脏副本扫得出问题。
    只看"没报错"就是教训 #34 说的那种假象。
    """
    src = io.open(SERVER_PY, encoding='utf-8').read()
    registries = _registries()

    clean_names, _ = _emit_sites(src, 'clean')
    assert not (clean_names - registries - set(_NON_EVENT_STRING_LITERALS)), \
        '干净副本不该有未分类事件'

    fake = "    emit('definitely_not_a_registered_event', {'x': 1}, room=room.id)\n"
    marker = 'def emit(event, data, to=None, room: str | None = None):\n'
    tainted = src.replace(marker, marker + fake, 1)
    assert tainted != src, '注入点没找到 —— 这条元测试自己失效了，必须修'
    # 注入点必须**合法**（插在函数体第一行）—— 插在模块级会 NameError，
    # 那样虽然也会"变红"，但红的是语法而不是守卫，等于什么都没验。
    ast.parse(tainted)

    tainted_names, _ = _emit_sites(tainted, 'tainted')
    leaked = tainted_names - registries - set(_NON_EVENT_STRING_LITERALS)
    assert 'definitely_not_a_registered_event' in leaked, (
        '守卫 (a) 没抓到刚插进去的假事件 —— 它就是一条绿着的摆设'
    )


def test_guard_a_catches_a_ternary_branch_that_is_not_registered():
    """★ 元测试之二：**三元表达式里**的一个分支没登记，也必须被抓住。

    这是最容易漏的形状：`emit('known' if c else 'unknown')` —— 只看第一个
    字符串字面量的话，`'unknown'` 会从眼皮底下溜过去。
    """
    src = io.open(SERVER_PY, encoding='utf-8').read()
    registries = _registries()
    fake = "    emit('game_log' if room.round else 'sneaky_unregistered_event', {}, room=room.id)\n"
    marker = 'def emit(event, data, to=None, room: str | None = None):\n'
    tainted = src.replace(marker, marker + fake, 1)
    assert tainted != src
    ast.parse(tainted)

    tainted_names, computed = _emit_sites(tainted, 'tainted-ternary')
    assert 'sneaky_unregistered_event' in (
        tainted_names - registries - set(_NON_EVENT_STRING_LITERALS)
    ), '三元表达式里未登记的分支溜过去了'
    assert any('sneaky_unregistered_event' in names for _l, _line, names in computed)


# ===========================================================================
# 守卫 (b)：无位置泄漏（双向）
# ===========================================================================

# 两台棋盘各自的 6 艘船。**故意做成两格船** —— 单格船时"挨打那艘船的坐标"
# 与被轰出去的那一格是同一个，泄漏看起来像"没多给什么"；两格船才暴露出
# `shield_absorbed` 真正的危害：它会把**没被打到的那一格**也送出去。
P1_SHIPS = [(i, 0) for i in range(6)]
P2_SHIPS = [(i, 5) for i in range(6)]
# 第 5 艘（坐标 (4,5)(5,5)）是被轰的那艘：只有 (3,5) 挨了炮，
# 所以 (5,5) 是**没被打过**的那一格 —— 它就是 `shield_absorbed` 会漏出去的东西。
BIG_SHIP_CELLS = ((4, 5), (5, 5))
ALL_SHIP_CELLS = frozenset(P1_SHIPS + P2_SHIPS)

# 观众**有权看到**的坐标（"动作"就是打哪儿 / 卡面公开的选区，藏了就没得看了）。
PUBLIC_HIT_CELL = (3, 5)
# 公开选区（`{x1,y1,x2,y2}` 的四个角）
PUBLIC_AREA = {'x1': 1, 'y1': 0, 'x2': 3, 'y2': 2}
PUBLIC_AREA_CELLS = frozenset({
    (PUBLIC_AREA['x1'], PUBLIC_AREA['y1']), (PUBLIC_AREA['x2'], PUBLIC_AREA['y2']),
})


def _collect_coords(node, out=None):
    """递归收集 payload 里所有坐标形状。

    认三种形状：`{'x':int,'y':int}` / `{'x1','y1','x2','y2'}`（区域）/
    `{'cell':[x,y]}`（留给后续批次）。数组形态的 `[x,y]` 只有挂在 `cell` 键下才算 ——
    否则会把 `[1, 1]` 这种普通数值对误判成坐标。
    """
    if out is None:
        out = []
    if isinstance(node, dict):
        if isinstance(node.get('x'), int) and isinstance(node.get('y'), int):
            out.append((node['x'], node['y']))
        if all(isinstance(node.get(k), int) for k in ('x1', 'y1', 'x2', 'y2')):
            out.append((node['x1'], node['y1']))
            out.append((node['x2'], node['y2']))
        cell = node.get('cell')
        if isinstance(cell, (list, tuple)) and len(cell) == 2 \
                and all(isinstance(v, int) for v in cell):
            out.append(tuple(cell))
        for value in node.values():
            _collect_coords(value, out)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _collect_coords(value, out)
    return out


def _collect_keys(node, out=None):
    """递归收集 payload 里出现的全部字典键。"""
    if out is None:
        out = set()
    if isinstance(node, dict):
        out.update(node.keys())
        for value in node.values():
            _collect_keys(value, out)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _collect_keys(value, out)
    return out


def _payloads(room):
    """`spectate.SPECTATE_EVENTS` 里每个事件 → 一份**真实形状**的 payload。

    形状全部照 `server.py` 的实际 emit 值抄（每个分支都写着它来自哪一行），
    这样"净化把坐标删干净了"才是真的验过，而不是因为样例本来就没有坐标。
    """
    hx, hy = PUBLIC_HIT_CELL
    area = dict(PUBLIC_AREA)
    return {
        # —— 开炮：必须**保留**被轰的那一格 ——
        'attack_result': {
            'attacker': 'p1', 'x': hx, 'y': hy, 'hit': True, 'ship_sunk': False,
            'remaining_attacks': 4, 'attacker_remaining_ships': 6,
            'defender_remaining_ships': 6, 'shield_blocked': True,
        },
        # ★ 最严重的一处：施法者**全部存活船**的坐标（server.py `shields_added`）
        'shields_added': {
            'player': 'p1', 'count': 6,
            'positions': [{'x': x, 'y': y} for x, y in P1_SHIPS],
        },
        # ★ 挨打那艘船的**全部**坐标（server.py `shield_absorbed`）——
        #    注意 (5,5) 从没被轰过：这就是它比 attack_result 多送出去的那一格。
        'shield_absorbed': {
            'player': 'p2',
            'positions': [{'x': x, 'y': y} for x, y in BIG_SHIP_CELLS],
        },
        # ★ 设陷阱那艘船的坐标（server.py `trap_set`）
        'trap_set': {'player': 'p1', 'positions': [{'x': 0, 'y': 0}]},
        # ★ 触发时被击沉那艘船的坐标（server.py `trap_triggered`）
        'trap_triggered': {
            'owner': 'p1', 'sunk_positions': [{'x': x, 'y': y} for x, y in BIG_SHIP_CELLS],
            'sacrificed': 2, 'message': '守株待兔：对方需牺牲2艘战舰',
        },
        # ★ 被牺牲那艘船的坐标（server.py `ship_sacrificed`）
        'ship_sacrificed': {
            'player': 'p1', 'positions': [{'x': x, 'y': y} for x, y in BIG_SHIP_CELLS],
            'reason': 'last_stand',
        },
        # —— 连锁：`targets` 是客户端提交的原始目标（形状不受控），必须剥掉 ——
        'magic_chain_updated': {
            'chain': [
                {'player_id': 'sid-p1', 'card': {'name': '卧薪尝胆', 'speed': 1},
                 'targets': [{'x': 0, 'y': 0}, {'x': 1, 'y': 0}], 'timestamp': 1.0,
                 'negated': False, 'negated_by': None},
                {'player_id': 'sid-p2', 'card': {'name': '失灵！', 'speed': 3},
                 'targets': [], 'timestamp': 2.0, 'negated': False, 'negated_by': None},
            ],
        },
        # —— 明文日志：detail 里带 target{x,y}，那是**已公开**的被轰格 ——
        'game_log': {
            'ts': 1, 'type': 'attack', 'text': '第5回合 · p1 攻击 (3,5) — 命中',
            'detail': {'attacker': 'p1', 'target': {'x': hx, 'y': hy}, 'hit': True,
                       'ship_sunk': False, 'shield_blocked': False},
        },
        # —— 绝处逢生的候选格：服务端**有意公开**给双方（对方要据此知道唯一那艘新船
        #    可能在哪，而且这些格子必须能打），所以它属于公开信息 ——
        'last_stand_cells': {'cells': [{'x': hx, 'y': hy}], 'owner': 'p1'},
        # —— 神威洞：卡面就是"公开宣布 N 回合后这片区域有船"，area 是公开选区 ——
        'shenwei_hole': {'player': 'p2', 'area': area, 'return_turn': 9},
        'shenwei_hole_restored': {'player': 'p2'},
        # —— 冻结区：范围是对双方公开的选区 ——
        'frozen_area': {
            'x1': area['x1'], 'y1': area['y1'], 'x2': area['x2'], 'y2': area['y2'],
            'owner': 'p2', 'caster': 'p1', 'frozen': 2, 'until_round': 9,
        },
        # —— 场地魔法：贴了什么卡对双方都是公开的 ——
        'field_magic_updated': {'player_id': 'p1', 'card': {'name': '伊甸园', 'type': '场地'}},
        # —— 其余事件的真实形状（都不含坐标；下面仍逐个断言）——
        'attacks_updated': {'current_attacker': 'p1', 'attacks_remaining': 4},
        'turn_change': {'current_attacker': 'p2', 'attacks_remaining': 5, 'phase': 'preparation'},
        'turn_skipped': {'skipped': 'p1', 'current_attacker': 'p2', 'round': 5},
        'phase_updated': {'current_phase': 'battle', 'current_attacker': 'p1'},
        'chain_resolved': {'results': [{'card': {'name': '卧薪尝胆'}, 'caster': 'p1',
                                        'success': True}]},
        'game_over': {'winner': 'p1', 'reason': 'normal'},
        'game_canceled': {'reason': 'opponent_disconnected', 'message': '对局已取消'},
        'game_message': {'message': '回光返照：棋盘已重摆', 'type': 'info'},
        'chat_message': {'username': 'p1', 'message': '你好', 'isMe': False},
        'dice_rolled': {'roll': 4, 'caster': 'p1', 'effect_text': '恢复一艘战舰'},
        'dice_discard_complete': {},
        'trap_expired': {'player': 'p1'},
        'lanyu_recalled': {'player': 'p1', 'count': 2},
        'reinforcement_activated': {'remaining_turns': 3},
        'reinforcement_turn_updated': {'remaining_turns': 2},
        'holy_heart_activated': {'remaining_turns': 3},
        'holy_heart_interrupted': {'reason': '有船被击沉'},
        'holy_heart_turn_updated': {'remaining_turns': 2},
        'opponent_disconnected': {'player_id': 'p1', 'seconds': 30, 'deadline': 1.0},
        'opponent_reconnected': {'player_id': 'p1'},
    }


def _sample_for(event, room):
    """取这个事件的样例 payload。

    ⚠️ 表里没有的形状一律用 `{}` —— **不是**随便塞一份带坐标的 payload。
    塞坐标会让"给观众"的合法事件（比如 `attacks_updated`）被自己的守卫判红，
    而它本来就没有坐标可漏。真正的泄漏面在 `MUST_NOT_LEAK_COORDS` 那 5 个上，
    它们的样例由 `test_raw_payloads_would_have_leaked` 反向校准（证明样例里真有船位）。
    """
    return _payloads(room).get(event, {})


def test_no_position_leak_in_any_spectator_payload():
    """★ 守卫 (b)：表里每个"给观众"的事件净化后都不许泄漏船位。"""
    room = server.GameRoom('spectate-guard')
    server.room_manager.rooms[room.id] = room
    try:
        for event in sorted(spectate.SPECTATE_EVENTS):
            raw = _sample_for(event, room)
            clean = spectate.sanitize_event(event, raw, room=room.id)
            assert clean is not None, '表里说给观众，净化却返回了 None：%s' % event

            forbidden = set(spectate.FORBIDDEN_PAYLOAD_KEYS) & _collect_keys(clean)
            assert not forbidden, (
                '%s 净化后仍带这些字段：%s（payload=%r）' % (event, sorted(forbidden), clean)
            )

            for cell in _collect_coords(clean):
                assert cell in ALL_SHIP_CELLS or cell == PUBLIC_HIT_CELL \
                    or cell in PUBLIC_AREA_CELLS, \
                    '%s 出现了棋外的怪坐标 %r' % (event, cell)
                if event in spectate.MUST_NOT_LEAK_COORDS:
                    raise AssertionError(
                        '%s 净化后仍有坐标 %r —— 这个事件被钉了"零坐标"（payload=%r）'
                        % (event, cell, clean)
                    )
                assert cell == PUBLIC_HIT_CELL or cell in PUBLIC_AREA_CELLS, (
                    '%s 泄露了未被轰过的船坐标 %r（只允许出现已公开的被轰格 %r 与公开选区 %r）'
                    % (event, cell, PUBLIC_HIT_CELL, sorted(PUBLIC_AREA_CELLS))
                )
    finally:
        server.room_manager.rooms.pop(room.id, None)


def test_raw_payloads_would_have_leaked():
    """反向校准：**未净化**的原始 payload 里确实有船坐标，且是**没被轰过**的船位。

    没有这一条，上面那条可能是"因为样例本来就没坐标"而假绿
    （正是本项目教训 #34 说的"零报错制造假象"）。
    """
    room = server.GameRoom('spectate-guard-raw')
    server.room_manager.rooms[room.id] = room
    try:
        for event in spectate.MUST_NOT_LEAK_COORDS:
            raw = _sample_for(event, room)
            raw_cells = set(_collect_coords(raw))
            leaked = raw_cells - {PUBLIC_HIT_CELL} - PUBLIC_AREA_CELLS
            assert leaked, \
                '%s 的原始样例里居然没有可泄漏的船坐标 —— 这条守卫是空转的' % event
            assert leaked & ALL_SHIP_CELLS, '%s 的原始样例坐标没落在真实船位上' % event

        # 最要紧的一格：`shield_absorbed` 漏的是**从没挨过炮**的那一格 ——
        # 这才是"多送出去"的信息（单格船的样例看不出这个差别）。
        shield_raw = set(_collect_coords(_sample_for('shield_absorbed', room)))
        assert (5, 5) in shield_raw and (5, 5) != PUBLIC_HIT_CELL
        shield_clean = spectate.sanitize_event('shield_absorbed', _sample_for('shield_absorbed', room))
        assert not _collect_coords(shield_clean)
    finally:
        server.room_manager.rooms.pop(room.id, None)


def test_spectator_payloads_keep_the_action():
    """★ 反向断言：净化**不许把动作信息也砍掉**。

    防的是"为了安全把该给的也砍了" —— 那种改法不报错、只是观众什么都看不到
    （"看得到动作"退化成"看不到"），正是本批核心不变量 #2 的反面。
    """
    room = server.GameRoom('spectate-guard-action')
    server.room_manager.rooms[room.id] = room
    try:
        for event, required in spectate.MUST_KEEP_ACTION_FIELDS.items():
            raw = _sample_for(event, room)
            clean = spectate.sanitize_event(event, raw, room=room.id)
            assert clean is not None, '%s 不该被丢掉' % event
            for field in required:
                assert field in clean, (
                    '%s 净化后丢了动作字段 %r（只剩下 %r）—— '
                    '观众会从"看得到动作"变成"什么都看不到"' % (event, field, sorted(clean))
                )

        # 开炮那一条最要紧：**打哪儿、中没中**必须还在
        attack = spectate.sanitize_event('attack_result', _sample_for('attack_result', room))
        assert (attack['x'], attack['y']) == PUBLIC_HIT_CELL
        assert attack['hit'] is True and attack['attacker'] == 'p1'
        assert attack['attacker_remaining_ships'] == 6

        # 加盾那一条：删坐标，但"谁加了几艘"必须还在
        shields = spectate.sanitize_event('shields_added', _sample_for('shields_added', room))
        assert shields['player'] == 'p1' and shields['count'] == 6
        assert 'positions' not in shields

        # 陷阱 / 牺牲：归属与数量还在
        trap = spectate.sanitize_event('trap_triggered', _sample_for('trap_triggered', room))
        assert trap['owner'] == 'p1' and trap['sacrificed'] == 2
        assert 'sunk_positions' not in trap
        sac = spectate.sanitize_event('ship_sacrificed', _sample_for('ship_sacrificed', room))
        assert sac['player'] == 'p1' and sac['sacrificed_cells'] == len(BIG_SHIP_CELLS)

        # 连锁：卡名与"有没有被康"必须还在，`targets` 必须没了
        chain = spectate.sanitize_event('magic_chain_updated',
                                        _sample_for('magic_chain_updated', room))
        assert chain['chain_len'] == 2
        assert [c['card']['name'] for c in chain['chain']] == ['卧薪尝胆', '失灵！']
        assert all('targets' not in c for c in chain['chain'])
        assert chain['targets_dropped'] == 2
    finally:
        server.room_manager.rooms.pop(room.id, None)


def test_guard_b_actually_catches_a_raw_position_payload():
    """★ 元测试：证明守卫 (b) 真的能抓到泄漏（教训 #34）。

    把 `trap_set` 的净化函数临时改成"原样放行"（模拟"有人忘了净化"），
    守卫 (b) 的核心断言必须变红。
    """
    room = server.GameRoom('spectate-guard-negative')
    server.room_manager.rooms[room.id] = room
    try:
        raw = _sample_for('trap_set', room)
        original = spectate.SPECTATE_EVENTS['trap_set']

        clean = spectate.sanitize_event('trap_set', raw, room=room.id)
        assert not (set(_collect_coords(clean)) - {PUBLIC_HIT_CELL} - PUBLIC_AREA_CELLS), \
            '正常路径不该泄漏'

        spectate.SPECTATE_EVENTS['trap_set'] = None
        try:
            leaky = spectate.sanitize_event('trap_set', raw, room=room.id)
            leaked = [c for c in _collect_coords(leaky)
                      if c != PUBLIC_HIT_CELL and c not in PUBLIC_AREA_CELLS]
            assert leaked, '把净化关掉之后居然还是没泄漏 —— 这条守卫是空的'
            assert set(leaked) & ALL_SHIP_CELLS, '泄漏的坐标没落在真实船位上'
        finally:
            spectate.SPECTATE_EVENTS['trap_set'] = original

        again = spectate.sanitize_event('trap_set', raw, room=room.id)
        assert not (set(_collect_coords(again)) - {PUBLIC_HIT_CELL} - PUBLIC_AREA_CELLS)
    finally:
        server.room_manager.rooms.pop(room.id, None)


def test_guard_b_actually_catches_a_dropped_action_field():
    """★ 元测试之三：证明"动作被砍掉"也会被抓住（反向断言不是摆设）。

    把 `shields_added` 的净化函数换成"整条丢掉"，反向断言必须变红。
    """
    room = server.GameRoom('spectate-guard-negative-2')
    server.room_manager.rooms[room.id] = room
    try:
        original = spectate.SPECTATE_EVENTS['shields_added']
        # ⚠️ 签名里必须有 `room=None`：第 2 批起净化函数的统一契约是
        #    `fn(data, room=None)`（座位标签要用房间的座位顺序算）。
        #    这里只是替身，替身的签名跟着契约走 —— 断言本身一个字没改。
        spectate.SPECTATE_EVENTS['shields_added'] = lambda _data, room=None: None
        try:
            dropped = spectate.sanitize_event('shields_added', _sample_for('shields_added', room))
            assert dropped is None, '把净化换成"整条丢掉"之后应当拿不到 payload'
            with pytest.raises(AssertionError):
                # 这就是守卫 (b) 反向断言的第一句
                assert dropped is not None, 'shields_added 不该被丢掉'
        finally:
            spectate.SPECTATE_EVENTS['shields_added'] = original

        back = spectate.sanitize_event('shields_added', _sample_for('shields_added', room))
        assert back is not None and back['count'] == 6
    finally:
        server.room_manager.rooms.pop(room.id, None)


# ===========================================================================
# emit 的第三条腿：通道接对了没有
# ===========================================================================

@pytest.fixture
def emitters(monkeypatch):
    """记录两个出口（`semit` / `socketio.emit`）收到的 (事件名, 收件人, 房间)。

    `semit` 用"有没有请求上下文"来模拟真实行为：无上下文就抛 RuntimeError，
    逼 `emit` 走 `socketio.emit` 兜底 —— 两条出口都要能被观察到。
    """
    calls = {'semit': [], 'socketio': []}

    def fake_semit(event, data=None, to=None, room=None, **kw):
        if not fake_semit.has_ctx:
            raise RuntimeError('working outside of request context')
        calls['semit'].append((event, to, room))
        return 'semit-ok'

    def fake_socketio_emit(event, data=None, to=None, room=None, **kw):
        calls['socketio'].append((event, to, room))
        return 'socketio-ok'

    fake_semit.has_ctx = True
    monkeypatch.setattr(server, 'semit', fake_semit)
    monkeypatch.setattr(server.socketio, 'emit', fake_socketio_emit)
    calls['set_ctx'] = lambda v: setattr(fake_semit, 'has_ctx', v)
    return calls


def _all_calls(emitters):
    """把 `semit` 与 `socketio.emit` 两个出口的调用合成一条流。"""
    return list(emitters['semit']) + list(emitters['socketio'])


def _spectate_targets(calls):
    """这些调用里，收件房间是观战通道的那些。"""
    return [(event, to, room) for (event, to, room) in calls
            if room and str(room).startswith(spectate.SPECTATE_ROOM_PREFIX)]


def test_emit_sends_spectator_copy_to_its_own_room(emitters):
    """广播类事件要额外发一份给 `spectate:<room_id>`；一份发对局、一份发观战。"""
    room_id = 'SPECTEST1'
    server.room_manager.create_room(room_id)
    try:
        server.emit('attack_result', {'attacker': 'p1', 'x': 3, 'y': 5, 'hit': True},
                    room=room_id)
    finally:
        server.room_manager.delete_room(room_id)

    calls = _all_calls(emitters)
    rooms = sorted(room for (_e, _t, room) in calls if _e == 'attack_result')
    assert rooms == [room_id, 'spectate:' + room_id], \
        '应该正好两份：一份对局房间、一份观战通道，实际 %r' % (rooms,)
    assert _spectate_targets(calls) == [('attack_result', None, 'spectate:' + room_id)]


def test_emit_spectator_copy_works_on_the_socketio_fallback(emitters):
    """★ 无请求上下文（后台任务/定时器）时也必须走第三条腿。

    只改 `semit` 那条出口的话，超时交回合 / 连锁超时 / 掉线判负这些广播
    在观战端会整段消失 —— 观众看到的是"卡住了"。
    """
    room_id = 'SPECTEST2'
    server.room_manager.create_room(room_id)
    try:
        emitters['set_ctx'](False)          # 逼 emit 走 socketio.emit 兜底
        server.emit('game_over', {'winner': 'p1'}, room=room_id)
    finally:
        server.room_manager.delete_room(room_id)

    assert emitters['socketio'], '没走兜底出口，这条用例失去意义'
    fired = sorted(room for (e, _t, room) in emitters['socketio'] if e == 'game_over')
    assert fired == [room_id, 'spectate:' + room_id], \
        '兜底出口漏了观战通道：%r' % (fired,)


def test_emit_never_forwards_private_events_to_spectators(emitters):
    """不该给观众的事件（手牌、船位、重连令牌）一个都不许出现在观战通道。"""
    room_id = 'SPECTEST3'
    server.room_manager.create_room(room_id)
    try:
        for event in ('hand_updated', 'ships_updated', 'player_ships_updated',
                      'room_sync', 'game_state', 'revealed_positions',
                      'sacrifice_request', 'placement_request', 'reconnect_token',
                      'active_effects', 'board_attacks_updated'):
            server.emit(event, {'hand': [{'name': '卧薪尝胆'}],
                                'positions': [{'x': 0, 'y': 0}]}, room=room_id)
    finally:
        server.room_manager.delete_room(room_id)

    spectated = [e for (e, _t, _r) in _spectate_targets(_all_calls(emitters))]
    assert spectated == [], '这些私有事件被转给了观众：%s' % spectated


def test_emit_does_not_open_a_phantom_spectate_channel_for_a_sid(emitters):
    """`room=<某个 sid>` 不是对局房间 → 不许建 `spectate:<sid>` 幻影通道。

    全文件有 5 处把 `room=player.sid` 用错（其中 `hand_updated` 发的是完整手牌）。
    本批不许动那些调用点，所以门禁写在 `_live_room_id` 里 —— 这条用例钉住它。
    """
    server.emit('hand_updated', {'hand': [{'name': '卧薪尝胆'}]}, room='some-browser-sid')
    assert _spectate_targets(_all_calls(emitters)) == [], \
        '给 sid 发了观战副本 —— 手牌会躺在一个幻影观战通道里'


def test_emit_single_recipient_events_are_not_broadcast(emitters):
    """`to=<sid>` 的单发是私人消息，不该被复制到观战通道。"""
    room_id = 'SPECTEST4'
    server.room_manager.create_room(room_id)
    try:
        server.emit('attack_result', {'attacker': 'p1', 'x': 3, 'y': 5}, to='sid-p1',
                    room=room_id)
    finally:
        server.room_manager.delete_room(room_id)
    calls = _all_calls(emitters)
    assert ('attack_result', 'sid-p1', room_id) in calls
    assert _spectate_targets(calls) == [], '单发事件被复制给观众了'


def test_spectate_room_name_is_not_the_game_room():
    """观战通道名必须与对局 room 名不同 —— 这是"不透视"的地基。"""
    assert spectate.spectate_room_id('abc123') != 'abc123'
    assert spectate.is_spectate_room(spectate.spectate_room_id('abc123'))
    assert not spectate.is_spectate_room('abc123')
    assert not spectate.is_spectate_room(None)


# ===========================================================================
# 观战开关判据
# ===========================================================================

def test_can_spectate_requires_both_sides():
    """观战开关：**双方都允许**才算允许；未知一律当不允许（朝安全那边兜）。"""
    assert spectate.can_spectate(True, True) is True
    assert spectate.can_spectate(True, False) is False
    assert spectate.can_spectate(False, True) is False
    assert spectate.can_spectate(False, False) is False
    # 读不到设置（游客 / 数据库缺失）不许退化成"允许"（教训 #21）
    assert spectate.can_spectate(None, True) is False
    assert spectate.can_spectate(True, None) is False
    assert spectate.can_spectate(None, None) is False
    assert spectate.can_spectate(0, 1) is False
    assert spectate.can_spectate('yes', 'yes') is True


def test_spectate_module_does_not_import_server():
    """`spectate.py` 不许在运行期 import server（教训 #19）。"""
    src = io.open(REPO_ROOT / 'spectate.py', encoding='utf-8').read()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            assert all(alias.name != 'server' for alias in node.names), \
                'spectate.py 不许 import server'
        elif isinstance(node, ast.ImportFrom):
            assert node.module != 'server', 'spectate.py 不许 from server import'
