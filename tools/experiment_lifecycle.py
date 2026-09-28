# -*- coding: utf-8 -*-
"""实验台（第二批）：把"续命节奏"这件事量成数字。

【上一批量到了什么】
`tools/probe_win_source.py` + 组消融已经确认三件事（都不是推测）：
  · 大师炮击击沉 **4.69 次/局**，终局只击沉对方 **2.61 艘** ⇒ 对手捞回 **2.07 艘**；
  · 困难炮击击沉 3.65 次 ⇒ 终局击沉大师 4.99 艘（这里"捞回"为负，说明关系非线性）；
  · 组消融：去掉续命类卡（死者苏生/增援/滥竽充数/疗愈）**−5.3 点**、
    去掉直接输出类（轰炸/神威!/硫磺火焰/火力全开/冻结）**−6.0 点**。
⇒ 大师赢的是**接力赛**：谁能让自己的船"多活一节"。

【这一批要回答的两个新问题】
  Q1「护盾」到底值不值：它在游戏里**不记进 `attacks`**（被盾挡下的那一炮不算
     打过这格）—— 也就是说一炮打在有盾的船上，那一炮**被作废**。
     量：整局被盾/无敌吸收的炮数是多少？谁吃的？
  Q2「看破！」值不值：卡面是"对方这一整大回合所有魔法卡无效"。
     大师每局出它 0.2 次（手里有就打），但对手（hard）本来每回合也只出 1 张
     —— 量一下它到底锁掉了对方几张牌。

⚠️ 只读：探针包在原函数外层，记完原样调用。
用法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/experiment_lifecycle.py --games 2000 --seed 1
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


def _quiet(games, seed):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return hg.run_many(hg.make_policy('master'), hg.make_policy('hard'),
                           games=games, seed=seed, quiet=True)


def measure_lifecycle(games, seed):
    """Q1 + Q2：护盾吸收量、看破封锁量、双方的续命/复活事件数。"""
    shielded = collections.Counter()
    blocked_cards = collections.Counter()     # 被看破挡下的出牌尝试
    played = collections.Counter()
    heal_events = collections.Counter()       # 复活/加船事件（按卡名）
    shield_grant = collections.Counter()

    orig_attack = server.handle_attack
    orig_use = server.handle_use_magic_card

    def attack_spy(data):
        resp = orig_attack(data)
        pid = data.get('player_id')
        seat = 'master' if str(pid or '').startswith('ai-') else 'hard'
        # 被盾/无敌吸收 = 返回 success 但没记进 attacks
        try:
            room = server.room_manager.get_room(data.get('room_id'))
            if room is not None and resp and resp.get('status') == 'success':
                me = room.players.get(pid)
                cell = (data.get('x'), data.get('y'))
                if me is not None and cell not in {(a.x, a.y) for a in me.attacks}:
                    shielded[seat] += 1
        except Exception:
            pass
        return resp

    def use_spy(data):
        room = server.room_manager.get_room(data.get('room_id'))
        pid = data.get('player_id')
        seat = 'master' if str(pid or '').startswith('ai-') else 'hard'
        name = (data.get('card') or {}).get('name')
        if room is not None:
            p = room.players.get(pid)
            if p is not None and getattr(p, 'magic_blocked', None):
                blocked_cards[seat] += 1
        resp = orig_use(data)
        if resp and resp.get('status') == 'success':
            played[(seat, name)] += 1
            if name in ('死者苏生', '增援', '滥竽充数', '疗愈', '命运骰子'):
                heal_events[(seat, name)] += 1
            if name in ('仁王之盾', '卧薪尝胆'):
                shield_grant[(seat, name)] += 1
        return resp

    server.handle_attack = attack_spy
    server.handle_use_magic_card = use_spy
    try:
        results = _quiet(games, seed)
    finally:
        server.handle_attack = orig_attack
        server.handle_use_magic_card = orig_use

    st = hg.summarize(results)
    dmg = hg.damage_stats(results)
    print(f'master vs hard  {games} 局  种子={seed}   胜率 {st["p1_win_rate"]:.4f}')
    print('=' * 78)
    print('【Q1 护盾/无敌吸收】—— 被盾挡下的那一炮**不记进 `attacks`**（那一炮被作废）')
    fired_m = dmg['shots_per_game']
    print(f'  master 吃的被吸收炮数 {shielded["master"]:6d}'
          f'  ({shielded["master"] / games:.3f}/局)')
    print(f'  hard   吃的被吸收炮数 {shielded["hard"]:6d}'
          f'  ({shielded["hard"] / games:.3f}/局)')
    tot = shielded['master'] + shielded['hard']
    print(f'  合计 {tot} ({tot / games:.3f}/局)  占开炮总数的'
          f' {tot / max(1, dmg["shots_per_game"] * games) * 100:.2f}%')
    print()
    print('【Q2 看破！封锁】—— 被看破时**尝试**出牌的次数（= 锁掉的牌）')
    print(f'  master 被锁 {blocked_cards["master"]:5d} ({blocked_cards["master"] / games:.3f}/局)')
    print(f'  hard   被锁 {blocked_cards["hard"]:5d} ({blocked_cards["hard"] / games:.3f}/局)')
    for seat in ('master', 'hard'):
        print(f'  {seat} 打出「看破！」 '
              f'{played[(seat, "看破！")]:5d} 次 ({played[(seat, "看破！")] / games:.3f}/局)')
    print()
    print('【续命/加船事件】')
    for (seat, name), n in sorted(heal_events.items(), key=lambda kv: -kv[1]):
        print(f'  {seat:<7s} {name:<8s} {n:5d} ({n / games:.3f}/局)')
    print('【护盾授予】')
    for (seat, name), n in sorted(shield_grant.items(), key=lambda kv: -kv[1]):
        print(f'  {seat:<7s} {name:<8s} {n:5d} ({n / games:.3f}/局)')
    print()
    print('【大师出牌明细】')
    ms = sorted(((n, c) for (s, c), n in played.items() if s == 'master'), reverse=True)
    tot_m = sum(n for n, _ in ms)
    print(f'  共 {tot_m} 张 ({tot_m / games:.2f} 张/局)')
    for n, c in ms:
        print(f'      {c:<10s} {n:6d}  ({n / games:.3f}/局)')
    print()
    print('【整局动作构成（大师座位）】')
    kinds = collections.Counter()
    for r in results:
        for kind, pid, _d in r.actions:
            if pid == r.p1:
                kinds[kind] += 1
    for kind, n in kinds.most_common():
        print(f'      {kind:<28s} {n:7d}  ({n / games:.2f}/局)')
    return results


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--games', type=int, default=2000)
    ap.add_argument('--seed', type=int, default=1)
    args = ap.parse_args(argv)
    measure_lifecycle(args.games, args.seed)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
