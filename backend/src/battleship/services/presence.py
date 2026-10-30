"""The single online table (presence) for the rewrite.

There is exactly ONE presence structure in this backend. The legacy stack grew
two in parallel (a lobby sid table and a friend uid table); CLAUDE.md #17 and
DECISIONS D1 forbid repeating that. Everything reads this one table:

* online count and GET /api/online_count;
* the lobby players list (lobby_state);
* friend online status and multi-tab push (sids_of);
* whether a logged-in account is currently seated in a room.

The table is keyed by socket id but each record carries the account id, so the
uid view is derived (never stored twice). A second tab of the same account is a
second record, exactly like the legacy lobby table.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..domain.lobby.rules import clean_name


def _norm_id(value: Any) -> str | None:
    if value is None or not isinstance(value, (str, int, float)):
        return None
    text = str(value).strip()
    return text or None


@dataclass
class PresenceRecord:
    sid: str
    name: str = ""
    user_id: str | None = None
    connected_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "user_id": self.user_id,
            "connected_at": self.connected_at,
        }


class PresenceService:
    """Online records + the "seated in a room" flag, guarded by one lock."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, PresenceRecord] = {}
        self._in_game: set[str] = set()

    # ------------------------------------------------------------- connections

    def add_connection(self, sid: str, name: Any = None, user_id: Any = None) -> None:
        key = _norm_id(sid)
        if key is None:
            return
        with self._lock:
            record = self._records.get(key)
            if record is None:
                record = PresenceRecord(sid=key)
                self._records[key] = record
            if name:
                record.name = clean_name(name, fallback=record.name or "")
            if user_id is not None:
                record.user_id = _norm_id(user_id)

    def update_identity(self, sid: str, name: Any = None, user_id: Any = None) -> None:
        key = _norm_id(sid)
        if key is None:
            return
        if key not in self._records:
            self.add_connection(key, name, user_id)
            return
        with self._lock:
            record = self._records[key]
            if name:
                record.name = clean_name(name, fallback=record.name or "")
            if user_id is not None:
                record.user_id = _norm_id(user_id)

    def remove_connection(self, sid: str) -> bool:
        key = _norm_id(sid)
        if key is None:
            return False
        with self._lock:
            record = self._records.pop(key, None)
            return record is not None

    def get(self, sid: str) -> PresenceRecord | None:
        key = _norm_id(sid)
        if key is None:
            return None
        with self._lock:
            return self._records.get(key)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {sid: record.as_dict() for sid, record in self._records.items()}

    def online_count(self) -> int:
        with self._lock:
            return len(self._records)

    # ----------------------------------------------------------------- uid view

    def sids_of(self, user_id: Any) -> list[str]:
        key = _norm_id(user_id)
        if key is None:
            return []
        with self._lock:
            return [sid for sid, record in self._records.items() if record.user_id == key]

    def is_online(self, user_id: Any) -> bool:
        return bool(self.sids_of(user_id))

    def online_uids(self) -> set[str]:
        with self._lock:
            return {record.user_id for record in self._records.values() if record.user_id}

    # -------------------------------------------------------------- in a game

    def set_in_game(self, user_id: Any, on: bool) -> None:
        key = _norm_id(user_id)
        if key is None:
            return
        with self._lock:
            if on:
                self._in_game.add(key)
            else:
                self._in_game.discard(key)

    def is_in_game(self, user_id: Any) -> bool:
        key = _norm_id(user_id)
        if key is None:
            return False
        with self._lock:
            return key in self._in_game

    def clear(self) -> None:
        """Test helper; production code never calls this."""
        with self._lock:
            self._records.clear()
            self._in_game.clear()
