# -*- coding: utf-8 -*-
"""对照实验台：`PLAY_THRESHOLD` 与 `CARDS_PER_TURN` 的**双半样本**验证。

【为什么必须两个独立半样本】
`docs/MASTER_AI_2026_09_21.md` §12.3 记着一条度量纪律：改动前后各跑 2000 局、
再比两个数字是**在读噪声**——同一个区间里的高频抖动就有 ±1.5 个百分点。
要判定一个改动，必须**两个独立的种子半样本互相对上**（或者把样本翻几倍）。

本脚本对每个档位都在 `--seeds` 给的几组种子上各跑 `--games` 局，
报**每组的 Wilson 区间**——只有两组区间都朝同一方向、且不互相重叠，
才算"有效"。

⚠️ 只读：只改内存里的模块常量，退出时还原；不改任何卡面/数值。
用法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/experiment_threshold.py --games 5000 --seeds 1,50000,900000
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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=5000)
    ap.add_argument('--seeds', default='1,50000,900000')
    ap.add_argument('--thresholds', default='50,58,65,72')
    ap.add_argument('--budgets', default='')
    args = ap.parse_args(argv)
    seeds = [int(s) for s in args.seeds.split(',') if s.strip()]
    ths = [int(s) for s in args.thresholds.split(',') if s.strip()]
    budgets = [int(s) for s in args.budgets.split(',') if s.strip()]

    orig_th = ai_brain.PLAY_THRESHOLD
    orig_budget = ai_brain.CARDS_PER_TURN
    buf = io.StringIO()
    print(f'master vs hard  每格 {args.games} 局 × {len(seeds)} 个独立种子'
          f' = {args.games * len(seeds)} 局')
    print('=' * 100)
    header = f'{"档位":<22s}' + ''.join(f'{"seed=" + str(s):>22s}' for s in seeds)
    print(header)
    try:
        for label, th, budget in ([('阈值 %d（线上）' % orig_th, orig_th, orig_budget)]
                                  + [('阈值 %d' % t, t, orig_budget) for t in ths if t != orig_th]
                                  + [('预算 %d 张/回合' % b, orig_th, b) for b in budgets]):
            ai_brain.PLAY_THRESHOLD = th
            ai_brain.CARDS_PER_TURN = budget
            cells = []
            for s in seeds:
                with contextlib.redirect_stdout(buf):
                    rs = hg.run_many(hg.make_policy('master'), hg.make_policy('hard'),
                                     games=args.games, seed=s, quiet=True)
                st = hg.summarize(rs)
                lo, hi = st['p1_win_rate_ci']
                cells.append(f'{st["p1_win_rate"] * 100:5.1f}% [{lo * 100:4.1f},{hi * 100:4.1f}]'
                             f' 卡死{st["stalled"]}')
            print(f'{label:<22s}' + ''.join(f'{c:>22s}' for c in cells))
    finally:
        ai_brain.PLAY_THRESHOLD = orig_th
        ai_brain.CARDS_PER_TURN = orig_budget
    print('=' * 100)
    print('判读：只有**所有**种子半样本都朝同一方向、且与基线区间不重叠，才算有效。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
