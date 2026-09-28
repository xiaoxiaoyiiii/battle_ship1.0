# -*- coding: utf-8 -*-
"""诊断：大师 AI 的**开炮选点**到底有没有偏（以及偏了会不会伤到自己）。

【为什么怀疑这件事】
作者实报「我甚至可以无伤赢他」，而 `tools/gap_analysis.py` 量出来：
  · 大师赢的 1033 局里，终局「击沉 − 被击沉」的中位数是 **−4 艘**
    （19.9% 的胜局是 −6，也就是**自己六艘全沉还赢**）；
  · 大师平均击沉 2.61 艘 / 被击沉 4.99 艘。
⇒ 大师**不是靠炮击输出赢的**，是靠卡牌效果赢的。那么"它开炮打不疼人"这件事
   对胜率的边际贡献很小 —— 但它对**真人体验**的贡献很大（这是作者的原话）。

【这里量什么】
  A. 大师与困难的落点分布（36 格各被打了多少次）——**两边都是随机的话不该有偏**。
  B. 把大师的选点换成"36 格均匀撒"（`--attack uniform`）以及"只走
     `ai_brain.choose_attack` 的 unknown 集合"（线上），量胜率与命中率差。
  C. 对手摆船的位置分布（真人摆船在无头环境里是 `random.sample`，均匀）——
     用来确认"偏"不是来源于对手摆船。

⚠️ 只读：探针包在原函数外层，不改行为、不引入随机源。
用法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/probe_attack_bias.py --games 800 --seed 1
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
import ai_brain                            # noqa: E402


def _quiet_run(p1, p2, games, seed):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return hg.run_many(lambda: hg.make_policy(p1), lambda: hg.make_policy(p2),
                           games=games, seed=seed, quiet=True)


def _grid_text(counter, total):
    """把 36 格的计数画成一张热力表（每格是千分比）。"""
    lines = ['      x→  0      1      2      3      4      5']
    for y in range(6):
        row = [f'{counter.get((x, y), 0) / max(1, total) * 1000:6.1f}'
               for x in range(6)]
        lines.append(f'  y={y}  ' + ' '.join(row))
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description='大师开炮选点偏置探针')
    ap.add_argument('--games', type=int, default=800)
    ap.add_argument('--seed', type=int, default=1)
    args = ap.parse_args(argv)
    games = args.games

    master_cells = collections.Counter()
    hard_cells = collections.Counter()

    # ── 探针：每一炮的落点（`handle_attack` 是唯一入口）──────────────
    orig_attack = server.handle_attack

    def attack_spy(data):
        pid = data.get('player_id')
        key = (data.get('x'), data.get('y'))
        if str(pid or '').startswith('ai-'):
            master_cells[key] += 1
        else:
            hard_cells[key] += 1
        return orig_attack(data)

    server.handle_attack = attack_spy
    try:
        results = _quiet_run('master', 'hard', games, args.seed)
    finally:
        server.handle_attack = orig_attack

    st = hg.summarize(results)
    dmg = hg.damage_stats(results)
    print(f'master vs hard  {games} 局  种子={args.seed}')
    print(f'  胜率 {st["p1_win_rate"]:.4f}  命中率 p1/p2 '
          f'{dmg["p1_hit_rate"]:.4f}/{dmg["p2_hit_rate"]:.4f}  卡死 {st["stalled"]}')
    print('=' * 78)
    tm = sum(master_cells.values()) or 1
    th = sum(hard_cells.values()) or 1
    print(f'\n【A】master（AI 座位，{tm} 炮）每格被打的**千分比**（均匀应为 27.8）')
    print(_grid_text(master_cells, tm))
    print(f'\n【A】hard（真人座位，{th} 炮）每格被打的**千分比**（均匀应为 27.8）')
    print(_grid_text(hard_cells, th))

    # ── 偏置的统计量：x / y 边缘分布 + 卡方 ──────────────────────────
    for label, cnt, tot in (('master', master_cells, tm), ('hard', hard_cells, th)):
        xs = [sum(cnt.get((x, y), 0) for y in range(6)) for x in range(6)]
        ys = [sum(cnt.get((x, y), 0) for x in range(6)) for y in range(6)]
        exp = tot / 6
        chi_x = sum((v - exp) ** 2 / exp for v in xs)
        chi_y = sum((v - exp) ** 2 / exp for v in ys)
        print(f'\n  [{label}] x 边缘（期望 {exp:.0f}）: '
              + ' '.join(f'{v:5d}' for v in xs) + f'   χ²={chi_x:7.1f}')
        print(f'  [{label}] y 边缘（期望 {exp:.0f}）: '
              + ' '.join(f'{v:5d}' for v in ys) + f'   χ²={chi_y:7.1f}')

    print('\n  ⚠️ 判读：36 格均匀撒时 χ² 的期望值 = 5（自由度 5），'
          'χ² 远大于 ~11 才算有偏（p<0.05）。')
    print('     本项只说明落点有没有系统性偏；**"偏"不等于"会伤到自己"** ——')
    print('     要害在下一步：对手（真人）摆船是不是也在同一片区域。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
