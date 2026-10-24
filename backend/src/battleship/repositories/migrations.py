"""Migration runner: backup -> Alembic upgrade -> verify, with rollback on failure.

The old stack had no schema version and mutated live databases in `init_db()`.
This module is the replacement operational contract:

* the target database file is copied with SQLite's online backup API **before**
  any DDL (WAL-safe, read-only source connection);
* `alembic upgrade head` runs the frozen revisions (the first one is idempotent on
  a legacy database that has no `alembic_version`);
* row counts, a per-table data fingerprint and the full schema are verified;
* any failure restores the backup atomically (database + `-wal`/`-shm`) and raises
  :class:`MigrationError`; a failed first-time migration removes the half-built file.

Run it with::

    python -m battleship.repositories.migrations --database path/to/battleship.db

Raw SQL stays in this module (the repositories layer); business code never builds SQL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from .models import Base
from .schema import verify_schema

HEAD_REVISION = "0002_task_progress"
BACKEND_ROOT = Path(__file__).resolve().parents[3]
INTERNAL_TABLES = frozenset({"sqlite_sequence", "alembic_version"})

#: Tables whose full contents are fingerprinted before/after. The two blob tables
#: (match_logs, match_replays) are checked by row count only: hashing MBs of JSON on
#: every production migration would be wasteful.
CORE_TABLES: tuple[str, ...] = tuple(
    name for name in Base.metadata.tables if name not in {"match_logs", "match_replays"}
)


class MigrationError(RuntimeError):
    """A migration failed and the database was (or could not be) restored."""

    def __init__(
        self,
        message: str,
        *,
        backup_path: Path | None = None,
        restored: bool = False,
        original: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.backup_path = backup_path
        self.restored = restored
        self.original = original


@dataclass(frozen=True)
class MigrationResult:
    database_path: Path
    from_revision: str | None
    to_revision: str
    backup_path: Path | None
    verified: bool
    row_counts: Mapping[str, int] = field(default_factory=dict)


def sqlite_url(database_path: str | Path) -> str:
    return f"sqlite:///{Path(database_path).as_posix()}"


def build_alembic_config(database_path: str | Path) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.attributes["database_url"] = sqlite_url(database_path)
    return config


def _connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def read_revision(database_path: str | Path) -> str | None:
    path = Path(database_path)
    if not path.exists():
        return None
    connection = sqlite3.connect(path)
    try:
        has_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone()
        if not has_table:
            return None
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        return str(row[0]) if row else None
    finally:
        connection.close()


def table_row_counts(database_path: str | Path) -> dict[str, int]:
    path = Path(database_path)
    if not path.exists() or path.stat().st_size == 0:
        return {}
    connection = _connect_readonly(path)
    try:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        counts: dict[str, int] = {}
        for name in names:
            if name in INTERNAL_TABLES:
                continue
            counts[name] = connection.execute(
                f'SELECT COUNT(*) FROM "{name}"'
            ).fetchone()[0]
        return counts
    finally:
        connection.close()


def _table_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()]


def _fingerprint(database_path: Path, table: str, columns: list[str]) -> str:
    connection = _connect_readonly(database_path)
    try:
        quoted = ", ".join(f'"{column}"' for column in columns)
        rows = connection.execute(
            f'SELECT {quoted} FROM "{table}" ORDER BY rowid'
        ).fetchall()
    finally:
        connection.close()
    payload = json.dumps([list(row) for row in rows], ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def core_fingerprints(database_path: str | Path) -> dict[str, dict[str, Any]]:
    """Fingerprint the pre-migration columns of every small/core table."""
    path = Path(database_path)
    if not path.exists() or path.stat().st_size == 0:
        return {}
    connection = _connect_readonly(path)
    try:
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        fingerprints: dict[str, dict[str, Any]] = {}
        for table in CORE_TABLES:
            if table not in existing:
                continue
            columns = _table_columns(connection, table)
            if not columns:
                continue
            fingerprints[table] = {
                "columns": columns,
                "sha256": _fingerprint(path, table, columns),
            }
        return fingerprints
    finally:
        connection.close()


def backup_database(database_path: str | Path) -> Path | None:
    """Copy the database with SQLite's backup API (WAL-safe). None if empty/missing."""
    path = Path(database_path)
    if not path.exists() or path.stat().st_size == 0:
        return None
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    unique = time.time_ns() % 1_000_000_000
    backup = path.with_name(f"{path.name}.backup-{stamp}-{os.getpid()}-{unique}.db")
    source = _connect_readonly(path)
    target = sqlite3.connect(backup)
    try:
        source.backup(target)
        check = target.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise MigrationError(f"备份文件完整性校验失败: {check}")
    finally:
        target.close()
        source.close()
    return backup


def restore_database(database_path: str | Path, backup_path: str | Path) -> None:
    path = Path(database_path)
    backup = Path(backup_path)
    for suffix in ("-wal", "-shm"):
        stale = Path(str(path) + suffix)
        if stale.exists():
            stale.unlink()
    temporary = path.with_name(path.name + ".restoring")
    shutil.copy2(backup, temporary)
    os.replace(temporary, path)


