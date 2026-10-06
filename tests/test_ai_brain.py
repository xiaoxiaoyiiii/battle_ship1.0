# -*- coding: utf-8 -*-
"""大师 AI 决策层 `ai_brain.py` 的纯函数测试。

两条最重要的守卫（见 `docs/MASTER_AI_2026_09_21.md` §4.1）：

  ① **行为级**：把对方船位改到别处、其余状态不变，
     `ai_brain` 的输出必须**完全一致**（说明它没偷看）。
  ② **源码级**：用 `ast` 断言模块里根本不存在
     `.ships` / `.magic_hand` / `.magic_deck` 这类访问。

第 ② 条是必须的：`pytest` 里 `ai_brain` 和 `server` 是同一进程的模块，
行为测试只能覆盖它**实际跑到**的分支；源码级断言才管得住
「今天没跑、明天会跑」的那些路径（CLAUDE.md 教训 #19 同型）。
"""
import ast
import io
import os
import random
from types import SimpleNamespace

import pytest

import ai_brain
from server import Position

AI_BRAIN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ai_brain.py')

# 只允许读「真人坐这个座位上也能看到」的信息。这几个属性都是私有的对方状态。
FORBIDDEN_ATTRS = {'ships', 'magic_hand', 'magic_deck', 'magic_temp_data'}


# ---------------------------------------------------------------------------
# 替身对象：ai_brain 是鸭子类型的，用最小替身同时也就框定了它只许碰哪些字段
# ---------------------------------------------------------------------------

def _mk_player(attacks=(), revealed=(), ships=None, remaining_ships=6,
               magic_hand=None):
    return SimpleNamespace(
        attacks=[Position(x, y) for x, y in attacks],
        revealed_positions=[Position(x, y) for x, y in revealed],
        ships=list(ships or []),
        remaining_ships=remaining_ships,
        magic_hand=list(magic_hand or []),
    )


def _mk_card(name):
    return SimpleNamespace(name=name)


def _mk_room(me, opp):
    return SimpleNamespace(players={'AI': me, 'HUMAN': opp})


def _mk_ship(*cells):
    return SimpleNamespace(positions=[Position(x, y) for x, y in cells])


AI, HUMAN = 'AI', 'HUMAN'


# ---------------------------------------------------------------------------
# choose_attack
# ---------------------------------------------------------------------------

def test_attack_prefers_revealed_cells():
    """已探明的敌船位置必须优先打（必中）——现状是一次都不读它。"""
    me = _mk_player(attacks=[(0, 0)], revealed=[(5, 5)])
    room = _mk_room(me, _mk_player())
    for seed in range(30):
        assert ai_brain.choose_attack(room, AI, random.Random(seed)) == (5, 5)


def test_attack_never_repeats_a_cell():
    """轰过的格子不能再轰（对局层也是这么算候选的）。"""
    attacked = [(x, 0) for x in range(6)]
    me = _mk_player(attacks=attacked)
    room = _mk_room(me, _mk_player())
    for seed in range(50):
        x, y = ai_brain.choose_attack(room, AI, random.Random(seed))
        assert y != 0, '打到了已经轰过的行'






def test_attack_is_deterministic_for_same_seed():
    me = _mk_player(attacks=[(0, 0)])
    room = _mk_room(me, _mk_player())
    a = [ai_brain.choose_attack(room, AI, random.Random(7)) for _ in range(5)]
    b = [ai_brain.choose_attack(room, AI, random.Random(7)) for _ in range(5)]
    assert a == b


# ---------------------------------------------------------------------------
# ★ 不作弊守卫
# ---------------------------------------------------------------------------

def test_no_cheating_behaviourally():
    """★ 把对方船位改到别处、其余状态不变 → 输出必须完全一致。

    这是「AI 没偷看对方船位」的行为级证明。若哪天有人为了「变强」
    去读 `opp.ships`，这条会立刻红。
    """
    me_a = _mk_player(attacks=[(0, 0), (1, 1)])
    me_b = _mk_player(attacks=[(0, 0), (1, 1)])          # 与 me_a 完全同状态

    def run(opp):
        room = _mk_room(me_a, opp)
        return [ai_brain.choose_attack(room, AI, random.Random(s)) for s in range(200)]

    opp_positions_v1 = [_mk_ship((2, 2)), _mk_ship((3, 4))]
    opp_positions_v2 = [_mk_ship((5, 0)), _mk_ship((0, 5))]
    seq1 = run(_mk_player(attacks=[(4, 4)], ships=opp_positions_v1))
    seq2 = run(_mk_player(attacks=[(4, 4)], ships=opp_positions_v2))
    assert seq1 == seq2, '对方船位变了输出就变了 —— ai_brain 在偷看对方棋盘'
    assert me_b.attacks == me_a.attacks  # 顺带确认替身没被改动




# ---------------------------------------------------------------------------
# resolve_ship_pick
# ---------------------------------------------------------------------------

def test_ship_pick_only_returns_from_candidates():
    """只能在调用方给的候选里挑（候选已滤掉沉船，选沉船等于零代价抵账）。"""
    me = _mk_player()
    room = _mk_room(me, _mk_player(attacks=[(1, 1)]))
    cands = [_mk_ship((0, 0)), _mk_ship((4, 4))]
    for seed in range(30):
        assert ai_brain.resolve_ship_pick(room, AI, 'demon_contract', cands,
                                          random.Random(seed)) in cands








# ---------------------------------------------------------------------------
# resolve_placement
# ---------------------------------------------------------------------------



