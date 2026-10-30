"""Socket adapter for the chain response window (ticket #12).

Only protocol translation: trusted identity -> MagicService.chain_response ->
ack. The legacy event name and ack shape are frozen (no length prefix, plain
`{status, message}`).
"""

from __future__ import annotations

from typing import Any

import socketio

from ..identity import connection_from_sio
from ...services.magic import MagicService


def register_chain_handlers(sio: socketio.AsyncServer, magic: MagicService) -> None:
    @sio.on("chain_response")
    async def chain_response(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await magic.chain_response(connection, data)


__all__ = ["register_chain_handlers"]
