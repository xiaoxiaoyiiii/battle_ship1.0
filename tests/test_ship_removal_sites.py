# -*- coding: utf-8 -*-
"""★ 穷举守卫：**"船从 `player.ships` 里消失 / 被替换"的每一个点都必须有交代**。

作者要求（2026-09-24 批）：
> 到现在为止，"船从 `player.ships` 里消失"已经长到 5 处了，靠人记是记不住的。
> 请 grep 全部可能的移除/替换写法，逐个点表态：它属于哪一类？该不该登记沉没？
> 然后加一条**源码级穷举守卫**：扫出所有这些位置，每个都必须在守卫的登记表里有交代
> （没登记的、或新出现的移除点 ⇒ 红）。

## 这一批之前的状态

回放的船位时间线（`replay._ship_cells`）只遍历 `player.ships`，所以**任何一个**
"把船从 `player.ships` 里摘掉"的地方，都会让那一格在回放里凭空消失。
前几批逐个修过四处（主动牺牲 / 绝处逢生 / 钢筋铁骨 / 滥竽充数**有意**消失），
本批修第五处（`神威！`致死）—— 但**靠人记是记不住的**：这五处之外还有几处
（轰炸 / 硫磺火焰）之所以一直没出事，只是因为它们**同时**产出了攻击步。

## 判据（本文件钉住的三件事）

1. **穷举**：扫 `server.py` 里所有对 `*.ships` 的 `remove` / `pop` / `del` / `clear` /
   `extend` / `insert` / **整体重建**（`x.ships = ...`）/ 下标赋值 —— 每一个点
   都必须在 `REMOVAL_SITES` 里有一条（**按函数名 + 容器变量 + 卡片分支**登记，
   **不按行号**：行号一定会漂移）；
2. **例外不烂在原地**：`REMOVAL_SITES` 里每个"不需要登记"的条目都要写明**非空理由**，
   而且它指向的那段代码**必须还在**（文件里找不到就判红 —— 删了代码却留着例外，
   下次有人新增同类写法的位置时，例外表就成了挡箭牌）；
3. **两个方向都要动**：新增一个移除点（或从表里删一条）⇒ 红；表里删一条 ⇒ 红。

## 合法的形状（先 grep 出全量再写判据，别误报）

* `Player.__init__` 里的 `self.ships = ships` —— **构造器**，不是移除；
* `test_set_player_ships` / `test_reset_game` / `test_set_opponent_ships` ——
  **调试事件**在换棋盘（`ENABLE_TEST_EVENTS=1` 才有），不是对局里的移除；
* 纯 `append`（复活 / 增援 / 神威归还…）—— **只增不减**，不产生"消失"；
* `handle_place_ships` / `_ai_place_ships` 的 `player.ships = []` —— **布船阶段**重建
  （对局还没开始 / 由 `note_board_replaced` 那一批覆盖的重摆路径）；
* 下标赋值 `x.ships[i] = ...` —— 全项目**一处都没有**（判据留着，出现了就红）。
"""
import ast
import io
import pathlib

import pytest

import replay
import server

# 只扫描 Player 的两个名字（`player` / `owner` / `caster` / 局部变量…），
# 排掉明显不是 Player 的容器（本项目里没有，留着给将来）：
_NON_PLAYER_CONTAINERS = ()

#: 五种成因（回放里"这一格不再有船"）—— 每条登记都必须归到其中一类。
#:
#: * `sink`       —— 游戏里双方看得见**沉没**（主动牺牲 / 自牺牲 / `神威！`致死）⇒ **要登记**；
#: * `attack`     —— 同时产出了攻击步（`attack_result` + `caster.attacks`）
#:                  ⇒ 回放的棋盘标记本来就会画成沉没，**不需要**再登记；
#: * `vanish`     —— **有意**消失（临时船收回 / 神威暂时除外）⇒ **绝不许**登记；
#: * `replace`    —— 棋盘整块换新 / 布船阶段重建 ⇒ 由 `note_board_replaced` 撤销旧账；
#: * `append`     —— 只增不减，不可能造成"消失"。
KINDS = ('sink', 'attack', 'vanish', 'replace', 'append')

