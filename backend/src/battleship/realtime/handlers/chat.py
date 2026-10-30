"""Socket adapter for in-game quick chat (ticket #14)."""

from __future__ import annotations

from typing import Any

import socketio

from ..identity import connection_from_sio
from ...services.chat import ChatService


def register_chat_handlers(sio: socketio.AsyncServer, chat: ChatService) -> None:
    @sio.on("chat_message")
    async def chat_message(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await chat.chat_message(connection, data)

    @sio.on("quick_chat")
    async def quick_chat(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await chat.quick_chat(connection, data)
