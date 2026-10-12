"""SQLite 的一致性备份与迁移副本验证；不触碰运行中数据库的 schema。"""
from __future__ import annotations

from pathlib import Path
from contextlib import closing
import sqlite3


def integrity_check(path: str | Path) -> str:
    """只读检查现有数据库。"""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    uri = source.resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as conn:
        result = conn.execute('PRAGMA integrity_check').fetchone()[0]
    if result != 'ok':
        raise RuntimeError(f'SQLite integrity_check 失败: {result}')
    return result


def backup_database(source: str | Path, destination: str | Path) -> Path:
    """用 SQLite backup API 复制含 WAL 中已提交事务的一致快照。"""
    source, destination = Path(source), Path(destination)
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.resolve() == destination.resolve():
        raise ValueError('备份目标不能是源数据库')
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # 排除旧目标，避免在已有备份上原地覆盖。
    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
    integrity_check(destination)
    return destination


def validate_migration_copy(source: str | Path, destination: str | Path) -> Path:
    """仅在备份副本运行当前代码的建表/加列迁移。"""
    from db import Database

    copied = backup_database(source, destination)
    probe = Database(db_path=copied)
    try:
        integrity_check(copied)
    finally:
        probe.close()
    return copied
