# -*- coding: utf-8 -*-
"""诊断：回合内**动作顺序**有没有把牌的收益白白吃掉。

【为什么问这个】
`server._ai_master_turn` 的战斗循环是「先出牌 → 再开炮 → 再出牌 → …」。
而有两张牌的收益**取决于它是在几炮之后打出去的**：

  · `火力全开`（12298）：`attacks_remaining = max(0, attacks_remaining) * 2`
    —— 翻的是**当前剩余次数**。第 0 炮之后打 = 2n；第 1 炮之后打 = 2n−1。

  也就是说"先打一发再翻倍"能多拿一次攻击。这是**加法的顺序问题**，
  不涉及任何卡面/数值改动，纯 AI 决策层。

本脚本量：`火力全开` 实际打出时是"第几炮之后"（= 剩余次数），
以及"如果统一挪到第一炮之后"能多拿多少次攻击。

⚠️ 只读：探针包在 `handle_attack` / `handle_use_magic_card` 外层。
用法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/probe_turn_order.py --games 2000 --seed 1
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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=2000)
    ap.add_argument('--seed', type=int, default=1)
    args = ap.parse_args(argv)
    games = args.games

    # 每个大师回合开始时的"本回合已开炮次数"（用来判断火力全开是在第几炮之后）
    shots_this_turn = collections.Counter()
    huoli_timing = collections.Counter()      # 打出火力全开时已开炮几次
    wuxian_shots = collections.Counter()      # 打出五险一金时已开炮几次
    state = {'cur': None, 'n': 0}

    orig_attack = server.handle_attack
    orig_use = server.handle_use_magic_card

    def attack_spy(data):
        pid = data.get('player_id')
        cur = server.room_manager.get_room(data.get('room_id'))
        if cur is not None and cur.current_attacker == pid and state['cur'] != cur.current_attacker:
            pass
        resp = orig_attack(data)
        if str(pid or '').startswith('ai-'):
            state['n'] += 1
        return resp

    def use_spy(data):
        pid = data.get('player_id')
        name = (data.get('card') or {}).get('name')
        if str(pid or '').startswith('ai-') and name in ('火力全开', '五险一金'):
            (huoli_timing if name == '火力全开' else wuxian_shots)[state['n']] += 1
        return orig_use(data)

    # 每换一个攻击者就重置计数（end_turn 是唯一的换手点）
    orig_end = server.end_turn

    def end_spy(data):
        resp = orig_end(data)
        if resp and resp.get('status') == 'success':
            shots_this_turn[state['n']] += 1
            state['n'] = 0
        return resp

    server.handle_attack = attack_spy
    server.handle_use_magic_card = use_spy
    server.end_turn = end_spy
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            results = hg.run_many(hg.make_policy('master'), hg.make_policy('hard'),
                                  games=games, seed=args.seed, quiet=True)
    finally:
        server.handle_attack = orig_attack
        server.handle_use_magic_card = orig_use
        server.end_turn = orig_end

    st = hg.summarize(results)
    print(f'master vs hard  {games} 局  种子={args.seed}   胜率 {st["p1_win_rate"]:.4f}')
    print('=' * 78)
    print('【火力全开 打出的时机】—— 打出时本回合已开炮几次')
    tot = sum(huoli_timing.values()) or 1
    for k in sorted(huoli_timing):
        n = huoli_timing[k]
        print(f'      第 {k} 炮之后: {n:5d} 次  ({n / tot * 100:5.1f}%)')
    print(f'  合计 {tot} 次（{tot / games:.3f}/局）')
    print()
    print('【五险一金 打出的时机】')
    tot2 = sum(wuxian_shots.values()) or 1
    for k in sorted(wuxian_shots):
        n = wuxian_shots[k]
        print(f'      第 {k} 炮之后: {n:5d} 次  ({n / tot2 * 100:5.1f}%)')
    print(f'  合计 {tot2} 次（{tot2 / games:.3f}/局）')
    print()
    print('【每回合大师实际开炮次数分布】')
    tot3 = sum(shots_this_turn.values()) or 1
    for k in sorted(shots_this_turn):
        n = shots_this_turn[k]
        print(f'      {k:2d} 炮: {n:5d} 回合  ({n / tot3 * 100:5.1f}%)')
    print(f'  合计 {tot3} 个大师回合，平均 {sum(k * v for k, v in shots_this_turn.items()) / tot3:.2f} 炮/回合')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
