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

def _mk_player(attacks=(), revealed=(), ships=None):
    return SimpleNamespace(
        attacks=[Position(x, y) for x, y in attacks],
        revealed_positions=[Position(x, y) for x, y in revealed],
        ships=list(ships or []),
    )


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


def test_attack_returns_none_when_board_exhausted():
    """36 格全轰过 → None（不能抛异常）。"""
    me = _mk_player(attacks=[(x, y) for x in range(6) for y in range(6)])
    room = _mk_room(me, _mk_player())
    assert ai_brain.choose_attack(room, AI, random.Random(0)) is None


def test_attack_skips_already_attacked_revealed_cells():
    """已探明但**已经打过**的格子要排除，否则会空耗一次攻击。"""
    me = _mk_player(attacks=[(5, 5)], revealed=[(5, 5)])
    room = _mk_room(me, _mk_player())
    assert ai_brain.choose_attack(room, AI, random.Random(0)) != (5, 5)


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


def test_no_cheating_source_level():
    """★ 源码级：模块里不许出现 `.ships` / `.magic_hand` / `.magic_deck` 访问。

    行为测试只覆盖跑到的分支；这条管住没跑到的。两种访问形式都要查：
    属性访问 `x.ships`，以及 `getattr(x, 'ships', ...)`。
    """
    src = io.open(AI_BRAIN_PATH, encoding='utf-8').read()
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRS:
            offenders.append((node.lineno, 'x.%s' % node.attr))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == 'getattr' and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in FORBIDDEN_ATTRS):
            offenders.append((node.lineno, "getattr(x, %r)" % node.args[1].value))
    assert not offenders, (
        'ai_brain.py 里出现了越权读取（AI 不许看对方的私有状态）: %s' % offenders)


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


def test_ship_pick_prefers_the_least_informative_ship():
    """要被牺牲/暴露时，挑「周围已被对方轰过」的那艘 —— 那片区域对方已经探过。"""
    me = _mk_player()
    # 对方轰过 (2,2) 一带，(5,5) 一带没碰过
    opp = _mk_player(attacks=[(1, 1), (1, 2), (2, 1), (2, 2), (3, 3)])
    room = _mk_room(me, opp)
    probed_ship = _mk_ship((2, 2))
    untouched_ship = _mk_ship((5, 5))
    picked = ai_brain.resolve_ship_pick(room, AI, 'demon_contract',
                                        [untouched_ship, probed_ship],
                                        random.Random(0))
    assert picked is probed_ship


def test_ship_pick_none_on_empty_candidates():
    room = _mk_room(_mk_player(), _mk_player())
    assert ai_brain.resolve_ship_pick(room, AI, 'demon_contract', [], None) is None
    assert ai_brain.resolve_ship_pick(room, AI, 'demon_contract', None, None) is None


def test_ship_pick_works_before_opponent_ever_fired():
    """对方一炮没开时不能崩（没有信息可用 → 退化成可复现的随机）。"""
    room = _mk_room(_mk_player(), _mk_player())
    cands = [_mk_ship((0, 0)), _mk_ship((1, 1))]
    a = [ai_brain.resolve_ship_pick(room, AI, 'kraken_eye', cands, random.Random(s))
         for s in range(10)]
    b = [ai_brain.resolve_ship_pick(room, AI, 'kraken_eye', cands, random.Random(s))
         for s in range(10)]
    assert a == b
    assert all(s in cands for s in a)


# ---------------------------------------------------------------------------
# resolve_placement
# ---------------------------------------------------------------------------

def test_placement_prefers_cells_opponent_already_fired_at():
    """放在对方打过的格子上：他不能重复轰同一格，等于免挨打。"""
    opp = _mk_player(attacks=[(0, 0)])
    room = _mk_room(_mk_player(), opp)
    cands = [(2, 2), (0, 0), (4, 4)]
    assert ai_brain.resolve_placement(room, AI, 'reinforce', cands,
                                      random.Random(0)) == (0, 0)


def test_placement_only_returns_from_candidates():
    """各卡对候选格有各自限制，函数不做二次过滤，只在给定集合里挑。"""
    opp = _mk_player(attacks=[(0, 0)])
    room = _mk_room(_mk_player(), opp)
    cands = [(1, 1), (2, 2)]
    for seed in range(20):
        assert ai_brain.resolve_placement(room, AI, 'lanyu', cands,
                                          random.Random(seed)) in cands


def test_placement_none_on_empty():
    room = _mk_room(_mk_player(), _mk_player())
    assert ai_brain.resolve_placement(room, AI, 'reinforce', [], None) is None
    assert ai_brain.resolve_placement(room, AI, 'reinforce', None, None) is None


