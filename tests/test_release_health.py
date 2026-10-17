"""发布门禁与健康端点不修改生产库，也不暴露内部路径。"""
import os
import builtins
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import api
from db import Database
from infrastructure.sqlite_maintenance import database_ready, validate_migration_copy
from tools.release_preflight import configuration_errors


def test_health_endpoints_use_read_only_database_probe(tmp_path, monkeypatch):
    path = tmp_path / 'health.db'
    monkeypatch.setenv('BATTLESHIP_DB_PATH', str(path))
    client = api.app.test_client()
    assert client.get('/health/live').json == {'status': 'ok'}
    response = client.get('/health/ready')
    assert response.status_code == 503
    assert response.json == {'status': 'unavailable'}
    assert not path.exists()

    database = Database(db_path=path)
    try:
        assert database_ready(path)
        response = client.get('/health/ready')
        assert response.status_code == 200
        assert response.json == {'status': 'ok'}
    finally:
        database.close()


def test_production_preflight_rejects_unsafe_configuration():
    safe = {'SECRET_KEY': 's' * 32, 'CORS_ORIGINS': 'https://game.example.com',
            'FLASK_DEBUG': '0', 'ENABLE_TEST_EVENTS': '0'}
    assert configuration_errors(safe) == []
    assert configuration_errors({})
    assert configuration_errors({**safe, 'ENABLE_TEST_EVENTS': '1'})
    assert configuration_errors({**safe, 'FLASK_DEBUG': '1'})
    assert configuration_errors({**safe, 'CORS_ORIGINS': '*'})
    assert configuration_errors({**safe, 'CORS_ORIGINS': 'https://game.example.com/path'})


def test_migration_probe_never_initializes_source_database(tmp_path, monkeypatch):
    source = tmp_path / 'source.db'
    copied = tmp_path / 'copy.db'
    sqlite3.connect(source).close()
    monkeypatch.setenv('BATTLESHIP_DB_PATH', str(source))

    # db 在整套测试中已导入；拦截这次 import，模拟模块首次导入时按环境变量建库。
    # 不在 Eventlet monkey_patch 后启动子进程，避免 Windows CI 的 subprocess 等待挂住。
    class ProbeDatabase:
        def __init__(self, db_path):
            assert Path(db_path) == copied

        def close(self):
            pass

    original_import = builtins.__import__
    observed = []

    def probe_import(name, *args, **kwargs):
        if name == 'db':
            path = Path(os.environ['BATTLESHIP_DB_PATH'])
            observed.append(path)
            with sqlite3.connect(path) as conn:
                conn.execute('CREATE TABLE import_probe (id INTEGER)')
            return SimpleNamespace(Database=ProbeDatabase)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', probe_import)
    validate_migration_copy(source, copied)
    assert observed == [copied.resolve()]
    assert os.environ['BATTLESHIP_DB_PATH'] == str(source)
    with sqlite3.connect(source) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    with sqlite3.connect(copied) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='import_probe'").fetchone()
