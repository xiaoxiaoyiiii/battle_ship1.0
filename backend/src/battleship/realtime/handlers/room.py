"""Socket adapters for room creation / seating (ticket #7).

Only protocol translation: pull the trusted connection identity, delegate to the
service, return its ack. No business rule is allowed to grow here.

Ticket #14 adds one orchestration detail: a seat change updates the lobby lists,
so the adapter asks the lobby to re-broadcast after a successful room event.
The broadcast itself (who receives it, what it contains) stays in LobbyService.
"""

from __future__ import annotations

from typing import Any

import socketio

from ..identity import connection_from_sio
from ...services.lobby import LobbyService
from ...services.rooms import RoomService


async def _broadcast_lobby(lobby: LobbyService | None) -> None:
    if lobby is None:
        return
    try:
        await lobby.broadcast()
    except Exception:  # noqa: BLE001 - a broken lobby frame must not fail the room event
        pass


def register_room_handlers(sio: socketio.AsyncServer, rooms: RoomService,
                           lobby: LobbyService | None = None) -> None:
    @sio.on("create_room")
    async def create_room(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        result = await rooms.create_room(connection, data)
        if result.get("status") == "success":
            await _broadcast_lobby(lobby)
        return result

    @sio.on("join_room")
    async def join_room(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        result = await rooms.join_room(connection, data)
        if result.get("status") == "success":
            await _broadcast_lobby(lobby)
        return result

    @sio.on("create_ai_room")
    async def create_ai_room(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        result = await rooms.create_ai_room(connection, data)
        if result.get("status") == "success":
            await _broadcast_lobby(lobby)
        return result

    @sio.on("set_decline_priority")
    async def set_decline_priority(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await rooms.set_decline_priority(connection, data)