def test_placement_only_returns_from_candidates():
    """各卡对候选格有各自限制，函数不做二次过滤，只在给定集合里挑。"""
    opp = _mk_player(attacks=[(0, 0)])
    room = _mk_room(_mk_player(), opp)
    cands = [(1, 1), (2, 2)]
    for seed in range(20):
        assert ai_brain.resolve_placement(room, AI, 'lanyu', cands,
                                          random.Random(seed)) in cands




# ---------------------------------------------------------------------------
# choose_taunt
# ---------------------------------------------------------------------------







# ---------------------------------------------------------------------------
# 残缺状态安全
# ---------------------------------------------------------------------------











# ---------------------------------------------------------------------------
# 牌价值表：必须覆盖每一张能摸到的卡
# ---------------------------------------------------------------------------

def test_value_table_covers_every_reachable_card():
    """★ 牌价值表漏一张的后果是**静默的**：那张牌价值恒为 0 → AI 永远不打它
    → 逐卡测试会红，但如果没写逐卡测试就完全看不出来。

    唯一允许缺席的是 `钢筋铁骨`：它在 `server.HIDDEN_CARD_NAMES` 里，
    建牌堆时就被剔除，双方都摸不到。
    """
    import json
    path = os.path.join(os.path.dirname(AI_BRAIN_PATH), 'static', 'magic_card.json')
    with io.open(path, encoding='utf-8') as f:
        names = {c['name'] for c in json.load(f)}

    import server
    hidden = set(getattr(server, 'HIDDEN_CARD_NAMES', set()) or set())
    missing = sorted(names - hidden - set(ai_brain.CARD_BASE_VALUE))
    assert not missing, '这些卡没登记价值（AI 会永远不打它们）: %s' % missing






# ---------------------------------------------------------------------------
# choose_card
# ---------------------------------------------------------------------------



def test_choose_card_only_returns_indices_it_was_given():
    me = _mk_player(magic_hand=[_mk_card('轰炸'), _mk_card('平等条约')])
    room = _mk_room(me, _mk_player())
    for seed in range(20):
        got = ai_brain.choose_card(room, AI, [1], random.Random(seed))
        assert got in (1, None)














# ---------------------------------------------------------------------------
# resolve_target
# ---------------------------------------------------------------------------

def test_resolve_target_area_matches_each_card_declared_size():
    """区域边长必须**按各卡自己的实现**，不是一律 3×3。

    ⚠️ 这条用例守的是一个真实的坑：`探测雷达` 的卡面与 `apply_magic_effect`
       都写 **2×2**，而第一版 `AREA_CARDS` 把三张卡一律当 3×3 处理 ——
       选区比卡面大一圈，多圈的格子会被白送（多显形 / 多扣船），
       而且**不报错**。所以断言写成"对着 `AREA_CARDS` 里声明的边长逐张验"。
    """
    room = _mk_room(_mk_player(), _mk_player())
    assert ai_brain.AREA_CARDS == {'神威！', '冻结', '探测雷达'}
    assert ai_brain.AREA_SIZE.get('探测雷达') == 2, '探测雷达卡面是 2*2'
    # ⚠️ AREA_CARDS 必须是**集合**：server 里要用它跟 LINE_CARDS/CELLS_CARDS 求并集。
    #    第一版把边长写进了 AREA_CARDS（dict）→ `dict | set` 抛 TypeError →
    #    被 readiness 的兜底 except 吞掉 → 大师一张牌都不出，而"被拒 0、卡死 0"
    #    看起来完全正常。这条断言就是那次事故的守卫。
    assert isinstance(ai_brain.AREA_CARDS, set)
    assert isinstance(ai_brain.LINE_CARDS, set)
    assert isinstance(ai_brain.CELLS_CARDS, set)
    _ = ai_brain.AREA_CARDS | ai_brain.LINE_CARDS | ai_brain.CELLS_CARDS
    for name, size in ai_brain.AREA_SIZE.items():
        assert name in ai_brain.AREA_CARDS, f'{name} 有尺寸但不在区域卡集合里'
        assert size >= 2, name
    for name, size in ai_brain.AREA_SIZE.items():
        got = ai_brain.resolve_target(room, AI, _mk_card(name))
        a = got['target_area']
        assert a['x2'] - a['x1'] == size - 1, f'{name} 宽度应为 {size}'
        assert a['y2'] - a['y1'] == size - 1, f'{name} 高度应为 {size}'
        assert 0 <= a['x1'] and a['x2'] < 6 and 0 <= a['y1'] and a['y2'] < 6, name






def test_resolve_target_line_is_a_valid_row_or_col():
    room = _mk_room(_mk_player(), _mk_player())
    got = ai_brain.resolve_target(room, AI, _mk_card('轰炸'))
    ln = got['target_line']
    assert ln['type'] in ('row', 'col')
    assert 0 <= ln['index'] < 6


def test_resolve_target_cells_returns_six_continuous_cells():
    room = _mk_room(_mk_player(), _mk_player())
    got = ai_brain.resolve_target(room, AI, _mk_card('硫磺火焰'))
    cells = [(c['x'], c['y']) for c in got['target_cells']]
    assert len(cells) == 6
    xs = sorted({c[0] for c in cells})
    ys = sorted({c[1] for c in cells})
    assert len(xs) == 1 or len(ys) == 1, '6 格必须连续: %s' % cells






# ---------------------------------------------------------------------------
# resolve_choice
# ---------------------------------------------------------------------------









# ---------------------------------------------------------------------------
# 新函数也要对残缺状态安全
# ---------------------------------------------------------------------------
