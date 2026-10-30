"""Friends, direct messages and friend invitations (ticket #14).

The legacy stack split this across api.py (HTTP), server.py (socket push) and
presence.py (online state). In the rewrite the route only parses the request and
this service owns every rule; the socket layer is not involved at all except
that the EventPublisher delivers pushes to every tab of the recipient.

Wire shapes are the frozen legacy ones (DECISIONS D19): no structured error
envelope on these routes, and some business rejections are deliberately HTTP 200
with a status/error body (blocked request, offline invite).

Level and rank label come from the progression modules that are still
placeholders; until they land this service projects the legacy defaults
(level 1, empty rank label), exactly like the lobby projection.
"""

from __future__ import annotations

import time
from typing import Any

from ..domain.social import messages as dm
from ..infra.logging import get_logger
from .presence import PresenceService
from .rooms import EventPublisher, NullPublisher, RoomService

logger = get_logger("friends")

MAX_FRIENDS = 50
FRIEND_REQUESTS_PER_HOUR = 10

MISSING_USERNAME = {"success": False, "error": "缺少 username 参数"}


def _int_or_zero(raw: Any) -> int:
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def payload_bool(raw: Any, default: bool = False) -> bool:
    """Normalise true/1/"true"/"1" (form bodies are strings)."""
    if raw is None:
        return default
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off", ""):
            return False
        return default
    return bool(raw)