# ---------------------------------------------------------------------------
# choose_taunt
# ---------------------------------------------------------------------------

def test_taunt_returns_a_line_from_the_table():
    room = _mk_room(_mk_player(), _mk_player())
    for event, lines in ai_brain.TAUNT_LINES.items():
        got = ai_brain.choose_taunt(room, AI, event, random.Random(0))
        assert got in lines, 'event=%s 拿到的台词不在表里: %r' % (event, got)


def test_taunt_unknown_event_is_silent():
    room = _mk_room(_mk_player(), _mk_player())
    assert ai_brain.choose_taunt(room, AI, 'nonsense', random.Random(0)) is None
    assert ai_brain.choose_taunt(room, AI, None, random.Random(0)) is None


def test_taunt_table_is_non_empty_and_unique_per_event():
    for event, lines in ai_brain.TAUNT_LINES.items():
        assert lines, '%s 的台词表是空的' % event
        assert all(isinstance(x, str) and x.strip() for x in lines), event


# ---------------------------------------------------------------------------
# 残缺状态安全
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('bad_room', [
    None,
    SimpleNamespace(),                          # 没有 players
    SimpleNamespace(players=None),
    SimpleNamespace(players={}),                # 里面没这个人
])
def test_broken_room_degrades_gracefully(bad_room):
    """残缺房间绝不能抛异常；而且**选船/放置必须仍然给出一个候选**。

    ⚠️ 这两个为什么不能返回 None —— 它们回答的是「AI 自己的待办」。
       返回 None 会让那个待办**没人消费** → AI 的回合永远交不出去。
       这正是 `docs/MASTER_AI_2026_09_21.md` §5.1 要消灭的失败模式，
       所以信息不足时应当退化成「可复现的随机」，而不是放弃。

    `choose_attack` 不同：没有可打的格返回 None 是对的 —— 调用方据此
    去进结束阶段，不会留下待办。
    """
    assert ai_brain.choose_attack(bad_room, AI, random.Random(0)) is None
    # choose_taunt 只看 event、不碰房间状态 → 坏房间照样给得出台词
    assert ai_brain.choose_taunt(bad_room, AI, 'behind',
                                 random.Random(0)) in ai_brain.TAUNT_LINES['behind']
    assert ai_brain.choose_taunt(bad_room, AI, 'no_such_event',
                                 random.Random(0)) is None
    # ↓ 这两个必须仍然给得出东西（哪怕房间是坏的）
    assert ai_brain.resolve_ship_pick(bad_room, AI, 'x', [_mk_ship((0, 0))],
                                      random.Random(0)) is not None
    assert ai_brain.resolve_placement(bad_room, AI, 'x', [(0, 0)],
                                      random.Random(0)) is not None


@pytest.mark.parametrize('bad_room', [None, SimpleNamespace(players=None)])
def test_broken_room_still_only_returns_real_candidates(bad_room):
    """退化成随机也不能凭空造一艘船出来 —— 只能从候选里挑。"""
    cands = [_mk_ship((0, 0)), _mk_ship((4, 4))]
    for seed in range(20):
        got = ai_brain.resolve_ship_pick(bad_room, AI, 'x', cands,
                                         random.Random(seed))
        assert got in cands


def test_functions_survive_player_missing_fields():
    """players 里的对象缺少 attacks / revealed_positions 也不能崩。"""
    bare = SimpleNamespace()
    room = SimpleNamespace(players={'AI': bare, 'HUMAN': bare})
    assert isinstance(ai_brain.choose_attack(room, AI, random.Random(0)), tuple)
    assert ai_brain.resolve_ship_pick(room, AI, 'x', [_mk_ship((0, 0))],
                                      random.Random(0)) is not None


def test_cell_of_accepts_dicts_and_objects():
    """revealed_positions 可能是 Position 对象也可能是 dict，两种都要认。"""
    assert ai_brain._cell_of(Position(3, 4)) == (3, 4)
    assert ai_brain._cell_of({'x': 3, 'y': 4}) == (3, 4)
    assert ai_brain._cell_of(None) is None
    assert ai_brain._cell_of({'x': 'a', 'y': 1}) is None


def test_known_enemy_cells_semantics():
    """语义方向：players[X].revealed_positions 是「X 知道的位置」。

    读反了就会拿对手的情报去打对手 —— 这里把方向钉住。
    """
    me = _mk_player(revealed=[(3, 3)])
    known = ai_brain._known_enemy_cells(me)
    assert known == {(3, 3)}
    assert ai_brain._known_enemy_cells(me, exclude={(3, 3)}) == set()
