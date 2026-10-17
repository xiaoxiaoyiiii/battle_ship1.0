"""旧 GameRoom/RoomManager 到房间领域模型的只读适配。"""
from __future__ import annotations

from typing import Any

from domain.rooms import DisconnectLease, MatchEntry, MatchQueue, RoomLifecycle


def build_match_queue(manager: Any) -> MatchQueue:
    entries = tuple(MatchEntry(
        sid=str(entry.get("sid", "")), name=str(entry.get("name", "")),
        user_id=entry.get("user_id"), mode=entry.get("mode", "casual"),
        ip=entry.get("ip", ""), enqueued_at=float(entry.get("enqueued_at", 0.0)),
    ) for entry in (getattr(manager, "match_queue", None) or []))
    return MatchQueue(entries)


def build_room_lifecycle(room: Any) -> RoomLifecycle:
    return RoomLifecycle(
        state=str(getattr(room, "state", "")),
        is_ai_room=bool(getattr(room, "is_ai_room", False)),
        players=tuple(getattr(room, "players", {}).keys()),
        disconnected=tuple((getattr(room, "disconnected", {}) or {}).keys()),
    )


def build_disconnect_lease(room: Any, player_id: str) -> DisconnectLease | None:
    entry = (getattr(room, "disconnected", {}) or {}).get(player_id)
    if not entry:
        return None
    return DisconnectLease(player_id, int(entry.get("token", 0)), float(entry.get("deadline", 0.0)))
