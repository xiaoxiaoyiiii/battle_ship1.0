"""In-game chat: free text (ticket #31) and quick phrases (ticket #14).

Free text is the legacy chat_message handler plus the guardrails this ticket
adds: an explicit length ceiling, the shared rate rule and a readable refusal
for every rejected line. The frame that goes out to the room keeps the frozen
legacy shape {username, message} (no isMe: the two recipients would disagree).

Free text never enters the game log or the replay; that matches the legacy
handler (only quick_chat wrote a log line). A bounded per-room history is kept
so a reconnecting seat receives the lines it missed while its socket was down,
without replaying lines it already received (the per-seat delivery watermark).

Quick phrases are unchanged: identity, whitelist, the shared 10s/3 rule, one
broadcast and one game_log line.
"""

from __future__ import annotations

import time
from typing import Any

from ..contracts import errors as socket_errors
from ..domain.social import quick_chat
from ..infra.logging import get_logger
from .rooms import Connection, EventPublisher, NullPublisher, RoomService

logger = get_logger("chat")

#: Legacy MAX_CHAT_MSG_LEN (server.py:1152). Exactly this many code points is
#: accepted; one more is refused with a readable reason (the legacy handler
#: truncated silently, which the ticket explicitly replaces with a refusal).
MAX_CHAT_MSG_LEN = 100

#: Bounded history for reconnect replay. The legacy chat was ephemeral, so this
#: is deliberately small: it only needs to cover a disconnect grace window.
CHAT_HISTORY_LIMIT = 50

CHAT_EMPTY = "说点什么再发送吧"
CHAT_TOO_LONG = "消息太长了，最多 %d 个字" % MAX_CHAT_MSG_LEN
CHAT_NOT_SEATED = "你不在这个房间里，无法发言"


def _display_name(connection: Connection, fallback_key: str) -> str:
    """Legacy name rule: account name wins, guests get 玩家<key prefix>."""

    name = str(connection.username or "").strip()
    if name:
        return name
    return f"玩家{str(fallback_key)[:6]}"


