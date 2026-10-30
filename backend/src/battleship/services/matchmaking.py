"""Matchmaking use case (ticket #16): queue, preference, room creation.

The socket adapter only translates frames; every rule lives here:

* mode is the literal `ranked` or `casual` (anything else is casual);
* ranked requires an account (guest ranked rooms could never be persisted);
* the cumulative ban gate uses CAP_RANKED for ranked and CAP_MATCH for casual
  (one capability for both would either disable casual at level 1 or let a
  level-2 account keep queueing);
* seats in a matchmaking room are keyed by the **sid captured at enqueue time**
  (the frozen identity contract); the account id lives only on Player.user_id;
* `room.ranked` is decided by the mode alone. Pairing preference
  (`assessed`) is ordering only -- see domain/matchmaking/guard.py and CLAUDE
  #33. Whether the match yields rank points is decided later by anti-cheat on
  match content.
"""

from __future__ import annotations

import time
from typing import Any

from ..contracts import errors as socket_errors
from ..domain.anticheat import suspicion
from ..domain.matchmaking import guard
from ..domain.room import (
    Player,
    Room,
    RoomState,
    new_room_id,
    opponent_seat_state,
    rank_payload,
    seat_label,
)
from ..infra.logging import get_logger
from ..repositories import Database
from .rooms import Connection, EventPublisher, NullPublisher, RoomService

logger = get_logger("matchmaking")

MATCH_MODE_CASUAL = "casual"
MATCH_MODE_RANKED = "ranked"
MATCH_MODES = (MATCH_MODE_CASUAL, MATCH_MODE_RANKED)


def normalize_match_mode(value: Any) -> str:
    """Only the literal string 'ranked' opens ranked; everything else is casual.

    Deliberately not case-insensitive: a typo must not put a guest into the
    ranked pool (where the match can never be persisted), and guessing what the
    client meant is how two behaviours drift apart.
    """
    return MATCH_MODE_RANKED if value == MATCH_MODE_RANKED else MATCH_MODE_CASUAL


