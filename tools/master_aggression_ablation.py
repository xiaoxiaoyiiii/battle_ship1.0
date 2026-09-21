# -*- coding: utf-8 -*-
"""对照实验：把"侵略性"这条线逐档量出来（同一批种子，只换一个开关）。

【为什么不用 `tools/master_ablation.py`】
那个脚本量的是**胜率**，并把 `summarize()` 的字段名写死了。本批要量的是
「打疼了没有」（击沉/被击沉/命中率/无伤获胜），是**另一个视角**；
而且要把两边一起报出来，看改动是不是"胜率换侵略性"。
所以这里复用它的做法（同一批种子、逐档开关），但换成读
`headless_game.damage_stats()`。

【量什么】
  · baseline          —— 线上默认（全池 34 张 + 每回合 3 张 + 读情报）
  · no_intel          —— 开炮不读情报（对照：情报值多少）
  · cards1 / cards2 / cards5 / cards8
                      —— 出牌预算扫描（**卡的"数量"值多少** —— CLAUDE.md #37）
  · full_plus_pool    —— 把池子扩到"所有能打的卡"（见下）
  · no_dead_weight    —— 从池里去掉"最常被试算闸门剔掉"的几张（让手牌能流动）

用法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/master_aggression_ablation.py --games 1000 --seed 1
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.headless_game as hg          # noqa: E402
import server                              # noqa: E402
import ai_brain                            # noqa: E402

_FULL_POOL = frozenset(server._MASTER_ENABLED_CARDS)
_ORIGINAL_CHOOSE_ATTACK = ai_brain.choose_attack
_ORIGINAL_CARDS_PER_TURN = ai_brain.CARDS_PER_TURN


def _plain_attack(room, ai_id, rng=None):
    """对照：不看情报，只在没打过的格子里均匀挑。

    ⚠️ 这里**不能**写 `rng = rng or random.Random()`（无参 = 系统熵播种）。
       那一版实测**同一 seed 连跑两次胜率 72.0% vs 70.7%**，整档数字是噪声 ——
       CLAUDE.md 教训 #36 的原文形状。必须用 `ai_brain._rng`（与 `random.seed()`
       同源）。守卫见 `tools/probe_rng_reproducibility.py`。
    """
    rng = ai_brain._rng(rng)
    me = (getattr(room, 'players', None) or {}).get(ai_id)
    if me is None:
        return None
    attacked = ai_brain._attacked_cells(me)
    cands = [c for c in ai_brain._all_cells() if c not in attacked]
    return rng.choice(sorted(cands)) if cands else None


def _reset(pool=None, cards=None, attack=None):
    server._MASTER_ENABLED_CARDS = frozenset(pool if pool is not None else _FULL_POOL)
    ai_brain.CARDS_PER_TURN = int(cards if cards is not None else _ORIGINAL_CARDS_PER_TURN)
    ai_brain.choose_attack = attack or _ORIGINAL_CHOOSE_ATTACK


# 「最常被 `_master_card_readiness` 剔掉」的几张（实测 top 榜，见
# tools/master_intel_diag.py 的输出）。它们在手里占位却几乎永远打不出去。
_DEAD_WEIGHT = ('回光返照', '平等条约', '加百列之光')

# ★ 实验性的扩池：把决策层**已经能给目标**、且 §9 口径允许的干员补上。
#   ⚠️ 这里**只**用于离线对照，跑完立刻还原（`_reset()`），不改线上默认池。
#   `克苏鲁之眼` 单独一档，因为它的收益路径与其它卡不同（见脚本末尾的说明）。
_EXTRA = ('伊甸园', '恶魔契约', '禁忌果实', '教皇旨意', '绝处逢生', '仁王之盾',
          'Freezing！', '神之宣告')

# 「直接让对方少船 / 直接造成伤害」的那几张。用来量"把预算全花在输出上"值多少。
_OFFENSIVE = ('轰炸', '火力全开', '神威！', '硫磺火焰', '冻结')
# 「把自己的船捞回来」的那几张。量"不给对手回血"值多少（对照 `no_dead_weight`）。
_REVIVAL = ('死者苏生', '增援', '疗愈', '滥竽充数')

CONFIGS = {
    'baseline': lambda: _reset(),
    'no_intel': lambda: _reset(attack=_plain_attack),
    'cards1': lambda: _reset(cards=1),
    'cards2': lambda: _reset(cards=2),
    'cards5': lambda: _reset(cards=5),
    'cards8': lambda: _reset(cards=8),
    'no_dead_weight': lambda: _reset(pool=_FULL_POOL - set(_DEAD_WEIGHT)),
    'add_kraken_eye': lambda: _reset(pool=_FULL_POOL | {'克苏鲁之眼'}),
    'pool_all_playable': lambda: _reset(pool=_FULL_POOL | set(_EXTRA)),
    # —— 量"卡的类型结构"值多少 ——
    'only_offensive': lambda: _reset(pool=_OFFENSIVE),
    'no_revival': lambda: _reset(pool=_FULL_POOL - set(_REVIVAL)),
    'slim_pool': lambda: _reset(pool=_FULL_POOL - set(_DEAD_WEIGHT) - set(_REVIVAL)),
}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=1000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--p2', default='hard')
    ap.add_argument('--configs', default=','.join(CONFIGS))
    args = ap.parse_args(argv)

    names = [n.strip() for n in args.configs.split(',') if n.strip()]
    unknown = [n for n in names if n not in CONFIGS]
    if unknown:
        raise SystemExit(f'未知档位 {unknown}；可用：{", ".join(CONFIGS)}')

    print(f'master vs {args.p2}   每档 {args.games} 局   起始种子={args.seed}')
    print(f'{"档位":<18s} {"胜率":>7s} {"击沉对方":>8s} {"被击沉":>7s} '
          f'{"炮击击沉":>8s} {"命中率":>7s} {"无伤胜率":>8s} {"卡死":>5s} {"被拒":>6s}')
    print('-' * 88)
    rows = {}
    try:
        for name in names:
            with contextlib.redirect_stdout(io.StringIO()):
                CONFIGS[name]()
                results = hg.run_many(lambda: hg.make_policy('master'),
                                      lambda: hg.make_policy(args.p2),
                                      games=args.games, seed=args.seed, quiet=True)
            stats = hg.summarize(results)
            dmg = hg.damage_stats(results)
            rows[name] = (stats, dmg)
            print(f'{name:<18s} {stats["p1_win_rate"] * 100:6.1f}% '
                  f'{dmg["sunk_by_p1"]:8.3f} {dmg["sunk_by_p2"]:7.3f} '
                  f'{dmg["kills_by_p1"]:8.3f} {dmg["p1_hit_rate"] * 100:6.2f}% '
                  f'{dmg["p1_flawless_rate"] * 100:7.1f}% {stats["stalled"]:5d} '
                  f'{stats["violations"]:6d}')
    finally:
        _reset()

    if 'baseline' in rows:
        bs, bd = rows['baseline']
        print('-' * 88)
        print(f'相对 baseline（胜率 {bs["p1_win_rate"] * 100:.1f}% / '
              f'击沉 {bd["sunk_by_p1"]:.3f} / 炮击击沉 {bd["kills_by_p1"]:.3f}）:')
        for name, (stats, dmg) in rows.items():
            if name == 'baseline':
                continue
            print(f'  {name:<18s} 胜率 {(stats["p1_win_rate"] - bs["p1_win_rate"]) * 100:+6.1f} 点'
                  f'   击沉 {dmg["sunk_by_p1"] - bd["sunk_by_p1"]:+.3f}'
                  f'   炮击击沉 {dmg["kills_by_p1"] - bd["kills_by_p1"]:+.3f}'
                  f'   被击沉 {dmg["sunk_by_p2"] - bd["sunk_by_p2"]:+.3f}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
