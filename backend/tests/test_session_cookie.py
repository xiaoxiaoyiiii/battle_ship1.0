"""登录会话 cookie 的持久化：写入必须带 31 天 Max-Age，退出必须清掉。

背景：`write_session()` 只设了 httponly / samesite / secure，没有 max_age，
于是 Set-Cookie 是「会话 cookie」。浏览器整进程不退出时看起来能记住登录，
但 Tauri/WebView2 桌面壳关窗就把它丢了 —— 桌面版每次都要重新登录。

这里只钉两件事：
  1. 登录/注册写出的 `Set-Cookie` 带 `Max-Age=2678400`（31*24*60*60）。
  2. 退出仍然能清掉同一个 cookie（Max-Age=0，而不是只清会话 cookie）。
"""
from __future__ import annotations

import os
from pathlib import Path

_BOOT = Path("/tmp/session-cookie-boot")
_BOOT.mkdir(parents=True, exist_ok=True)
(_BOOT / "dist").mkdir(exist_ok=True)
(_BOOT / "dist" / "index.html").write_text("<!doctype html><html></html>", encoding="utf-8")
os.environ["SECRET_KEY"] = "test-secret-session-cookie-v1"
os.environ["BATTLESHIP_DB_PATH"] = str(_BOOT / "boot.db")
os.environ["FRONTEND_DIST"] = str(_BOOT / "dist")
os.environ["FRONTEND_MODE"] = "spa"
os.environ["LOG_LEVEL"] = "ERROR"
os.environ["LOG_JSON"] = "false"
os.environ["DEBUG_ADMIN_USER_IDS"] = ""

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.responses import Response
from types import SimpleNamespace

import battleship

from battleship.config import Settings
from battleship.main import create_application
from battleship.repositories.migrations import migrate_database

EXPECTED_MAX_AGE = 31 * 24 * 60 * 60


def _cookie_lines(headers) -> list[str]:
    return [value for key, value in headers.items() if key.lower() == "set-cookie"]


def _session_line(headers) -> str:
    lines = [line for line in _cookie_lines(headers) if line.startswith("session=")]
    assert lines, f"没有 session 的 Set-Cookie：{_cookie_lines(headers)}"
    return lines[0]


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    # 本机并存多棵 checkout 时，可编辑安装容易把 `battleship` 指到别的树，
    # 那会让本测试对着旧代码「假绿」。这里先钉死导入来源。
    assert Path(battleship.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1]), (
        f"battleship 来自 {battleship.__file__}，不是本工作树；请用 PYTHONPATH=backend/src 运行"
    )
    root = tmp_path_factory.mktemp("session-cookie")
    database = root / "session.db"
    dist = root / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><html></html>", encoding="utf-8")
    migrate_database(database, backup=False, verify=True)
    settings = Settings(
        _env_file=None,
        secret_key=SecretStr("test-secret-session-cookie-v1"),
        database_path=database,
        frontend_dist=dist,
        daily_puzzles_path=Path("/workspace/config/daily_puzzles.json"),
        log_json=False,
        log_level="ERROR",
    )
    created = create_application(settings)
    with TestClient(created.fastapi) as test_client:
        yield test_client


def register(client: TestClient, name: str):
    response = client.post("/register", json={"username": name, "password": "secret1"})
    assert response.status_code == 200, response.text
    return response


def test_register_sets_persistent_session_cookie(client):
    response = register(client, "cookie_register")
    line = _session_line(response.headers)
    assert "Max-Age=" + str(EXPECTED_MAX_AGE) in line, line
    assert "httponly" in line.lower(), line
    assert "path=/" in line.lower(), line
    assert "samesite=lax" in line.lower().replace(" ", ""), line


def test_login_sets_persistent_session_cookie(client):
    register(client, "cookie_login")
    client.cookies.clear()
    response = client.post("/login", json={"username": "cookie_login", "password": "secret1"})
    assert response.status_code == 200, response.text
    line = _session_line(response.headers)
    assert "Max-Age=" + str(EXPECTED_MAX_AGE) in line, line


def test_logout_still_ends_the_session(client):
    """退出走的是「写一份空签名会话」，加 Max-Age 不能让它变成还能用。"""
    register(client, "cookie_logout")
    assert client.get("/api/profile").status_code == 200
    response = client.post("/logout")
    assert response.status_code in (200, 204), response.text
    assert client.get("/api/profile").status_code in (401, 403)


def test_clear_session_deletes_the_cookie():
    """`clear_session()` 是另一条清除路径，加 max_age 之后必须仍是删除语义。"""
    from starlette.requests import Request

    from battleship.http.session import clear_session, write_session

    secret = SecretStr("test-secret-session-cookie-v1")
    app = SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(secret_key=secret)))
    request = Request({
        "type": "http",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "query_string": b"",
        "headers": [],
        "server": ("testserver", 80),
        "app": app,
    })
    written = Response()
    write_session(written, request, {"user_id": "u1"})
    assert "Max-Age=" + str(EXPECTED_MAX_AGE) in written.headers["set-cookie"]

    cleared = Response()
    clear_session(cleared, request)
    line = _session_line(cleared.headers)
    assert "Max-Age=0" in line, line
