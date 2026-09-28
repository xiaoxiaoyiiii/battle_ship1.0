# -*- coding: utf-8 -*-
"""实验台：把「大杠杆」候选各跑一遍，看哪一条真的动胜率（不是调参数）。

【为什么单开一个脚本而不是往 `master_ablation.py` 里堆】
`master_ablation.py` 的档位都是"换一个决策函数/卡池"（属于**调参**），
而 `docs/MASTER_AI_2026_09_21.md` §12.4/§12.5 已经把那条路走到底了
（每张卡 ±1 点以内、预算 3 张已饱和、选牌器换成随机的胜率一样）。
本脚本量的是**结构性**的候选 —— 每一条都对应一个"以前没做过的机制"：

  · `oracle_attack`   —— **上界**：开炮知道对方全部船位会是几成？
                        （这不是能上线的改法，是"选点还有多少空间"的标尺）
  · `reset_each_turn` —— 重摆类（回光返照 / 败者食尘）每回合都推倒重来：
                        它在"对方已经打过的格"上重摆 ⇒ 对方永远打不到我。
                        量它值多少，就知道"重摆是外挂还是噱头"。
  · `place_safe`      —— 自己摆船时**优先挑对方已经打过的格**（同一机制，
                        只用在摆放而不是用整张卡）。
  · `prefer_revive`   —— 出牌时把续命类卡（死者苏生/增援/滥竽充数/疗愈）
                        的价值抬到最高（组消融量出它们合计值 −5.3）。

⚠️ 本脚本**只做实验**，不落地任何改动；每条都在同一批局面上跑。
用法：
    $env:PYTHONIOENCODING='utf-8'
    python tools/experiment_big_levers.py --games 3000 --seed 1
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


def _quiet(games, seed):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return hg.run_many(hg.make_policy('master'), hg.make_policy('hard'),
                           games=games, seed=seed, quiet=True)


def _row(name, results, base):
    st = hg.summarize(results)
    dmg = hg.damage_stats(results)
    lo, hi = st['p1_win_rate_ci']
    delta = '' if base is None else '%+5.1f' % ((st['p1_win_rate'] - base) * 100)
    print('%-20s %6.1f%%  (95%%CI %5.1f~%5.1f) %7s  卡死%4d  击沉%.2f/%.2f '
          '炮击击沉%.2f  命中%.4f  回合%.2f'
          % (name, st['p1_win_rate'] * 100, lo * 100, hi * 100, delta,
             st['stalled'], dmg['sunk_by_p1'], dmg['sunk_by_p2'],
             dmg['kills_by_p1'], dmg['p1_hit_rate'], st['avg_rounds']))
    return st['p1_win_rate']


def main(argv=None):
    ap = argparse.ArgumentParser(description='大师 AI 大杠杆候选实验（只读，不落地）')
    ap.add_argument('--games', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--configs', default='baseline,oracle_attack,reset_each_turn,'
                                         'place_safe,prefer_revive')
    args = ap.parse_args(argv)
    games, seed = args.games, args.seed
    want = set(n.strip() for n in args.configs.split(',') if n.strip())

    orig_attack = ai_brain.choose_attack
    orig_place = ai_brain.resolve_placement
    orig_value = ai_brain.card_value
    orig_pick = server._ai_master_pick
    orig_turn = server._ai_master_turn
    base = None

    def _restore():
        ai_brain.choose_attack = orig_attack
        ai_brain.resolve_placement = orig_place
        ai_brain.card_value = orig_value
        server._ai_master_pick = orig_pick
        server._ai_master_turn = orig_turn

    def run(name, fn):
        nonlocal base
        _restore()
        if fn is not None:
            fn()
        results = _quiet(games, seed)
        w = _row(name, results, base)
        if base is None:
            base = w
        _restore()

    print(f'master vs hard  {games} 局  种子={seed}')
    print('=' * 118)

    if 'baseline' in want:
        run('baseline', None)

    if 'oracle_attack' in want:
        # ★ 上界标尺：开炮时**直接读对方船位**。这不是能上线的改法
        #   （AI 不许作弊，CLAUDE.md/docs §4.1），只是用来量"选点还剩多少空间"。
        def _oracle():
            def attack(room, ai_id, rng=None):
                opp_id = ai_brain._opponent_id(room, ai_id)
                opp = (room.players or {}).get(opp_id) if opp_id else None
                me = (room.players or {}).get(ai_id)
                if opp is None or me is None:
                    return orig_attack(room, ai_id, rng)
                attacked = ai_brain._attacked_cells(me)
                for sh in (getattr(opp, 'ships', None) or []):
                    if len(sh.hits or []) >= len(sh.positions or []):
                        continue
                    for c in ai_brain._cells_of(sh):
                        if c not in attacked:
                            return c
                return orig_attack(room, ai_id, rng)
            ai_brain.choose_attack = attack
        run('oracle_attack', _oracle)

    if 'place_safe' in want:
        # 自己摆船 / 卡牌放置都优先挑"对方已经打过的格"（打过的格不会再被打）。
        def _place_safe():
            def place(room, ai_id, kind, candidates, rng=None):
                return orig_place(room, ai_id, kind, candidates, rng)
            ai_brain.resolve_placement = place

            def place_board(room, pid):
                """摆满自己的棋盘时，优先挑**对方已经打过**的格。"""
                player = room.players.get(pid)
                if player is None:
                    return False
                count = int(getattr(player, 'max_ships', None) or 6)
                if len(getattr(player, 'ships', None) or []) >= count:
                    return False
                opp_id = ai_brain._opponent_id(room, pid)
                opp = (room.players or {}).get(opp_id) if opp_id else None
                probed = ai_brain._attacked_cells(opp) if opp is not None else set()
                cells = [(x, y) for x in range(6) for y in range(6)]
                safe = [c for c in cells if c in probed]
                rest = [c for c in cells if c not in probed]
                ai_brain._rng().shuffle(safe)
                ai_brain._rng().shuffle(rest)
                chosen = (safe + rest)[:count]
                from server import PlayerShip, Position
                player.ships = [PlayerShip(positions=[Position(x=x, y=y)], hits=[])
                                for x, y in chosen]
                player.remaining_ships = 0
                ships = [{'positions': [{'x': p.x, 'y': p.y} for p in sh.positions],
                          'hits': []} for sh in player.ships]
                from server import handle_place_ships
                resp = handle_place_ships({'room_id': room.id, 'player_id': pid,
                                           'ships': ships})
                return bool(resp and resp.get('status') == 'success')

            server._ai_place_board = place_board
        run('place_safe', _place_safe)

    if 'prefer_revive' in want:
        # 续命类卡的价值抬到最高（组消融里它们合计值 −5.3）。
        def _prefer_revive():
            REVIVE = ('死者苏生', '增援', '滥竽充数', '疗愈')
            def value(name):
                v = orig_value(name)
                return max(v, 999) if str(name) in REVIVE else v
            ai_brain.card_value = value
        run('prefer_revive', _prefer_revive)

    if 'reset_each_turn' in want:
        # 重摆类：每回合开头把棋盘推倒重来（量"重摆是不是外挂"）。
        def _reset():
            def turn(room_id, room, ai_id):
                try:
                    cur = server.room_manager.get_room(room_id)
                    if cur is not None and cur.state == 'attacking':
                        server._ai_place_board(cur, ai_id)
                except Exception:
                    pass
                return orig_turn(room_id, room, ai_id)
            server._ai_master_turn = turn
        run('reset_each_turn', _reset)

    if 'huoli_after_shot' in want:
        # 火力全开 翻的是**当前剩余次数**（server.py:12298 的
        # `attacks_remaining = max(0, attacks_remaining) * 2`）。
        # 第 0 炮之后打 = 2n；第 1 炮之后打 = 1 + 2(n−1) = 2n−1。
        # ⇒ **先打一发再翻倍能多拿一次攻击**。这是加法顺序问题，
        #   不改任何卡面/数值，只在 AI 决策层把这张卡推迟到第一炮之后。
        def _huoli():
            HUOLI = '火力全开'
            def pick(room, ai_id, cards_played=0):
                player = room.players.get(ai_id)
                if player is None:
                    return orig_pick(room, ai_id, cards_played)
                hand = list(player.magic_hand or [])
                state_ok = (getattr(room, 'state', '') == 'attacking'
                            and getattr(room, 'current_phase', '') == 'battle')
                if state_ok and int(getattr(room, 'attacks_remaining', 0) or 0) > 1:
                    # 本回合**一发都还没打**时才推迟（打过了就不用再推迟）
                    has_huoli = any(getattr(c, 'name', None) == HUOLI for c in hand)
                    if has_huoli and not _huoli_fired(room, ai_id):
                        saved = server._MASTER_ENABLED_CARDS
                        server._MASTER_ENABLED_CARDS = saved - {HUOLI}
                        try:
                            return orig_pick(room, ai_id, cards_played)
                        finally:
                            server._MASTER_ENABLED_CARDS = saved
                return orig_pick(room, ai_id, cards_played)

            def _huoli_fired(room, ai_id):
                """本回合是否已经开过炮（`last_attack` 的 attacker 是我 + 同回合）。"""
                la = getattr(room, 'last_attack', None) or {}
                return (la.get('attacker') == ai_id
                        and la.get('round', room.round) == room.round)

            server._ai_master_pick = pick
        run('huoli_after_shot', _huoli)

    _restore()
    print('=' * 118)
    print('⚠️ `oracle_attack` 是**上界标尺**，不是能上线的改法（AI 不许读对方船位）。')
    print('   其余各条都是"结构性"改动：值多少分就是多少分，不是调参数。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
