"""发布门禁与健康端点不修改生产库，也不暴露内部路径。"""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import api
from db import Database
from infrastructure.sqlite_maintenance import database_ready
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


def test_migration_probe_never_initializes_source_database(tmp_path):
    source = tmp_path / 'source.db'
    copied = tmp_path / 'copy.db'
    sqlite3.connect(source).close()
    script = ('from infrastructure.sqlite_maintenance import validate_migration_copy; '
              'import sys; validate_migration_copy(sys.argv[1], sys.argv[2])')
    env = {**os.environ, 'BATTLESHIP_DB_PATH': str(source),
           'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
    result = subprocess.run([sys.executable, '-c', script, str(source), str(copied)],
                            env=env, cwd=str(tmp_path), text=True, capture_output=True,
                            timeout=30)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(source) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    assert database_ready(copied)
