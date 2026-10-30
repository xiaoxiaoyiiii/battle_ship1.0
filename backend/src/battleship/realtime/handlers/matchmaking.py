"""Socket adapters for matchmaking (ticket #16).

Protocol translation only: pull the trusted connection identity, delegate to the
service, return its ack. No pairing rule is allowed to grow here.
"""

from __future__ import annotations

from typing import Any

import socketio

from ..identity import connection_from_sio
from ...services.matchmaking import MatchmakingService


def register_matchmaking_handlers(sio: socketio.AsyncServer,
                                  matchmaking: MatchmakingService) -> None:
    @sio.on("find_match")
    async def find_match(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await matchmaking.find_match(connection, data)

    @sio.on("cancel_match")
    async def cancel_match(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await matchmaking.cancel_match(connection, data)
