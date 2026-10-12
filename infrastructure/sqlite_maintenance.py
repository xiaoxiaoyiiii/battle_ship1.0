"""SQLite 的一致性备份与迁移副本验证；不触碰运行中数据库的 schema。"""
from __future__ import annotations

from pathlib import Path
from contextlib import closing
import sqlite3
import os


def configured_database_path() -> Path:
    """返回当前部署使用的 SQLite 路径，不打开或修改数据库。"""
    return Path(os.environ.get('BATTLESHIP_DB_PATH') or
                Path(__file__).resolve().parents[1] / 'data' / 'battleship.db')


def database_ready(path: str | Path) -> bool:
    """只读探测关键表；绝不让健康检查触发建库或迁移。"""
    source = Path(path)
    if not source.is_file():
        return False
    try:
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro',
                                     uri=True, timeout=2)) as conn:
            return conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
            ).fetchone() is not None
    except sqlite3.Error:
        return False


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
    copied = backup_database(source, destination)
    # db 模块首次导入会实例化默认连接。临时将默认路径指向副本，
    # 防止这个隐式初始化抢在显式 Database(db_path=...) 之前修改源库。
    previous = os.environ.get('BATTLESHIP_DB_PATH')
    try:
        os.environ['BATTLESHIP_DB_PATH'] = str(copied.resolve())
        from db import Database
        probe = Database(db_path=copied)
        try:
            integrity_check(copied)
        finally:
            probe.close()
    finally:
        if previous is None:
            os.environ.pop('BATTLESHIP_DB_PATH', None)
        else:
            os.environ['BATTLESHIP_DB_PATH'] = previous
    return copied
