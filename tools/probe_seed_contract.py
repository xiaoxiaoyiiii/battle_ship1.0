# -*- coding: utf-8 -*-
"""证明「同一 seed 两次跑，逐局 action_hash 序列完全一致」这条根本契约还成立。

【为什么单开一个脚本】
CLAUDE.md 教训 #36 记着：模拟器"固定种子可复现"是 `tools/headless_game.py` 的
**根本契约**，却一直**没有用例守着** —— 于是 `ai_brain` 里 4 处
`rng = rng or random.Random()`（无参 = 系统熵播种）活了很久，
让此前**每一次**"改动前 / 改动后比两个数字"都掺了噪声。

本脚本只做一件事：把**逐局** `action_hash` 打出来，跑两次，逐行比对。
它比只比"胜率"严得多 —— 胜率相同完全可能来自两条不同的动作序列。

⚠️ 本脚本**只读**：不改 `headless_game.py` 的契约、不改任何对局行为、
   不新增随机源。两次运行跑的是同一份代码。

用法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/probe_seed_contract.py --games 300 --seed 1 --dump .tmp\hashes.txt
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.headless_game as hg          # noqa: E402


def _run(p1, p2, games, seed):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return hg.run_many(lambda: hg.make_policy(p1), lambda: hg.make_policy(p2),
                           games=games, seed=seed, quiet=True)


def _digest(results):
    """每局一行：`seed|winner座位|rounds|action_hash`（座位名归一成 p1/p2）。"""
    lines = []
    for r in results:
        seat = 'p1' if r.winner == r.p1 else ('p2' if r.winner == r.p2 else 'draw')
        lines.append(f'{r.seed}|{seat}|{r.rounds}|{r.action_hash()}')
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description='固定种子可复现契约探针')
    ap.add_argument('--games', type=int, default=300)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--p1', default='master')
    ap.add_argument('--p2', default='hard')
    ap.add_argument('--dump', default='', help='把第一次运行的逐局哈希写到这个文件')
    args = ap.parse_args(argv)

    first = _digest(_run(args.p1, args.p2, args.games, args.seed))
    second = _digest(_run(args.p1, args.p2, args.games, args.seed))

    print(f'{args.p1} vs {args.p2}  {args.games} 局  种子={args.seed}')
    print('=' * 74)
    print('第 1 次运行（前 6 局逐局哈希）:')
    for line in first[:6]:
        print(f'    {line}')
    print('第 2 次运行（前 6 局逐局哈希）:')
    for line in second[:6]:
        print(f'    {line}')

    diffs = [(i, a, b) for i, (a, b) in enumerate(zip(first, second)) if a != b]
    same = len(first) == len(second) and not diffs
    print('=' * 74)
    print(f'逐局哈希一致 : {"是（完全一致）" if same else "否"}')
    print(f'不一致局数   : {len(diffs)} / {len(first)}')
    for i, a, b in diffs[:5]:
        print(f'    第 {i + 1} 局  第1次={a}')
        print(f'               第2次={b}')
    if args.dump:
        with open(args.dump, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(first) + '\n')
        print(f'第一次运行的 {len(first)} 行逐局哈希已写入 {args.dump}')
    return 0 if same else 1


if __name__ == '__main__':
    raise SystemExit(main())
