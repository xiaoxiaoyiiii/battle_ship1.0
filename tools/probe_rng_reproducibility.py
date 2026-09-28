# -*- coding: utf-8 -*-
"""专项诊断：**换掉 `ai_brain.choose_attack` 会不会破坏可复现性**。

【为什么单开一个工具】
`tools/master_aggression_ablation.py` 的 `no_intel` 档（把开炮换成"不看情报、
均匀撒"）实测**同一 seed 连跑两次结果不同**，而同脚本的 `baseline` 档两次完全一致。
这说明问题出在"替换 `choose_attack`"这条路上，不是整套度量坏了。

这类"度量工具自己不可复现"的问题必须先查清楚再谈任何数字：
CLAUDE.md 教训 #36 就是这个形状（同一 seed 连跑 6 次胜负都翻）。

本工具逐个变量地试：
  A. 原样（不换任何东西）—— 对照组
  B. 用**同样的实现**包一层 spy（返回值和 `_ORIGINAL` 一模一样）
  C. 换成 `_plain_attack`（均匀撒）
  D. 只用 `random.Random(0)` 的"确定性版"均匀撒

判据：A/B/D 必须两次完全一致；C 若不一致，就是它自己的随机源问题。

用法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/probe_rng_reproducibility.py --games 300 --seed 1
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.headless_game as hg          # noqa: E402
import ai_brain                            # noqa: E402
import random                              # noqa: E402

_ORIGINAL = ai_brain.choose_attack


def _same_spy(room, ai_id, rng=None):
    """与 `_ORIGINAL` **逐字节相同**的实现（用来隔离"换函数"这件事本身）。"""
    return _ORIGINAL(room, ai_id, rng)


def _plain_attack(room, ai_id, rng=None):
    """均匀撒 —— **故意**保留无参 `random.Random()`（这是被测的坏形状）。

    ⚠️ 这个函数是**反例**，不要"顺手修好"：它复现的是 `random.Random()` 的
       系统熵播种，用来证明"同一 seed 会跑出不同结果"。真正的工具
       （`tools/master_ablation.py` / `tools/master_aggression_ablation.py`）
       已经改成 `ai_brain._rng` 了，并由用例守着。
    """
    rng = rng or random.Random()
    me = (getattr(room, 'players', None) or {}).get(ai_id)
    if me is None:
        return None
    attacked = ai_brain._attacked_cells(me)
    cands = [c for c in ai_brain._all_cells() if c not in attacked]
    return rng.choice(sorted(cands)) if cands else None


def _plain_attack_seeded(room, ai_id, rng=None):
    """均匀撒，但用**注入的/全局的** rng（与 `_rng()` 同源），不用无参 `Random()`。"""
    rng = ai_brain._rng(rng)
    me = (getattr(room, 'players', None) or {}).get(ai_id)
    if me is None:
        return None
    attacked = ai_brain._attacked_cells(me)
    cands = [c for c in ai_brain._all_cells() if c not in attacked]
    return rng.choice(sorted(cands)) if cands else None


def _run(fn, games, seed):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ai_brain.choose_attack = fn
        try:
            results = hg.run_many(lambda: hg.make_policy('master'),
                                  lambda: hg.make_policy('hard'),
                                  games=games, seed=seed, quiet=True)
        finally:
            ai_brain.choose_attack = _ORIGINAL
    stats = hg.summarize(results)
    dmg = hg.damage_stats(results)
    return (round(stats['p1_win_rate'], 6),
            tuple(r.action_hash() for r in results),
            round(dmg['kills_by_p1'], 6))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=300)
    ap.add_argument('--seed', type=int, default=1)
    args = ap.parse_args(argv)

    cases = (('A 原样（不换）', _ORIGINAL),
             ('B 换成""逐字节相同""的 spy', _same_spy),
             ('C 均匀撒（无参 Random()，与线上工具同款）', _plain_attack),
             ('D 均匀撒（用 ai_brain._rng，与 seed 同源）', _plain_attack_seeded))
    print(f'{args.games} 局 / 种子 {args.seed} —— 每种跑两次，比胜率 + 动作哈希 + 击沉')
    print('=' * 78)
    for label, fn in cases:
        a = _run(fn, args.games, args.seed)
        b = _run(fn, args.games, args.seed)
        same = a[1] == b[1]
        print(f'{label:<42s} {"一致 ✅" if same else "**不一致 ❌**"}')
        print(f'    第一次 胜率 {a[0]:.4f}  击沉 {a[2]:.3f}  首局哈希 {a[1][0]}')
        if not same:
            print(f'    第二次 胜率 {b[0]:.4f}  击沉 {b[2]:.3f}  首局哈希 {b[1][0]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
