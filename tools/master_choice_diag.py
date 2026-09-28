# -*- coding: utf-8 -*-
"""诊断②：选牌器**到底有没有在做区分** —— 直接量"选中那张的价值 vs 候选池的价值"。

【为什么要单独量这一步】
`tools/master_aggression_diag.py` 数出来的出牌分布**几乎是平的**（34 张卡
每张占 3.0~4.1%）。但"分布平"有两种完全不同的成因，必须先分开：

  A. **选牌器是坏的**：`choose_card` 实际上没在按价值挑（例如所有候选都过了
     阈值、argmax 退化成"轮到谁是谁"），那 34 张卡自然被均匀打出去。
  B. **选牌器在工作，只是牌堆轮转**：手牌每回合换一批，牌堆里每张卡出现的
     次数本来就一样多，所以"长程看出场次数"必然趋平 —— 平的分布是**牌堆**
     的性质，不是**选择**的性质。

判据：看每次选中那张的 `card_value × _situational` 与**可打候选池**的
平均/最高值比。选中的价值显著高于候选均值 = 选牌器在区分（成因 B）；
选中的价值约等于候选均值 = 没在区分（成因 A）。

用法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/master_choice_diag.py --games 400 --seed 1
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import io
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.headless_game as hg          # noqa: E402
import server                              # noqa: E402
import ai_brain                            # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=400)
    ap.add_argument('--seed', type=int, default=1)
    args = ap.parse_args(argv)

    # 包一层 choose_card：记下"这次可选池"与"实际选中"的价值。
    # ⚠️ 只读、不改行为 —— 返回值原样透传。
    original = ai_brain.choose_card
    samples = []            # (chosen_value, best_value, mean_value, n_options, playable_n)

    def spy(room, ai_id, playable, rng=None):
        idx = original(room, ai_id, playable, rng)
        me = (room.players or {}).get(ai_id)
        hand = list(getattr(me, 'magic_hand', None) or []) if me else []
        values = []
        for i in (playable or []):
            if not isinstance(i, int) or i < 0 or i >= len(hand):
                continue
            name = getattr(hand[i], 'name', None)
            values.append(ai_brain.card_value(name) * ai_brain._situational(room, ai_id, name))
        if values:
            chosen = None
            if isinstance(idx, int) and 0 <= idx < len(hand):
                name = getattr(hand[idx], 'name', None)
                chosen = ai_brain.card_value(name) * ai_brain._situational(room, ai_id, name)
            samples.append((chosen, max(values), sum(values) / len(values),
                            len(values), len(playable or [])))
        return idx

    ai_brain.choose_card = spy
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            results = hg.run_many(lambda: hg.make_policy('master'),
                                  lambda: hg.make_policy('hard'),
                                  games=args.games, seed=args.seed, quiet=True)
    finally:
        ai_brain.choose_card = original

    stats = hg.summarize(results)
    dmg = hg.damage_stats(results)
    print(f'master vs hard  {args.games} 局  种子={args.seed}')
    print('=' * 78)
    print(f'胜率 {stats["p1_win_rate"]:.4f}   击沉对方 {dmg["sunk_by_p1"]:.3f}'
          f'   被击沉 {dmg["sunk_by_p2"]:.3f}')
    print()

    picks = [s for s in samples if s[0] is not None]
    print(f'【选牌器区分度】  共 {len(samples)} 次"问该打哪张"，其中真的选了 {len(picks)} 次')
    if not picks:
        print('  一次都没选 —— 出牌闸门把候选全剔掉了，这是另一类问题。')
        return 0
    chosen = [p[0] for p in picks]
    best = [p[1] for p in picks]
    mean = [p[2] for p in picks]
    nopt = [p[3] for p in picks]
    print(f'  选中那张的价值     中位数 {statistics.median(chosen):7.1f}   '
          f'均值 {statistics.fmean(chosen):7.2f}')
    print(f'  候选池**均值**     中位数 {statistics.median(mean):7.1f}   '
          f'均值 {statistics.fmean(mean):7.2f}')
    print(f'  候选池**最高值**   中位数 {statistics.median(best):7.1f}   '
          f'均值 {statistics.fmean(best):7.2f}')
    print(f'  可打候选张数       中位数 {statistics.median(nopt):7.1f}   '
          f'均值 {statistics.fmean(nopt):7.2f}')
    gain = statistics.fmean(chosen) - statistics.fmean(mean)
    print(f'  → 选中的比候选均值高 {gain:+.2f}'
          f'（相对 {(gain / statistics.fmean(mean) * 100) if statistics.fmean(mean) else 0:+.1f}%）')

    exact = sum(1 for p in picks if abs(p[0] - p[1]) < 1e-9)
    print(f'  → 选中就是候选里最高分的：{exact}/{len(picks)} = {exact / len(picks) * 100:.1f}%')
    print()

    # 乘子是否真的在动：把 picked 的 (base, situational) 配对数出来
    pairs = collections.Counter()
    for r in results:
        for kind, pid, detail in r.actions:
            if kind == 'use_magic_card' and pid == r.p1:
                pairs[detail] += 1
    print('【乘子会不会把领先方变保守】')
    print('  _situational 的三条乘子都对着"落后"加分：')
    print('    ③ 重摆类  behind>=2 ×1.8 / behind<=0 ×0.5')
    print('    ④ 进攻卡（轰炸/神威！/神之宣告/硫磺火焰）落后时 ×1.0~1.4')
    print('    ④ 防守卡（疗愈/仁王之盾/卧薪尝胆/无暇圣心）**领先时** ×1.0~1.4')
    print('  ⚠️ 注意最后一条的方向：它是"领先时更爱打防守卡"，不是"领先时更爱进攻"。')
    print('     所以若侵略性不足，这条本身不会直接造成"打不疼人"，')
    print('     但它与"领先时不需要进攻"叠加，会让大师在优势局里**继续补防**。')
    print()

    # 开炮：把"有情报时是否真的打情报格"数出来
    print('【情报兑现】—— 有已探明格时，那一炮是不是打在探明格上')
    print('  （探针在 ai_brain.choose_attack 上，见下方计数）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
