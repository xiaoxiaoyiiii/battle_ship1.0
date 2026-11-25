"""自定义对局的单次再战邀请，独立于旧房间的存活期。"""
from __future__ import annotations

import asyncio
import secrets
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable

from ..domain import mutations
from ..domain.anticheat import suspicion
from ..domain.mystery_tech.draft import enforce_mode
from ..domain.room import Player, Room, RoomState, build_room_sync, new_room_id
from .rooms import Connection, RoomService

INVITE_SECONDS = 60
OPEN_STATES = frozenset({'available', 'pending'})


@dataclass(eq=False, slots=True)
class RematchSeat:
    player_id: str
    account_id: str | None
    sid: str | None
    name: str
    commander_id: str
    commander_level: int
    cosmetics: dict[str, Any]
    token: str
    reconnect_proof: str | None
    previous_guest_sids: set[str] = field(default_factory=set)

    def matches(self, connection: Connection, proof: Any = None) -> bool:
        if self.account_id:
            return connection.user_id == self.account_id
        if connection.user_id:
            return False
        if self.sid == connection.sid:
            return True
        return isinstance(proof, str) and 16 <= len(proof) <= 128 and any(
            token and secrets.compare_digest(token.encode(), proof.encode(errors='replace'))
            for token in (self.token, self.reconnect_proof)
        )

    def matches_activity(self, sid: str | None, account_id: str | None) -> bool:
        if self.account_id:
            return self.account_id == account_id
        return sid is not None and (sid == self.sid or sid in self.previous_guest_sids)


@dataclass(slots=True)
class Rematch:
    room_id: str
    name: str
    public: bool
    mystery_tech: bool
    mutation_ids: tuple[str, ...]
    ban_enabled: bool
    ban_quota: int
    seats: tuple[RematchSeat, RematchSeat]
    changed_at: float
    status: str = 'available'
    sender: RematchSeat | None = None
    expires_at: int | None = None
    new_room_id: str | None = None
    new_player_ids: tuple[str, str] | None = None