def _remove_database_files(path: Path) -> None:
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        if candidate.exists():
            candidate.unlink()


def ensure_wal(database_path: str | Path) -> None:
    connection = sqlite3.connect(Path(database_path))
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.commit()
    finally:
        connection.close()


def verify_database(
    database_path: str | Path,
    *,
    expected_row_counts: Mapping[str, int] | None = None,
    expected_fingerprints: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[str]:
    """Return a list of verification problems; empty means success."""
    path = Path(database_path)
    if not path.exists():
        return ["database file does not exist"]
    problems: list[str] = []

    connection = sqlite3.connect(path)
    try:
        check = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    if check != "ok":
        problems.append(f"integrity_check: {check}")

    engine = sa.create_engine(sqlite_url(path), future=True)
    try:
        with engine.connect() as sql_connection:
            problems.extend(verify_schema(sql_connection))
    finally:
        engine.dispose()

    if expected_row_counts is not None:
        current = table_row_counts(path)
        for table, expected in expected_row_counts.items():
            actual = current.get(table)
            if actual != expected:
                problems.append(f"row count changed: {table} {expected} -> {actual}")

    if expected_fingerprints is not None:
        for table, expected in expected_fingerprints.items():
            columns = list(expected["columns"])
            if table not in table_row_counts(path):
                problems.append(f"table disappeared: {table}")
                continue
            actual = _fingerprint(path, table, columns)
            if actual != expected["sha256"]:
                problems.append(f"data changed: {table}")

    return problems


def migrate_database(
    database_path: str | Path,
    *,
    backup: bool = True,
    verify: bool = True,
) -> MigrationResult:
    """Upgrade to head with a pre-migration backup and fail-closed verification."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    existed_before = path.exists() and path.stat().st_size > 0
    from_revision = read_revision(path)
    before_counts = table_row_counts(path) if existed_before else {}
    before_fingerprints = core_fingerprints(path) if existed_before else {}
    backup_path = backup_database(path) if backup and existed_before else None

    try:
        command.upgrade(build_alembic_config(path), "head")
        ensure_wal(path)
        if verify:
            problems = verify_database(
                path,
                expected_row_counts=before_counts,
                expected_fingerprints=before_fingerprints,
            )
            if problems:
                raise MigrationError(
                    "迁移后校验失败: " + "; ".join(problems),
                    backup_path=backup_path,
                )
    except BaseException as exc:
        restored = False
        if backup_path is not None:
            restore_database(path, backup_path)
            restored = True
        elif not existed_before:
            _remove_database_files(path)
        if isinstance(exc, MigrationError):
            exc.backup_path = backup_path or exc.backup_path
            exc.restored = restored
            raise
        raise MigrationError(
            f"迁移失败: {type(exc).__name__}: {exc}",
            backup_path=backup_path,
            restored=restored,
            original=exc,
        ) from exc

    to_revision = read_revision(path) or HEAD_REVISION
    return MigrationResult(
        database_path=path,
        from_revision=from_revision,
        to_revision=to_revision,
        backup_path=backup_path,
        verified=bool(verify),
        row_counts=table_row_counts(path),
    )


def _default_database_path() -> Path:
    override = os.environ.get("BATTLESHIP_DB_PATH")
    return Path(override) if override else Path("./battleship.db")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate the battleship database.")
    parser.add_argument("--database", type=Path, default=None, help="SQLite database path")
    parser.add_argument("--no-backup", action="store_true", help="skip the pre-migration backup")
    parser.add_argument(
        "--verify-only", action="store_true", help="verify schema/row counts, do not migrate"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    arguments = parser.parse_args(argv)
    database = arguments.database or _default_database_path()

    try:
        if arguments.verify_only:
            problems = verify_database(database)
            if arguments.json:
                print(json.dumps({"database": str(database), "problems": problems}, ensure_ascii=False))
            else:
                print(f"database: {database}")
                print("verification: " + ("ok" if not problems else "FAILED"))
                for problem in problems:
                    print(f"  - {problem}")
            return 0 if not problems else 1

        result = migrate_database(
            database,
            backup=not arguments.no_backup,
        )
    except MigrationError as exc:
        payload = {
            "database": str(database),
            "error": str(exc),
            "backup": str(exc.backup_path) if exc.backup_path else None,
            "restored": exc.restored,
        }
        if arguments.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(f"migration FAILED: {exc}", file=sys.stderr)
            if exc.backup_path:
                print(f"backup: {exc.backup_path}", file=sys.stderr)
            print(f"restored: {exc.restored}", file=sys.stderr)
        return 1

    payload = {
        "database": str(result.database_path),
        "from_revision": result.from_revision,
        "to_revision": result.to_revision,
        "backup": str(result.backup_path) if result.backup_path else None,
        "row_counts": dict(result.row_counts),
    }
    if arguments.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"database: {result.database_path}")
        print(f"revision: {result.from_revision} -> {result.to_revision}")
        print(f"backup: {result.backup_path or '(none)'}")
        print(f"tables: {len(result.row_counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
