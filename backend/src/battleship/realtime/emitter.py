"""Socket.IO implementation of the service layer's EventPublisher.

Kept in the realtime layer so services never import socketio and can be tested
with a recording publisher.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

import socketio

#: Called after every emit with the same target arguments (the legacy "third
#: leg" that copied sanitised broadcasts into the spectator channel). Kept as a
#: callback so the publisher stays a pure transport adapter.
MirrorHook = Callable[..., Awaitable[None]]


class SocketIoPublisher:
    def __init__(self, sio: socketio.AsyncServer, *,
                 mirror: MirrorHook | None = None) -> None:
        self._sio = sio
        self._mirror = mirror

    async def emit(
        self,
        event: str,
        data: dict[str, Any],
        *,
        to: str | None = None,
        room: str | None = None,
    ) -> None:
        await self._sio.emit(event, data, to=to, room=room)
        if self._mirror is not None:
            await self._mirror(event, data, to=to, room=room)

    async def enter_room(self, sid: str, room: str) -> None:
        await self._sio.enter_room(sid, room)

    async def leave_room(self, sid: str, room: str) -> None:
        await self._sio.leave_room(sid, room)