class MatchmakingService:
    def __init__(
        self,
        rooms: RoomService,
        *,
        database: Database | None = None,
        auth: Any | None = None,
        lobby: Any | None = None,
    ) -> None:
        self.rooms = rooms
        self.database = database
        self.auth = auth
        self.lobby = lobby
        self._publisher: EventPublisher = NullPublisher()

    # --------------------------------------------------------------- wiring

    def bind(self, publisher: EventPublisher) -> None:
        self._publisher = publisher

    # ------------------------------------------------------------- facts

    def recent_foes(self, user_id: str | None) -> tuple[str, ...]:
        """Last N opponents of this account (order-only pairing preference).

        A failed read means "no recent opponents": one avoidance layer less is
        better than breaking matchmaking. No time filter is applied -- the same
        dead `RECENT_OPPONENT_COOLDOWN_SEC` as the legacy stack is not revived
        (DECISIONS D11); the lookback window is the last N matches.
        """
        if not user_id or self.database is None:
            return ()
        try:
            with self.database.unit_of_work() as uow:
                return tuple(
                    uow.matches.recent_opponent_ids(
                        user_id, limit=guard.RECENT_OPPONENT_LOOKBACK
                    )
                )
        except Exception as error:  # noqa: BLE001 - preference must not break queueing
            logger.error(
                "recent opponent read failed; treating as none",
                extra={"error_type": type(error).__name__},
                exc_info=error,
            )
            return ()

    def _candidate(self, entry: dict[str, Any]) -> guard.Candidate:
        try:
            return guard.Candidate(
                sid=str(entry.get("sid") or ""),
                uid=entry.get("user_id"),
                mode=str(entry.get("mode") or ""),
                ip=entry.get("ip") or "",
                recent_foes=self.recent_foes(entry.get("user_id")),
                # The legacy `_dirty_ips()` is always empty (IPs are not stored;
                # D11 says do not resurrect it). same_ip_dirty therefore cannot
                # trigger today, but hard_block still knows how if it ever does.
                ip_dirty=False,
                waited_sec=int(time.time() - (entry.get("enqueued_at") or time.time())),
            )
        except Exception:
            # Minimal candidate keeps same-mode and same-account rules alive.
            return guard.Candidate(
                sid=str(entry.get("sid") or ""),
                uid=entry.get("user_id"),
                mode=str(entry.get("mode") or ""),
            )

    # --------------------------------------------------------------- events

    async def find_match(self, connection: Connection,
                         data: dict[str, Any] | None = None) -> dict[str, Any]:
        data = data if isinstance(data, dict) else {}
        mode = normalize_match_mode(data.get("mode"))
        player_name = data.get("player_name", "匿名玩家")

        # The lobby name is only known at this moment for a guest, so write it
        # into the single presence table (same as the legacy handler).
        self.rooms.presence.update_identity(
            connection.sid,
            name=connection.username or player_name,
            user_id=connection.user_id,
        )

        if mode == MATCH_MODE_RANKED and not connection.user_id:
            return await self._deny(connection.sid, "排位模式需要先登录")

        capability = (
            suspicion.CAP_RANKED if mode == MATCH_MODE_RANKED else suspicion.CAP_MATCH
        )
        denied = self._capability_denied(connection.user_id, capability)
        if denied:
            return await self._deny(connection.sid, denied)

        if any(entry.get("sid") == connection.sid for entry in self.rooms.match_queue):
            return {"status": "error", "message": "你已经在匹配队列中"}

        self.rooms.match_queue.append({
            "sid": connection.sid,
            "name": (
                connection.username
                if connection.user_id and connection.username
                else player_name
            ),
            "user_id": connection.user_id,
            "registered": bool(connection.user_id),
            "mode": mode,
            "enqueued_at": time.time(),
            "ip": connection.ip,
        })
        await self._publisher.emit(
            "match_queued",
            {"status": "success", "message": "已加入匹配队列", "mode": mode},
            to=connection.sid,
        )

        matched = self._pair()
        await self._announce(matched)
        await self._broadcast_lobby()
        return {"status": "success", "message": "开始寻找匹配"}

    async def cancel_match(self, connection: Connection,
                           data: dict[str, Any] | None = None) -> dict[str, Any]:
        self.rooms.remove_from_match_queue(connection.sid)
        payload = {"status": "success", "message": "已取消匹配"}
        await self._publisher.emit("match_canceled", payload, to=connection.sid)
        await self._broadcast_lobby()
        return {"status": "success", "message": "已取消匹配"}

    # --------------------------------------------------------------- pairing

    def _pair(self) -> list[tuple[Room, dict, dict]]:
        """Pair as many rooms as possible, atomically.

        The critical section is synchronous on purpose: this service is only
        called from async socket handlers on one event loop, and a synchronous
        pass cannot interleave with another enqueue between the candidate scan
        and the two pops.
        """
        matched: list[tuple[Room, dict, dict]] = []
        while len(self.rooms.match_queue) >= 2:
            entries = list(self.rooms.match_queue)
            candidates = [self._candidate(entry) for entry in entries]
            # `assessed` is intentionally discarded: it is a preference,
            # not a settlement verdict (CLAUDE #33).
            index_a, index_b, _assessed = guard.pick_pair(candidates)
            if index_a is None:
                # No legal pair (different modes / same account / hard block):
                # leave the queue untouched and wait for a new arrival.
                break
            second = self.rooms.match_queue.pop(index_b)
            first = self.rooms.match_queue.pop(index_a)
            matched.append(self._create_room(first, second))
        return matched

    def _create_room(self, first: dict, second: dict) -> tuple[Room, dict, dict]:
        room = Room(id=new_room_id())
        room.ranked = first.get("mode") == MATCH_MODE_RANKED
        room.matchmade = True
        for entry in (first, second):
            seat_id = str(entry.get("sid") or "")
            room.players[seat_id] = Player(
                name=entry.get("name"),
                user_id=entry.get("user_id"),
                socket_id=seat_id,
                registered=bool(entry.get("registered")),
            )
        for seat_id in room.players:
            room.init_player_magic(seat_id)
        room.transition(RoomState.PLACING_SHIPS)
        self.rooms.rooms[room.id] = room
        return room, first, second

    async def _announce(self, matched: list[tuple[Room, dict, dict]]) -> None:
        for room, first, second in matched:
            for entry in (first, second):
                await self._publisher.enter_room(str(entry["sid"]), room.id)
            self._bind_presence_game(room)
            rank_fields = rank_payload(room)
            for me, opponent in ((first, second), (second, first)):
                await self._publisher.emit(
                    "game_state",
                    {
                        "state": RoomState.PLACING_SHIPS.value,
                        "room_id": room.id,
                        "player_id": me["sid"],
                        "player_seat": seat_label(room, str(me["sid"])),
                        "player_name": me.get("name"),
                        "opponent_name": opponent.get("name"),
                        # Ticket #51: additive per-seat wait state; each side
                        # sees its own opponent, so this cannot be a broadcast.
                        **opponent_seat_state(room, str(me["sid"])),
                        **rank_fields,
                    },
                    to=me["sid"],
                )
            # And the snapshot the placement screen already consumes, so the
            # wait starts with known ready/online values instead of "unknown".
            await self.rooms.push_room_sync(room)

    def _bind_presence_game(self, room: Room) -> None:
        for player in room.players.values():
            if player.user_id:
                self.rooms.presence.set_in_game(player.user_id, True)

    async def _broadcast_lobby(self) -> None:
        if self.lobby is None:
            return
        try:
            await self.lobby.broadcast()
        except Exception:  # noqa: BLE001 - a lobby frame must not fail a match
            logger.exception("lobby broadcast after matchmaking failed")

    # ---------------------------------------------------------------- gates

    def _capability_denied(self, user_id: str | None, capability: str) -> str:
        if not user_id or self.auth is None:
            return ""
        try:
            return self.auth.capability_denied(user_id, capability)
        except Exception as error:  # noqa: BLE001 - fail open, but leave a signal
            logger.error(
                "ban gate failed; allowing matchmaking",
                extra={"error_type": type(error).__name__},
                exc_info=error,
            )
            return ""

    async def _deny(self, sid: str, message: str) -> dict[str, Any]:
        await self._publisher.emit(
            "error",
            socket_errors.error_detail(socket_errors.OPERATION_FAILED, message),
            to=sid,
        )
        return {"status": "error", "message": message}