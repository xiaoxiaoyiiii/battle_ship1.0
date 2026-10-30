"""Socket.IO ASGI 适配层。

新的 socket 事件适配层按领域迁移到 `handlers/*`。当前负责：
连接计数、会话身份落盘、续局提示/重连 token、房间与重连事件接线、
未登记事件的明确拒绝，以及 `/metrics` 需要的事件计数。
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import socketio

from ..contracts.events_in import is_debug_event
from ..http.session import session_from_cookie_header, session_user_id, session_username
from ..infra.logging import get_logger, log_context
from ..services.ai import AiService
from ..services.battle import BattleService
from ..services.chat import ChatService
from ..services.friends import FriendsService
from ..services.gameplay import GameplayService
from ..services.lobby import LobbyService
from ..services.magic import MagicService
from ..services.matchmaking import MatchmakingService
from ..services.presence import PresenceService
from ..services.rooms import Connection, RoomService
from ..services.spectators import SpectatorService
from .emitter import SocketIoPublisher
from .handlers.battle import register_battle_handlers
from .handlers.chain import register_chain_handlers
from .handlers.chat import register_chat_handlers
from .handlers.debug import (
    DEBUG_EVENT_DISABLED_MESSAGE,
    register_debug_handlers,
    register_debug_implementations,
)
from .handlers.lobby import register_lobby_handlers
from .handlers.magic import register_magic_handlers
from .handlers.matchmaking import register_matchmaking_handlers
from .handlers.reconnect import register_reconnect_handlers
from .handlers.room import register_room_handlers
from .handlers.spectate import register_spectate_handlers

if TYPE_CHECKING:
    from ..config import Settings
    from ..infra.metrics import MetricsRegistry

logger = get_logger("realtime")


def create_socket_server(
    settings: "Settings",
    metrics: "MetricsRegistry",
    rooms: RoomService | None = None,
    gameplay: GameplayService | None = None,
    battle: BattleService | None = None,
    magic: MagicService | None = None,
    lobby: LobbyService | None = None,
    presence: PresenceService | None = None,
    friends: FriendsService | None = None,
    chat: ChatService | None = None,
    matchmaking: MatchmakingService | None = None,
    spectators: SpectatorService | None = None,
    ai: AiService | None = None,
) -> socketio.AsyncServer:
    presence = presence or (rooms.presence if rooms is not None else None)
    presence = presence or PresenceService()
    rooms = rooms or RoomService(
        presence=presence, turn_timeout_seconds=settings.turn_timeout_seconds
    )
    lobby = lobby or LobbyService(rooms, presence)
    # Without a database nobody may be watched: unknown (None) fails closed.
    spectators = spectators or SpectatorService(rooms)
    lobby.spectators = spectators
    gameplay = gameplay or GameplayService(
        rooms, turn_timeout_seconds=settings.turn_timeout_seconds
    )
    battle = battle or BattleService(rooms, touch_turn=gameplay.touch_turn)
    if gameplay.fire_hook is None:
        gameplay.fire_hook = battle.fire
    # Ticket #10: one magic service holds the shared deck, hand sync, target
    # channels and the card-effect registry. Wiring lives here so every caller
    # of create_socket_server (including tests) gets the same seams.
    matchmaking = matchmaking or MatchmakingService(rooms, lobby=lobby)
    magic = magic or MagicService(
        rooms, chain_display_delay_seconds=settings.chain_display_delay_seconds
    )
    gameplay.magic = magic
    battle.state_sync_hook = magic._sync_each_seat
    if gameplay.draw_hook is None:
        gameplay.draw_hook = magic.draw
    if gameplay.turn_start_hook is None:
        gameplay.turn_start_hook = lambda room, _pid: magic.settle_wuyou_dream(room)
    if gameplay.draw_skip_hook is None:
        gameplay.draw_skip_hook = magic.consume_bingliang_skip
    if gameplay.after_draw_hook is None:
        gameplay.after_draw_hook = lambda room, _pid: magic.settle_bingliang(room)
    if gameplay.round_end_hook is None:
        gameplay.round_end_hook = magic.on_new_big_round
    if magic.ai_place_hook is None:
        magic.ai_place_hook = gameplay.ai_place_board_now
    # Ticket #13: one turn driver for every AI tier. It shares the magic timer
    # registry so a destroyed room also cancels a running AI turn, and it is the
    # only place that installs the gameplay hook.
    ai = ai or AiService(rooms, gameplay, battle, magic, timers=magic.timers)
    if gameplay.ai_turn_hook is None:
        gameplay.ai_turn_hook = ai.run_turn
    if magic.finish_hook is None:
        magic.finish_hook = battle.finish_game
    if magic.on_ship_sunk not in battle.sink_hooks:
        battle.sink_hooks.append(magic.on_ship_sunk)
    if magic.on_damage not in battle.damage_hooks:
        battle.damage_hooks.append(magic.on_damage)
    if magic.on_attacks_exhausted not in battle.attacks_exhausted_hooks:
        battle.attacks_exhausted_hooks.append(magic.on_attacks_exhausted)
    sio = socketio.AsyncServer(
        async_mode="asgi",
        cors_allowed_origins=settings.cors_origins or [],
        logger=False,
        engineio_logger=False,
    )

    @sio.event
    async def connect(sid: str, environ: dict, auth=None) -> bool:
        metrics.connection_opened()
        # Carry the signed-cookie identity onto the socket. ticket #7 reads this
        # instead of trusting a client-supplied user_id/player_id claim.
        cookie_header = (environ or {}).get("HTTP_COOKIE") or (environ or {}).get("COOKIE")
        session = session_from_cookie_header(
            settings.secret_key.get_secret_value(), cookie_header
        )
        # REMOTE_ADDR is the only trustworthy peer address (legacy _client_ip;
        # no reverse proxy in front of the app). Matchmaking normalises private
        # and loopback addresses to "not judged".
        remote_ip = str((environ or {}).get("REMOTE_ADDR") or "").strip()
        await sio.save_session(
            sid,
            {
                "user_id": session_user_id(session),
                "username": session_username(session),
                "ip": remote_ip,
            },
        )
        connection = Connection(
            sid=sid,
            user_id=session_user_id(session),
            username=session_username(session),
            ip=remote_ip,
        )
        # Register the connection in the single online table before anything
        # else (the legacy connect handler did this first, so every later
        # branch -- including resume_game -- sees the player as online).
        await rooms.handle_connect(connection)
        # Remember the serving loop for spectator cleanup triggered outside a
        # coroutine (the room table is popped synchronously).
        spectators.bind_loop(asyncio.get_running_loop())
        lobby.ensure_ticker()
        # A returning account may still sit in an unfinished room: push
        # resume_game + a fresh reconnect token so the client can rejoin.
        await rooms.notify_resume(connection)
        with log_context(event="connect"):
            logger.info(
                "socket connected",
                extra={"socket_id": sid, "authenticated": bool(session_user_id(session))},
            )
        return True

    @sio.event
    async def disconnect(sid: str, reason=None) -> None:
        metrics.connection_closed()
        # Start the 30s grace in a background task. This handler must never wait
        # on the grace window (the legacy eventlet hub deadlock).
        await rooms.handle_disconnect(sid)
        # Presence and lobby membership are gone now; tell the remaining
        # members. A failure here must never break the disconnect path.
        try:
            await lobby.handle_disconnect(sid)
            await lobby.broadcast()
        except Exception:  # noqa: BLE001
            logger.exception("lobby broadcast on disconnect failed")
        # A spectator's connection closing must update the spectator count; it
        # must never start a room grace timer or touch the match seats.
        try:
            await spectators.handle_disconnect(sid)
        except Exception:  # noqa: BLE001
            logger.exception("spectator cleanup on disconnect failed")
        with log_context(event="disconnect"):
            logger.info("socket disconnected", extra={"socket_id": sid, "reason": str(reason)})

    @sio.on("debug_status")
    async def debug_status(sid: str, data=None) -> dict:
        return {
            "status": "success",
            "enabled": bool(settings.enable_test_events),
            "whitelist_configured": bool(settings.debug_admin_user_ids),
        }

    # namespace 级 catch-all：python-socketio 传参顺序是 (event, sid, data)。
    @sio.on("*")
    async def unknown_event(event: str, sid: str, *args) -> dict:
        started = time.perf_counter()
        name = str(event)
        if is_debug_event(name):
            # 开关关闭时调试 handler 没有注册，由这里给出与旧栈一致的拒绝。
            message = DEBUG_EVENT_DISABLED_MESSAGE
        else:
            message = f"未登记的事件: {name}"
        with log_context(event=name):
            logger.warning("unhandled socket event", extra={"debug_event": is_debug_event(name)})
        metrics.record_socket_event(
            name, (time.perf_counter() - started) * 1000, error=True
        )
        return {"status": "error", "message": message}

    publisher = SocketIoPublisher(sio, mirror=spectators.mirror_event)
    rooms.bind(publisher)
    lobby.bind(publisher)
    spectators.bind(publisher)
    gameplay.bind(publisher)
    battle.bind(publisher)
    magic.bind(publisher)
    matchmaking.bind(publisher)
    rooms.room_dropped_hook = spectators.on_room_dropped
    battle.board_flush_hook = spectators.flush_board
    if friends is not None:
        friends.bind(publisher)
    if chat is not None:
        chat.bind(publisher)
        register_chat_handlers(sio, chat)
        # Ticket #31: rejoin replays only the chat lines this seat missed.
        rooms.rejoin_hook = chat.replay_missed
    register_room_handlers(sio, rooms, lobby)
    register_lobby_handlers(sio, lobby)
    register_battle_handlers(sio, gameplay, battle)
    register_magic_handlers(sio, magic)
    register_matchmaking_handlers(sio, matchmaking)
    register_chain_handlers(sio, magic)
    register_reconnect_handlers(sio, rooms)
    register_spectate_handlers(sio, spectators)
    register_debug_implementations(battle, magic, rooms, gameplay)
    register_debug_handlers(sio, settings, metrics)
    return sio
