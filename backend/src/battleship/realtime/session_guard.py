"""所有实时事件统一验证登录会话，包括调试和未登记事件。"""
from __future__ import annotations

import asyncio
from functools import wraps

import socketio

from ..repositories import Database
from ..services.auth_sessions import has_login_identity, valid_session


def install_session_guard(sio: socketio.AsyncServer, database: Database | None) -> None:
    """在全部 handler 注册后安装；匿名连接保留，失效登录连接关闭。"""
    async def close_after_ack(sid: str, namespace: str) -> None:
        # handler 返回后 Socket.IO 才发送 ack；让其先进入发送队列。
        await asyncio.sleep(0)
        await sio.disconnect(sid, namespace=namespace)

    def protect(handler, *, catch_all: bool, namespace: str):
        @wraps(handler)
        async def guarded(*args, **kwargs):
            sid = args[1] if catch_all else args[0]
            try:
                session = await sio.get_session(sid, namespace=namespace) or {}
            except KeyError:
                session = {"user_id": "expired"}
            if has_login_identity(session) and not valid_session(session, database):
                sio.start_background_task(close_after_ack, sid, namespace)
                return {"status": "error", "code": "session_expired", "message": "登录已失效，请重新登录"}
            return await handler(*args, **kwargs)
        return guarded

    for namespace, handlers in sio.handlers.items():
        for event, handler in list(handlers.items()):
            if event not in {"connect", "disconnect"}:
                handlers[event] = protect(handler, catch_all=event == "*", namespace=namespace)
