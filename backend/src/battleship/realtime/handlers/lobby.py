"""Socket adapters for the lobby (ticket #14).

Only protocol translation: pull the trusted connection identity, delegate to
LobbyService, return its ack. No business rule is allowed to grow here.

lobby_state is a broadcast to the lobby room. It cannot be personalised with an
"is_me" flag; the client compares lobby_hello.key with players[].key, exactly
like the legacy frontend.
"""

from __future__ import annotations

from typing import Any

import socketio

from ..identity import connection_from_sio
from ...services.lobby import LobbyService


def register_lobby_handlers(sio: socketio.AsyncServer, lobby: LobbyService) -> None:
    @sio.on("lobby_subscribe")
    async def lobby_subscribe(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await lobby.subscribe(connection, data)

    @sio.on("lobby_unsubscribe")
    async def lobby_unsubscribe(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await lobby.unsubscribe(connection, data)

    @sio.on("lobby_refresh")
    async def lobby_refresh(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await lobby.refresh(connection, data)

    @sio.on("lobby_create_room")
    async def lobby_create_room(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await lobby.create_room(connection, data)

    @sio.on("lobby_chat_send")
    async def lobby_chat_send(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await lobby.chat_send(connection, data)

    @sio.on("close_room")
    async def close_room(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await lobby.close_room(connection, data)
