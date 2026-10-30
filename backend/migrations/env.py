"""Alembic environment for the new backend.

The database URL comes from (in order): the programmatic runner
(`config.attributes["database_url"]`), the environment, or alembic.ini.
DDL lives in the revision files; models are only used for autogenerate support.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SRC = BACKEND_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from battleship.repositories.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None and Path(config.config_file_name).exists():
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    url = config.attributes.get("database_url")
    if url:
        return str(url)
    url = os.environ.get("BATTLESHIP_DB_URL")
    if url:
        return url
    path = os.environ.get("BATTLESHIP_DB_PATH")
    if path:
        return f"sqlite:///{Path(path).as_posix()}"
    return config.get_main_option("sqlalchemy.url") or "sqlite:///./battleship.db"


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_database_url(), poolclass=pool.NullPool, future=True)
    try:
        with connectable.connect() as connection:
            # WAL is part of the database contract (old stack enabled it on every
            # connection). Journal mode is persistent, so setting it once here means
            # a database that only ever ran migrations still ends up in WAL mode.
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.exec_driver_sql("PRAGMA busy_timeout=5000")
            # PRAGMA statements autobegin a transaction in SQLAlchemy 2.x. Leave
            # Alembic as the only transaction owner, otherwise its version-row
            # INSERT is never committed (it would be rolled back on close).
            connection.commit()
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