class CustomRematchService:
    def __init__(self, rooms: RoomService, *, clock: Callable[[], float] = time.time) -> None:
        self.rooms = rooms
        self.clock = clock
        self._records: dict[str, Rematch] = {}

    async def publish_finished(self, room: Room) -> None:
        """只在原局结算与最后一次同步完成后提供入口。"""
        if (
            room.state != RoomState.GAME_OVER or not room.settled or len(room.players) != 2
            or room.is_ai_room or room.matchmade or room.ranked or room.daily_challenge
            or room.id in self._records
        ):
            return
        self._prune()
        seats = tuple(
            RematchSeat(
                player_id=pid, account_id=player.user_id if player.registered else None,
                sid=player.socket_id, name=player.name or '玩家',
                commander_id=player.commander_id, commander_level=player.commander_level,
                cosmetics=deepcopy(player.commander_cosmetics),
                token=secrets.token_urlsafe(32), reconnect_proof=room.reconnect_tokens.get(pid),
            )
            for pid, player in room.players.items()
        )
        record = Rematch(
            room_id=room.id, name=room.name, public=room.public, mystery_tech=room.mystery_tech,
            mutation_ids=tuple(room.mutation_ids), ban_enabled=room.ban_enabled,
            ban_quota=room.ban_quota, seats=(seats[0], seats[1]), changed_at=self.clock(),
        )
        self._records[room.id] = record
        if self._busy(record):
            self._transition(record, 'unavailable')
        await self._send_state(record)

    async def sync(self, connection: Connection, data: dict[str, Any] | None = None) -> dict:
        found = self._identify(connection, data, accept_latest=True)
        if found is None:
            return {'status': 'success', 'rematch': None}
        record, seat, changed_connection = found
        if self._refresh(record) or changed_connection:
            await self._send_state(record)
        if record.status == 'started':
            await self._restore_started(record, seat, connection)
        return self._ack(record, seat)

    async def invite(self, connection: Connection, data: dict[str, Any] | None) -> dict:
        found = self._identify(connection, data)
        if found is None:
            return self._error('只有上局玩家可以发起再战')
        record, seat, _ = found
        seat.sid = connection.sid
        if self._refresh(record):
            await self._send_state(record)
        if record.status == 'started':
            return self._ack(record, seat)
        if record.status == 'pending':
            if record.sender is seat:
                return self._ack(record, seat)
            return await self._accept(record, seat)
        if record.status != 'available':
            return self._error('这局的再战机会已结束', record, seat)
        if not all(self._online_sid(item) for item in record.seats):
            return self._error('等双方重新在线后再邀请', record, seat)
        record.sender = seat
        record.status = 'pending'
        record.expires_at = int(self.clock() * 1000) + INVITE_SECONDS * 1000
        self.rooms._spawn(self._wait_until_expired(record))
        await self._send_state(record)
        return self._ack(record, seat)

    async def reply(self, connection: Connection, data: dict[str, Any] | None) -> dict:
        found = self._identify(connection, data)
        if found is None:
            return self._error('再战邀请不存在')
        record, seat, _ = found
        action = (data or {}).get('action')
        seat.sid = connection.sid
        if self._refresh(record):
            await self._send_state(record)
        if record.status == 'started' and action == 'accept':
            return self._ack(record, seat)
        if record.status != 'pending':
            return self._error('再战邀请已结束', record, seat)
        if seat is record.sender and action == 'cancel':
            self._transition(record, 'canceled')
        elif seat is not record.sender and action == 'decline':
            self._transition(record, 'declined')
        elif seat is not record.sender and action == 'accept':
            return await self._accept(record, seat)
        else:
            return self._error('这个操作不适用于当前邀请', record, seat)
        await self._send_state(record)
        return self._ack(record, seat)

    def on_seating(self, connection: Connection) -> None:
        """挂在现有占座/入队的同步临界区，离开新活动也不会恢复邀请。"""
        for record in self._records.values():
            if record.status in OPEN_STATES and any(
                seat.matches_activity(connection.sid, connection.user_id) for seat in record.seats
            ):
                if not self._expire(record):
                    self._transition(record, 'unavailable')
                self.rooms._spawn(self._send_state(record))

    def on_disconnect(self, sid: str) -> None:
        for record in self._records.values():
            for seat in record.seats:
                seat.previous_guest_sids.discard(sid)
            if record.status in OPEN_STATES and any(seat.sid == sid for seat in record.seats):
                self.rooms._spawn(self._send_state(record))

    def _identify(
        self, connection: Connection, data: dict[str, Any] | None, *, accept_latest: bool = False,
    ) -> tuple[Rematch, RematchSeat, bool] | None:
        self._prune()
        data = data if isinstance(data, dict) else {}
        room_id = data.get('room_id')
        if room_id is None and accept_latest:
            records = reversed(self._records.values())
        elif isinstance(room_id, str) and room_id in self._records:
            records = (self._records[room_id],)
        else:
            return None
        for record in records:
            for seat in record.seats:
                if seat.matches(connection, data.get('token')):
                    previous = seat.sid
                    bound = self.rooms.presence.get(previous) if previous else None
                    if previous != connection.sid and (not seat.account_id or not bound):
                        if not seat.account_id and bound:
                            # 刷新前后连接可能同时在线，旧连接的活动仍会影响这次邀请。
                            seat.previous_guest_sids.add(bound.sid)
                        seat.previous_guest_sids.discard(connection.sid)
                        seat.sid = connection.sid
                    return record, seat, previous != seat.sid
        return None

    def _online_sid(self, seat: RematchSeat) -> str | None:
        online = self.rooms.presence.get(seat.sid) if seat.sid else None
        if online and online.user_id == seat.account_id:
            return online.sid
        if seat.account_id:
            return next(iter(self.rooms.presence.sids_of(seat.account_id)), None)
        return None

    def _busy(self, record: Rematch, *, keep_room_id: str | None = None) -> bool:
        def matches(sid: str | None, uid: str | None) -> bool:
            return any(seat.matches_activity(sid, uid) for seat in record.seats)
        if any(matches(entry.get('sid'), entry.get('user_id')) for entry in self.rooms.match_queue):
            return True
        return any(
            any(matches(player.socket_id, player.user_id if player.registered else None)
                for player in room.players.values())
            for room in self.rooms.rooms.values()
            if room.state != RoomState.GAME_OVER and room.id != keep_room_id
        )

    def _transition(self, record: Rematch, status: str) -> None:
        record.status = status
        record.changed_at = self.clock()

    def _expire(self, record: Rematch) -> bool:
        if record.status == 'pending' and self.clock() * 1000 >= record.expires_at:
            self._transition(record, 'expired')
            return True
        return False

    def _refresh(self, record: Rematch) -> bool:
        if self._expire(record):
            return True
        if record.status in OPEN_STATES and self._busy(record):
            self._transition(record, 'unavailable')
            return True
        return False

    async def _wait_until_expired(self, record: Rematch) -> None:
        while record.status == 'pending':
            await asyncio.sleep(max(0.0, record.expires_at / 1000 - self.clock()))
            if self._expire(record):
                await self._send_state(record)

    def _prune(self) -> None:
        cutoff = self.clock() - max(INVITE_SECONDS, self.rooms.ended_room_retention_seconds)
        for room_id, record in list(self._records.items()):
            self._expire(record)
            if record.changed_at > cutoff or record.status == 'pending':
                continue
            if record.status == 'available' and (
                self.rooms.get_room(room_id) is not None
                or any(self._online_sid(seat) for seat in record.seats)
            ):
                continue
            del self._records[room_id]

    def _state(self, record: Rematch, seat: RematchSeat) -> dict:
        opponent = next(item for item in record.seats if item is not seat)
        online = bool(self._online_sid(seat) and self._online_sid(opponent))
        role = None if record.sender is None else 'sender' if record.sender is seat else 'recipient'
        return {
            'room_id': record.room_id, 'token': seat.token, 'opponent_name': opponent.name,
            'status': record.status, 'role': role,
            'expires_at': record.expires_at if record.status == 'pending' else None,
            'server_now': int(self.clock() * 1000),
            'can_invite': record.status == 'available' and online,
            'can_accept': record.status == 'pending' and role == 'recipient' and online,
        }

    async def _send_state(self, record: Rematch) -> None:
        for seat in record.seats:
            sid = self._online_sid(seat)
            if sid:
                await self.rooms._publisher.emit('custom_rematch_state', self._state(record, seat), to=sid)

    def _ack(self, record: Rematch, seat: RematchSeat) -> dict:
        return {'status': 'success', 'rematch': self._state(record, seat)}

    def _error(self, message: str, record: Rematch | None = None, seat: RematchSeat | None = None) -> dict:
        result = {'status': 'error', 'message': message}
        if record is not None and seat is not None:
            result['rematch'] = self._state(record, seat)
        return result

    async def _accept(self, record: Rematch, seat: RematchSeat) -> dict:
        """从复查到预留两个新席位之间不等待 I/O，防止与入房和同时邀请交错。"""
        if self._refresh(record):
            await self._send_state(record)
        if record.status != 'pending':
            return self._error('再战邀请已结束', record, seat)
        connections: list[Connection] = []
        for item in record.seats:
            sid = self._online_sid(item)
            if not sid:
                return self._error('等双方重新在线后再开始', record, seat)
            item.sid = sid
            connection = Connection(sid, item.account_id, item.name)
            denied = self.rooms._capability_denied(connection, suspicion.CAP_ROOM)
            if denied:
                self._transition(record, 'unavailable')
                await self._send_state(record)
                return self._error(denied, record, seat)
            connections.append(connection)
        if self._busy(record) or connections[0].sid == connections[1].sid:
            self._transition(record, 'unavailable')
            await self._send_state(record)
            return self._error('有玩家已进入其他活动，这次再战已结束', record, seat)

        room = self._new_room(record, connections)
        old = self.rooms.get_room(record.room_id)
        old_sids = {connection.sid for connection in connections}
        if old is not None:
            for player in old.players.values():
                if player.socket_id:
                    old_sids.add(player.socket_id)
                player.socket_id = None
        record.new_room_id = room.id
        new_ids = tuple(room.players)
        record.new_player_ids = (new_ids[0], new_ids[1])
        self._transition(record, 'started')
        self.rooms.rooms[room.id] = room
        self.rooms._bind_presence_game(room)
        for connection in connections:
            self.on_seating(connection)

        for sid in old_sids:
            if self.rooms.presence.get(sid):
                await self.rooms._publisher.leave_room(sid, record.room_id)
        for pid, player in room.players.items():
            sid = player.socket_id
            # 连接可能在前一帧 I/O 时已更换，恢复流程会为新连接重发。
            if sid and self.rooms.presence.get(sid):
                await self.rooms._publisher.enter_room(sid, room.id)
                if player.socket_id == sid:
                    await self._send_started(record, room, pid, sid)
        await self._send_state(record)
        return self._ack(record, seat)

    def _new_room(self, record: Rematch, connections: list[Connection]) -> Room:
        room_id = new_room_id()
        while room_id in self.rooms.rooms or room_id in self._records:
            room_id = new_room_id()
        room = Room(id=room_id, name=record.name, public=record.public, mystery_tech=record.mystery_tech,
                    ban_enabled=record.ban_enabled, ban_quota=record.ban_quota)
        if not room.public:
            room.invite_token = secrets.token_urlsafe(32)
        if room.mystery_tech:
            enforce_mode(room)
        else:
            mutations.configure_room(room, 'custom', ids=list(record.mutation_ids),
                                     rng=self.rooms.mutation_rng, now=self.rooms.mutation_clock())
        for seat, connection in zip(record.seats, connections, strict=True):
            pid = connection.user_id or connection.sid
            room.players[pid] = Player(
                name=seat.name, user_id=pid, socket_id=connection.sid, registered=bool(connection.user_id),
                commander_id=seat.commander_id, commander_level=seat.commander_level,
                commander_cosmetics=deepcopy(seat.cosmetics),
            )
            room.issue_reconnect_token(pid)
        self.rooms.prepare_full_room(room)
        return room

    async def _restore_started(self, record: Rematch, seat: RematchSeat, connection: Connection) -> None:
        room = self.rooms.get_room(record.new_room_id)
        if room is None or room.state == RoomState.GAME_OVER or record.new_player_ids is None:
            return
        pid = record.new_player_ids[record.seats.index(seat)]
        player = room.players[pid]
        if player.socket_id != connection.sid:
            if (player.socket_id and self.rooms.presence.get(player.socket_id)
                    or self._busy(record, keep_room_id=room.id)):
                return
            rebound = await self.rooms.rejoin_room(connection, {
                'room_id': room.id, 'player_id': pid, 'token': room.reconnect_tokens[pid],
            })
            if rebound.get('status') != 'success':
                return
        if player.socket_id == connection.sid and room.state != RoomState.GAME_OVER:
            await self._send_started(record, room, pid, connection.sid)

    async def _send_started(self, record: Rematch, room: Room, pid: str, sid: str) -> None:
        await self.rooms._publisher.emit('custom_rematch_started', {
            'source_room_id': record.room_id, 'room_id': room.id,
            'reconnect_token': room.reconnect_tokens[pid],
            'game': build_room_sync(room, pid, turn_timeout_seconds=self.rooms.turn_timeout_seconds),
        }, to=sid)