class FriendsService:
    def __init__(
        self,
        database: Any,
        presence: PresenceService,
        rooms: RoomService,
        publisher: EventPublisher | None = None,
    ) -> None:
        self._database = database
        self._presence = presence
        self._rooms = rooms
        self._publisher: EventPublisher = publisher or NullPublisher()

    def bind(self, publisher: EventPublisher) -> None:
        self._publisher = publisher

    # ---------------------------------------------------------------- pushing

    async def push(self, user_id: str, event: str, payload: dict[str, Any]) -> bool:
        """Deliver one event to every online tab; False when nobody received it."""
        if not user_id or not self._presence.is_online(user_id):
            return False
        delivered = False
        for sid in self._presence.sids_of(user_id):
            try:
                await self._publisher.emit(event, payload, to=sid)
                delivered = True
            except Exception:  # noqa: BLE001 - one dead tab must not stop the rest
                logger.exception("friend push failed", extra={"socket_id": sid})
        return delivered

    # ------------------------------------------------------ settlement hook

    def recent_opponent_hook(self, room: Any, uow: Any, context: Any) -> None:
        """Append the legacy recent_opponent frames for a finished match.

        Legacy sends one private frame to each seat before game_over, and only
        when both seats really are accounts (AI / guest seats have no user row).
        Registering this as a settlement hook keeps every ending path on one
        funnel, exactly like the legacy _finalize_match hook.
        """

        facts = context.facts
        winner_uid = facts.winner_user_id
        loser_uid = facts.loser_user_id
        if not winner_uid or not loser_uid:
            return
        winner_row = uow.users.get(winner_uid)
        loser_row = uow.users.get(loser_uid)
        if winner_row is None or loser_row is None:
            return
        for me_uid, other_uid, me_seat, other_seat in (
            (str(winner_uid), str(loser_uid), facts.winner_id, facts.loser_id),
            (str(loser_uid), str(winner_uid), facts.loser_id, facts.winner_id),
        ):
            me = room.players.get(me_seat)
            player = room.players.get(other_seat)
            if me is None or player is None:
                continue
            # Frame goes to *my* seat; the payload describes my opponent.
            target = getattr(me, "socket_id", None)
            if not target:
                continue
            context.events.append(
                {
                    "phase": "before",
                    "event": "recent_opponent",
                    "to": target,
                    "data": {
                        "user_id": other_uid,
                        "username": str(
                            getattr(player, "name", "")
                            or getattr(other_row, "username", "")
                            or other_uid
                        ),
                        "avatar": str(getattr(player, "avatar", "") or ""),
                        "relation": uow.social.get_friend_relation(me_uid, other_uid),
                    },
                }
            )

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _username(raw: Any) -> str:
        return str(raw or "").strip()

    def _target(self, uow, raw: Any):
        """Resolve a username to (user, error). Mirrors legacy _target_user."""
        username = self._username(raw)
        if not username:
            return None, (400, MISSING_USERNAME)
        user = uow.users.get_by_username(username)
        if user is None:
            return None, (404, {"success": False, "error": f"账号不存在：{username}"})
        return user, None

    @staticmethod
    def _identity(user) -> dict[str, str]:
        return {
            "username": str(getattr(user, "username", "") or ""),
            "avatar": str(getattr(user, "avatar", "") or ""),
        }

    @staticmethod
    def _public_message(row: dict[str, Any], me_uid: str) -> dict[str, Any]:
        return {
            "id": _int_or_zero(row.get("id")),
            "from_uid": str(row.get("from_uid") or ""),
            "to_uid": str(row.get("to_uid") or ""),
            "body": str(row.get("body") or ""),
            "created_at": _int_or_zero(row.get("created_at")),
            "stamp": dm.stamp(row.get("created_at")),
            "mine": str(row.get("from_uid") or "") == str(me_uid or ""),
        }

    # ------------------------------------------------------------ friend list

    async def list_friends(self, user_id: str) -> tuple[int, dict[str, Any]]:
        with self._database.unit_of_work() as uow:
            friend_rows = uow.social.friends_of(user_id)
            incoming_rows = uow.social.incoming_requests(user_id)
            outgoing_rows = uow.social.outgoing_requests(user_id)
            ids = [row["user_id"] for row in friend_rows + incoming_rows + outgoing_rows]
            users = uow.users.list_by_ids(ids)
            unread_map = uow.social.unread_by_friend(user_id)
            unread_total = uow.social.count_unread_messages(user_id)

        friends = []
        for row in friend_rows:
            other = str(row.get("user_id") or "")
            if not other:
                continue
            user = users.get(other)
            info = self._identity(user) if user is not None else {"username": "", "avatar": ""}
            friends.append(
                {
                    "user_id": other,
                    "username": info["username"],
                    "avatar": info["avatar"],
                    "level": 1,
                    "rank_label": "",
                    "online": self._presence.is_online(other),
                    "in_game": self._presence.is_online(other)
                    and self._presence.is_in_game(other),
                    "unread": _int_or_zero(unread_map.get(other)),
                }
            )
        # Online first, then players free to play (not in a game), then name.
        friends.sort(
            key=lambda row: (
                not row["online"],
                row["in_game"],
                (row["username"] or "").lower(),
                row["user_id"],
            )
        )

        def brief(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            out = []
            for row in rows:
                other = str(row.get("user_id") or "")
                if not other:
                    continue
                user = users.get(other)
                info = (
                    self._identity(user) if user is not None
                    else {"username": "", "avatar": ""}
                )
                out.append(
                    {
                        "user_id": other,
                        "username": info["username"],
                        "avatar": info["avatar"],
                        "created_at": _int_or_zero(row.get("created_at")),
                    }
                )
            return out

        return 200, {
            "friends": friends,
            "incoming": brief(incoming_rows),
            "outgoing": brief(outgoing_rows),
            "limits": {
                "max_friends": MAX_FRIENDS,
                "requests_per_hour": FRIEND_REQUESTS_PER_HOUR,
            },
            "counts": {
                "friends": len(friends),
                "incoming": len(incoming_rows),
                "unread_total": _int_or_zero(unread_total),
            },
        }

    # -------------------------------------------------------------- requests

    async def request(self, user_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        now = int(time.time())
        with self._database.unit_of_work() as uow:
            target, error = self._target(uow, payload.get("username"))
            if error:
                return error
            assert target is not None
            if str(target.id) == str(user_id):
                return 400, {"status": "self"}
            profile = uow.social.get_profile(str(target.id)) or {}
            raw_open = profile.get("friend_requests_open")
            if int(1 if raw_open is None else raw_open) == 0:
                return 403, {"status": "error", "error": "对方暂时不接受好友申请"}
            if uow.social.count_friends(user_id) >= MAX_FRIENDS:
                return 400, {"error": "好友数量已达上限"}
            if uow.social.count_requests_since(user_id, now - 3600) >= FRIEND_REQUESTS_PER_HOUR:
                return 429, {"error": "申请太频繁，请稍后再试"}
            status = uow.social.send_friend_request(user_id, str(target.id), now=now)
            me = uow.users.get(user_id)
            identity = self._identity(me) if me is not None else {"username": "", "avatar": ""}
            target_id = str(target.id)

        if status == "sent":
            await self.push(
                target_id,
                "friend_request",
                {
                    "from_user_id": str(user_id),
                    "from_username": identity["username"],
                    "from_avatar": identity["avatar"],
                },
            )
        if status == "blocked":
            # Deliberately HTTP 200: the client reads body.status/error, and the
            # direction of the block is never disclosed.
            return 200, {
                "status": "blocked",
                "error": "暂时无法向该玩家发送好友申请",
            }
        return 200, {"status": status}

    async def respond(self, user_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        now = int(time.time())
        with self._database.unit_of_work() as uow:
            target, error = self._target(uow, payload.get("username"))
            if error:
                return error
            assert target is not None
            other = str(target.id)
            if payload_bool(payload.get("accept"), default=False):
                if not uow.social.accept_friend_request(user_id, other, now=now):
                    return 200, {"status": "error"}
                me = uow.users.get(user_id)
                identity = self._identity(me) if me is not None else {
                    "username": "", "avatar": ""
                }
                accepted = True
            else:
                if not uow.social.remove_friend_request(user_id, other):
                    return 200, {"status": "error"}
                accepted = False
                identity = {"username": "", "avatar": ""}

        if accepted:
            await self.push(
                other,
                "friend_accepted",
                {
                    "user_id": str(user_id),
                    "username": identity["username"],
                    "avatar": identity["avatar"],
                },
            )
            return 200, {"status": "accepted"}
        return 200, {"status": "declined"}

    async def remove(self, user_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        with self._database.unit_of_work() as uow:
            target, error = self._target(uow, payload.get("username"))
            if error:
                return error
            assert target is not None
            if str(target.id) == str(user_id):
                return 400, {"status": "error", "error": "不能删除自己"}
            if not uow.social.remove_friend(user_id, str(target.id)):
                return 200, {"status": "error"}
        return 200, {"status": "ok"}

    async def block(self, user_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        now = int(time.time())
        with self._database.unit_of_work() as uow:
            target, error = self._target(uow, payload.get("username"))
            if error:
                return error
            assert target is not None
            if str(target.id) == str(user_id):
                return 400, {"status": "error", "error": "不能拉黑自己"}
            if not uow.social.block_user(user_id, str(target.id), now=now):
                return 200, {"status": "error"}
        return 200, {"status": "ok"}

    # ---------------------------------------------------------------- invite

    async def invite(self, user_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        with self._database.unit_of_work() as uow:
            target, error = self._target(uow, payload.get("username"))
            if error:
                return error
            assert target is not None
            other = str(target.id)
            me = uow.users.get(user_id)
            identity = self._identity(me) if me is not None else {"username": "", "avatar": ""}
        if other == str(user_id):
            return 400, {"status": "error", "error": "不能邀请自己"}
        # The inviter also enters the new room (the client calls join_room after
        # the invite succeeds), so an account already in a game is refused here.
        if self._presence.is_in_game(user_id):
            return 409, {"status": "error", "error": "你正在对局中，结束这局再邀战"}
        # Check online before creating the room; otherwise offline friends leave
        # a zombie waiting room behind.
        if not self._presence.is_online(other):
            return 200, {"status": "error", "error": "对方不在线"}
        room_id = self._rooms.create_invite_room()
        if not room_id:
            return 200, {"status": "error", "error": "建房失败，请稍后再试"}
        delivered = await self.push(
            other,
            "friend_invite",
            {
                "room_id": room_id,
                "from_user_id": str(user_id),
                "from_username": identity["username"],
            },
        )
        if not delivered:
            return 200, {"status": "error", "error": "推送失败，请稍后再试"}
        return 200, {"status": "ok", "room_id": room_id}

    # -------------------------------------------------------- direct messages

    def _dm_target(self, uow, raw: Any):
        target, error = self._target(uow, raw)
        if error:
            return None, error
        assert target is not None
        return target, None

    async def list_messages(
        self, user_id: str, username: Any, limit: Any, before: Any
    ) -> tuple[int, dict[str, Any]]:
        try:
            page = int(limit or dm.PAGE_SIZE)
        except (TypeError, ValueError):
            page = dm.PAGE_SIZE
        page = max(1, min(page, dm.MAX_PAGE_SIZE))
        try:
            before_id = int(before) if before not in (None, "") else None
        except (TypeError, ValueError):
            # A bad cursor means "newest page", never a 400.
            before_id = None

        with self._database.unit_of_work() as uow:
            target, error = self._dm_target(uow, username)
            if error:
                return error
            assert target is not None
            other = str(target.id)
            if other == str(user_id):
                return 400, {"status": "error", "error": "不能和自己私聊"}
            if uow.social.get_friend_relation(user_id, other) != "friends":
                return 403, {"status": "error", "error": "你们还不是好友，无法私聊"}
            rows = uow.social.list_friend_messages(user_id, other, limit=page, before_id=before_id)
            oldest = _int_or_zero(rows[0].get("id")) if rows else 0
            has_more = bool(oldest) and uow.social.has_more_friend_messages(
                user_id, other, oldest
            )

        messages = [self._public_message(row, user_id) for row in rows]
        return 200, {"status": "ok", "has_more": has_more, "messages": messages}

    async def send_message(self, user_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        now = int(time.time())
        with self._database.unit_of_work() as uow:
            target, error = self._dm_target(uow, payload.get("username"))
            if error:
                return error
            assert target is not None
            other = str(target.id)
            if other == str(user_id):
                return 400, {"status": "error", "error": "不能和自己私聊"}
            if uow.social.get_friend_relation(user_id, other) != "friends":
                return 403, {"status": "error", "error": "你们还不是好友，无法私聊"}
            # Normalise first: '  \n ' must become "empty", not pass the length
            # check and then land in the database as a blank line.
            body = dm.normalize_body(payload.get("body"))
            reason = dm.body_error(body)
            if reason:
                return 400, {"status": "error", "error": reason}
            if uow.social.count_friend_messages_since(
                user_id, now - dm.RATE_WINDOW_SECONDS
            ) >= dm.PER_MINUTE:
                return 429, {
                    "status": "error",
                    "error": f"发得太频繁了，每分钟最多 {dm.PER_MINUTE} 条",
                }
            message_id = uow.social.add_friend_message(user_id, other, body, created_at=now)
            row = uow.social.get_friend_message(message_id)
            me = uow.users.get(user_id)
            identity = self._identity(me) if me is not None else {
                "username": "", "avatar": ""
            }
            if row is None:
                return 500, {"status": "error", "error": "发送失败，请稍后重试"}

        message = self._public_message(row, user_id)
        pushed = dict(message, from_username=identity["username"], from_avatar=identity["avatar"])
        # Delivery failure does not fail the request: the row is committed and
        # the recipient pulls it when they open the conversation.
        await self.push(other, "friend_message", dm.push_payload(pushed))
        return 200, {"status": "ok", "message": message}

    async def mark_read(self, user_id: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        now = int(time.time())
        with self._database.unit_of_work() as uow:
            target, error = self._dm_target(uow, payload.get("username"))
            if error:
                return error
            assert target is not None
            other = str(target.id)
            if other == str(user_id):
                return 400, {"status": "error", "error": "不能和自己私聊"}
            if uow.social.get_friend_relation(user_id, other) != "friends":
                return 403, {"status": "error", "error": "你们还不是好友，无法私聊"}
            marked = uow.social.mark_friend_messages_read(
                to_uid=user_id, from_uid=other, read_at=now
            )
        return 200, {"status": "ok", "read": _int_or_zero(marked)}
