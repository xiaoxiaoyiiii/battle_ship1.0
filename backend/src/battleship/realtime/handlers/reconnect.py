"""Socket adapters for reconnect / hand self-healing (ticket #7)."""

from __future__ import annotations

from typing import Any

import socketio

from ..identity import connection_from_sio
from ...services.rooms import RoomService


def register_reconnect_handlers(sio: socketio.AsyncServer, rooms: RoomService) -> None:
    @sio.on("get_reconnect_token")
    async def get_reconnect_token(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await rooms.get_reconnect_token(connection, data)

    @sio.on("rejoin_room")
    async def rejoin_room(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await rooms.rejoin_room(connection, data)

    @sio.on("request_hand_sync")
    async def request_hand_sync(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await rooms.request_hand_sync(connection, data)
