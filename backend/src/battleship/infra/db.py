"""SQLAlchemy 2.x 引擎与健康探测。

仓储层是唯一写 SQL 的地方；这里只负责"怎么连"与"能不能连"，
启动时不建表 —— 建表由 Alembic 迁移负责（见 repositories/migrations.py）。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event, literal, select
from sqlalchemy.engine import Engine

from ..config import Settings


def _prepare_path(database_path: Path) -> None:
    if str(database_path) == ":memory:":
        return
    database_path.parent.mkdir(parents=True, exist_ok=True)


def create_engine_for_url(database_url: str) -> Engine:
    """Create the SQLite engine, keeping the old stack's WAL + busy_timeout."""
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()

    return engine


def create_engine_for(settings: Settings) -> Engine:
    """Create the SQLite engine for the configured database path."""
    _prepare_path(settings.database_path)
    return create_engine_for_url(settings.database_url)


def check_database(settings: Settings) -> tuple[bool, str]:
    """返回 (ok, detail)。供 /healthz 使用，不抛异常。"""

    engine: Engine | None = None
    try:
        engine = create_engine_for(settings)
        with engine.connect() as connection:
            connection.execute(select(literal(1)))
        return True, str(settings.database_path)
    except Exception as exc:  # 健康检查必须能报告失败，而不是把 500 抛给探针
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        if engine is not None:
            engine.dispose()
