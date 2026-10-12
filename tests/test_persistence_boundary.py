import sqlite3
import ast
from pathlib import Path
from types import SimpleNamespace

import api
import db
import server
from infrastructure.persistence import REPOSITORY_OPERATIONS, repository
from infrastructure.sqlite_maintenance import (
    backup_database, integrity_check, validate_migration_copy,
)


def test_api_and_server_share_injectable_repository():
    assert server.db is repository
    assert api.db is repository
    fake = SimpleNamespace(get_user=lambda uid: {'id': uid})
    old = repository.use_backend(fake)
    try:
        assert server.db.get_user('u') == {'id': 'u'}
        assert api.db.get_user('v') == {'id': 'v'}
    finally:
        repository.use_backend(old)


def test_http_and_socket_layers_only_use_declared_repository_operations():
    root = Path(__file__).resolve().parents[1]
    for filename in ('api.py', 'server.py'):
        tree = ast.parse((root / filename).read_text(encoding='utf-8'))
        names = {node.attr for node in ast.walk(tree)
                 if isinstance(node, ast.Attribute)
                 and isinstance(node.value, ast.Name) and node.value.id == 'db'}
        assert names <= REPOSITORY_OPERATIONS, (filename, names - REPOSITORY_OPERATIONS)
    assert not hasattr(repository, 'db')
    assert not hasattr(repository, 'conn')


def test_repository_queries_preserve_public_columns_and_history(tmp_path):
    database = db.Database(db_path=tmp_path / 'queries.db')
    old = repository.use_backend(SimpleNamespace(
        recent_foes=lambda uid, limit: db.recent_foes(uid, limit),
        consecutive_losses=lambda uid, limit=50: db.consecutive_losses(uid, limit),
        public_user_cards=lambda uids: db.public_user_cards(uids),
    ))
    # 查询必须针对临时实例，不依赖模块级单例；本测试直接在实例上验证 SQL。
    try:
        with database._lock:
            database.conn.execute(
                "INSERT INTO matches(id, winner_id, loser_id, timestamp) VALUES ('m1','a','b',1)"
            )
            database.conn.execute(
                "INSERT INTO matches(id, winner_id, loser_id, timestamp) VALUES ('m2','c','a',2)"
            )
            database.conn.commit()
        # 为实例连接替换单例仅限本测试作用域，恢复在 finally。
        current = db.db
        db.db = database
        try:
            assert repository.recent_foes('a', 10) == {'b', 'c'}
            assert repository.consecutive_losses('a') == 1
            assert repository.public_user_cards(['missing']) == {}
        finally:
            db.db = current
    finally:
        repository.use_backend(old)
        database.close()


def test_wal_backup_and_migration_copy_leave_source_untouched(tmp_path):
    original = tmp_path / 'live.db'
    source = db.Database(db_path=original)
    try:
        with source._lock:
            source.conn.execute(
                "INSERT INTO matches(id, winner_id, loser_id, timestamp) VALUES ('before','a','b',1)"
            )
            source.conn.commit()
        backup = backup_database(original, tmp_path / 'backup.db')
        migrated = validate_migration_copy(original, tmp_path / 'migration-check.db')
        assert integrity_check(backup) == integrity_check(migrated) == 'ok'
        with source._lock:
            source.conn.execute(
                "INSERT INTO matches(id, winner_id, loser_id, timestamp) VALUES ('after','a','b',2)"
            )
            source.conn.commit()
        with sqlite3.connect(backup) as copied:
            ids = {row[0] for row in copied.execute('SELECT id FROM matches')}
        assert ids == {'before'}
        with sqlite3.connect(original) as live:
            assert {row[0] for row in live.execute('SELECT id FROM matches')} == {'before', 'after'}
    finally:
        source.close()
