# -*- coding: utf-8 -*-
"""诊断：把大师与困难在真对局里的**行为**逐项数出来，找出强度漏在哪。

不看胜率，只看"它到底做了什么"：出了哪些牌、命中率多少、情报有没有用上。
用法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/master_diag.py --games 400 --seed 1
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.headless_game as hg          # noqa: E402
import server                              # noqa: E402
import ai_brain                             # noqa: E402


def _run(p1, p2, games, seed):
    """跑一批对局，顺带统计每个座位的动作与卡牌使用。

    ⚠️ 必须给**每一局、每一个座位**造新策略对象：`ExistingAIPolicy` 带
       `cards_played` / `_pending_targets` 这类回合状态，共用一个实例会让
       两边的状态互相污染（第一版本脚本就踩了：把同一个对象同时当 p1/p2 传进去，
       统计出来"大师一张牌都没出"，其实是两边共用了同一份计数）。
    """
    plays = collections.Counter()      # (difficulty, card) -> 次数
    acts = collections.Counter()       # (difficulty, kind) -> 次数
    wins = collections.Counter()       # difficulty -> 胜局
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        results = hg.run_many(lambda: hg.make_policy(p1), lambda: hg.make_policy(p2),
                              games=games, seed=seed)
    for r in results:
        # r.p1 = AI 座位（p1 难度），r.p2 = 对手座位（p2 难度）
        seat_of = {r.p1: p1, r.p2: p2}
        if r.winner in seat_of:
            wins[seat_of[r.winner]] += 1
        for kind, pid, detail in r.actions:
            d = seat_of.get(pid)
            if d is None:
                continue
            acts[(d, kind)] += 1
            if kind == 'use_magic_card':
                plays[(d, detail)] += 1
    return results, plays, acts, wins


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=400)
    ap.add_argument('--seed', type=int, default=1)
    args = ap.parse_args(argv)

    for p1, p2 in (('master', 'hard'), ('hard', 'master')):
        results, plays, acts, wins = _run(p1, p2, args.games, args.seed)
        stats = hg.summarize(results)
        print('=' * 76)
        print(f'p1={p1} vs p2={p2}   {args.games} 局  平均回合 {stats["avg_rounds"]:.2f}')
        for d in (p1, p2):
            n_attack = acts[(d, 'attack')]
            n_card = acts[(d, 'use_magic_card')]
            print(f'  {d:7s} 胜 {wins[d]:4d}  出牌 {n_card:6d}  开炮 {n_attack:6d}'
                  f'  出牌/开炮 {n_card / max(1, n_attack):.2f}')
        print('  —— 各档出牌明细 ——')
        for d in (p1, p2):
            items = sorted(((c, n) for (dd, c), n in plays.items() if dd == d),
                           key=lambda kv: -kv[1])
            if not items:
                continue
            print(f'  [{d}] 共 {sum(n for _c, n in items)} 张 / {len(items)} 种')
            for c, n in items:
                print(f'        {c:8s} {n:6d}')

    # 命中率：master 的开炮里有多少真的打中（对局层不直接给，用攻击结果推）
    print('=' * 76)
    print('说明：命中率需要读 attack_result，这里用"出牌/开炮比"先定位结构问题。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