#: 穷举登记表 —— **一个"改 ships 的地方"一条**。
#:
#: 每条：`{fn, container, ops, card, kind, need, why}`：
#:
#: * `fn` / `container` / `card` —— 这个点是谁：`container` = `.ships` 的持有者名
#:   （`player` / `caster` / `opponent` / `target_player` / `owner` / `self`…，
#:   同一函数里有多个移除点时靠它分开）；`card` = 最近一层 `card.name == '…'`
#:   的字面量（`apply_magic_effect` 一个函数里有 7 个点，只有卡片名能钉住它们）；
#: * `ops` —— 这个点用到的操作（`remove` / `pop` / `clear` / `extend` / `insert` /
#:   `delitem` / `setitem` / `reassign` / `augassign`）。同一个点可能"整体重建 + 逐艘 append"
#:   一起用，所以是一组；
#: * `kind` —— 属于哪种成因（见 `KINDS`）；
#: * `need` —— `'sink'` / `'replace'` 时要求调用方真的有登记调用（见
#:   `test_registration_calls_match_the_registry_one_for_one`）。
#:
#: ⚠️ **不按行号登记**：行号每次提交都会漂移（CLAUDE.md 开篇就写着）。
REMOVAL_SITES = [
    # ---- ① 主动牺牲 / 自牺牲：游戏里双方看得见沉没 ⇒ 必须登记 ----
    dict(fn='_do_demon_contract_sacrifice', container='player', ops=['remove'], card=None,
         kind='sink', need='sink',
         why='主动牺牲的唯一实现点（4 种 reason 全汇到这里）；紧挨着就是 `replay.note_ship_lost`'),
    dict(fn='apply_magic_effect', container='caster', ops=['remove'], card='绝处逢生',
         kind='sink', need='sink',
         why='`绝处逢生` 牺牲自己**全部**战舰（不走 `_do_demon_contract_sacrifice`）'),
    dict(fn='apply_magic_effect', container='caster', ops=['remove'], card='钢筋铁骨',
         kind='sink', need='sink',
         why='`钢筋铁骨` 牺牲一艘换无敌（同上）'),
    # ---- ② 神威！：致死那一支要登记；暂时除外那一支**绝不许**登记 ----
    dict(fn='apply_magic_effect', container='target_player', ops=['delitem'], card='神威！',
         kind='sink', need='sink',
         why='★ 本批修的第五处：致死那一支（`board != "self"` 且区域内恰好 1 艘）会 '
             '`_mark_ship_sunken`，**且不产生攻击步** ⇒ 不登记就凭空消失。'
             '同一行的"暂时除外"那一支**有意不登记**（下个大回合原样归还）'),
    # ---- ③ 同时产出攻击步：回放靠 attack 标记画红叉，**不需要**登记 ----
    dict(fn='apply_magic_effect', container='opponent', ops=['remove'], card='轰炸',
         kind='attack', need=None,
         why='轰炸逐格写 `caster.attacks`（`hit=True, ship_sunk=True`）并 emit `attack_result`。'
             '⚠️ 这两处**不写** `type="attack"` 的游戏日志 ⇒ 改前回放**画不出**这些格'
             '（第 7 处，作者实报）—— 本批已修：回放的标记收敛到 `attacks` 时间线'
             '（数据源 = `Player.attacks`），见 `docs/REPLAY_2026_09_23.md` §H'),
    dict(fn='apply_magic_effect', container='opponent', ops=['remove'], card='硫磺火焰',
         kind='attack', need=None,
         why='同上：逐格 `caster.attacks` + `attack_result`（不写 attack 日志；本批修好）'),
    # ---- ④ 有意消失：临时船收回 / 神威暂时除外 ⇒ 一格沉没标记都不许有 ----
    dict(fn='_recall_lanyu_ships', container='player', ops=['remove'], card=None,
         kind='vanish', need=None,
         why='滥竽充数临时船被大回合末强制收回，卡面明写"不会显示沉没"'),
    # ---- ⑤ 棋盘整块换新 / 布船阶段重建：由 `note_board_replaced` 撤掉旧账 ----
    dict(fn='confirm_magic_target', container='player', ops=['reassign'], card=None,
         kind='replace', need='replace',
         why='灵气复苏：双方棋盘整块换新（紧跟着 `replay.note_board_replaced(room)`）'),
    dict(fn='apply_magic_effect', container='player', ops=['reassign'], card='败者食尘',
         kind='replace', need='replace',
         why='败者食尘：双方棋盘清空重摆'),
    dict(fn='apply_magic_effect', container='caster', ops=['reassign'], card='回光返照',
         kind='replace', need='replace',
         why='回光返照：只重摆施法者那一块（`note_board_replaced(room, caster_id)`）'),
    dict(fn='handle_place_ships', container='players', ops=['reassign'], card=None,
         kind='replace', need=None,
         why='布船阶段重建棋盘（`room.players[player_id].ships = [...]`；'
             '`room.state` 还是 placing_ships，没有"沉没"可言）'),
    dict(fn='_ai_place_ships', container='player', ops=['reassign', 'append'], card=None,
         kind='replace', need=None,
         why='AI 座位布船：清空 + 逐艘 append，同上（布船阶段）'),
    # ---- ⑥ 只增不减 / 构造器：不可能造成"消失" ----
    dict(fn='__init__', container='self', ops=['reassign'], card=None, kind='append', need=None,
         why='`Player.__init__` 的 `self.ships = ships` —— 构造器，不是移除'),
    dict(fn='test_set_player_ships', container='player', ops=['reassign', 'append'],
         card=None, kind='append', need=None,
         why='调试事件换棋盘（`ENABLE_TEST_EVENTS=1` 才有）'),
    dict(fn='test_reset_game', container='player', ops=['reassign'], card=None,
         kind='append', need=None, why='调试事件清棋盘'),
    dict(fn='test_set_opponent_ships', container='opponent', ops=['reassign', 'append'],
         card=None, kind='append', need=None, why='调试事件换棋盘（对手侧）'),
    dict(fn='_revive_sunken_ships', container='player', ops=['append'], card=None,
         kind='append', need=None, why='疗愈原地复活：把船放回棋盘'),
    dict(fn='handle_confirm_reinforcement', container='caster', ops=['append'], card=None,
         kind='append', need=None, why='增援 / 死者苏生 / 神机妙算重新部署（5 处 append）'),
    dict(fn='_restore_due_shenwei', container='owner', ops=['append'], card=None,
         kind='append', need=None, why='神威！到期归还：把除外的船放回原位'),
]


