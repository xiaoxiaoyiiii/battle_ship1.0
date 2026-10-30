#!/usr/bin/env python
"""Five-minute rollback: stop -> restore DB -> switch release/commit -> health.

The deploy runbook keeps the previous release around. A rollback is:

    python ops/rollback.py --database /var/lib/battleship/battleship.db \
        --backup /var/lib/battleship/battleship.db.backup-20261020T....db \
        --to <previous commit or tag>

    # or, when the previous release is a directory kept next to the checkout:
    python ops/rollback.py --database ... --backup ... --release-dir /opt/battleship/releases/20261019

Order of operations (also printed by `--dry-run`):

1. validate the database backup (exists + PRAGMA integrity_check == ok) and the
   target commit/release; anything missing exits 2 before the service is touched;
2. stop the service;
3. keep a safety copy of the *current* database next to it;
4. restore the selected backup;
5. switch the checkout to the previous commit (git checkout --detach) or repoint
   the current release symlink;
6. rebuild the frontend for that release unless --no-build;
7. start the service and poll the health endpoint; failure exits 3 with the
   exact commands to go back (safety backup + previous commit are printed);
8. warn when the whole rollback exceeded the 5-minute budget.

`--dry-run` performs every validation and prints the plan; it never stops a
service, restores a database, checks out code or runs a build.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))
ROLLBACK_BUDGET_SECONDS = 300


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _integrity(path: Path) -> str:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()


def _run(command: str, *, dry_run: bool) -> int:
    print(("would run: " if dry_run else "run: ") + command)
    if dry_run:
        return 0
    result = subprocess.run(command, shell=True)
    return result.returncode


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )


def _validate_commit(target: str) -> str:
    result = _git("rev-parse", "--verify", target + "^{commit}")
    if result.returncode != 0:
        raise SystemExit(f"目标 commit/tag 不存在: {target}\n{result.stderr.strip()}")
    return result.stdout.strip()


def _current_commit() -> str:
    return _git("rev-parse", "HEAD").stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ops/rollback.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database", default=os.environ.get("BATTLESHIP_DB_PATH"),
                        help="SQLite path (default: BATTLESHIP_DB_PATH)")
    parser.add_argument("--backup", required=True, help="database backup to restore")
    parser.add_argument("--to", default=None, help="previous commit or tag")
    parser.add_argument("--release-dir", default=None,
                        help="previous release directory (alternative to --to)")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--stop-command", default="systemctl stop battleship")
    parser.add_argument("--start-command", default="systemctl restart battleship")
    parser.add_argument("--health-url", default="http://127.0.0.1:5000/health")
    parser.add_argument("--health-timeout", type=float, default=120.0)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if not args.database:
        print("缺少 --database 或 BATTLESHIP_DB_PATH", file=sys.stderr)
        return 2
    database = Path(args.database).resolve()
    backup = Path(args.backup).resolve()
    root = Path(args.root).resolve()

    # 1. fail before touching the service: backup and target must both be good.
    if not backup.is_file():
        print(f"回滚中止: 数据库备份 (backup) 不存在 {backup}", file=sys.stderr)
        return 2
    try:
        integrity = _integrity(backup)
    except Exception as error:  # noqa: BLE001 - reported
        print(f"回滚中止: 备份无法打开: {error}", file=sys.stderr)
        return 2
    if integrity != "ok":
        print(f"回滚中止: 备份完整性校验失败 ({integrity})", file=sys.stderr)
        return 2

    previous_commit = _current_commit() if (root / ".git").exists() else ""
    target_commit = ""
    if args.release_dir:
        release = Path(args.release_dir).resolve()
        if not (release / "backend" / "src" / "battleship").is_dir():
            print(f"回滚中止: release 目录里没有 backend/src/battleship: {release}",
                  file=sys.stderr)
            return 2
    elif args.to:
        target_commit = _validate_commit(args.to)
    else:
        print("回滚中止: 需要 --to <commit|tag> 或 --release-dir <dir>", file=sys.stderr)
        return 2

    started = time.monotonic()
    print(f"[rollback] database: {database}")
    print(f"[rollback] backup:   {backup} (integrity ok)")
    if args.release_dir:
        print(f"[rollback] release:  {args.release_dir}")
    else:
        print(f"[rollback] commit:   {previous_commit} -> {target_commit}")

    # 2. stop, 3. safety copy, 4. restore.
    _run(args.stop_command, dry_run=args.dry_run)
    safety = database.with_name(f"{database.name}.pre-rollback-{_stamp()}.db")
    print(("would copy: " if args.dry_run else "copy: ") + f"{database} -> {safety}")
    if args.dry_run:
        print(f"would restore: {backup} -> {database}")
    else:
        from battleship.repositories.migrations import backup_database, restore_database

        if database.exists() and database.stat().st_size > 0:
            made = backup_database(database)
            if made is not None:
                safety = made
        print(f"[rollback] safety copy: {safety}")
        print(f"[rollback] restore: {backup} -> {database}")
        restore_database(database, backup)

    # 5. switch the release.
    if args.release_dir:
        current = root / "current"
        print(f"would switch: {current} -> {args.release_dir}")
        if not args.dry_run:
            temporary = root / "current.switching"
            try:
                if temporary.exists() or temporary.is_symlink():
                    temporary.unlink()
                os.symlink(Path(args.release_dir).resolve(), temporary)
                os.replace(temporary, current)
            except OSError as error:
                print(f"回滚中止: 无法切换 current 软链: {error}", file=sys.stderr)
                return 2
    else:
        if args.dry_run:
            print(f"would run: git -C {root} checkout --detach {target_commit}")
        else:
            result = _git("checkout", "--detach", target_commit)
            print(f"run: git -C {root} checkout --detach {target_commit}")
            if result.returncode != 0:
                print(f"回滚中止: git checkout 失败: {result.stderr}", file=sys.stderr)
                return 2

    # 6. rebuild the frontend for the selected release.
    build_command = f"{sys.executable} {root / 'ops' / 'build.py'} --frontend-only"
    if args.release_dir:
        print("build: skipped for --release-dir (the directory carries its own dist/)")
    elif args.no_build:
        print("build: skipped (--no-build); the previous dist/ is reused")
    elif not (root / "ops" / "build.py").is_file():
        print(f"回滚中止: {root / 'ops' / 'build.py'} 不存在；该版本没有新栈构建脚本。"
              "跨 Phase 5 回滚请保留 release 目录并用 --release-dir。", file=sys.stderr)
        return 2
    else:
        code = _run(build_command, dry_run=args.dry_run)
        if code != 0:
            print("回滚中止: 前端构建失败", file=sys.stderr)
            return 2

    # 7. start + health.
    _run(args.start_command, dry_run=args.dry_run)
    healthy = False
    if not args.dry_run:
        import urllib.request

        deadline = time.monotonic() + args.health_timeout
        last = "not checked"
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(args.health_url, timeout=3) as response:
                    last = f"HTTP {response.status}"
                    healthy = response.status == 200
                    if healthy:
                        break
            except Exception as error:  # noqa: BLE001 - retry loop
                last = f"{type(error).__name__}: {error}"
            time.sleep(0.5)
    else:
        print(f"would poll: {args.health_url} until status ok")
        healthy = True

    elapsed = time.monotonic() - started
    if not healthy:
        print(f"回滚后健康检查失败 ({last})。手动恢复：", file=sys.stderr)
        print(f"  cp {safety} {database}", file=sys.stderr)
        if previous_commit:
            print(f"  git -C {root} checkout --detach {previous_commit}", file=sys.stderr)
        print(f"  {args.start_command}", file=sys.stderr)
        return 3

    print(f"[rollback] healthy in {elapsed:.1f}s")
    if elapsed > ROLLBACK_BUDGET_SECONDS:
        print(f"[rollback] WARNING: 超过 {ROLLBACK_BUDGET_SECONDS}s 预算，请记录原因",
              file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())