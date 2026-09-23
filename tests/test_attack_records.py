# -*- coding: utf-8 -*-
"""★★ 穷举守卫：**"写 `Player.attacks` / 发 `attack_result`"的每一个点都必须有交代**。

作者要求（2026-09-24 第 7 处批）：
> grep **全部**会写 `Player.attacks` / 会 `emit('attack_result')` / 会做"多格一次攻击"的地方，
> **逐个表态**：它的格子会不会出现在回放的标记里？走的哪条路？
> 然后加一条**源码级穷举守卫**：所有"写 attacks / 发 attack_result"的位置都必须在登记表里
> 有交代（新出现的攻击点没登记 ⇒ **红**）。登记按**函数名 + 内容特征**，**不要按行号**。

## 这批之前的状态

回放的棋盘标记是从 `type='attack'` 的**游戏日志步**反推的，而**只有普通炮击**写那种日志
（`handle_attack` 的 `add_game_log(..., 'attack', ...)`）。于是"写 `caster.attacks` 但不写
attack 日志"的那些点，打出的格子在回放里**一个标记都没有**（作者实报："看着是没挨过炮的海面"）。

修法（本批定的口径，**这一份实现**）：回放的标记收敛到一条**稀疏 + 增量**的 `attacks`
时间线，数据源 = `Player.attacks`（与观战棋盘帧同一份权威动作记录）。
"谁写 `attacks`"于是**自动**进时间线（`replay._record_snapshot` 比上一次快照取新增的格），
**不需要**每个点单独登记 —— 所以这条穷举守卫守的不是"谁会画出来"，而是：

1. **穷举**：扫 `server.py` 里所有 `X.attacks` 的写入点（`append` / `extend` / `insert` /
   `remove` / `clear` / 下标赋值 / 整体重建）与所有 `emit('attack_result', ...)` 的调用点，
   **每一处**都必须在 `ATTACK_SITES` 里有交代（按**函数名 + 容器 + 操作 + 卡片分支**登记，
   **不按行号** —— 行号每次提交都会漂移）；
2. **例外不许烂在原地**：登记表里每条都要有**非空理由**，而且它指向的代码**必须还在**
   （找不到就红：删了代码却留着例外，下次有人新增同类写法时它就成挡箭牌）；
3. **"只在回放内部走一遍"**：`attacks` 时间线的键必须来自 `replay._side_label`
   （同一份口径），有一个用例专门钉住这件事 —— 它是"两份 id 空间串味"的老病根
   （CLAUDE.md 教训 #20）。
"""
import ast
import io
import pathlib

import pytest

import replay
import server

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER_PY = REPO_ROOT / 'server.py'

#: 写入点所属的"成因"——每条登记都必须归到其中一类。
#:
#: * `timeline`  —— 写进 `Player.attacks`，**自动**进回放的 `attacks` 时间线（本批修好之后的口径）；
#: * `single`    —— 只对**一个乘客**生效的写入（`_clear_attacks_on_cells` 那种"撤掉一格"），
#:                  回放侧由 `board_resets` 负责擦除（不是"记一笔"）；
#: * `fixture`   —— 调试事件 / 测试夹具（`ENABLE_TEST_EVENTS=1` 才有），不进真对局；
#: * `reset`     —— 整体清空（棋盘整块换新 / 布船阶段重建），旧账由 `note_board_reset` 撤。
KINDS = ('timeline', 'clear', 'fixture', 'reset')

