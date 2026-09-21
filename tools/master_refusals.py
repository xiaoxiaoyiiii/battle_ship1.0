# -*- coding: utf-8 -*-
"""统计**大师座位**出牌被拒的卡与原因 —— 逐条补进 `_master_card_readiness` 的清单。

被拒动作本身不致命（牌会退回手牌、预算也不扣），但每一次都意味着：
试算漏判了一条前置 → 长此以往"开放一张新卡就换回一批新漏判"。
所以这批数字要压到 0，并且每条原因都要在闸门里找到对应判据。
"""
import collections
import contextlib
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'tools'))

import tools.headless_game as hg          # noqa: E402

GAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 1000

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    results = hg.run_many(lambda: hg.make_policy('master'),
                          lambda: hg.make_policy('hard'),
                          games=GAMES, seed=1)

counter = collections.Counter()
for r in results:
    for v in r.violations:
        if r.p1 not in v or '出牌被拒' not in v:
            continue
        m = re.search(r"message': '([^']*)'", v)
        parts = v.split('出牌被拒：')[1].split(' ')
        card = parts[1] if len(parts) > 1 else '?'
        counter[(card, m.group(1) if m else '?')] += 1

print('大师座位出牌被拒（%d 局，共 %d 次）：' % (GAMES, sum(counter.values())))
for (card, why), n in counter.most_common(30):
    print('%5d  %-8s %s' % (n, card, why))
