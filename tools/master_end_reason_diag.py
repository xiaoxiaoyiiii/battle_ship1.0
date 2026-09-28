# -*- coding: utf-8 -*-
"""诊断③：船到底是被什么打沉的、对局到底因为什么结束。

【为什么要问到这一步】
`master_aggression_diag.py` 已经量出两件反直觉的事（1000 局，seed=1）：
  · 大师平均**打沉对方 2.59 艘**，自己**被击沉 4.98 艘** —— 它在"拼船"上是亏的；
  · 可它**赢 68.8%**。

这两个数放在一起只有一种解释：大师**不是靠把对方打光来赢的**。而"赢法"决定了
"侵略性"该怎么改 —— 如果它赢在卡牌输出上，那"多开几炮"根本不是提升路径。
所以先把两条链路拆开量：

  A. `_apply_ship_sunk_effects` 的调用来源：**炮击** vs **卡牌效果**各造成多少沉船。
  B. `_finish_game_win` 的日志文案：直接标出每一局是"把对方打光"赢的，
     还是被 `绝处逢生击杀即胜` / `回光返照判负` 之类的**特殊判据**结束的。

⚠️ 本脚本只**读**现有实现（打补丁包一层、记完就原样调用），不改任何行为、
   不引入随机源。跑完在 finally 里还原。
用法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/master_end_reason_diag.py --games 1000 --seed 1
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tools.headless_game as hg          # noqa: E402
import server                              # noqa: E402


# 日志文案里区分"谁把谁打沉的"用的前缀（`_log_name` 出来的是座位名）。
# 这里不用正则去认名字，而是**按调用栈来源**分：`_apply_ship_sunk_effects`
# 的 `source` 参数是显式传进来的（server.py 的卡牌分支传 'magic'，炮击走 'attack'）。
def _classify(reason):
    text = str(reason or '')
    if '绝处逢生' in text and '获胜' in text:
        return '特殊判据：绝处逢生击杀即胜'
    if '回光返照' in text:
        return '特殊判据：回光返照（被击中即判负）'
    if '掉线' in text:
        return '掉线判胜'
    if '投降' in text:
        return '投降'
    if '获胜' in text:
        return '常规：打光对方全部战舰'
    return f'其他：{text[:40]}'


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=1000)
    ap.add_argument('--seed', type=int, default=1)
    args = ap.parse_args(argv)

    end_reasons = collections.Counter()          # 结束原因 -> 局数
    end_by_winner = collections.Counter()        # (原因, 赢家座位标签) -> 局数
    sink_source = collections.Counter()          # 沉船由谁触发：attack / magic / 其他
    sink_by_attacker = collections.Counter()     # 沉船由哪个座位造成

    orig_finish = server._finish_game_win
    orig_sank = server._apply_ship_sunk_effects

    def finish_spy(room, room_id, winner_id, loser_id, log_message=None):
        # `log_message is None` 时 server 自己写默认文案（= 炮击打光对方）。
        reason = _classify(log_message) if log_message else '常规：打光对方全部战舰'
        end_reasons[reason] += 1
        seat = ('master/ai' if winner_id and str(winner_id).startswith('ai-')
                else 'human/opp')
        end_by_winner[(reason, seat)] += 1
        return orig_finish(room, room_id, winner_id, loser_id, log_message)

    def sank_spy(*a, **kw):
        # 签名： (room, room_id, attacker_id, defender_id, ship, x, y)
        attacker = a[2] if len(a) > 2 else None
        seat = 'master/ai' if attacker and str(attacker).startswith('ai-') else 'human/opp'
        sink_by_attacker[seat] += 1
        return orig_sank(*a, **kw)

    server._finish_game_win = finish_spy
    server._apply_ship_sunk_effects = sank_spy
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            results = hg.run_many(lambda: hg.make_policy('master'),
                                  lambda: hg.make_policy('hard'),
                                  games=args.games, seed=args.seed, quiet=True)
    finally:
        server._finish_game_win = orig_finish
        server._apply_ship_sunk_effects = orig_sank

    stats = hg.summarize(results)
    dmg = hg.damage_stats(results)
    games = args.games
    print(f'master vs hard  {games} 局  种子={args.seed}')
    print('=' * 78)
    print(f'胜率 {stats["p1_win_rate"]:.4f}   击沉对方 {dmg["sunk_by_p1"]:.3f}'
          f'   被击沉 {dmg["sunk_by_p2"]:.3f}   卡死 {stats["stalled"]}')
    print()

    print('【A 对局因为什么结束】')
    for reason, n in end_reasons.most_common():
        print(f'  {reason:<28s} {n:5d} 局  ({n / games * 100:5.1f}%)')
    print()
    print('【A2 结束原因 × 赢家】')
    for (reason, seat), n in sorted(end_by_winner.items(), key=lambda kv: -kv[1]):
        print(f'  {reason:<28s} 赢家={seat:<10s} {n:5d} 局')
    print()

    print('【B 船是被什么打沉的】（`_apply_ship_sunk_effects` 的调用来源）')
    for seat, n in sink_by_attacker.most_common():
        print(f'  由 {seat:<10s} 造成的沉船事件 {n:6d} 次  ({n / games:5.2f}/局)')
    total_sunk_events = sum(sink_by_attacker.values())
    print(f'  合计 {total_sunk_events} 次  ({total_sunk_events / games:.2f}/局)')
    print('  ⚠️ 与 `sunk_by_p1 + sunk_by_p2` 对照：后者读终局船数差，前者数过程事件 ——')
    print('     两者不等说明有卡牌在**改船数上限 / 复活**（死者苏生、增援、滥竽充数）。')
    print(f'  终局船数差合计 {dmg["sunk_by_p1"] + dmg["sunk_by_p2"]:.2f}/局')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
