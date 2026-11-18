"""0015_card_skins 迁移：upgrade -> downgrade -> upgrade，并核对 schema。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from battleship.repositories.migrations import (
    HEAD_REVISION,
    build_alembic_config,
    read_revision,
    verify_database,
)

NEW_TABLES = (
    "card_skins_owned",
    "card_skin_shard_wallets",
    "card_skin_shard_ledger",
    "card_skin_selections",
    "gacha_requests",
)


def _tables(path: Path) -> set[str]:
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {name for (name,) in rows}
    finally:
        connection.close()


def test_head_revision_is_0015():
    # 随着 0016_commanders 合入，HEAD_REVISION 由 0015_card_skins 推进为 0016_commanders。
    assert HEAD_REVISION == "0016_commanders"


def test_upgrade_downgrade_upgrade(tmp_path):
    database = tmp_path / "migrate-0015.db"
    config = build_alembic_config(database)
    command.upgrade(config, "0014_collection")
    assert read_revision(database) == "0014_collection"
    before = _tables(database)
    for name in NEW_TABLES:
        assert name not in before

    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO tide_ash_wallets(user_id, balance, updated_at) VALUES ('keeper', 88, 1)"
    )
    connection.commit()
    connection.close()

    command.upgrade(config, "0015_card_skins")
    assert read_revision(database) == "0015_card_skins"
    after_upgrade = _tables(database)
    for name in NEW_TABLES:
        assert name in after_upgrade

    connection = sqlite3.connect(database)
    connection.execute(
        "INSERT INTO card_skins_owned(user_id, skin_id, source, source_id, granted_at) "
        "VALUES ('keeper', 'neon-kanpo', 'gacha', 'req-1', 1)"
    )
    connection.execute(
        "INSERT INTO card_skin_shard_wallets(user_id, balance, updated_at) VALUES ('keeper', 5, 1)"
    )
    connection.commit()
    connection.close()

    command.downgrade(config, "0014_collection")
    assert read_revision(database) == "0014_collection"
    after_down = _tables(database)
    for name in NEW_TABLES:
        assert name not in after_down
    connection = sqlite3.connect(database)
    balance = connection.execute(
        "SELECT balance FROM tide_ash_wallets WHERE user_id='keeper'"
    ).fetchone()
    connection.close()
    assert balance == (88,)

    command.upgrade(config, "head")
    assert read_revision(database) == HEAD_REVISION
    assert verify_database(database) == []
    connection = sqlite3.connect(database)
    owned = connection.execute("SELECT COUNT(*) FROM card_skins_owned").fetchone()[0]
    shards = connection.execute("SELECT COUNT(*) FROM card_skin_shard_wallets").fetchone()[0]
    ledger = connection.execute("SELECT COUNT(*) FROM card_skin_shard_ledger").fetchone()[0]
    selections = connection.execute("SELECT COUNT(*) FROM card_skin_selections").fetchone()[0]
    requests = connection.execute("SELECT COUNT(*) FROM gacha_requests").fetchone()[0]
    wallet = connection.execute(
        "SELECT balance FROM tide_ash_wallets WHERE user_id='keeper'"
    ).fetchone()
    connection.close()
    assert (owned, shards, ledger, selections, requests) == (0, 0, 0, 0, 0)
    assert wallet == (88,)