def _card_branch_of(node, parent, src):
    """往上找最近一层 `X.name == '<卡名>'` 的判据（找不到返回 None）。

    ⚠️ **不按行号**登记：行号每次提交都会漂移（CLAUDE.md 开篇就写着）。
       卡片名是 `apply_magic_effect` 里唯一稳定的"这一节是谁"的标识。
    """
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
            if 'card.name' in seg:
                return seg.strip()[:60]
    return None


def _scan_ship_mutations():
    """扫出 `server.py` 里所有"改 `*.ships`"的点。

    判据只认**属性写法** `X.ships` 本身（含下标 `X.ships[i]`）：

    * `X.ships.remove(...)` / `.pop` / `.clear` / `.extend` / `.insert` / `.append`；
    * `del X.ships[i]`、`X.ships[i] = ...`；
    * `X.ships = ...`（整体重建）、`X.ships += ...`。

    ⚠️ **不认** `game_state['ships'] = ...` 这种**字典键**（`server.handle_place_ships`
      里就有一处：那是回给前端的会话快照，跟 `player.ships` 没有半点关系 ——
      本批第一版扫描器就是把它当成了"整体重建"而假红）。
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
                return cur.name
        return '<module>'

    def ships_attr(node):
        """`X.ships` 里的 `X` 标识（不是就返回 None）。

        `room.players[player_id].ships` 这种下标持有点也要认出来 —— 返回
        `'players'`（`room.players` 的属性名），而不是 `None`（本批实测：返回 None 时
        `handle_place_ships` 那一处会被漏掉，登记表就"指向不存在的代码"了）。
        """
        if not (isinstance(node, ast.Attribute) and node.attr == 'ships'):
            return None
        base = node.value
        while isinstance(base, ast.Subscript):
            base = base.value
        name = getattr(base, 'id', None) or getattr(base, 'attr', None)
        return name

    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and ships_attr(fn.value) \
                    and fn.attr in ('remove', 'pop', 'clear', 'extend', 'insert', 'append'):
                found.append(dict(fn=owner_fn(node), container=ships_attr(fn.value),
                                  op=fn.attr, card=_card_branch_of(node, parent, src),
                                  line=node.lineno,
                                  seg=(ast.get_source_segment(src, node) or '')[:90]))
        elif isinstance(node, ast.Delete):
            for t in node.targets:
                if isinstance(t, ast.Subscript) and ships_attr(t.value):
                    found.append(dict(fn=owner_fn(node), container=ships_attr(t.value),
                                      op='delitem', card=_card_branch_of(node, parent, src),
                                      line=node.lineno,
                                      seg=(ast.get_source_segment(src, node) or '')[:90]))
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Subscript) and ships_attr(t.value):
                    found.append(dict(fn=owner_fn(node), container=ships_attr(t.value),
                                      op='setitem', card=_card_branch_of(node, parent, src),
                                      line=node.lineno,
                                      seg=(ast.get_source_segment(src, node) or '')[:90]))
                elif ships_attr(t):
                    found.append(dict(fn=owner_fn(node), container=ships_attr(t),
                                      op='reassign', card=_card_branch_of(node, parent, src),
                                      line=node.lineno,
                                      seg=(ast.get_source_segment(src, node) or '')[:90]))
        elif isinstance(node, ast.AugAssign) and ships_attr(node.target):
            found.append(dict(fn=owner_fn(node), container=ships_attr(node.target),
                              op='augassign', card=_card_branch_of(node, parent, src),
                              line=node.lineno,
                              seg=(ast.get_source_segment(src, node) or '')[:90]))
    return src, found


def _key(site):
    """一个点的身份：**函数名 + 容器 + 操作 + 卡片分支**（不按行号）。"""
    return (site['fn'], site['container'], site['op'], site['card'])


def _registry_key(entry):
    """登记条目的身份（`ops` 是一组：同一个点可能 `reassign` + `append` 一起用）。"""
    return (entry['fn'], entry['container'], tuple(sorted(entry['ops'])), entry['card'])


def _removal_kind(op):
    """哪些操作会让船"消失"（`append` / `insert` / `extend` 只会让船变多）。"""
    return op in ('remove', 'pop', 'clear', 'delitem', 'setitem', 'reassign', 'augassign')


def test_every_ship_mutation_site_is_registered():
    """★★ 穷举守卫：每一个改 `*.ships` 的点都必须在 `REMOVAL_SITES` 里有交代。

    两条腿都会红：
      · **新增**一个移除点（例如把某处 `ships.remove` 复制到新函数里）⇒ 左腿红；
      · 从表里**删**一条 ⇒ 右腿红。
    """
    src, found = _scan_ship_mutations()
    assert len(found) >= 25, '扫描只找到 %d 个点 —— 扫描器坏了？' % len(found)

    site_key = {(e['fn'], e['container'], e['card']): e for e in REMOVAL_SITES}
    assert len(site_key) == len(REMOVAL_SITES), '登记表里有重复条目（同函数+容器+卡片）'

    unregistered, bad_ops = [], []
    for s in found:
        entry = site_key.get((s['fn'], s['container'], s['card']))
        if entry is None:
            unregistered.append(s)
        elif s['op'] not in entry['ops']:
            bad_ops.append((s, entry))

    assert not unregistered, (
        '这些"改 ships 的点"没有在 REMOVAL_SITES 里交代（新写法？漏登记？）：\n'
        + '\n'.join('  %s:%d  %s' % (s['fn'], s['line'], s['seg']) for s in unregistered))
    assert not bad_ops, (
        '登记条目的 `ops` 与实际代码对不上（换写法了？）：\n'
        + '\n'.join('  %s:%d 实际 %s，登记 %s'
                    % (s['fn'], s['line'], s['op'], e['ops']) for (s, e) in bad_ops))

    scanned = {(s['fn'], s['container'], s['card']) for s in found}
    stale = [k for k in site_key if k not in scanned]
    assert not stale, (
        '登记表里有**指向不存在的代码**的条目（例外表烂在原地了 —— 删了代码却留着例外，'
        '下次有人新增同类写法时它就成挡箭牌）：\n'
        + '\n'.join('  %s' % (k,) for k in stale))


def test_registry_kinds_are_from_the_known_five():
    """★ 每条登记都要归到五种成因之一，且理由**非空**。"""
    for entry in REMOVAL_SITES:
        assert entry.get('kind') in KINDS, entry
        assert (entry.get('why') or '').strip(), '登记条目没写理由：%s' % (entry,)
        assert entry.get('need') in (None, 'sink', 'replace'), entry
        assert entry.get('ops'), '登记条目没写它用了哪些操作：%s' % (entry,)
        # 只有"沉没"这一类才允许要求登记沉没（别的类要求登记就是分类写错了）
        if entry['need'] == 'sink':
            assert entry['kind'] == 'sink', entry
        if entry['kind'] in ('vanish', 'append') and entry['need'] is not None:
            raise AssertionError('"有意消失"与"只增不减"这两类不许要求登记：%s' % (entry,))


def test_kind_matches_the_operation_shape():
    """★★ 方向守卫：分类必须与**操作形状**一致（两边的错法都当场红）。

    * `append` 类（只增不减 / 构造器 / 调试夹具）里**不许**混进"真移除"的操作
      （`remove` / `pop` / `delitem` / `clear`）—— 那是把"会消失的点"标成"不会消失"；
    * `vanish` 类反过来：**必须**是真移除（不然它凭什么"消失"）。
    """
    additive_ops = ('append', 'insert', 'extend')
    for entry in REMOVAL_SITES:
        if entry['kind'] == 'append':
            bad = [op for op in entry['ops'] if op not in additive_ops and op != 'reassign']
            assert not bad, (
                '把"会移除船"的操作归成了"只增不减"：%s（操作 %s）' % (entry, bad))
        if entry['kind'] in ('vanish', 'sink', 'attack'):
            assert any(_removal_kind(op) for op in entry['ops']), (
                '这一类的操作必须是"真的会把船弄没"的：%s' % (entry,))


def _note_ship_lost_call_sites():
    """`replay.note_ship_lost(...)` 的全部调用点所在的函数名。"""
    src = io.open(server.__file__, encoding='utf-8').read()
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
        if not (isinstance(fn, ast.Attribute) and fn.attr == 'note_ship_lost'
                and getattr(fn.value, 'id', None) == 'replay'):
            continue
        cur = node
        while cur is not None:
            cur = parent.get(cur)
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                hits.append(cur.name)
                break
    return hits


def test_registration_calls_match_the_registry_one_for_one():
    """★★ `note_ship_lost` 的调用点必须与登记表里 `need='sink'` 的条目**一一对应**。

    这条把"新增一处沉没登记"与"新增一个移除点"绑在一起：不更新登记表就没法通过。
    """
    hits = sorted(_note_ship_lost_call_sites())
    want = sorted(e['fn'] for e in REMOVAL_SITES if e['need'] == 'sink')
    assert hits == want, (
        '`note_ship_lost` 调用点与登记表对不上：\n  实际 %s\n  登记表 %s' % (hits, want))


def test_replace_registrations_match_the_registry_one_for_one():
    """★★ `note_board_replaced` 的调用点必须与 `need='replace'` 的条目一一对应。"""
    src = io.open(server.__file__, encoding='utf-8').read()
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
        if not (isinstance(fn, ast.Attribute) and fn.attr == 'note_board_replaced'
                and getattr(fn.value, 'id', None) == 'replay'):
            continue
        cur = node
        while cur is not None:
            cur = parent.get(cur)
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                hits.append(cur.name)
                break
    want = sorted(e['fn'] for e in REMOVAL_SITES if e['need'] == 'replace')
    assert sorted(hits) == want, (
        '`note_board_replaced` 调用点与登记表对不上：\n  实际 %s\n  登记表 %s'
        % (sorted(hits), want))


def test_no_site_reassigns_a_single_cell_of_ships():
    """★ 合法形状里**没有**这一种：全项目没有任何 `x.ships[i] = ...`。

    出现了就红（它同样是"换掉一艘船"，但不在任何既有成因里 —— 必须先想清楚再登记）。
    """
    src, found = _scan_ship_mutations()
    bad = [s for s in found if s['op'] in ('setitem', 'augassign')]
    assert not bad, '出现了新形状 `ships[i] = ...` / `ships += ...`：%s' % bad


def test_scanner_actually_sees_the_five_known_causes():
    """★ 自检：扫描器必须真的看得见"五种成因"各至少一个点（否则判据是空的）。"""
    src, found = _scan_ship_mutations()
    site_kind = {(e['fn'], e['container'], e['card']): e['kind'] for e in REMOVAL_SITES}
    kinds = set()
    for s in found:
        kind = site_kind.get((s['fn'], s['container'], s['card']))
        if kind:
            kinds.add(kind)
    missing = set(KINDS) - kinds
    assert not missing, '扫描结果里缺这几类成因（判据覆盖不到）：%s' % missing


def test_replay_side_registration_surface_is_small_and_named():
    """★ 回放侧的登记入口就这么几个（新增入口必须先想清楚它属于哪一类）。"""
    src = io.open(pathlib.Path(replay.__file__), encoding='utf-8').read()
    tree = ast.parse(src)
    public = sorted(n.name for n in tree.body
                    if isinstance(n, ast.FunctionDef) and not n.name.startswith('_'))
    for name in ('note_ship_lost', 'note_ship_returned', 'note_board_replaced',
                 'note_board_reset', 'refresh_ships'):
        assert name in public, '回放的登记入口 %s 不见了' % name
    # 不许再冒出第二个"记沉没"的入口（同一件事两份实现必然漂移 —— 教训 #1）
    sink_entries = [n for n in public if 'lost' in n or 'sunk' in n]
    assert sink_entries == ['note_ship_lost'], \
        '回放侧"记沉没"的入口必须只有一个：%s' % sink_entries
