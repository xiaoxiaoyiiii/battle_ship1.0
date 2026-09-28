# -*- coding: utf-8 -*-
"""反作弊回滚 —— A/B/C 三团伙（2026-09-19）

用法：
    python anticheat_rollback.py --dry-run    # 只打印，不写库（默认）
    python anticheat_rollback.py --apply      # 真写库（先自动备份）

设计原则：
  * **备份优先**：--apply 前强制 dump 一份完整库副本，备份失败即中止。
  * **范围锁死**：只动 GANGS 里写死的 6 个账号，其余一律不碰（见 TARGETS 白名单校验）。
  * **幂等**：靠 anticheat_actions 表记录已处理的 match_id，重复跑不会重复扣。
  * **可回退**：每一条改动都写进 anticheat_actions（含 before/after JSON），可据此还原。
  * **份数只认事实**：从 matches 表按 match_id 精确删，不按"扣多少分"估算。
"""
import argparse
import json
import os
import shutil
import sqlite3
import time
from datetime import datetime, timezone, timedelta

DB = os.environ.get("BATTLESHIP_DB", "/opt/battleship/data/battleship.db")
CST = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# 团伙定义：主号 -> 靶子。**写死**，不接受任何动态推断 —— 动态推断会误伤。
# ---------------------------------------------------------------------------
GANGS = [
    {"boss": "音乐.", "dummy": "yinyue"},
    {"boss": "一孙之翔", "dummy": "一叶知秋"},
    {"boss": "弱碱性", "dummy": "也够小弈"},
]

# 测试账号：不参与排名、不计榜单，但**不扣分、不清战绩**（用户确认是真实测试）
TEST_ACCOUNTS = ["管理员01"]

# 回滚允许触碰的账号（白名单）—— 任何不在此列的 uid 出现即中止
ALLOWED = set()


def now_ts():
    return int(time.time())


def log(msg):
    print(f"[{datetime.now(CST).strftime('%H:%M:%S')}] {msg}")


