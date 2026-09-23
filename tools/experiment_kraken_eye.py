# -*- coding: utf-8 -*-
"""实验台：`克苏鲁之眼` 补上"自己那一格"之后值不值。

【背景（读代码读出来的，不是猜）】
`_MASTER_ENABLED_CARDS` 里没有它，而 `_master_card_readiness` 又对它
**无条件返回 None** —— 也就是"光加进池子也没用，必须同时补能力"。
不补的原因写在 `server.py:6238` 附近：它要施法者先给出
「自己那一艘船的坐标」（`apply_magic_effect` 里的 `_pick_cell_from_target`），
而决策层给不出来。

但它**其实是给得出来的**：`_pick_cell_from_target` 接受 `{'x': x, 'y': y}`，
而"我该献出哪一艘"正是 `ai_brain.resolve_ship_pick` 已经在回答的问题
（`reason='kraken_eye'` 那条分支现成）。所以这不是"做不到"，
而是"**没人把这两件已有的东西接起来**"。

更关键的是上一批量出来的不对称：大师每局**被击沉 4.99 艘**、
只击沉对方 2.61 艘 —— 也就是"我暴露一艘"的边际代价远小于
"多知道对方一艘"的边际收益。这正好是这张卡成立的前提。

本脚本用**猴补**（不改仓库代码）把这条能力临时接上，量它值多少。
值正就落地；不值就留档，别开。

⚠️ 只读：猴补在跑完的 finally 里还原。
用法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/experiment_kraken_eye.py --games 5000 --seeds 1,50000,900000
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

KRAKEN = '克苏鲁之眼'


def _own_cell_targets(room, ai_id, card):
    """替大师回答「献出自己哪一艘」：走 `resolve_ship_pick`（唯一一份选船实现）。"""
    if str(getattr(card, 'name', '')) != KRAKEN:
        return None
    caster = room.players.get(ai_id)
    opp_id = server._opponent_of(room, ai_id)
    opp = room.players.get(opp_id) if opp_id else None
    if caster is None or opp is None:
        return None
    alive = [s for s in (caster.ships or []) if server._is_ship_alive(caster, s)]
    if not alive or not [s for s in (opp.ships or []) if server._is_ship_alive(opp, s)]:
        return None
    picked = ai_brain.resolve_ship_pick(room, ai_id, 'kraken_eye', alive)
    if picked is None:
        return None
    for pos in (getattr(picked, 'positions', None) or []):
        cell = ai_brain._cell_of(pos)
        if cell is not None:
            return {'x': cell[0], 'y': cell[1]}
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=5000)
    ap.add_argument('--seeds', default='1,50000,900000')
    args = ap.parse_args(argv)
    seeds = [int(s) for s in args.seeds.split(',') if s.strip()]

    base_pool = frozenset(server._MASTER_ENABLED_CARDS)
    orig_readiness = server._master_card_readiness
    buf = io.StringIO()

    def enabled_readiness(room, ai_id, card):
        t = _own_cell_targets(room, ai_id, card)
        if t is not None:
            return t
        return orig_readiness(room, ai_id, card)

    def run(label, pool, readiness):
        server._MASTER_ENABLED_CARDS = pool
        server._master_card_readiness = readiness
        cells = []
        for s in seeds:
            with contextlib.redirect_stdout(buf):
                rs = hg.run_many(hg.make_policy('master'), hg.make_policy('hard'),
                                 games=args.games, seed=s, quiet=True)
            st = hg.summarize(rs)
            lo, hi = st['p1_win_rate_ci']
            cells.append('%5.1f%% [%4.1f,%4.1f]' % (st['p1_win_rate'] * 100,
                                                    lo * 100, hi * 100))
        print('%-34s' % label + ''.join('%21s' % c for c in cells))

    print(f'master vs hard  每格 {args.games} 局 × {len(seeds)} 个独立种子')
    print('%-34s' % '档位' + ''.join('%21s' % ('seed=%d' % s) for s in seeds))
    print('=' * 100)
    try:
        run('baseline（线上池）', base_pool, orig_readiness)
        run('+克苏鲁之眼（补自己那一格）', base_pool | {KRAKEN}, enabled_readiness)
        run('+克苏鲁之眼（不加能力=对照）', base_pool | {KRAKEN}, orig_readiness)
    finally:
        server._MASTER_ENABLED_CARDS = base_pool
        server._master_card_readiness = orig_readiness
    print('=' * 100)
    print('对照项 `不加能力` 应该与 baseline **逐位相同**（说明 README 说的')
    print('"光加池子没用"是真的、且本实验的猴补范围是干净的）。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