#: 穷举登记表 —— **一个"写 attacks / 发 attack_result"的点一条**。
#:
#: 每条：`{fn, container, ops, card, kind, why}`：
#:   * `fn` / `container` / `card` —— 这个点是谁（`container` = `.attacks` 的持有者名；
#:     `card` = 最近一层 `card.name == '…'` 的字面量，`apply_magic_effect` 一个函数里有
#:     6 个点，只有卡片名能钉住它们）；
#:   * `ops` —— 用到的操作（`append` / `remove` / `setitem` / `reassign` / `emit`）；
#:   * `why` —— **为什么它在这个类里**（非空）。
ATTACK_SITES = [
    # ---- ① 写进 Player.attacks：自动进回放的 attacks 时间线 ----
    dict(fn='handle_attack', container='players', ops=['append'], card=None, kind='timeline',
         why='普通炮击（唯一的"两条腿都有"的点：既 append `attacker.attacks`，又写 attack 日志）'),
    dict(fn='apply_magic_effect', container='caster', ops=['append'], card='溅射',
         kind='timeline',
         why='★ 本批一并查出来的第 3 处：【溅射】逐格写 `caster.attacks`（四格）但**不写** '
             'attack 日志 —— 改前那四格在回放里一个标记都没有'),
    dict(fn='apply_magic_effect', container='caster', ops=['append'], card='雷达子弹',
         kind='timeline',
         why='★ 第 4 处：【雷达子弹】逐格写周围八格（未命中的那些），同样不写 attack 日志'),
    dict(fn='apply_magic_effect', container='caster', ops=['append'], card='探测雷达',
         kind='timeline',
         why='★ 第 5 处：【探测雷达】逐格写 2×2 里落空的格，同样不写 attack 日志'),
    dict(fn='apply_magic_effect', container='caster', ops=['append'], card='轰炸',
         kind='timeline',
         why='★ 本批修的缺陷本身（第 7 处）：整行/整列 6 格逐格写 `caster.attacks`，'
             '两条循环（命中的 + 落空的）都写'),
    dict(fn='apply_magic_effect', container='caster', ops=['append'], card='硫磺火焰',
         kind='timeline',
         why='★ 同上（整列 6 格），与轰炸是同一形状的两个实现点'),
    dict(fn='test_auto_attack', container='players', ops=['append'], card=None, kind='fixture',
         why='调试事件（`ENABLE_TEST_EVENTS=1` 才有）：它自己造了一个匿名类当 Position，'
             '不进真对局；回放侧一旦被它调用也走同一条时间线'),
    # ---- ② 撤掉某几格（"这一格不再算打过"）：回放由 board_resets 擦 ----
    dict(fn='_clear_attacks_on_cells', container='players', ops=['reassign'], card=None,
         kind='clear',
         why='疗愈复活 / 增援 / 死者苏生 / 滥竽充数 / 神机妙算共用的**唯一**清格入口；'
             '它调 `replay.note_board_reset(room, board_owner_id)`，回放靠那一条擦除'
             '（`tests/test_replay_bomb_marks.py` 有用例钉住"擦除是 board_resets 的活"）'),
    # ⚠️ 下面这些是**间接**点：它们自己**不**直接碰 `attacks`，而是调上面那个入口
    #    （`_revive_sunken_ships` / `handle_confirm_reinforcement` 共 5 处），
    #    或者走整体重建（布船阶段）。它们**不在扫描结果里**，所以也**不许**出现在
    #    登记表里（"例外表不许烂在原地"：登记表只登记**扫得到**的点）。
    #    —— 本批第一版把这三条写进了表里，被"指向不存在的代码"那条腿当场红掉。
    # ---- ③ 整体清空：棋盘整块换新（`attacks = []`） ----
    dict(fn='confirm_magic_target', container='player', ops=['reassign'], card=None,
         kind='reset',
         why='灵气复苏：双方 `attacks = []` + `replay.note_board_reset(room)`（双方）'),
    dict(fn='apply_magic_effect', container='player', ops=['reassign'], card='败者食尘',
         kind='reset',
         why='败者食尘：双方清空 + `note_board_reset(room)`'),
    dict(fn='apply_magic_effect', container='players', ops=['reassign'], card='回光返照',
         kind='reset',
         why='回光返照：只清施法者那一块 + `note_board_reset(room, caster_id)`'
             '（`room.players[opponent_id].attacks = []` 那种下标持有 = 容器名 `players`）'),
    dict(fn='__init__', container='self', ops=['reassign'], card=None, kind='fixture',
         why='`Player.__init__` 的 `self.attacks = attacks` —— 构造器，不是对局里的写入'),
    dict(fn='test_reset_game', container='player', ops=['reassign'], card=None, kind='fixture',
         why='调试事件清空（ENABLE_TEST_EVENTS=1 才有）'),
]

#: `emit('attack_result', ...)` 的调用点（按函数名 + 次数）。
#:
#: ⚠️ **这批不改它**：实战前端就靠这条事件逐格画叉，回放侧**不读**它
#:    （回放读的是 `Player.attacks` 那条时间线）。列在这里是为了"新增一个发
#:    `attack_result` 的攻击点"时能被点到名上 —— 那个点八成也写了 `attacks`。
EXPECTED_ATTACK_RESULT_SITES = {
    'handle_attack': 1,
    # 溅射 2 + 雷达子弹 1 + 轰炸 2 + 硫磺火焰 2 + 探测雷达 1 = 8？—— 实测是 7：
    # 《雷达子弹》那一支的发送点在 `if hit: continue` 之后，落空格才发。
    'apply_magic_effect': 7,
}


