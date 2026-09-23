# -*- coding: utf-8 -*-
"""诊断：把「大师 vs 困难」这 30 个百分点的差距**拆开量**。

这是本批的核心交付 —— 在动手之前先说清楚"漏在哪"。四条独立的口径：

  【口径 1】**输在哪**：大师输掉的局里局势长什么样（无伤输 / 被压着打 /
    打到很少回合就结束 / 对方靠什么结束的）。
  【口径 2】**决策空间**：每一个"问该打哪张牌"的时刻，可打候选有几张，
    以及空候选时到底是"没手牌 / 不在池里 / 被规则闸门挡 / 被试算闸门剔"。
  【口径 3】**池外每张卡值多少**：把每一张池外卡**单独**加进池子跑同一批局面
    （同一 seed 序列），报胜率 + Wilson 区间 + 局数。
    ★ 有意不开的卡（会等施法者自己点选 / 会把回合卡死）也一并量 ——
      量出来的数字**只用来判断"值不值得去实现那个交互能力"**，不是"开回去"。
  【口径 4】**侵略性缺口**：大师"能打却没打"的时刻有多少、
    每一炮的落点是否浪费在已经证明是空的格子上。

⚠️ 本脚本**只读**：不改对局行为、不改 `headless_game.py` 的契约、
   不引入新的随机源（探针都包在原函数外层，记完就原样调用）。
用法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/gap_analysis.py --games 2000 --seed 1 --section all
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


def _pct(n, d):
    return (n / d * 100) if d else 0.0


def _ci_text(wins, total):
    lo, hi = hg.wilson_interval(wins, total)
    return f'{lo * 100:.1f}~{hi * 100:.1f}'


# ===========================================================================
# 口径 1：输在哪
# ===========================================================================
def section_loss(games, seed):
    results = _quiet_run('master', 'hard', games, seed)
    stats = hg.summarize(results)
    dmg = hg.damage_stats(results)
    wins = [r for r in results if r.winner == r.p1]
    losses = [r for r in results if r.winner == r.p2]

    print('=' * 78)
    print(f'【口径 1】输在哪   master vs hard  {games} 局  种子={seed}')
    print(f'  胜率 {stats["p1_win_rate"]:.4f}  (95%CI {_ci_text(stats["p1_wins"], games)})'
          f'  卡死 {stats["stalled"]}')
    print(f'  大师 {len(wins)} 胜 / {len(losses)} 负')

    # ── 终局船数差：赢/输两侧各是什么形状 ────────────────────────────────
    for label, group in (('大师赢的局', wins), ('大师输的局', losses)):
        if not group:
            continue
        diffs = collections.Counter(r.sunk.get(r.p1, 0) - r.sunk.get(r.p2, 0) for r in group)
        print(f'\n  {label}：终局「大师击沉 − 被击沉」分布（负数 = 大师船更少却赢/输）')
        for k in sorted(diffs):
            n = diffs[k]
            print(f'      {k:+d} 艘: {n:5d} 局  ({_pct(n, len(group)):5.1f}%)'
                  f'  {"#" * int(_pct(n, len(group)) / 2)}')

    # ── ★ 无伤：这才是作者那句「我甚至可以无伤赢他」的位置 ──────────────
    print('\n  ★ 无伤口径（严格：整局一艘都没被击沉）')
    if wins:
        c = sum(1 for r in wins if r.sunk.get(r.p1, 0) == 0)
        print(f'      大师赢的 {len(wins)} 局里，自己一艘没沉 : {c} 局 ({_pct(c, len(wins)):.1f}%)')
    if losses:
        c = sum(1 for r in losses if r.sunk.get(r.p2, 0) == 0)
        print(f'      大师输的 {len(losses)} 局里，困难一艘没沉 : {c} 局'
              f' ({_pct(c, len(losses)):.1f}%)  ← 作者说的"无伤赢大师"')
        c2 = sum(1 for r in losses if r.sunk.get(r.p2, 0) <= 1)
        print(f'      大师输的 {len(losses)} 局里，困难只沉 ≤1 艘 : {c2} 局'
              f' ({_pct(c2, len(losses)):.1f}%)')
        c3 = sum(1 for r in losses if r.sunk.get(r.p1, 0) <= 2)
        print(f'      大师输的 {len(losses)} 局里，大师只打沉 ≤2 艘 : {c3} 局'
              f' ({_pct(c3, len(losses)):.1f}%)')
    print(f'  全局：大师击沉对方 {dmg["sunk_by_p1"]:.3f} / 被击沉 {dmg["sunk_by_p2"]:.3f}'
          f'  命中率 {dmg["p1_hit_rate"]:.4f} vs 困难 {dmg["p2_hit_rate"]:.4f}')

    # ── 回合数：输的局是不是"很快就被打光" ──────────────────────────────
    print('\n  平均大回合数：赢 %.2f / 输 %.2f'
          % ((sum(r.rounds for r in wins) / len(wins)) if wins else 0,
             (sum(r.rounds for r in losses) / len(losses)) if losses else 0))
    return results


# ===========================================================================
# 口径 2：决策空间 + 口径 4：侵略性缺口（同一趟跑，共用探针）
# ===========================================================================
def section_space(games, seed):
    """一次跑同时量决策空间与侵略性缺口（探针都只读）。"""
    picks = collections.Counter()
    empty_reason = collections.Counter()
    empty_card = collections.Counter()
    attach = collections.Counter()       # 开炮落点的性质
    cards_played_hist = collections.Counter()
    rounds_seen = [0]

    ##########################################################################
    # 探针 A：选牌时的候选数（`ai_brain.choose_card` 被调用 = 一次真实决策）
    ##########################################################################
    orig_card = ai_brain.choose_card

    def card_spy(room, ai_id, playable, rng=None):
        n = len(playable or [])
        picks[f'候选数={n}' if n <= 3 else '候选数>=4'] += 1
        if n == 0:
            _attribute_empty(room, ai_id, empty_reason, empty_card)
        elif n == 1:
            picks['唯一候选（没得选）'] += 1
        else:
            picks['多候选（真的在选）'] += 1
        return orig_card(room, ai_id, playable, rng)

    ##########################################################################
    # 探针 B：每张池外卡的"在手上 / 打得出"机会（决定它值不值得实现能力）
    ##########################################################################
    pool = set(server._MASTER_ENABLED_CARDS)
    outpool_in_hand = collections.Counter()   # 池外卡在手上被看到的次数
    outpool_ready = collections.Counter()     # 池外卡**此刻真能打**的次数
    outpool_total_hand = collections.Counter()  # 每次决策时手上的总张数

    orig_pick = server._ai_master_pick

    def pick_spy(room, ai_id, cards_played=0):
        player = room.players.get(ai_id)
        if player is not None:
            outpool_total_hand[len(player.magic_hand or [])] += 1
            for c in (player.magic_hand or []):
                name = getattr(c, 'name', None)
                if name in pool:
                    continue
                outpool_in_hand[name] += 1
                try:
                    if not server.can_play_magic_card(room, ai_id, c):
                        continue
                except Exception:
                    continue
                try:
                    if server._master_card_readiness(room, ai_id, c) is None:
                        continue
                except Exception:
                    continue
                outpool_ready[name] += 1
        return orig_pick(room, ai_id, cards_played)

    ##########################################################################
    # 探针 C：开炮落点 —— 有多少炮打在"已经证明是空的格"上
    ##########################################################################
    orig_attack = ai_brain.choose_attack

    def attack_spy(room, ai_id, rng=None):
        cell = orig_attack(room, ai_id, rng)
        if cell is not None:
            try:
                known, safe, unknown = ai_brain.enemy_cell_model(room, ai_id)
            except Exception:
                known = safe = unknown = set()
            if cell in known:
                attach['打的是已探明格（必中）'] += 1
            elif cell in safe:
                # 单格船打中即沉 → 这些格是**证明为空**的。大师的第一版模型
                # 不会往这里打（unknown 已经从候选里剔掉了），所以它应当恒为 0。
                attach['★ 打在已证明是空的格（纯浪费）'] += 1
            else:
                attach['打在未知格（可能命中）'] += 1
            attach['总开炮'] += 1
        return cell

    ai_brain.choose_card = card_spy
    server._ai_master_pick = pick_spy
    ai_brain.choose_attack = attack_spy
    try:
        results = _quiet_run('master', 'hard', games, seed)
    finally:
        ai_brain.choose_card = orig_card
        server._ai_master_pick = orig_pick
        ai_brain.choose_attack = orig_attack

    stats = hg.summarize(results)
    print('=' * 78)
    print(f'【口径 2】决策空间   {games} 局  种子={seed}   胜率 {stats["p1_win_rate"]:.4f}')
    asked = sum(v for k, v in picks.items() if k.startswith('候选数'))
    for k in sorted(picks):
        if not k.startswith('候选数'):
            continue
    dist = collections.Counter()
    for k, v in picks.items():
        if k.startswith('候选数='):
            dist[int(k.split('=')[1])] += v
    print(f'  共被问 {asked} 次（{asked / games:.2f} 次/局）')
    for n in sorted(dist):
        print(f'      候选 {n} 张 : {dist[n]:7d}  ({_pct(dist[n], asked):5.1f}%)')
    for label in ('唯一候选（没得选）', '多候选（真的在选）'):
        print(f'      {label} : {picks[label]:7d}  ({_pct(picks[label], asked):5.1f}%)')
    print('  —— 空候选的归因 ——')
    for k, v in empty_reason.most_common():
        print(f'      {k:<40s} {v:6d}  ({_pct(v, max(1, dist[0])):5.1f}%)')
    if empty_card:
        print('  —— 空候选时**手上在池里却打不出去**的卡（前 15）——')
        for name, n in empty_card.most_common(15):
            print(f'      {name:<12s} {n:6d}')

    print()
    print(f'【口径 4】侵略性缺口   {games} 局')
    tot = attach['总开炮'] or 1
    for k in ('总开炮', '打的是已探明格（必中）', '打在未知格（可能命中）',
              '★ 打在已证明是空的格（纯浪费）'):
        print(f'      {k:<28s} {attach[k]:7d}  ({_pct(attach[k], tot):5.1f}%)')
    # 每次"想问牌"就是一次出牌机会；`choose_card` 被问几次 = 几次真实机会
    print(f'      出牌机会 {asked} 次 vs 真的出了牌 '
          f'{sum(1 for r in results for k, pid, _d in r.actions if k == "use_magic_card" and pid == r.p1)} 张')

    # ── 池外卡的机会表 ─────────────────────────────────────────────────
    print()
    print('【口径 3A】池外卡在手上的机会（这是"实现交互能力值不值得"的依据）')
    total_decisions = sum(outpool_total_hand.values())
    grand_total_handed = sum(outpool_in_hand.values())
    print(f'  每次决策时手上平均 {grand_total_handed / max(1, total_decisions):.2f} 张池外卡'
          f'（决策 {total_decisions} 次）')
    print(f'  {"卡名":<12s} {"在手次数":>8s} {"在手占比":>8s} {"此刻能打":>8s} {"能打/在手":>9s}')
    for name, n in outpool_in_hand.most_common():
        ready = outpool_ready.get(name, 0)
        print(f'  {name:<12s} {n:8d} {_pct(n, total_decisions):7.1f}%'
              f' {ready:8d} {_pct(ready, n):8.1f}%')
    return results


def _attribute_empty(room, ai_id, reason, per_card):
    """空候选时到底是"手里没牌"还是"有牌但打不出去"（两者改法不同）。"""
    player = (room.players or {}).get(ai_id)
    hand = list(getattr(player, 'magic_hand', None) or []) if player else []
    if not hand:
        reason['手里一张牌都没有'] += 1
        return
    in_pool = [c for c in hand if getattr(c, 'name', None) in server._MASTER_ENABLED_CARDS]
    if not in_pool:
        reason['有手牌但一张都不在池里（全是池外卡）'] += 1
        for c in hand:
            per_card[f'池外·{getattr(c, "name", "?")}'] += 1
        return
    playable_now = [c for c in in_pool if server.can_play_magic_card(room, ai_id, c)]
    if not playable_now:
        reason['在池的牌全被 can_play 挡住（阶段/回合/速阶/锁卡）'] += 1
        for c in in_pool:
            per_card[f'闸门·{getattr(c, "name", "?")}'] += 1
        return
    reason['过了 can_play 但被 readiness 试算剔掉'] += 1
    for c in playable_now:
        try:
            if server._master_card_readiness(room, ai_id, c) is None:
                per_card[getattr(c, 'name', '?')] += 1
        except Exception:
            per_card[getattr(c, 'name', '?')] += 1


# ===========================================================================
# 口径 3B：逐张池外卡加进池子，量胜率（只用来判断"值不值得实现能力"）
# ===========================================================================
# ⚠️ 这张表**不是待办清单**。每一项都先读 `_MASTER_ENABLED_CARDS` 旁边的
#    "为什么不开"再跑 —— 「会等施法者自己点选 / 会把回合卡死」的那些即使
#    胜率是正的也**不许**直接开回去（CLAUDE.md 教训 #38）。
_OUT_POOL_CARDS = (
    '克苏鲁之眼',    # 要施法者给出自己那一格；就算能打，收益也要等对手回答
    '神之宣告',      # 死 2 艘换对方 1 艘，对自己净亏
    '恶魔契约',      # 双方绑定，只会加大自己的损失
    '教皇旨意',      # AI 没有"弃卡换攻击"，打出去 = 把自己回合清零
    '禁忌果实',      # 封掉双方魔法，AI 靠魔法赢 = 自废武功
    '伊甸园',        # 实测否掉
    '命运骰子',      # 摇到 3 点开 pending_dice_discard，AI 侧无消费点
    '绝处逢生',      # 实测否掉
    '仁王之盾',      # 实测无差别
)


def section_outpool(games, seed):
    base_pool = frozenset(server._MASTER_ENABLED_CARDS)
    print('=' * 78)
    print(f'【口径 3B】池外逐张加回（同一批局面）  {games} 局  种子={seed}')
    print(f'  {"档位":<24s} {"胜率":>7s}  {"95% CI":>14s} {"相对基线":>9s}'
          f' {"卡死":>5s} {"被拒":>6s}')
    rows = []
    for name in (None,) + _OUT_POOL_CARDS:
        server._MASTER_ENABLED_CARDS = (base_pool if name is None
                                        else base_pool | {name})
        results = _quiet_run('master', 'hard', games, seed)
        st = hg.summarize(results)
        rows.append((name or '(基线)', st))
        lo, hi = st['p1_win_rate_ci']
        delta = ''
        if name is not None:
            delta = '%+.1f' % ((st['p1_win_rate'] - rows[0][1]['p1_win_rate']) * 100)
        print(f'  {(name or "(基线·线上池)"):<24s} {st["p1_win_rate"] * 100:6.1f}%'
              f'  {lo * 100:6.1f}~{hi * 100:5.1f}% {delta:>9s}'
              f' {st["stalled"]:5d} {st["violations"]:6d}')
    server._MASTER_ENABLED_CARDS = base_pool
    print('  ⚠️ 这张表**不是"该开哪些卡"的清单** —— 每一项都要先读 `_MASTER_ENABLED_CARDS`')
    print('     旁边写的"为什么不开"再判断：交互要等施法者本人的卡，即使胜率正')
    print('     也必须先实现"就地自己回答"的能力（教训 #38），不能只看分数开回去。')
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description='大师 AI 差距分析（只读度量）')
    ap.add_argument('--games', type=int, default=2000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--section', default='all',
                    choices=('all', 'loss', 'space', 'outpool'))
    args = ap.parse_args(argv)

    if args.section in ('all', 'loss'):
        section_loss(args.games, args.seed)
        print()
    if args.section in ('all', 'space'):
        section_space(args.games, args.seed)
        print()
    if args.section in ('all', 'outpool'):
        section_outpool(args.games, args.seed)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
