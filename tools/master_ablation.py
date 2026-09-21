# -*- coding: utf-8 -*-
"""离线对照实验台：在大师的不同能力开关下跑「master vs hard」胜率。

为什么需要它：设计文档 §12 里的两个结论都是**量出来的**，不是推出来的
（「放开卡池反而更弱」「读情报在没情报时是空操作」）。本批每一档能力也一样 ——
只有把开关逐档打开、各自跑 1000 局，才能知道哪一档真的加分、哪一档在扣分。

用法（**必须带 UTF-8，否则中文卡名在控制台是乱码**）：
    $env:PYTHONIOENCODING='utf-8'
    python tools/master_ablation.py --games 1000 --seed 1

⚠️ 每一档都在**同一个种子序列**上跑：局面完全相同，只有 AI 的开关不同。
   这样两档之间的差值就是该开关的净效果，不受"换了一批局面"的干扰。

⚠️ 度量前提（第一版就栽在这里）：`master vs hard` 的**两个座位都是 AI**，
   房间级的单一 `ai_difficulty` 会让对手也套用大师的卡池与开炮逻辑 ——
   于是量出来的是"大师 vs 大师"，胜率必然贴 50%。驱动器已改为**逐座位**下发
   （`room.ai_difficulty_by_player`）。改动前 master vs hard 是 50.0%，
   改动后立刻变成 43.7% —— 那 6 个百分点的差就是"度量工具量错了对象"。
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

# 第 1 批的 9 张安全卡（无目标、无待办、无前置）—— 用作"卡池"这档的对照。
_SAFE9 = ('余音绕梁', '火力全开', '无中生有', '极限增援', '无暇圣心',
          '看破！', '五险一金', '八方来财', '百亿补贴')

# 本批线上的默认卡池（`server._MASTER_ENABLED_CARDS` 的原始值，先存下来）。
_FULL_POOL = frozenset(server._MASTER_ENABLED_CARDS)

# 「按情报开炮 + 不浪费已排除格」那套敌船模型（第 1 批就有，用作对照）。
_ORIGINAL_CHOOSE_ATTACK = ai_brain.choose_attack


def _set(pool=None, cards=None, attack=None):
    """把开关设成指定值；None = 不动。"""
    if pool is not None:
        server._MASTER_ENABLED_CARDS = frozenset(pool)
    if cards is not None:
        ai_brain.CARDS_PER_TURN = int(cards)
    if attack is not None:
        ai_brain.choose_attack = attack


def _without(*names):
    """全池**去掉**这几张 —— 用来单独量某张卡是加分还是扣分。

    ⚠️ 这是定位"哪一张把胜率拉下来"最快的手段：一次一张，
       而不是把整批一起打开再看总账（总账看不出是谁的锅）。
    """
    return _FULL_POOL - set(names)


def _plain_attack(room, ai_id, rng=None):
    """对照组用的"朴素开炮"：只在**没打过**的格子里均匀挑（不看情报）。

    这是 `choose_attack` 的第一版行为 —— 用来单独量"读情报"值多少分。
    """
    import random as _random
    rng = rng or _random.Random()
    me = (getattr(room, 'players', None) or {}).get(ai_id)
    if me is None:
        return None
    attacked = ai_brain._attacked_cells(me)
    cands = [c for c in ai_brain._all_cells() if c not in attacked]
    return rng.choice(sorted(cands)) if cands else None


# 档位：名字 → (说明, 设置函数)
CONFIGS = {
    'safe9_1': ('对照：9 张安全卡 + 每回合 1 张（第 1 批的卡池口径）',
                lambda: _set(pool=_SAFE9, cards=1, attack=_ORIGINAL_CHOOSE_ATTACK)),
    'safe9_3': ('9 张安全卡 + 每回合 3 张（单独量"出牌预算"）',
                lambda: _set(pool=_SAFE9, cards=3, attack=_ORIGINAL_CHOOSE_ATTACK)),
    'full_1': ('全卡池 + 每回合 1 张（单独量"卡池"，预算不变）',
               lambda: _set(pool=_FULL_POOL, cards=1, attack=_ORIGINAL_CHOOSE_ATTACK)),
    'full_3': ('全卡池 + 每回合 3 张（本批线上默认）',
               lambda: _set(pool=_FULL_POOL, cards=3, attack=_ORIGINAL_CHOOSE_ATTACK)),
    'full_3_noinfo': ('全卡池 + 3 张，但开炮**不读情报**（单独量"读情报"）',
                      lambda: _set(pool=_FULL_POOL, cards=3, attack=_plain_attack)),
    # 逐张排查：全池各去掉一张，用来定位"哪张卡把胜率拉下来"
    'no_yuyin': ('全卡池去掉「余音绕梁」', lambda: _set(pool=_without('余音绕梁'))),
    'no_mingzhi': ('全卡池去掉「明智埋葬」', lambda: _set(pool=_without('明智埋葬'))),
    'no_shenji': ('全卡池去掉「神机妙算」', lambda: _set(pool=_without('神机妙算'))),
    'no_woxin': ('全卡池去掉「卧薪尝胆」', lambda: _set(pool=_without('卧薪尝胆'))),
    'no_repl': ('全卡池去掉重摆三张（回光返照/败者食尘/滥竽充数）',
                lambda: _set(pool=_without('回光返照', '败者食尘', '滥竽充数'))),
}


def main(argv=None):
    ap = argparse.ArgumentParser(description='大师 AI 能力开关对照实验')
    ap.add_argument('--games', type=int, default=1000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--p2', default='hard', help='对手（默认困难）')
    ap.add_argument('--configs', default=','.join(CONFIGS),
                    help='只跑指定的档，逗号分隔；档名见 --list')
    ap.add_argument('--list', action='store_true', help='列出档位后退出')
    args = ap.parse_args(argv)

    if args.list:
        for name, (desc, _fn) in CONFIGS.items():
            print('%-16s %s' % (name, desc))
        return 0

    names = [n.strip() for n in args.configs.split(',') if n.strip()]
    unknown = [n for n in names if n not in CONFIGS]
    if unknown:
        raise SystemExit(f'未知档位 {unknown}；可用：{", ".join(CONFIGS)}')

    print(f'对手 p2={args.p2}  每档 {args.games} 局  起始种子={args.seed}')
    print('=' * 78)
    rows = []
    for name in names:
        desc, setup = CONFIGS[name]
        setup()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            results = hg.run_many(hg.make_policy('master'), hg.make_policy(args.p2),
                                  games=args.games, seed=args.seed)
        stats = hg.summarize(results)
        rows.append((name, desc, stats))
        print('%-15s %s' % (name, desc))
        print('%15s 胜率 %.1f%%  (95%%CI %.1f~%.1f)  卡死 %d  被拒 %d  平均回合 %.2f'
              % ('', stats['p1_win_rate'] * 100,
                 stats['p1_win_rate_ci'][0] * 100, stats['p1_win_rate_ci'][1] * 100,
                 stats['stalled'], stats['violations'], stats['avg_rounds']))
    print('=' * 78)
    base = rows[0][2]['p1_win_rate']
    for name, _desc, stats in rows:
        print('%-15s %6.1f%%  相对 %-9s %+6.1f 个百分点'
              % (name, stats['p1_win_rate'] * 100, rows[0][0],
                 (stats['p1_win_rate'] - base) * 100))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