class ChatService:
    def __init__(self, rooms: RoomService, publisher: EventPublisher | None = None) -> None:
        self._rooms = rooms
        self._publisher: EventPublisher = publisher or NullPublisher()

    def bind(self, publisher: EventPublisher) -> None:
        self._publisher = publisher

    async def _fail(self, connection: Connection, message: str) -> dict[str, Any]:
        """Explain the refusal to the sender only, then return the error ack."""

        try:
            await self._publisher.emit(
                "error",
                socket_errors.error_detail(socket_errors.OPERATION_FAILED, message),
                to=connection.sid,
            )
        except Exception:  # noqa: BLE001 - the ack is the authoritative result
            logger.exception("chat error frame failed")
        return {"status": "error", "message": message}

    # ------------------------------------------------------------ free text

    async def chat_message(self, connection: Connection,
                           data: dict[str, Any] | None = None) -> dict[str, Any]:
        data = data if isinstance(data, dict) else {}
        raw = data.get("message")
        message = raw.strip() if isinstance(raw, str) else ""
        if not message:
            return await self._fail(connection, CHAT_EMPTY)
        if len(message) > MAX_CHAT_MSG_LEN:
            return await self._fail(connection, CHAT_TOO_LONG)

        room = self._rooms.get_room(data.get("room_id"))
        if room is None:
            # Legacy fallback (no room / unknown room id): echo to the sender
            # only, with isMe because the payload has exactly one recipient.
            await self._publisher.emit(
                "chat_message",
                {
                    "username": _display_name(connection, connection.sid),
                    "message": message,
                    "isMe": True,
                },
                to=connection.sid,
            )
            return {"status": "success"}

        # Identity is the seat whose registered socket is this connection. The
        # client never supplies a player_id here, so there is nothing to spoof;
        # identity_ok additionally checks the session owner.
        seat_key = next(
            (
                player_id
                for player_id, player in room.players.items()
                if getattr(player, "socket_id", None) == connection.sid
            ),
            None,
        )
        if seat_key is None or not self._rooms.identity_ok(room, seat_key, connection):
            return await self._fail(connection, CHAT_NOT_SEATED)

        now = time.time()
        recent = [
            stamp
            for stamp in (room.chat_recent.get(seat_key) or [])
            if now - stamp < quick_chat.WINDOW_SECONDS
        ]
        allowed, reason = quick_chat.check_rate(
            recent,
            now,
            room.chat_last.get(seat_key),
            message,
            noun="消息",
            duplicate_reason=(
                f"同一句话 {quick_chat.WINDOW_SECONDS} 秒内不能重复发送"
            ),
        )
        # Expired stamps are dropped even on a refusal; a refused line is never
        # recorded (otherwise the refusal itself would fill the window).
        room.chat_recent[seat_key] = recent
        if not allowed:
            return await self._fail(connection, reason)
        recent.append(now)
        room.chat_last[seat_key] = {"id": message, "ts": now}

        username = _display_name(connection, seat_key)
        baseline = room.chat_seq
        # A seat that has never seen chat starts at the current head: joining a
        # match in progress must not backfill the history it was not present for.
        for player_id in room.players:
            room.chat_delivered.setdefault(player_id, baseline)
        seq = baseline + 1
        room.chat_seq = seq
        room.chat_history.append(
            {"seq": seq, "username": username, "message": message, "ts": int(now)}
        )
        if len(room.chat_history) > CHAT_HISTORY_LIMIT:
            room.chat_history = room.chat_history[-CHAT_HISTORY_LIMIT:]

        await self._publisher.emit(
            "chat_message", {"username": username, "message": message}, room=room.id
        )

        # Advance the watermark only for seats whose socket was actually online
        # when the frame went out. Everyone else is caught up by replay_missed.
        for player_id, player in room.players.items():
            socket_id = getattr(player, "socket_id", None)
            if player_id == seat_key or (socket_id and self._rooms.presence.get(socket_id)):
                room.chat_delivered[player_id] = seq
        return {"status": "success"}

    async def replay_missed(self, room: Any, player_id: str, sid: str) -> None:
        """Reconnect hook: send only the lines this seat did not receive.

        Called by RoomService after a successful rejoin, before the seat starts
        acting again. The legacy payload shape is preserved, so an old client
        simply appends them (they were never delivered, so there is no
        duplicate row on its side either).
        """

        if room is None or not sid:
            return
        key = str(player_id)
        delivered = room.chat_delivered.get(key)
        if delivered is None:
            return
        missed = [entry for entry in room.chat_history if entry["seq"] > delivered]
        for entry in missed:
            await self._publisher.emit(
                "chat_message",
                {"username": entry["username"], "message": entry["message"]},
                to=sid,
            )
        if missed:
            room.chat_delivered[key] = missed[-1]["seq"]

    # --------------------------------------------------------- quick phrases

    async def quick_chat(self, connection: Connection,
                         data: dict[str, Any] | None = None) -> dict[str, Any]:
        data = data if isinstance(data, dict) else {}
        room_id = data.get("room_id")
        player_id = data.get("player_id")
        msg_id = data.get("msg_id")

        room = self._rooms.get_room(room_id)
        if room is None:
            return await self._fail(connection, "房间不存在")
        if player_id not in room.players or not self._rooms.identity_ok(
            room, player_id, connection
        ):
            return await self._fail(connection, "无效的房间或玩家")

        item = quick_chat.by_id(msg_id)
        if item is None:
            return await self._fail(connection, "无效的快捷语")

        now = time.time()
        recent = [t for t in (room.quick_chat_recent.get(player_id) or [])
                  if now - t < quick_chat.WINDOW_SECONDS]
        allowed, reason = quick_chat.check_rate(
            recent, now, room.quick_chat_last.get(player_id), msg_id
        )
        # Drop expired timestamps even on a refusal (the room list must not grow
        # forever), but a refused phrase is never recorded.
        room.quick_chat_recent[player_id] = recent
        if not allowed:
            return await self._fail(connection, reason)

        recent.append(now)
        room.quick_chat_recent[player_id] = recent
        room.quick_chat_last[player_id] = {"id": msg_id, "ts": now}

        player = room.players[player_id]
        name = str(getattr(player, "name", "") or player_id)
        await self._publisher.emit(
            "quick_chat",
            {
                "player_id": player_id,
                "name": name,
                "msg_id": msg_id,
                "text": item["text"],
                "ts": int(now),
            },
            room=room.id,
        )
        entry = {
            "ts": int(now),
            "type": "quick_chat",
            "text": f"{name}：{item['text']}",
            "detail": {"player_id": player_id, "msg_id": msg_id},
        }
        room.game_logs.append(entry)
        await self._publisher.emit("game_log", entry, room=room.id)
        return {"status": "success", "msg_id": msg_id, "text": item["text"]}
