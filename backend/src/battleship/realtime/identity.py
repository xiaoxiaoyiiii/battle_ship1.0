"""Bridge from a Socket.IO connection to the trusted service identity."""

from __future__ import annotations

import socketio

from ..http.session import session_user_id, session_username
from ..services.rooms import Connection


async def connection_from_sio(sio: socketio.AsyncServer, sid: str) -> Connection:
    session = await sio.get_session(sid) or {}
    return Connection(
        sid=sid,
        user_id=session_user_id(session),
        username=session_username(session),
        # Captured from the ASGI environ at connect time; never a header.
        ip=str(session.get("ip") or ""),
    )
