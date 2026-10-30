"""Spectator use cases: the switch, joining/leaving, chat and the live feed.

The socket handlers are pure protocol translation; every rule about who may watch
what lives here. This service is the only producer of the spectator channel
(`spectate:<room_id>`): spectators never enter the match room and are never
written into `room.players`.

The "third leg" of the legacy `emit()` lives here too: every broadcast to a live
game room is copied -- sanitised -- into the spectator channel. Events that are
not on the frozen allowlist simply do not reach spectators (default deny), so a
new game event cannot leak a board by being added somewhere else in the code.

Database access goes through the UnitOfWork repositories (ticket #5); no SQL is
written in this layer.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from ..contracts import errors as socket_errors
from ..domain import spectate
from ..domain.lobby.rules import LOBBY_ROOM
from ..domain.social import quick_chat
from ..infra.logging import get_logger
from .rooms import Connection, EventPublisher, NullPublisher, RoomService

logger = get_logger("spectators")

INVALID_CONNECTION = "观战请求异常：缺少连接信息"
LOGIN_REQUIRED = "观战需要先登录"
ROOM_MISSING = "缺少房间号"
ROOM_NOT_FOUND = "房间不存在"
ROOM_FINISHED = "对局已结束，无法观战"
ROOM_NOT_STARTED = "对局还没开始，无法观战"
AI_ROOM = "人机房不支持观战"
OWN_GAME = "你是这一局的玩家，不能观战自己的对局"
SEATS_FULL = "观战席已满（上限 %d 人）" % spectate.SPECTATOR_LIMIT
NOT_ALLOWED = "这一局的玩家没有开放观战"

CHAT_INVALID_CONNECTION = "发言失败：缺少连接信息"
CHAT_LOGIN_REQUIRED = "观战席发言需要先登录"
CHAT_NOT_SEATED = "你不在观战席上"
CHAT_WRONG_ROOM = "你不在这一局的观战席上"
CHAT_EMPTY = "说点什么再发送吧"

#: The legacy lobby cached this flag for 5s because lobby_state re-broadcasts
#: every 4s. Joining a room never uses the cache (the switch is read once, at
#: the moment the spectator enters).
ALLOW_CACHE_TTL_SECONDS = 5.0

#: Only these room states count as a watchable match in the lobby list.
LIVE_MATCH_STATES = ("placing_ships", "rock_paper_scissors", "attacking")


def _state_value(value: Any) -> Any:
    return getattr(value, "value", value)


class SpectatorService:
    def __init__(
        self,
        rooms: RoomService,
        database: Any | None = None,
        *,
        clock: Callable[[], float] | None = None,
        allow_cache_ttl: float = ALLOW_CACHE_TTL_SECONDS,
    ) -> None:
        self._rooms = rooms
        self._database = database
        self._clock = clock or time.time
        self.allow_cache_ttl = float(allow_cache_ttl)
        self._allow_cache: dict[str, tuple[float, bool | None]] = {}
        self._publisher: EventPublisher = NullPublisher()
        # The room table can be popped from a non-async context (tests, future
        # admin paths). Remember the serving loop so "tell the spectators" still
        # runs on the loop that owns the Socket.IO server.
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------ wiring

    def bind(self, publisher: EventPublisher) -> None:
        self._publisher = publisher

    def bind_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop

    # ------------------------------------------------------------- allow switch

    def invalidate_allow_cache(self, user_id: str | None = None) -> None:
        if user_id is None:
            self._allow_cache.clear()
        else:
            self._allow_cache.pop(str(user_id), None)

    def _read_allow_fresh(self, user_id: str | None) -> bool | None:
        """True / False / None (= unknown: no database, no account, read error).

        None must never degrade into "allowed": one missed spectator is cheap,
        one exposed board is not (legacy lesson #21).
        """

        if not user_id or self._database is None:
            return None
        try:
            with self._database.unit_of_work() as uow:
                if uow.users.get(str(user_id)) is None:
                    return None
                return uow.social.get_allow_spectate(str(user_id))
        except Exception:  # noqa: BLE001 - a lobby frame must not 500
            logger.exception("allow_spectate read failed", extra={"user_id": str(user_id)})
            return None

    def allow_spectate(self, user_id: str | None) -> bool | None:
        """Cached read used by the lobby's live-match list."""

        if not user_id:
            return None
        key = str(user_id)
        now = self._clock()
        cached = self._allow_cache.get(key)
        if cached is not None and now - cached[0] < self.allow_cache_ttl:
            return cached[1]
        value = self._read_allow_fresh(key)
        self._allow_cache[key] = (now, value)
        return value

    def get_setting(self, user_id: str) -> bool | None:
        """The GET route: a fresh read, so a write from another tab is visible."""

        return self._read_allow_fresh(user_id)

    def has_account(self, user_id: str | None) -> bool | None:
        if not user_id or self._database is None:
            return None
        try:
            with self._database.unit_of_work() as uow:
                return uow.users.get(str(user_id)) is not None
        except Exception:  # noqa: BLE001 - reported as "unknown", never as ok
            logger.exception("account lookup failed", extra={"user_id": str(user_id)})
            return None

    def set_setting(self, user_id: str, allow: bool) -> bool:
        if not user_id or self._database is None:
            return False
        try:
            with self._database.unit_of_work() as uow:
                if uow.users.get(str(user_id)) is None:
                    return False
                uow.social.set_allow_spectate(str(user_id), bool(allow))
        except Exception:  # noqa: BLE001 - the route reports a save failure
            logger.exception("allow_spectate write failed", extra={"user_id": str(user_id)})
            return False
        self.invalidate_allow_cache(user_id)
        return True

    def _seat_allow(self, player: Any) -> bool | None:
        """One seat's answer to "may others watch my game?" (True/False/None)."""

        user_id = getattr(player, "user_id", None)
        if not user_id:
            return None
        # Fresh read: a spectator entering right after the switch was flipped off
        # must be refused, even if the lobby cache still says True.
        return self._read_allow_fresh(str(user_id))

    def spectate_allowed(self, room: Any) -> bool:
        """Both seats must allow it. Read once, at the moment of joining."""

        seats = list(room.players.values())
        if len(seats) != 2:
            return False
        return spectate.can_spectate(self._seat_allow(seats[0]), self._seat_allow(seats[1]))

    # ------------------------------------------------------- spectator channel

    async def _fail(self, connection: Connection, message: str) -> dict:
        """Refuse with a reason on both paths (error frame + ack), never silently."""

        try:
            await self._publisher.emit(
                "error",
                socket_errors.error_detail(socket_errors.SPECTATE_DENIED, message),
                to=connection.sid,
            )
        except Exception:  # noqa: BLE001 - the ack is the authoritative result
            logger.exception("spectate error frame failed")
        return {"status": "error", "message": message}

    def roster(self, room: Any) -> dict[str, Any]:
        """Spectator seat list: display names + join time only (no uid, no sid)."""

        return {
            "spectators": [
                {"name": (info or {}).get("name"), "joined_at": (info or {}).get("joined_at")}
                for info in (getattr(room, "spectators", None) or {}).values()
            ],
            "count": self.count(room),
            "limit": spectate.SPECTATOR_LIMIT,
        }

    async def _announce(self, room: Any, event: str, name: Any) -> None:
        await self._publisher.emit(
            event, {"name": name}, room=spectate.spectate_room_name(room.id)
        )

    async def _broadcast_roster(self, room: Any) -> None:
        await self._publisher.emit(
            "spectate_roster",
            self.roster(room),
            room=spectate.spectate_room_name(room.id),
        )

    async def _broadcast_count(self, room: Any) -> None:
        """Count only (no names) to the players; the third leg copies it to spectators."""

        await self._publisher.emit(
            "spectate_count_changed", {"count": self.count(room)}, room=room.id
        )

    # ----------------------------------------------------------------- joining

    async def join(self, connection: Connection,
                   data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        room_id = data.get("room_id")
        sid = connection.sid

        if not sid:
            return await self._fail(connection, INVALID_CONNECTION)
        if not connection.user_id:
            # Observing is logged-in only (author decision; guests have no switch).
            return await self._fail(connection, LOGIN_REQUIRED)
        if not room_id:
            return await self._fail(connection, ROOM_MISSING)

        room = self._rooms.get_room(str(room_id))
        if room is None:
            return await self._fail(connection, ROOM_NOT_FOUND)
        state = _state_value(getattr(room, "state", None))
        if state == "game_over":
            return await self._fail(connection, ROOM_FINISHED)
        if state == "waiting":
            # Not "switch off": the real reason is that the match has not started,
            # otherwise the player would go looking for the wrong setting.
            return await self._fail(connection, ROOM_NOT_STARTED)
        if getattr(room, "is_ai_room", False):
            return await self._fail(connection, AI_ROOM)

        uid = str(connection.user_id)
        for player_id, player in room.players.items():
            if (
                str(player_id) == sid
                or getattr(player, "socket_id", None) == sid
                or (getattr(player, "user_id", None) is not None
                    and str(getattr(player, "user_id")) == uid)
            ):
                return await self._fail(connection, OWN_GAME)

        already_seated = sid in (room.spectators or {})
        if not already_seated:
            if self.count(room) >= spectate.SPECTATOR_LIMIT:
                return await self._fail(connection, SEATS_FULL)
            if not self.spectate_allowed(room):
                return await self._fail(connection, NOT_ALLOWED)

            # Only the room-level spectator table: never room.players.
            room.spectators[sid] = {
                "name": connection.username or uid,
                "user_id": uid,
                "joined_at": int(self._clock()),
            }
            await self._publisher.enter_room(sid, spectate.spectate_room_name(room.id))
            await self._broadcast_count(room)
            # join_room must come first, otherwise the newcomer misses his own
            # first roster (he would render a list that is missing himself).
            await self._announce(room, "spectate_joined", room.spectators[sid]["name"])
            await self._broadcast_roster(room)

        # The one-shot snapshot and "your name" are sent on every join, including
        # a re-entry: a refreshed client has lost whatever it had cached.
        await self._publisher.emit(
            "spectate_you", {"name": room.spectators[sid]["name"]}, to=sid
        )
        await self._publisher.emit(
            "spectate_sync", spectate.build_spectate_snapshot(room), to=sid
        )
        return {
            "status": "success",
            "room_id": room_id,
            "count": self.count(room),
            "limit": spectate.SPECTATOR_LIMIT,
        }

    async def leave(self, connection: Connection,
                    data: dict[str, Any] | None = None) -> dict:
        sid = connection.sid
        if not sid:
            return await self._fail(connection, "退出观战失败：缺少连接信息")
        room = self.room_of_sid(sid)
        if room is None:
            # Idempotent leave still explains itself ("you are not on any seat").
            return await self._fail(connection, "你不在任何观战席上")

        left_name = (room.spectators.get(sid) or {}).get("name")
        room.spectators.pop(sid, None)
        room_id = room.id
        # Broadcast before leaving the channel: after leave_room the departing
        # spectator would no longer receive the count/roster update.
        await self._broadcast_count(room)
        await self._announce(room, "spectate_left", left_name)
        await self._broadcast_roster(room)
        await self._publisher.leave_room(sid, spectate.spectate_room_name(room_id))
        return {"status": "success", "room_id": room_id, "count": self.count(room)}

    async def chat_send(self, connection: Connection,
                        data: dict[str, Any] | None = None) -> dict:
        data = data if isinstance(data, dict) else {}
        sid = connection.sid
        if not sid:
            return await self._fail(connection, CHAT_INVALID_CONNECTION)
        if not connection.user_id:
            return await self._fail(connection, CHAT_LOGIN_REQUIRED)

        room = self.room_of_sid(sid)
        if room is None:
            return await self._fail(connection, CHAT_NOT_SEATED)
        claimed = data.get("room_id")
        if claimed and str(claimed) != str(room.id):
            return await self._fail(connection, CHAT_WRONG_ROOM)

        message = data.get("message")
        message = (message or "").strip() if isinstance(message, str) else ""
        if not message:
            return await self._fail(connection, CHAT_EMPTY)
        message = message[: spectate.MAX_SPECTATE_CHAT_LEN]

        now = self._clock()
        recent = [
            stamp
            for stamp in (room.spectate_chat_recent.get(sid) or [])
            if now - stamp < quick_chat.WINDOW_SECONDS
        ]
        allowed, reason = quick_chat.check_rate(
            recent, now, room.spectate_chat_last.get(sid), message
        )
        # Expired stamps are dropped even on a refusal; a refused line is not recorded.
        room.spectate_chat_recent[sid] = recent
        if not allowed:
            return await self._fail(connection, reason)
        recent.append(now)
        room.spectate_chat_last[sid] = {"id": message, "ts": now}

        name = (room.spectators.get(sid) or {}).get("name") or str(connection.user_id)
        payload = {"name": name, "message": message, "ts": int(now)}
        # Only the spectator channel: the two players are not in that room set,
        # so the isolation is structural, not a post-hoc recipient filter.
        await self._publisher.emit(
            "spectate_chat", payload, room=spectate.spectate_room_name(room.id)
        )
        return {"status": "success", "message": payload}

    # -------------------------------------------------------- disconnect / end

    async def handle_disconnect(self, sid: str) -> None:
        """A spectator's socket closed: drop the seat and tell the others."""

        room_id, left_name = self.sid_left(sid)
        if not room_id:
            return
        room = self._rooms.get_room(room_id)
        if room is None:
            return
        # The legacy background task ran after Socket.IO had already removed the
        # dead sid from spectate:<room>, so the departing viewer never saw the
        # count update. Leaving explicitly here reproduces that recipient set.
        await self._publisher.leave_room(sid, spectate.spectate_room_name(room_id))
        await self._broadcast_count(room)
        if left_name:
            await self._announce(room, "spectate_left", left_name)
            await self._broadcast_roster(room)

    def on_room_dropped(self, room: Any, reason: str = "对局已结束") -> None:
        """RoomService drop hook: tell still-seated spectators the feed is gone.

        Synchronous because the room table is popped synchronously; the actual
        frame is scheduled on the running loop (there is no hub to block here).
        """

        if room is None or not self.count(room):
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not None:
            running.create_task(self.end_room(room, reason))
        elif self._loop is not None:
            asyncio.run_coroutine_threadsafe(self.end_room(room, reason), self._loop)
        else:
            logger.warning(
                "room dropped with spectators but no event loop is bound",
                extra={"room_id": getattr(room, "id", None)},
            )

    async def end_room(self, room: Any, reason: str = "对局已结束") -> None:
        if room is None or not self.count(room):
            return
        room_id = room.id
        room.spectators.clear()
        await self._publisher.emit(
            "spectate_ended",
            {"room_id": room_id, "reason": reason},
            room=spectate.spectate_room_name(room_id),
        )

    # ------------------------------------------------------------ live feed

    async def mirror_event(self, event: str, data: Any, *, to: str | None = None,
                           room: str | None = None) -> None:
        """The legacy emit() third leg: sanitised copy into the spectator channel.

        Only broadcasts to a live match room are copied. Private frames (to=sid)
        never are: they are not "what happened in the match", they are answers to
        one connection.
        """

        if to is not None or not room:
            return
        if spectate.is_spectate_room(room):
            return  # never feed the spectator channel back into itself
        if room == LOBBY_ROOM:
            return  # the lobby is not a match; nothing to copy
        room_obj = self._rooms.get_room(room)
        if room_obj is None:
            # Not a live match room (lobby room, stale id). Never silent: this is
            # how the legacy 9 "sid used as room" mistakes stayed invisible.
            logger.warning(
                "broadcast target is not a live game room; no spectator copy",
                extra={"event": event, "room": str(room)},
            )
            return
        clean = spectate.sanitize_event(event, data, room=room_obj)
        if clean is None:
            return
        await self._publisher.emit(
            event, clean, room=spectate.spectate_room_name(room_obj.id)
        )

    async def publish_board(self, room: Any) -> None:
        """Push one canonical board frame to the spectator channel (no players)."""

        if room is None or spectate.is_spectate_room(getattr(room, "id", None)):
            return
        clean = spectate.canonical_frame_json(spectate.build_board_frame(room))
        await self._publisher.emit(
            "spectate_board", clean, room=spectate.spectate_room_name(room.id)
        )

    async def mark_board_dirty(self, room: Any) -> None:
        """Declare "the visible board changed" (cards that clear/rebuild a board).

        The frame is published immediately and the room is marked so the card
        flow can flush a more complete frame once the whole effect has settled
        (a half-applied frame -- e.g. ship count still 5 -- must not be the last
        thing a spectator sees).
        """

        if room is None:
            return
        await self.publish_board(room)
        try:
            room.spectate_board_dirty = True
        except AttributeError:  # test doubles have no such field
            pass

    async def flush_board(self, room: Any) -> None:
        if room is None or not getattr(room, "spectate_board_dirty", False):
            return
        room.spectate_board_dirty = False
        await self.publish_board(room)

    # ------------------------------------------------------------- lobby listing

    def _lobby_flag(self, player: Any) -> bool | None:
        user_id = getattr(player, "user_id", None)
        if not user_id:
            return None
        return self.allow_spectate(str(user_id))

    def live_matches(self) -> list[dict[str, Any]]:
        """Watchable matches for lobby_state.matches.

        Product rules (legacy, unchanged): only full non-AI rooms in a started
        state, and only when both seats allow spectating -- otherwise the entry
        is a button that always fails.
        """

        seats: list[tuple[Any, list[tuple[str, Any]]]] = []
        for room in self._rooms.get_all_rooms().values():
            if _state_value(getattr(room, "state", None)) not in LIVE_MATCH_STATES:
                continue
            if getattr(room, "is_ai_room", False):
                continue
            entries = list(room.players.items())
            if len(entries) != 2:
                continue
            seats.append((room, entries))

        rows: list[dict[str, Any]] = []
        for room, entries in seats:
            if not spectate.can_spectate(
                self._lobby_flag(entries[0][1]), self._lobby_flag(entries[1][1])
            ):
                continue
            rows.append(
                {
                    "room_id": room.id,
                    "names": [str(getattr(player, "name", "") or "") for _key, player in entries],
                    "round": int(getattr(room, "round", 0) or 0),
                    "spectators": self.count(room),
                    "spectator_limit": spectate.SPECTATOR_LIMIT,
                    "ranked": bool(getattr(room, "ranked", False)),
                }
            )
        # Most-watched first, then a stable room-id order (the room dict itself
        # has no guaranteed order and would shuffle the list every frame).
        rows.sort(key=lambda row: (-row["spectators"], row["room_id"]))
        return rows

    # ------------------------------------------------------------------ counts

    def count(self, room: Any) -> int:
        return len(getattr(room, "spectators", None) or {})

    def room_of_sid(self, sid: str | None) -> Any | None:
        if not sid:
            return None
        for room in self._rooms.get_all_rooms().values():
            if sid in (getattr(room, "spectators", None) or {}):
                return room
        return None

    def sid_left(self, sid: str) -> tuple[str | None, str | None]:
        """Detach one spectator; returns (room_id, display name)."""

        room = self.room_of_sid(sid)
        if room is None:
            return None, None
        info = (getattr(room, "spectators", None) or {}).pop(sid, None)
        return room.id, (info or {}).get("name")
