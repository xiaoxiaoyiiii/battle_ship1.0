# -*- coding: utf-8 -*-
"""诊断④：情报（已探明格）到底有没有兑现，以及出牌机会为什么被浪费。

【要回答的三个问题】
  Q-A 大师开炮时，**手上有已探明格**的比例是多少？有多少炮真的打在探明格上？
      命中率上不去到底是因为"没情报"还是"有情报没打"。
  Q-B 每次"问该打哪张牌"时，可打候选有几张？**候选为空**（打不出牌）占多少？
      这决定了 `CARD_BASE_VALUE × _situational` 这套选牌逻辑有没有决策空间。
  Q-C 一回合里大师到底出满了几张（预算 3）？没出满的原因是哪一类。

用法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/master_intel_diag.py --games 400 --seed 1
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


def _attribute_empty(room, ai_id, hands, rejected):
    """空候选时到底是"手里没牌"还是"有牌但打不出去" —— 两者改法完全不同。

    `can_play_magic_card`（阶段/回合/速阶/锁卡）是**规则闸门**；
    `_master_card_readiness`（前置条件/目标形状）是**试算闸门**。
    分开数才知道该动哪一个。
    """
    player = (room.players or {}).get(ai_id)
    hand = list(getattr(player, 'magic_hand', None) or []) if player else []
    in_pool = [c for c in hand if getattr(c, 'name', None) in server._MASTER_ENABLED_CARDS]
    if not hand:
        hands['手里一张牌都没有'] += 1
        return
    if not in_pool:
        hands['有手牌但一张都不在池里'] += 1
        return
    playable_now = [c for c in in_pool if server.can_play_magic_card(room, ai_id, c)]
    if not playable_now:
        hands['在池的牌全被 can_play 挡住（阶段/回合/速阶）'] += 1
        return
    hands['过了 can_play 但被 readiness 试算剔掉'] += 1
    for c in playable_now:
        rejected[getattr(c, 'name', '?')] += 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=400)
    ap.add_argument('--seed', type=int, default=1)
    args = ap.parse_args(argv)

    # ── 探针 A：开炮选点 ────────────────────────────────────────────────
    orig_attack = ai_brain.choose_attack
    shots = collections.Counter()      # 'known_available' / 'known_taken' / 'unknown_taken'

    def attack_spy(room, ai_id, rng=None):
        me = (room.players or {}).get(ai_id)
        known, _safe, unknown = ai_brain.enemy_cell_model(room, ai_id)
        cell = orig_attack(room, ai_id, rng)
        if me is not None:
            if known:
                shots['有已探明格'] += 1
                if cell in known:
                    shots['→ 打的是探明格'] += 1
                else:
                    shots['→ 有探明格却打了别处'] += 1
            else:
                shots['无探明格'] += 1
            if cell is not None:
                shots['总开炮'] += 1
        return cell

    # ── 探针 B：问该打哪张牌 ────────────────────────────────────────────
    orig_card = ai_brain.choose_card
    picks = collections.Counter()
    rejected = collections.Counter()       # 通过了 can_play 却被 readiness 剔掉的卡
    hands = collections.Counter()          # 空候选时的归因

    def card_spy(room, ai_id, playable, rng=None):
        n = len(playable or [])
        picks[f'候选数={n}'] += 1
        if n == 0:
            picks['空候选（打不出牌）'] += 1
            _attribute_empty(room, ai_id, hands, rejected)
        elif n == 1:
            picks['唯一候选（没得选）'] += 1
        else:
            picks['多候选（真的在选）'] += 1
        return orig_card(room, ai_id, playable, rng)

    ai_brain.choose_attack = attack_spy
    ai_brain.choose_card = card_spy
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            results = hg.run_many(lambda: hg.make_policy('master'),
                                  lambda: hg.make_policy('hard'),
                                  games=args.games, seed=args.seed, quiet=True)
    finally:
        ai_brain.choose_attack = orig_attack
        ai_brain.choose_card = orig_card

    stats = hg.summarize(results)
    dmg = hg.damage_stats(results)
    print(f'master vs hard  {args.games} 局  种子={args.seed}')
    print('=' * 78)
    print(f'胜率 {stats["p1_win_rate"]:.4f}   击沉对方 {dmg["sunk_by_p1"]:.3f}'
          f'   被击沉 {dmg["sunk_by_p2"]:.3f}   炮击击沉 {dmg["kills_by_p1"]:.3f}')
    print()

    print('【Q-A 情报兑现】')
    total = shots['总开炮'] or 1
    for k in ('总开炮', '有已探明格', '无探明格', '→ 打的是探明格', '→ 有探明格却打了别处'):
        print(f'  {k:<22s} {shots[k]:7d}  ({shots[k] / total * 100:5.1f}%)')
    print(f'  → 开炮时**手上有情报**的比例 {(shots["有已探明格"] / total * 100):.1f}%')
    print('  ⚠️ 这个比例就是"按情报开炮"能贡献的上限：没有情报时再怎么选也是瞎打。')
    print()

    print('【Q-B 选牌决策空间】')
    asked = sum(v for k, v in picks.items() if k.startswith('候选数='))
    for label in ('空候选（打不出牌）', '唯一候选（没得选）', '多候选（真的在选）'):
        n = picks[label]
        print(f'  {label:<22s} {n:7d}  ({n / max(1, asked) * 100:5.1f}%)')
    print(f'  共被问 {asked} 次  ({asked / args.games:.2f} 次/局)')
    print('  ⚠️ "唯一候选"占多数 = 选牌逻辑**没有决策空间**，价值表乘子再准也无处发力。')
    print()
    print('  —— 空候选的归因（决定该动哪个闸门）——')
    for k, v in hands.most_common():
        print(f'    {k:<34s} {v:6d}')
    if rejected:
        print('  —— 过了 can_play 却被 readiness 剔掉的卡（前 12）——')
        for name, n in rejected.most_common(12):
            print(f'    {name:<12s} {n:6d}')
    print()

    print('【Q-C 出牌预算】')
    plays = collections.Counter()
    for r in results:
        n = sum(1 for k, pid, _d in r.actions if k == 'use_magic_card' and pid == r.p1)
        plays[n] += 1
    print(f'  master 每局出牌张数分布（预算 {ai_brain.CARDS_PER_TURN} 张/回合 ×'
          f' {stats["avg_rounds"]:.1f} 回合 = {ai_brain.CARDS_PER_TURN * stats["avg_rounds"]:.1f}）:')
    for n in sorted(plays):
        print(f'      {n} 张/局: {plays[n]:5d} 局')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
