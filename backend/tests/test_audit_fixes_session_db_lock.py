"""P1-2：用临时库的可控写锁，看同步 valid_session 会不会拖住另一房间的计时器。"""
from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from pathlib import Path

from battleship.repositories import Database
from battleship.repositories.migrations import migrate_database
from battleship.services.auth_sessions import SESSION_ID, issue_session, valid_session


LOCK_HOLD_SECONDS = 0.4
OTHER_ROOM_TIMER_SECONDS = 0.05
# 若事件循环被同步查库堵住，另一房间计时器会接近锁持有时间才触发。
DELAY_EVIDENCE_SECONDS = 0.2


def _make_database(tmp_path: Path) -> tuple[Database, dict]:
    database_path = tmp_path / "session-lock.db"
    migrate_database(database_path, backup=False, verify=True)
    database = Database.from_path(database_path)
    password_hash = "hash-for-lock-test"
    with database.unit_of_work() as uow:
        uow.users.create(user_id="user-a", username="user-a", password_hash=password_hash)
        session_id = issue_session(uow, "user-a", password_hash)
    return database, {SESSION_ID: session_id, "user_id": "user-a"}


def _hold_exclusive_write(database_path: Path, hold_seconds: float, started: threading.Event, released: threading.Event) -> None:
    connection = sqlite3.connect(str(database_path), isolation_level=None)
    try:
        connection.execute("PRAGMA busy_timeout=0")
        connection.execute("BEGIN EXCLUSIVE")
        connection.execute("CREATE TABLE IF NOT EXISTS _audit_lock_probe(x INTEGER)")
        connection.execute("INSERT INTO _audit_lock_probe(x) VALUES (1)")
        started.set()
        time.sleep(hold_seconds)
        connection.execute("COMMIT")
    finally:
        released.set()
        connection.close()


def test_sync_session_lookup_under_write_lock_does_not_delay_other_room_timer(tmp_path):
    database, payload = _make_database(tmp_path)
    try:
        started = threading.Event()
        released = threading.Event()
        locker = threading.Thread(
            target=_hold_exclusive_write,
            args=(database.path, LOCK_HOLD_SECONDS, started, released),
            daemon=True,
        )
        locker.start()
        assert started.wait(3.0), "写锁线程没有在约定时间内拿到锁"

        timings: dict[str, float] = {}

        async def other_room_timer():
            began = time.monotonic()
            await asyncio.sleep(OTHER_ROOM_TIMER_SECONDS)
            timings["other_room_timer"] = time.monotonic() - began

        async def session_lookup():
            await asyncio.sleep(0)
            began = time.monotonic()
            timings["session_ok"] = float(valid_session(payload, database))
            timings["session_lookup"] = time.monotonic() - began

        async def run():
            await asyncio.gather(other_room_timer(), session_lookup())

        asyncio.run(run())
        locker.join(timeout=3.0)
        assert released.is_set()

        timer_elapsed = timings["other_room_timer"]
        lookup_elapsed = timings["session_lookup"]
        # 把实测写进 assertion 信息，便于红/绿日志作为证据。
        evidence = (
            f"other_room_timer={timer_elapsed:.3f}s "
            f"session_lookup={lookup_elapsed:.3f}s "
            f"lock_hold={LOCK_HOLD_SECONDS:.3f}s "
            f"session_ok={timings.get('session_ok')}"
        )
        assert timer_elapsed < DELAY_EVIDENCE_SECONDS, (
            "另一房间计时器被同步 session 查库拖住了：" + evidence
        )
        print("P1-2 timings:", evidence)
    finally:
        database.dispose()
