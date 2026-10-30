#!/usr/bin/env python
"""Operator wrapper around `battleship.repositories.migrations`.

It exists so systemd (ExecStartPre) and the deploy runbook have one stable entry
point instead of a PYTHONPATH-sensitive `-m` invocation:

    ops/migrate.py --database /var/lib/battleship/battleship.db

Guarantees (owned by the repository layer): SQLite online backup before any DDL,
Alembic upgrade to head, schema/row-count verification, automatic restore on
failure. `--dry-run` prints the plan without writing.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))


def _revision(database: Path) -> str | None:
    from battleship.repositories.migrations import read_revision

    return read_revision(database)


def _backup_note(database: Path) -> str:
    if database.exists() and database.stat().st_size > 0:
        return f"before upgrade: {database}.backup-<UTC stamp>.db"
    return "database does not exist yet (a fresh schema is created; no backup)"


def _integrity(path: Path) -> str:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    from battleship.repositories.migrations import HEAD_REVISION

    parser = argparse.ArgumentParser(prog="ops/migrate.py", description=__doc__)
    parser.add_argument("--database", default=os.environ.get("BATTLESHIP_DB_PATH"),
                        help="SQLite path (default: BATTLESHIP_DB_PATH)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)

    if not args.database:
        print("缺少 --database 或 BATTLESHIP_DB_PATH（fail-fast）", file=sys.stderr)
        return 2
    database = Path(args.database).resolve()

    if args.dry_run:
        print(f"database: {database}")
        print(f"revision: {_revision(database)} -> {HEAD_REVISION}")
        print(f"backup: {_backup_note(database)}")
        print("verify: schema + row counts after upgrade")
        print("dry-run: nothing was written")
        return 0

    from battleship.repositories.migrations import MigrationError, migrate_database

    try:
        if args.verify_only:
            from battleship.repositories.migrations import verify_database

            problems = verify_database(database)
            print(f"database: {database}")
            print("verification: " + ("ok" if not problems else "FAILED"))
            for problem in problems:
                print(f"  - {problem}")
            return 0 if not problems else 1

        result = migrate_database(database, backup=not args.no_backup)
    except MigrationError as exc:
        print(f"migration FAILED: {exc}", file=sys.stderr)
        if exc.backup_path:
            print(f"backup: {exc.backup_path}", file=sys.stderr)
        print(f"restored: {exc.restored}", file=sys.stderr)
        return 2

    print(f"database: {result.database_path} (integrity {_integrity(result.database_path)})")
    print(f"revision: {result.from_revision} -> {result.to_revision}")
    print(f"backup: {result.backup_path or '(none)'}")
    print(f"tables: {len(result.row_counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
