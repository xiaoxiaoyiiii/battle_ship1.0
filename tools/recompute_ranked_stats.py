#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按「人机对局不计入战绩」重算 users 的胜场 / 负场 / 连胜。

背景
----
2026-09-13 之前，打人机的对局同样会写进 users.wins / users.current_streak，
而排行榜是 ORDER BY wins DESC —— 打电脑必胜，于是榜单一刷就假（线上账号
z1w6qn 的「3 胜 0 负 3 连胜」全部来自人机）。修复后新对局不再计数，本脚本
把历史数据一次性对齐。

口径
----
- 只统计 matches 表中双方都不是 AI 的对局（AI 的 id 形如 ai-xxxxxx）；
- 按 timestamp 升序重放，重算 wins / losses / current_streak / longest_streak；
- 默认 dry-run，只打印差异；加 --apply 才真正写回。

用法
----
    python tools/recompute_ranked_stats.py                     # 预演
    python tools/recompute_ranked_stats.py --apply             # 写回
    python tools/recompute_ranked_stats.py --db path/to.db --apply
"""

import argparse
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(ROOT, 'data', 'battleship.db')


def _is_ai(pid):
    return isinstance(pid, str) and pid.startswith('ai-')


def recompute(conn):
    """返回 (计划变更列表, 统计信息)。plan 中每一项为 dict。"""
    conn.row_factory = sqlite3.Row
    users = conn.execute(
        'SELECT id, username, wins, losses, current_streak, longest_streak FROM users'
    ).fetchall()
    matches = conn.execute(
        'SELECT winner_id, loser_id, timestamp FROM matches ORDER BY timestamp ASC, rowid ASC'
    ).fetchall()

    wins, losses, streak, longest = {}, {}, {}, {}
    for row in matches:
        w, l = row['winner_id'], row['loser_id']
        if _is_ai(w) or _is_ai(l):
            continue  # 人机对局不计入
        if w:
            wins[w] = wins.get(w, 0) + 1
            streak[w] = streak.get(w, 0) + 1
            longest[w] = max(longest.get(w, 0), streak[w])
        if l:
            losses[l] = losses.get(l, 0) + 1
            streak[l] = 0

    plan, ai_matches = [], 0
    for row in users:
        uid = row['id']
        new = {
            'wins': wins.get(uid, 0),
            'losses': losses.get(uid, 0),
            'current_streak': streak.get(uid, 0),
            'longest_streak': longest.get(uid, 0),
        }
        old = {k: (row[k] or 0) for k in new}
        if old != new:
            plan.append({'id': uid, 'username': row['username'], 'old': old, 'new': new})

    for row in matches:
        if _is_ai(row['winner_id']) or _is_ai(row['loser_id']):
            ai_matches += 1
    return plan, {'users': len(users), 'matches': len(matches), 'ai_matches': ai_matches}


def main(argv=None):
    ap = argparse.ArgumentParser(description='按人机不计入的口径重算用户战绩')
    ap.add_argument('--db', default=DEFAULT_DB, help='sqlite 数据库路径（默认 data/battleship.db）')
    ap.add_argument('--apply', action='store_true', help='真正写回（默认只预演）')
    args = ap.parse_args(argv)

    if not os.path.exists(args.db):
        print('找不到数据库: %s' % args.db)
        return 2

    conn = sqlite3.connect(args.db)
    try:
        plan, info = recompute(conn)
        print('数据库: %s' % args.db)
        print('用户 %d 个，对局 %d 场，其中人机 %d 场（不计入）' % (info['users'], info['matches'], info['ai_matches']))
        if not plan:
            print('无需变更：现有战绩已符合口径。')
            return 0
        print('需要修正 %d 个用户：' % len(plan))
        for item in plan:
            print('  %-20s 胜场 %d -> %d，负场 %d -> %d，当前连胜 %d -> %d，最长连胜 %d -> %d' % (
                item['username'],
                item['old']['wins'], item['new']['wins'],
                item['old']['losses'], item['new']['losses'],
                item['old']['current_streak'], item['new']['current_streak'],
                item['old']['longest_streak'], item['new']['longest_streak'],
            ))
        if not args.apply:
            print('预演结束（未写库）。确认无误后加 --apply 执行。')
            return 0
        for item in plan:
            conn.execute(
                'UPDATE users SET wins = ?, losses = ?, current_streak = ?, longest_streak = ? WHERE id = ?',
                (item['new']['wins'], item['new']['losses'], item['new']['current_streak'],
                 item['new']['longest_streak'], item['id']),
            )
        conn.commit()
        print('已写回 %d 个用户。' % len(plan))
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
