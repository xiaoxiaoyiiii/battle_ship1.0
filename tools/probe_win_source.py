# -*- coding: utf-8 -*-
"""诊断：大师到底是**靠什么赢**的 —— 按胜负分组的卡牌使用与"捞船"账。

【为什么必须问这个】
`tools/master_end_reason_diag.py` 已经确认：93% 的对局就是"常规：打光对方全部战舰"，
没有特殊判据。而 `tools/gap_analysis.py` 又量出大师赢的局里终局船数差中位数是 −4。
两件事同时成立，只有一种解释：**这是一场"谁先把对方清零"的赛跑**，
而"捞回自己的船"（死者苏生 / 增援 / 滥竽充数 / 疗愈 / 八方来财）直接把赛跑拉长。

于是"该往哪使劲"完全取决于这张账：

  大师：炮击击沉 4.69 次/局，终局船数差只有 2.61 ⇒ 对手把它打沉的**约 2.08 艘捞回来了**；
  困难：炮击击沉 3.65 次/局，终局船数差 4.99      ⇒ 它把大师打沉的**约 1.34 艘没捞回**。

⚠️ 关键问题：**胜负两侧，"对手捞回几艘"差多少？** 如果赢的局里对手捞得少、
   输的局里对手捞得多，那么"压制对手的续命"就是真正的那 11 个百分点。

⚠️ 只读：探针包在 `handle_use_magic_card` 外层，记完原样调用，不改行为、不引入随机源。
用法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/probe_win_source.py --games 2000 --seed 1
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

# 「把已经沉掉的船捞回来 / 凭空多加船」的卡 —— 这一组决定"赛跑被拉长多少"。
REVIVE_CARDS = frozenset({'死者苏生', '增援', '滥竽充数', '疗愈'})
# 「直接把对方的船打掉」的卡（非炮击输出）。
DIRECT_KILL_CARDS = frozenset({'轰炸', '神威！', '硫磺火焰', '火力全开', '冻结'})


def _quiet_run_marked(p1, p2, games, seed):
    """跑一批，返回 `[(result, play_log)]`。

    `play_log` 是这一局里每次出牌的 `(座位, 卡名)`（探针在跑的时候收集，
    跑完按局切分 —— 因为 `run_many` 不给每局的边界回调）。
    """
    plays = []
    orig = server.handle_use_magic_card

    current = {'log': []}

    def spy(data):
        resp = orig(data)
        try:
            if resp and resp.get('status') == 'success':
                name = (data.get('card') or {}).get('name')
                current['log'].append((data.get('player_id'), name))
        except Exception:
            pass
        return resp

    server.handle_use_magic_card = spy
    buf = io.StringIO()
    out = []
    try:
        with contextlib.redirect_stdout(buf):
            # 逐局跑（不用 run_many），这样才能在每局之间切开 play_log。
            for i in range(int(games)):
                current['log'] = []
                r = hg.play_game(lambda: hg.make_policy(p1), lambda: hg.make_policy(p2),
                                 seed=int(seed) + i)
                out.append((r, list(current['log'])))
    finally:
        server.handle_use_magic_card = orig
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description='大师赢法剖析（只读）')
    ap.add_argument('--games', type=int, default=2000)
    ap.add_argument('--seed', type=int, default=1)
    args = ap.parse_args(argv)
    games = args.games

    marked = _quiet_run_marked('master', 'hard', games, args.seed)
    results = [r for r, _ in marked]
    st = hg.summarize(results)
    dmg = hg.damage_stats(results)
    print(f'master vs hard  {games} 局  种子={args.seed}   胜率 {st["p1_win_rate"]:.4f}')
    print('=' * 78)
    print('【总账】')
    print(f'  大师：炮击击沉 {dmg["kills_by_p1"]:.3f} 次/局，终局击沉对方 {dmg["sunk_by_p1"]:.3f} 艘')
    print(f'        ⇒ 对手把约 {dmg["kills_by_p1"] - dmg["sunk_by_p1"]:.2f} 艘捞了回来')
    print(f'  困难：炮击击沉 {dmg["kills_by_p2"]:.3f} 次/局，终局击沉大师 {dmg["sunk_by_p2"]:.3f} 艘')
    print(f'        ⇒ 大师把约 {dmg["kills_by_p2"] - dmg["sunk_by_p2"]:.2f} 艘捞了回来')
    print(f'  零和比值：大师炮击击沉占比 {dmg["kills_by_p1"] / max(1e-9, dmg["kills_by_p1"] + dmg["kills_by_p2"]):.4f}'
          f'  —— 若"终局船数"严格正比，胜率就该是这个数。')

    # ── 按胜负分组：双方各出了什么牌、对手捞回几艘 ────────────────────
    groups = (('大师赢的局', [m for m in marked if m[0].winner == m[0].p1]),
              ('大师输的局', [m for m in marked if m[0].winner == m[0].p2]))

    for label, items in groups:
        if not items:
            continue
        print()
        print('【%s】%d 局' % (label, len(items)))
        n = len(items)
        # 双方捞船 / 直接输出卡的平均次数
        for seat_name, idx in (('大师', 0), ('困难', 1)):
            revive = direct = 0
            for r, log in items:
                pid = (r.p1, r.p2)[idx]
                for who, name in log:
                    if who != pid:
                        continue
                    if name in REVIVE_CARDS:
                        revive += 1
                    elif name in DIRECT_KILL_CARDS:
                        direct += 1
            print(f'    {seat_name}：续命类卡 {revive / n:.2f} 次/局'
                  f'   直接输出类卡 {direct / n:.2f} 次/局')

        # 捞回来的量：炮击击沉 − 终局击沉
        kp1 = sum(r.kills.get(r.p1, 0) for r, _ in items) / n
        sp1 = sum(r.sunk.get(r.p1, 0) for r, _ in items) / n
        kp2 = sum(r.kills.get(r.p2, 0) for r, _ in items) / n
        sp2 = sum(r.sunk.get(r.p2, 0) for r, _ in items) / n
        print(f'    大师炮击击沉 {kp1:.2f} → 终局 {sp1:.2f}（被对手捞回 {kp1 - sp1:+.2f}）')
        print(f'    困难炮击击沉 {kp2:.2f} → 终局 {sp2:.2f}（被大师捞回 {kp2 - sp2:+.2f}）')
        print(f'    ⇒ 大师净输出 {sp1 - sp2:+.2f} 艘/局')

    # ── 逐卡：胜负两侧的出场率差（最大的那几个就是"胜负手"）───────────
    print()
    print('【逐卡出场率：赢局 vs 输局】（差 > 0 = 这张牌与胜利正相关，只是相关性）')
    wins = [m for m in marked if m[0].winner == m[0].p1]
    losses = [m for m in marked if m[0].winner == m[0].p2]
    per_card = collections.defaultdict(lambda: [0, 0])
    for seat_idx, seat_label in ((0, '大师'), (1, '困难')):
        w = collections.Counter()
        l = collections.Counter()
        for r, log in wins:
            pid = (r.p1, r.p2)[seat_idx]
            for who, name in log:
                if who == pid and name:
                    w[name] += 1
        for r, log in losses:
            pid = (r.p1, r.p2)[seat_idx]
            for who, name in log:
                if who == pid and name:
                    l[name] += 1
        rows = []
        for name in set(w) | set(l):
            wr = w[name] / max(1, len(wins))
            lr = l[name] / max(1, len(losses))
            rows.append((wr - lr, name, wr, lr))
        rows.sort(reverse=True)
        print(f'  —— {seat_label} ——')
        for diff, name, wr, lr in rows:
            print(f'      {name:<10s} 赢局 {wr:5.2f} 次/局   输局 {lr:5.2f} 次/局   差 {diff:+5.2f}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