def _src(path):
    return io.open(path, encoding='utf-8').read()


def _tree(path):
    return ast.parse(_src(path))


def _parent_map(tree):
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    return parent


def _scanner():
    """扫出 `server.py` 里所有"写 `X.attacks`"与"`emit('attack_result', ...)`"的点。"""
    src = _src(SERVER_PY)
    tree = ast.parse(src)
    parent = _parent_map(tree)

    def owner_fn(node):
        cur = node
        while cur is not None:
            cur = parent.get(cur)
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return cur.name
        return '<module>'

    def card_branch(node):
        cur = node
        while cur is not None:
            cur = parent.get(cur)
            if isinstance(cur, (ast.If, ast.While)):
                seg = ast.get_source_segment(src, cur.test) or ''
                for quote in ("'", '"'):
                    head = 'name == ' + quote
                    if head in seg:
                        rest = seg.split(head, 1)[1]
                        if quote in rest:
                            return rest.split(quote, 1)[0]
        return None

    def attacks_owner(node):
        """`X.attacks` 里的 `X` 标识（`room.players[...]` 这种下标持有也认出来）。"""
        if not (isinstance(node, ast.Attribute) and node.attr == 'attacks'):
            return None
        base = node.value
        while isinstance(base, ast.Subscript):
            base = base.value
        return getattr(base, 'id', None) or getattr(base, 'attr', None)

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and attacks_owner(fn.value) \
                    and fn.attr in ('append', 'extend', 'insert', 'remove', 'pop', 'clear'):
                found.append(dict(fn=owner_fn(node), container=attacks_owner(fn.value),
                                  op=fn.attr, card=card_branch(node), line=node.lineno))
            # emit('attack_result', ...)
            if getattr(fn, 'id', None) == 'emit' and node.args \
                    and isinstance(node.args[0], ast.Constant) \
                    and node.args[0].value == 'attack_result':
                found.append(dict(fn=owner_fn(node), container='emit', op='emit',
                                  card=card_branch(node), line=node.lineno))
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Subscript) and attacks_owner(t.value):
                    found.append(dict(fn=owner_fn(node), container=attacks_owner(t.value),
                                      op='setitem', card=card_branch(node), line=node.lineno))
                elif attacks_owner(t):
                    found.append(dict(fn=owner_fn(node), container=attacks_owner(t),
                                      op='reassign', card=card_branch(node), line=node.lineno))
        elif isinstance(node, ast.AugAssign) and attacks_owner(node.target):
            found.append(dict(fn=owner_fn(node), container=attacks_owner(node.target),
                              op='augassign', card=card_branch(node), line=node.lineno))
    return src, found


def _key(site):
    return (site['fn'], site['container'], site['card'])


def test_every_attack_write_site_is_registered():
    """★★ 穷举：每个"写 attacks / 发 attack_result"的点都必须在 `ATTACK_SITES` 里有交代。

    两条腿都会红：
      · **新增**一个攻击点（例如把某处 `caster.attacks.append(...)` 复制到新函数里，
        或者新写一张"多格一次攻击"的卡）⇒ 左腿红；
      · 从表里**删**一条 ⇒ 右腿红（"指向不存在的代码"）。
    """
    src, found = _scanner()
    assert len(found) >= 20, '扫描只找到 %d 个点 —— 扫描器坏了？' % len(found)

    # ⚠️ `emit('attack_result', ...)` 那批**不参与左腿的逐点比对**（它们的身份是"哪个函数里
    #    的第几次发送"，不是"谁写 attacks"）—— 由
    #    `test_attack_result_emit_sites_are_registered` 按函数名 + 次数守。
    found = [s for s in found if s['container'] != 'emit']

    site_key = {_key(e): e for e in ATTACK_SITES}
    assert len(site_key) == len(ATTACK_SITES), '登记表里有重复条目（同函数+容器+卡片）'

    unregistered, bad_ops = [], []
    for s in found:
        entry = site_key.get(_key(s))
        if entry is None:
            unregistered.append(s)
        elif s['op'] not in entry['ops']:
            bad_ops.append((s, entry))

    assert not unregistered, (
        '这些"写 attacks / 发 attack_result"的点没有在 ATTACK_SITES 里交代'
        '（新写法？漏登记？）：\n'
        + '\n'.join('  %s:%d  op=%s card=%s' % (s['fn'], s['line'], s['op'], s['card'])
                    for s in unregistered))
    assert not bad_ops, (
        '登记条目的 `ops` 与实际代码对不上（换写法了？）：\n'
        + '\n'.join('  %s:%d 实际 %s，登记 %s' % (s['fn'], s['line'], s['op'], e['ops'])
                    for (s, e) in bad_ops))

    scanned_keys = {_key(s) for s in found if s['container'] != 'emit'}
    stale = [k for k in site_key if k not in scanned_keys]
    assert not stale, (
        '登记表里有**指向不存在的代码**的条目（例外表烂在原地了 —— 删了代码却留着例外，'
        '下次有人新增同类写法时它就成挡箭牌）：\n' + '\n'.join('  %s' % (k,) for k in stale))


