"""Socket adapters for the spectator channel (ticket #17).

Pure protocol translation: take the trusted connection identity, delegate to
SpectatorService, return its ack. Business rules stay in the service -- in
particular the handler never joins the match room and never touches
`room.players`.
"""

from __future__ import annotations

from typing import Any

import socketio

from ..identity import connection_from_sio
from ...services.spectators import SpectatorService


def register_spectate_handlers(sio: socketio.AsyncServer,
                               spectators: SpectatorService) -> None:
    @sio.on("spectate_join")
    async def spectate_join(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await spectators.join(connection, data)

    @sio.on("spectate_leave")
    async def spectate_leave(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await spectators.leave(connection, data)

    @sio.on("spectate_chat_send")
    async def spectate_chat_send(sid: str,
                                 data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await spectators.chat_send(connection, data)
