# -*- coding: utf-8 -*-
"""诊断：大师**真正**的回合画像 —— 起点船数、攻击次数、实际开炮数、出牌数。

【为什么前面的数不敢用】
前几版把"本回合已开炮数"记在一个只在 `end_turn` 重置的计数器里。可是
`end_turn` 里 `end_turn` 可能被**反复调用**（收尾重试、优先权询问），
于是同一个回合会被切段、计数被重复归零 —— 算出来的"每回合开炮次数"是错的
（曾经得出"49.8% 的回合一炮没打"，那其实是把对手的回合也算进去了）。

本脚本改成**在每次攻击者切换时归属**：记录 `(攻击者, 该回合开炮数)`，
只有攻击者与上一次不同才结算上一段。这样每一段都只属于一个座位。

⚠️ 只读：探针包在 `handle_attack` / `end_turn` 外层，记完原样调用。
用法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/probe_turn_profile.py --games 2000 --seed 1
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

    # 攻击段：按 (座位) 归属的开炮次数分布
    shots_by_seat = collections.defaultdict(collections.Counter)
    # 每次开炮时的 (本段已开炮数, 当时剩余攻击次数)
    rem_at_shot = collections.defaultdict(collections.Counter)
    # 每次开炮时"本段起点"是几次（第一炮时 attacks_remaining+1）
    seg = {'seat': None, 'n': 0}
    hand_size = collections.defaultdict(collections.Counter)
    # 大师回合开始时的船数
    start_ships = collections.Counter()

    orig_attack = server.handle_attack

    def seat_of(pid):
        return 'master' if str(pid or '').startswith('ai-') else 'hard'

    def attack_spy(data):
        room = server.room_manager.get_room(data.get('room_id'))
        pid = data.get('player_id')
        seat = seat_of(pid)
        if seg['seat'] != seat:
            if seg['seat'] is not None:
                shots_by_seat[seg['seat']][seg['n']] += 1
            seg['seat'], seg['n'] = seat, 0
        if room is not None:
            rem_at_shot[seat][int(getattr(room, 'attacks_remaining', 0) or 0)] += 1
        resp = orig_attack(data)
        seg['n'] += 1
        return resp

    orig_end = server.end_turn

    def end_spy(data):
        resp = orig_end(data)
        rid = data.get('room_id')
        room = server.room_manager.get_room(rid) if rid else None
        if room is not None:
            for pid, p in room.players.items():
                hand_size[seat_of(pid)][len(getattr(p, 'magic_hand', None) or [])] += 1
        return resp

    orig_enter = server.enter_battle_phase

    def enter_spy(data, *a, **kw):
        room = server.room_manager.get_room(data.get('room_id'))
        pid = data.get('player_id')
        if room is not None and str(pid or '').startswith('ai-'):
            if room.current_phase == 'preparation' and room.current_attacker == pid:
                start_ships[int(getattr(room.players[pid], 'remaining_ships', 0) or 0)] += 1
        return orig_enter(data, *a, **kw)

    server.handle_attack = attack_spy
    server.end_turn = end_spy
    server.enter_battle_phase = enter_spy
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            results = hg.run_many(hg.make_policy('master'), hg.make_policy('hard'),
                                  games=games, seed=args.seed, quiet=True)
    finally:
        server.handle_attack = orig_attack
        server.end_turn = orig_end
        server.enter_battle_phase = orig_enter
    if seg['seat'] is not None:
        shots_by_seat[seg['seat']][seg['n']] += 1

    st = hg.summarize(results)
    dmg = hg.damage_stats(results)
    print(f'master vs hard  {games} 局  种子={args.seed}   胜率 {st["p1_win_rate"]:.4f}')
    print(f'  炮击击沉 大师 {dmg["kills_by_p1"]:.3f} / 困难 {dmg["kills_by_p2"]:.3f} 次/局'
          f'   开炮总数 {dmg["shots_per_game"]:.2f} 次/局')
    print('=' * 82)
    for seat in ('master', 'hard'):
        cnt = shots_by_seat[seat]
        tot = sum(cnt.values())
        if not tot:
            continue
        avg = sum(k * v for k, v in cnt.items()) / tot
        print(f'\n【{seat} 的"攻击段"数】共 {tot} 段（{tot / games:.2f} 段/局），'
              f'平均 {avg:.2f} 炮/段')
        for k in sorted(cnt):
            n = cnt[k]
            bar = '#' * int(n / tot * 60)
            print(f'      {k:2d} 炮: {n:5d} 段  ({n / tot * 100:5.1f}%)  {bar}')

    print('\n【开炮那一刻的攻击剩余次数】—— 1 = 这是本段最后一炮')
    for seat in ('master', 'hard'):
        cnt = rem_at_shot[seat]
        tot = sum(cnt.values()) or 1
        print(f'  {seat}: ' + '  '.join(f'{k}:{cnt[k] * 100 / tot:.0f}%' for k in sorted(cnt)[:9]))

    print('\n【大师进战斗阶段时的船数】（= 本回合基础攻击次数）')
    tot = sum(start_ships.values()) or 1
    for k in sorted(start_ships):
        print(f'      {k} 艘: {start_ships[k]:5d} ({start_ships[k] / tot * 100:5.1f}%)')

    print('\n【每次 end_turn 时的双方手牌张数】')
    for seat in ('master', 'hard'):
        cnt = hand_size[seat]
        tot = sum(cnt.values()) or 1
        avg = sum(k * v for k, v in cnt.items()) / tot
        print(f'  {seat}: 平均 {avg:.2f} 张（样本 {tot}）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
