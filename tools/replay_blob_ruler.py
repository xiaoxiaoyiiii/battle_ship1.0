# -*- coding: utf-8 -*-
"""回放 blob 体积尺子（真打一局、读 `replay.build()`/`finalize()`）。

为什么要它：回放批的体积账每次都必须**实测**（契约 §1），而"改了多少"只有
**同一批种子、同一对策略**跑两次才可比 —— 把两次的输出贴出来做逐局差值。

用法：
    python tools/replay_blob_ruler.py                 # seed 4242 起 10 局
    python tools/replay_blob_ruler.py --games 10 --seed 4242 --p1 master --p2 random
    python tools/replay_blob_ruler.py --json out.json # 落一份逐局明细，供逐局比对

⚠️ 它**只读**房间、只调纯函数（`replay.build` / `replay.finalize`），不写库、不 emit。
"""
import argparse
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import replay  # noqa: E402
from tools import headless_game as hg  # noqa: E402


def measure(seed, p1, p2, max_rounds, max_actions):
    game = hg.HeadlessGame(hg.make_policy(p1), hg.make_policy(p2), seed=seed,
                           max_rounds=max_rounds, max_actions=max_actions)
    with game:
        result = game.run()
        room = game.room
        payload = replay.finalize(room) if room is not None else None
        blob = replay.blob_bytes(payload or {})
        steps = len((payload or {}).get('steps') or [])
        row = {
            'seed': seed,
            'rounds': result.rounds,
            'steps': steps,
            'blob': blob,
            'timeline': {
                key: len((payload or {}).get(key) or [])
                for key in ('ships', 'hands', 'effects', 'attacks', 'board_resets', 'nodes')
            },
            'stalled': bool(result.stalled),
            'violations': len(result.violations),
        }
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description='回放 blob 体积尺子')
    ap.add_argument('--games', type=int, default=10)
    ap.add_argument('--seed', type=int, default=4242)
    ap.add_argument('--p1', default='master')
    ap.add_argument('--p2', default='random')
    ap.add_argument('--max-rounds', type=int, default=200)
    ap.add_argument('--max-actions', type=int, default=4000)
    ap.add_argument('--json', default=None)
    args = ap.parse_args(argv)

    rows = [measure(args.seed + i, args.p1, args.p2, args.max_rounds, args.max_actions)
            for i in range(args.games)]
    blobs = [r['blob'] for r in rows]
    print('p1=%s p2=%s seeds=%d..%d' % (args.p1, args.p2, args.seed,
                                        args.seed + args.games - 1))
    for r in rows:
        print('  seed=%d rounds=%d steps=%d blob=%d B  %s%s'
              % (r['seed'], r['rounds'], r['steps'], r['blob'],
                 json.dumps(r['timeline'], ensure_ascii=False),
                 '  STALLED' if r['stalled'] else ''))
    print('median=%d B  worst=%d B  total=%d B'
          % (int(statistics.median(blobs)), max(blobs), sum(blobs)))
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=1)
        print('已写出 %s' % args.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
