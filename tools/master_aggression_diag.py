# -*- coding: utf-8 -*-
"""诊断：大师 AI「打不疼人」到底疼在哪 —— 逐项数出来，不靠猜。

【为什么需要它】
作者实报两条：「出牌太快」与「我甚至可以无伤赢他」。第二条在**此前的度量里
完全看不见** —— 验收指标只有胜率（master vs hard = 68.8%），而 68.8% 同时
兼容两种截然不同的对局：
    · 每一局都是互有攻防、双方各沉 5 艘的险胜；
    · 对手从头到尾没打中过我，我却也只是靠卡牌效果赢。
所以第一步是**先造出能看见它的量**（`headless_game.damage_stats` 的
`sunk_by_p1` / `sunk_by_p2`），再拿这个量去问"漏在哪"。

本脚本回答四个问题（每个都给数字，包括**否掉**的方向）：
  Q1 大师开炮聚焦吗？—— 命中率 vs "均匀撒"的理论值，以及命中率随局面的变化。
  Q2 出牌预算被浪费在低收益牌上了吗？—— 实际打出的牌分布 × 基础价值。
  Q3 `_situational` 的乘子让大师**领先时变保守**了吗？—— 领先/落后时的
     出牌构成与开炮数对比。
  Q4 情报类卡（探测雷达）有没有被用起来？—— 它的出场次数，以及
     "已探明格"到底贡献了多少次开炮。

用法（**必须带 UTF-8，否则中文卡名在控制台是乱码**）：
    $env:PYTHONIOENCODING='utf-8'
    python tools/master_aggression_diag.py --games 1000 --seed 1
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


def _sunk_histogram(results, seat_attr):
    """某座位「被击沉几艘」的分布 —— 0 就是"无伤"。"""
    hist = collections.Counter()
    for r in results:
        hist[r.sunk.get(getattr(r, seat_attr), 0)] += 1
    return hist


def _report_distribution(title, hist, games):
    print(f'  {title}')
    for k in sorted(hist):
        n = hist[k]
        print(f'      {k} 艘: {n:5d} 局  ({n / games * 100:5.1f}%)  '
              f'{"#" * int(n / games * 60)}')


def _card_plays(results, p1):
    """p1 实际打出的牌 → 次数（只数真的进了 `use_magic_card` 动作的那些）。"""
    plays = collections.Counter()
    for r in results:
        for kind, pid, detail in r.actions:
            if kind == 'use_magic_card' and pid == r.p1:
                plays[detail] += 1
    return plays


def _attack_focus(results):
    """开炮到底聚不聚焦：命中率 + 每局的炮数。

    对照基线：单格船、6 艘船、36 格。
      · **完全均匀撒**的期望命中率 = 6/36 ≈ 0.1667（在"没打过"的格子里均匀挑，
        单格船打中即沉，所以每次开炮的条件命中率会随已排除格上升）。
      · "情报全部兑现"的上界 ≈ 只看命中率的上界，需要每艘船都被探明。
    所以 0.16 ~ 0.20 之间说明**基本等同于均匀撒**，聚焦没有发生。
    """
    return hg.damage_stats(results)


def _seat_snapshots(results, seat_attr, difficulty):
    """逐**炮**记录当时的局面：谁领先、大师还有几次攻击。

    ⚠️ 这里不重新驱动对局，而是复用 `r.actions` 的顺序 —— 每个 `attack` 动作
    前后各有什么动作决定了"当时领先几艘"。为了不引入第二份真相，本函数只用
    动作序列里能直接看到的量（出牌/开炮的先后），不做状态重放。
    """
    out = collections.Counter()
    for r in results:
        attacks = sum(1 for k, pid, _d in r.actions if k == 'attack' and pid == getattr(r, seat_attr))
        cards = sum(1 for k, pid, _d in r.actions
                    if k == 'use_magic_card' and pid == getattr(r, seat_attr))
        out[(difficulty, attacks, cards)] += 1
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description='大师 AI 侵略性诊断')
    ap.add_argument('--games', type=int, default=1000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--p2', default='hard')
    args = ap.parse_args(argv)

    games = args.games
    print(f'p1=master  p2={args.p2}   {games} 局   起始种子={args.seed}')
    print('=' * 78)

    results = _quiet_run('master', args.p2, games, args.seed)
    stats = hg.summarize(results)
    dmg = hg.damage_stats(results)

    # ── 全局 ────────────────────────────────────────────────────────────
    print('【总览】')
    print(f'  胜率              : {stats["p1_win_rate"]:.4f}')
    print(f'  平均击沉对方      : {dmg["sunk_by_p1"]:.3f} 艘/局')
    print(f'  平均被击沉        : {dmg["sunk_by_p2"]:.3f} 艘/局')
    print(f'  命中率 p1 / p2    : {dmg["p1_hit_rate"]:.4f} / {dmg["p2_hit_rate"]:.4f}')
    print(f'  每局开炮          : {dmg["shots_per_game"]:.2f} 次')
    print(f'  卡死 / 被拒动作   : {stats["stalled"]} / {stats["violations"]}')
    print()
    print('  ⚠️ 参照：6 艘单格船 / 36 格，**完全均匀撒**的理论命中率 ≈ 0.1667。')
    print('     命中率停在这一带 = 开炮没有聚焦，"有情报就打掉"没有发生。')
    print()

    # ── 分布：无伤到底占多少 ─────────────────────────────────────────────
    print('【Q0 被击沉分布】—— "无伤赢"在这张表里的位置')
    _report_distribution(f'大师（{args.p2} 视角下大师被打沉几艘）:',
                         _sunk_histogram(results, 'p1'), games)
    _report_distribution(f'{args.p2}（大师打沉对方几艘）:',
                         _sunk_histogram(results, 'p2'), games)
    wins = [r for r in results if r.winner == r.p1]
    losses = [r for r in results if r.winner == r.p2]
    if wins:
        clean = sum(1 for r in wins if r.sunk.get(r.p1, 0) == 0)
        print(f'  大师赢的 {len(wins)} 局里，自己**一艘没沉**的有 {clean} 局'
              f'（{clean / len(wins) * 100:.1f}%）← 这是"防守端"的无伤')
        low = sum(1 for r in wins if r.sunk.get(r.p2, 0) <= 2)
        print(f'  大师赢的局里，对方存活 ≥4 艘（= 大师只打沉 ≤2 艘）的有 {low} 局'
              f'（{low / len(wins) * 100:.1f}%）')
    if losses:
        # ★ 这一行才是作者那句「我甚至可以无伤赢他」在数据里的位置：
        #   **对手赢的那些局里，对手自己一艘都没沉**。
        clean_loss = sum(1 for r in losses if r.sunk.get(r.p2, 0) == 0)
        print(f'  {args.p2} 赢的 {len(losses)} 局里，{args.p2} 自己**一艘没沉**的有 '
              f'{clean_loss} 局（{clean_loss / len(losses) * 100:.1f}%）'
              f'← 这是"对手无伤赢"')
        # 对面赢的局里大师打沉了几艘 —— 直接量"大师打不疼人"的严重程度
        hist = collections.Counter(r.sunk.get(r.p1, 0) for r in losses)
        print(f'  对手赢的局里，大师打沉对方的分布（0 = 大师一艘没打沉）：')
        for k in sorted(hist):
            n = hist[k]
            print(f'      {k} 艘: {n:5d} 局  ({n / len(losses) * 100:5.1f}%)  '
                  f'{"#" * int(n / len(losses) * 50)}')
    print()

    # ── Q1 开炮聚焦 ─────────────────────────────────────────────────────
    print('【Q1 开炮聚焦吗】')
    print(f'  master 命中率 {dmg["p1_hit_rate"]:.4f} vs {args.p2} {dmg["p2_hit_rate"]:.4f}'
          f'   （差 {(dmg["p1_hit_rate"] - dmg["p2_hit_rate"]) * 100:+.2f} 个百分点）')
    stats_by_kind = collections.Counter()
    for r in results:
        for kind, _pid, _d in r.actions:
            stats_by_kind[kind] += 1
    print('  动作构成（全部座位）:')
    for kind, n in stats_by_kind.most_common():
        print(f'      {kind:28s} {n:7d}  ({n / games:6.2f}/局)')
    print()

    # ── Q2 出牌预算花在哪 ───────────────────────────────────────────────
    print('【Q2 出牌预算花在哪】')
    plays = _card_plays(results, 'master')
    total = sum(plays.values())
    print(f'  master 共出牌 {total} 张（{total / games:.2f} 张/局，'
          f'预算 {ai_brain.CARDS_PER_TURN} 张/回合 × {stats["avg_rounds"]:.1f} 回合'
          f' = {ai_brain.CARDS_PER_TURN * stats["avg_rounds"]:.1f}）')
    print(f'  {"卡名":<10s} {"次数":>6s} {"占比":>7s} {"基础价值":>8s} {"价值×次数":>10s}')
    waste = 0.0
    for name, n in plays.most_common():
        v = ai_brain.card_value(name)
        print(f'  {name:<10s} {n:6d} {n / total * 100:6.1f}% {v:8d} {v * n:10.0f}')
        if v < 70:
            waste += n
    print(f'  —— 基础价值 <70 的"低收益牌"共 {waste:.0f} 张，占 {waste / total * 100:.1f}%')
    print()

    # ── Q4 情报卡 ───────────────────────────────────────────────────────
    print('【Q4 情报类卡有没有被用起来】')
    for name in ('探测雷达', '雷达子弹', '明智埋葬', '克苏鲁之眼'):
        print(f'  {name:<8s} 出场 {plays.get(name, 0):5d} 次  '
              f'（{"在池" if name in server._MASTER_ENABLED_CARDS else "**不在池**"}）')
    print('  ⚠️ 探测雷达让"已探明"的格子变成必中；它的价值必须由**后续炮击**兑现 ——')
    print('     所以看它的出场数还不够，要看命中率有没有被它抬起来（见 Q1）。')
    print()

    # ── Q3 领先/落后时的行为 ────────────────────────────────────────────
    print('【Q3 领先时是否变保守】')
    print('  （用"最终击沉差"分组，看两组的出牌构成与炮数 —— 这是能在动作序列上')
    print('    直接数出来的量；不重放状态，避免造出第二份真相）')
    ahead = [r for r in results if r.sunk.get(r.p1, 0) > r.sunk.get(r.p2, 0)]
    behind = [r for r in results if r.sunk.get(r.p1, 0) < r.sunk.get(r.p2, 0)]
    for label, group in (('最终领先（击沉更多）', ahead), ('最终落后', behind)):
        if not group:
            continue
        shots = sum(r.attacks_fired.get(r.p1, 0) for r in group) / len(group)
        cards = sum(1 for r in group for k, pid, _d in r.actions
                    if k == 'use_magic_card' and pid == r.p1) / len(group)
        print(f'  {label}: {len(group)} 局   大师开炮 {shots:.2f} 次/局   '
              f'出牌 {cards:.2f} 张/局')
    print()

    # ── 出牌率 ──────────────────────────────────────────────────────────
    print('【出牌预算利用率】')
    plays_per_game = total / games
    capacity = ai_brain.CARDS_PER_TURN * stats['avg_rounds']
    print(f'  实际 {plays_per_game:.2f} 张/局  ÷ 上限 {capacity:.2f} 张/局 '
          f'= {plays_per_game / capacity * 100:.1f}%')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