def test_attack_result_emit_sites_are_registered():
    """★ `emit('attack_result', ...)` 的点**逐个点名**（回放不读它，但新点必须表态）。"""
    _src_, found = _scanner()
    tally = {}
    for s in found:
        if s['container'] == 'emit':
            tally[s['fn']] = tally.get(s['fn'], 0) + 1
    assert tally == EXPECTED_ATTACK_RESULT_SITES, (
        '`attack_result` 的发送点变了 —— 回放不读它，但新增一个发它的地方必须先想清楚'
        '那个点有没有写 `Player.attacks`：\n  实际：%s\n  期望：%s'
        % (dict(sorted(tally.items())), dict(sorted(EXPECTED_ATTACK_RESULT_SITES.items()))))


def test_registry_kinds_and_reasons_are_valid():
    """★ 每条登记都要归到已知成因之一，且理由**非空**。"""
    for entry in ATTACK_SITES:
        assert entry.get('kind') in KINDS, entry
        assert (entry.get('why') or '').strip(), '登记条目没写理由：%s' % (entry,)
        assert entry.get('ops'), '登记条目没写用了哪些操作：%s' % (entry,)


def test_the_replay_marker_timeline_is_the_only_reader():
    """★★ 回放的标记**只有一份读者**：`replay._attack_cells`（读 `Player.attacks`）。

    判据（源码级）：`_attack_cells` 必须存在，且它是 `replay.py` 里**唯一**遍历
    `player.attacks` 的地方；`replay.build()` 必须产出 `attacks` 键。
    """
    src = _src(pathlib.Path(replay.__file__))
    tree = ast.parse(src)
    parent = _parent_map(tree)
    # `Player.attacks` 的实际读法：`_attack_cells` 里那句 `getattr(player, 'attacks', None)`
    holders = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'getattr' \
                and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                and node.args[1].value == 'attacks':
            cur = node
            while cur is not None:
                cur = parent.get(cur)
                if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    holders[cur.name] = holders.get(cur.name, 0) + 1
                    break
    assert holders, '`replay.py` 里没有任何地方读 `player.attacks` —— 时间线接丢了？'
    assert set(holders) == {'_attack_cells'}, (
        '读 `player.attacks` 的地方必须只有 `_attack_cells`（一份数据一份读者）：%s' % holders)


def test_build_payload_carries_the_attacks_timeline():
    """★★ `replay.build()` 必须产出 `attacks` 键（前端读它，缺了就永远画不出标记）。"""

    class _P:
        pass

    room = _P()
    room.players = {}
    room.game_logs = []
    payload = replay.build(room)
    assert 'attacks' in payload, '`replay.build()` 没有产出 `attacks` 时间线'
    assert isinstance(payload['attacks'], list)


def test_the_timeline_key_comes_from_the_side_label():
    """★★★ 时间线的键必须来自 `replay._side_label`（**同一份口径**，不许另算一套）。

    为什么单列一条：这份数据的键是**座位代号**，而"谁算这个代号"一旦长出第二份实现，
    症状是"标记画到对调的那块棋盘上"——不抛异常、不报错（第 6 批观战批的原病根，
    CLAUDE.md 教训 #20：判据的输入必须来自同一套 id 空间）。
    """
    src = _src(pathlib.Path(replay.__file__))
    body = None
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == '_record_snapshot':
            body = ast.get_source_segment(src, node) or ''
    assert body, '找不到 `_record_snapshot`'
    assert "_side_label(room, pid)" in body, (
        '`attacks` 行的键必须用 `_side_label(room, pid)` 算（与观战 / 船位时间线同一份口径）')
    # 反向校准：座位代号映射只有 `_side_label` 一处（`you_are` 那次是**另一件事**：
    # 它按 `seats` 里已存的代号取值，不重新算），所以按"算代号"的写法数：
    assert src.count("return 'p%d' % (idx + 1)") == 1, (
        '座位代号的**计算**必须只有一处（`_side_label`）；第二处就是"两份 id 空间"的开端')