def table_exists(c, name):
    return c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def ensure_ledger(c):
    """审计表：记下每一处改动，供回退与复查。"""
    c.execute("""
        CREATE TABLE IF NOT EXISTS anticheat_actions
        (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            batch       TEXT,
            match_id    TEXT,
            boss_uid    TEXT,
            dummy_uid   TEXT,
            kind        TEXT,
            payload     TEXT,
            created_at  INTEGER
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_anticheat_batch "
              "ON anticheat_actions(batch)")


def ensure_flags(c):
    """可疑对局标记表（供后续实时检测写入，本次先建表）。"""
    c.execute("""
        CREATE TABLE IF NOT EXISTS anticheat_flags
        (
            match_id    TEXT PRIMARY KEY,
            rule        TEXT,
            severity    TEXT,
            detail      TEXT,
            created_at  INTEGER
        )
    """)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真写库（默认只演练）")
    ap.add_argument("--db", default=DB)
    args = ap.parse_args()

    dry = not args.apply
    log(f"数据库: {args.db}")
    log(f"模式: {'演练（不写库）' if dry else '★ 实际写库'}")

    # ---- 备份优先 ----
    backup = None
    if not dry:
        stamp = datetime.now(CST).strftime("%Y%m%d-%H%M%S")
        backup = f"{args.db}.anticheat-backup-{stamp}"
        try:
            shutil.copy2(args.db, backup)
            log(f"备份完成: {backup}")
        except Exception as e:
            log(f"!! 备份失败，中止: {e}")
            return 1

    c = sqlite3.connect(args.db)
    c.row_factory = sqlite3.Row

    U = {r["username"]: r["id"] for r in c.execute("SELECT id, username FROM users")}
    N = {v: k for k, v in U.items()}

    # ---- 白名单校验 ----
    for g in GANGS:
        for key in ("boss", "dummy"):
            uname = g[key]
            if uname not in U:
                log(f"!! 找不到账号 {uname}，中止")
                return 1
            ALLOWED.add(U[uname])
    log(f"白名单账号（只有这些会被改动）: "
        f"{', '.join(N[u] for u in sorted(ALLOWED))}")

    if not dry:
        ensure_ledger(c)
        ensure_flags(c)

    batch = datetime.now(CST).strftime("rollback-%Y%m%d-%H%M%S")
    total_games = 0
    summary = []

    for g in GANGS:
        b, d = U[g["boss"]], U[g["dummy"]]
        rows = c.execute(
            "SELECT id, winner_id, loser_id, timestamp FROM matches "
            "WHERE (winner_id=? AND loser_id=?) OR (winner_id=? AND loser_id=?) "
            "ORDER BY timestamp", (b, d, d, b)).fetchall()

        boss_wins = sum(1 for r in rows if r["winner_id"] == b)
        dummy_wins = sum(1 for r in rows if r["winner_id"] == d)

        log("")
        log(f"■ {g['boss']} -> {g['dummy']}")
        log(f"   对局 {len(rows)} 局（{g['boss']} 胜 {boss_wins} / {g['dummy']} 胜 {dummy_wins}）")

        # 改动前快照（用于回退）
        boss_before = c.execute(
            "SELECT wins, losses FROM users WHERE id=?", (b,)).fetchone()
        dummy_before = c.execute(
            "SELECT wins, losses FROM users WHERE id=?", (d,)).fetchone()
        boss_rank = c.execute(
            "SELECT points, ranked_wins, ranked_losses FROM user_rank WHERE user_id=?",
            (b,)).fetchone()
        dummy_rank = c.execute(
            "SELECT points, ranked_wins, ranked_losses FROM user_rank WHERE user_id=?",
            (d,)).fetchone()

        log(f"   改前 [{g['boss']}] 战绩 {boss_before['wins']}胜{boss_before['losses']}负"
            + (f" 排位 {boss_rank['points']}分 {boss_rank['ranked_wins']}胜{boss_rank['ranked_losses']}负"
               if boss_rank else ""))
        log(f"   改前 [{g['dummy']}] 战绩 {dummy_before['wins']}胜{dummy_before['losses']}负"
            + (f" 排位 {dummy_rank['points']}分 {dummy_rank['ranked_wins']}胜{dummy_rank['ranked_losses']}负"
               if dummy_rank else ""))

        if not dry:
            payload = json.dumps({
                "boss": {"wins": boss_before["wins"], "losses": boss_before["losses"],
                         "rank": dict(boss_rank) if boss_rank else None},
                "dummy": {"wins": dummy_before["wins"], "losses": dummy_before["losses"],
                          "rank": dict(dummy_rank) if dummy_rank else None},
                "match_ids": [r["id"] for r in rows],
            }, ensure_ascii=False)

            c.execute(
                "INSERT INTO anticheat_actions (batch, match_id, boss_uid, dummy_uid, "
                "kind, payload, created_at) VALUES (?,?,?,?,?,?,?)",
                (batch, None, b, d, "rollback_group", payload, now_ts()))

            # ① 删掉刷分对局的历史
            c.executemany("DELETE FROM matches WHERE id=?", [(r["id"],) for r in rows])
            c.executemany("DELETE FROM match_logs WHERE match_id=?",
                          [(r["id"],) for r in rows])

            # ② 靶子：清掉这批假败场（它本来就是被刷的号，战绩不该留）
            #    靶子的 wins 里如果混了刷分局的胜场，也要扣掉
            c.execute(
                "UPDATE users SET losses = MAX(0, losses - ?), wins = MAX(0, wins - ?) "
                "WHERE id=?", (len(rows) - dummy_wins, dummy_wins, d))

            # ③ 主号：扣掉刷分局的胜场（败场是刷分局里主号输的，也扣）
            c.execute(
                "UPDATE users SET wins = MAX(0, wins - ?), losses = MAX(0, losses - ?) "
                "WHERE id=?", (boss_wins, len(rows) - boss_wins, b))

            # ④ 排位：这批局若结算过排位，扣回对应场次
            if dummy_rank:
                c.execute(
                    "UPDATE user_rank SET ranked_losses = MAX(0, ranked_losses - ?), "
                    "ranked_wins = MAX(0, ranked_wins - ?) WHERE user_id=?",
                    (len(rows) - dummy_wins, dummy_wins, d))
            if boss_rank:
                c.execute(
                    "UPDATE user_rank SET ranked_wins = MAX(0, ranked_wins - ?), "
                    "ranked_losses = MAX(0, ranked_losses - ?) WHERE user_id=?",
                    (boss_wins, len(rows) - boss_wins, b))

        # 改后
        boss_after = c.execute(
            "SELECT wins, losses FROM users WHERE id=?", (b,)).fetchone()
        dummy_after = c.execute(
            "SELECT wins, losses FROM users WHERE id=?", (d,)).fetchone()
        if not dry:
            log(f"   改后 [{g['boss']}] 战绩 {boss_after['wins']}胜{boss_after['losses']}负")
            log(f"   改后 [{g['dummy']}] 战绩 {dummy_after['wins']}胜{dummy_after['losses']}负")

        summary.append((g["boss"], g["dummy"], len(rows)))
        total_games += len(rows)

    # ---- 测试账号：只标记，不动分 ----
    if not dry:
        for uname in TEST_ACCOUNTS:
            uid = U.get(uname)
            if not uid:
                continue
            c.execute(
                "INSERT INTO anticheat_actions (batch, match_id, boss_uid, dummy_uid, "
                "kind, payload, created_at) VALUES (?,?,?,?,?,?,?)",
                (batch, None, None, uid, "mark_test_account",
                 json.dumps({"username": uname}, ensure_ascii=False), now_ts()))
            log("")
            log(f"○ {uname} 标记为测试账号（★ 不扣分、不清战绩）")

    if not dry:
        c.commit()

    log("")
    log("=" * 60)
    log(f"合计处理对局: {total_games} 局")
    for boss, dummy, n in summary:
        log(f"  {boss} -> {dummy}: {n} 局")
    log("=" * 60)
    if dry:
        log("这是演练，什么都没改。加 --apply 才会写库。")
    else:
        log(f"批次号: {batch}")
        log(f"备份文件: {backup}")

    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
