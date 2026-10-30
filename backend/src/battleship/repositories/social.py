"""user_profile, likes, wall messages, friendships and friend messages."""

from __future__ import annotations

import time
from typing import Any, Mapping

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .mapping import instance_dict
from .models import (
    FriendMessage,
    ProfileLike,
    ProfileMessage,
    UserFriend,
    UserProfile,
)

PROFILE_COLUMNS = frozenset(
    {
        "title_id",
        "tags",
        "status_text",
        "avatar_alt",
        "frame_id",
        "card_bg_id",
        "profile_bg_id",
        "pointer_effect_id",
        "title_effect_id",
        "show_stats",
        "show_fav_cards",
        "show_history",
        "updated_at",
        "show_guestbook",
        "show_rank",
        "friend_requests_open",
        "allow_spectate",
        "allow_replay",
    }
)


class ProfileUpdateError(ValueError):
    """The caller tried to write a column that is not part of user_profile."""


class SocialRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ---------------------------------------------------------------- profile

    def get_profile(self, user_id: str | None) -> dict[str, Any] | None:
        if not user_id:
            return None
        profile = self.session.get(UserProfile, user_id)
        return instance_dict(profile) if profile is not None else None

    def save_profile(
        self,
        user_id: str,
        fields: Mapping[str, Any] | None = None,
        *,
        updated_at: int | None = None,
    ) -> dict[str, Any]:
        """Partial upsert. Unspecified columns keep their old value / DB default."""
        values = dict(fields or {})
        unknown = set(values) - PROFILE_COLUMNS
        if unknown:
            raise ProfileUpdateError(f"unknown user_profile columns: {sorted(unknown)}")
        if updated_at is not None:
            values["updated_at"] = updated_at

        statement = sqlite_insert(UserProfile).values(user_id=user_id, **values)
        if values:
            statement = statement.on_conflict_do_update(
                index_elements=["user_id"], set_=values
            )
        else:
            statement = statement.on_conflict_do_nothing(index_elements=["user_id"])
        self.session.execute(statement)
        self.session.flush()
        profile = self.get_profile(user_id)
        assert profile is not None  # the statement above guarantees the row
        return profile

    def get_allow_spectate(self, user_id: str | None) -> bool | None:
        """Read the "let others watch my games" switch: True / False / None.

        Legacy semantics: a missing profile row means the default (allowed); an
        empty id or an unreadable row means unknown (None), which callers must
        treat as "not allowed". Unknown is never rewritten to allowed.
        """

        if not user_id:
            return None
        profile = self.get_profile(str(user_id))
        if profile is None:
            return True
        flag = profile.get("allow_spectate")
        if flag is None:
            return True
        return bool(int(flag))

    def set_allow_spectate(self, user_id: str | None, allow: bool) -> bool:
        """Write ONLY the allow_spectate column (never the whole profile row)."""

        if not user_id:
            return False
        self.save_profile(
            str(user_id),
            {"allow_spectate": 1 if allow else 0, "updated_at": int(time.time())},
        )
        return True

    # ------------------------------------------------------------------ likes

    def add_reaction(
        self, from_user_id: str, to_user_id: str, kind: str, *, created_at: int
    ) -> bool:
        statement = sqlite_insert(ProfileLike).values(
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            kind=kind,
            created_at=created_at,
        )
        statement = statement.on_conflict_do_nothing(
            index_elements=["from_user_id", "to_user_id", "kind"]
        )
        result = self.session.execute(statement)
        return bool(result.rowcount)

    def remove_reaction(self, from_user_id: str, to_user_id: str, kind: str) -> bool:
        result = self.session.execute(
            delete(ProfileLike).where(
                ProfileLike.from_user_id == from_user_id,
                ProfileLike.to_user_id == to_user_id,
                ProfileLike.kind == kind,
            )
        )
        return bool(result.rowcount)

    def reaction_counts(self, to_user_id: str) -> dict[str, int]:
        statement = (
            select(ProfileLike.kind, func.count())
            .where(ProfileLike.to_user_id == to_user_id)
            .group_by(ProfileLike.kind)
        )
        return {kind: int(count) for kind, count in self.session.execute(statement)}

    # ---------------------------------------------------------- wall messages

    def add_wall_message(
        self,
        *,
        to_user_id: str,
        from_user_id: str,
        from_name: str,
        content: str,
        created_at: int,
    ) -> int:
        message = ProfileMessage(
            to_user_id=to_user_id,
            from_user_id=from_user_id,
            from_name=from_name,
            content=content,
            created_at=created_at,
            deleted=0,
        )
        self.session.add(message)
        self.session.flush()
        return int(message.id)

    def list_wall_messages(
        self, to_user_id: str, *, limit: int = 20, before_id: int | None = None
    ) -> list[dict[str, Any]]:
        safe_limit = min(max(1, int(limit)), 100)
        statement = (
            select(
                ProfileMessage.id,
                ProfileMessage.to_user_id,
                ProfileMessage.from_user_id,
                ProfileMessage.from_name,
                ProfileMessage.content,
                ProfileMessage.created_at,
            )
            .where(
                ProfileMessage.to_user_id == to_user_id,
                ProfileMessage.deleted == 0,
            )
            .order_by(ProfileMessage.id.desc())
            .limit(safe_limit)
        )
        if before_id is not None:
            statement = statement.where(ProfileMessage.id < int(before_id))
        return [dict(row._mapping) for row in self.session.execute(statement)]

    def soft_delete_wall_message(self, message_id: int, to_user_id: str) -> bool:
        result = self.session.execute(
            update(ProfileMessage)
            .where(
                ProfileMessage.id == message_id,
                ProfileMessage.to_user_id == to_user_id,
                ProfileMessage.deleted == 0,
            )
            .values(deleted=1)
        )
        return bool(result.rowcount)

    def my_reactions(self, from_user_id: str, to_user_id: str) -> dict[str, bool]:
        """Which of the two reactions the viewer already sent (button state)."""
        mine = {"like": False, "flower": False}
        if not from_user_id or not to_user_id:
            return mine
        statement = select(ProfileLike.kind).where(
            ProfileLike.from_user_id == from_user_id,
            ProfileLike.to_user_id == to_user_id,
        )
        for kind in self.session.scalars(statement):
            if kind in mine:
                mine[kind] = True
        return mine

    def get_wall_message(self, message_id: Any) -> dict[str, Any] | None:
        """One message including the internal owner/deleted columns.

        Deletion permission needs the owner id and the soft-delete flag, but the
        route strips both before answering (legacy behaviour: deleting twice is
        idempotent, not a 404).
        """
        try:
            mid = int(message_id)
        except (TypeError, ValueError):
            return None
        message = self.session.get(ProfileMessage, mid)
        if message is None:
            return None
        return {
            "id": int(message.id),
            "to_user_id": str(message.to_user_id or ""),
            "from_user_id": str(message.from_user_id or ""),
            "from_name": str(message.from_name or ""),
            "content": str(message.content or ""),
            "created_at": int(message.created_at or 0),
            "deleted": int(message.deleted or 0),
        }

    def wall_message_page(self, to_user_id: str, *, limit: int = 20,
                          before_id: int | None = None) -> dict[str, Any]:
        """One cursor page + total, excluding soft-deleted rows."""
        safe_limit = max(1, min(int(limit), 50))
        base_filters = (
            ProfileMessage.to_user_id == to_user_id,
            ProfileMessage.deleted == 0,
        )
        total = int(
            self.session.scalar(
                select(func.count()).select_from(ProfileMessage).where(*base_filters)
            )
            or 0
        )
        statement = (
            select(
                ProfileMessage.id,
                ProfileMessage.to_user_id,
                ProfileMessage.from_user_id,
                ProfileMessage.from_name,
                ProfileMessage.content,
                ProfileMessage.created_at,
            )
            .where(*base_filters)
            .order_by(ProfileMessage.id.desc())
            .limit(safe_limit + 1)
        )
        if before_id is not None:
            statement = statement.where(ProfileMessage.id < int(before_id))
        rows = [dict(row._mapping) for row in self.session.execute(statement)]
        has_more = len(rows) > safe_limit
        return {"messages": rows[:safe_limit], "has_more": has_more, "total": total}

    def count_wall_messages_since(self, from_user_id: str, to_user_id: str,
                                  since: int) -> int:
        """Daily per-author quota input; soft-deleted rows still count."""
        if not from_user_id or not to_user_id:
            return 0
        statement = (
            select(func.count())
            .select_from(ProfileMessage)
            .where(
                ProfileMessage.from_user_id == from_user_id,
                ProfileMessage.to_user_id == to_user_id,
                ProfileMessage.created_at >= int(since),
            )
        )
        return int(self.session.scalar(statement) or 0)

    # -------------------------------------------------------------- friends

    def get_friend(self, user_id: str, friend_id: str) -> UserFriend | None:
        return self.session.get(UserFriend, (user_id, friend_id))

    def friend_status(self, user_id: str, friend_id: str) -> str | None:
        friend = self.get_friend(user_id, friend_id)
        return friend.status if friend is not None else None

    def upsert_friend(
        self, user_id: str, friend_id: str, status: str, *, now: int
    ) -> str:
        """Create/update one directed edge. Returns "created" or "updated"."""
        friend = self.get_friend(user_id, friend_id)
        if friend is None:
            self.session.add(
                UserFriend(
                    user_id=user_id,
                    friend_id=friend_id,
                    status=status,
                    created_at=now,
                    updated_at=now,
                )
            )
            self.session.flush()
            return "created"
        friend.status = status
        friend.updated_at = now
        self.session.flush()
        return "updated"

    def list_friends(self, user_id: str, status: str | None = None) -> list[dict[str, Any]]:
        statement = select(
            UserFriend.friend_id,
            UserFriend.status,
            UserFriend.created_at,
            UserFriend.updated_at,
        ).where(UserFriend.user_id == user_id)
        if status is not None:
            statement = statement.where(UserFriend.status == status)
        statement = statement.order_by(UserFriend.friend_id)
        return [dict(row._mapping) for row in self.session.execute(statement)]

    def delete_friend(self, user_id: str, friend_id: str) -> bool:
        result = self.session.execute(
            delete(UserFriend).where(
                UserFriend.user_id == user_id,
                UserFriend.friend_id == friend_id,
            )
        )
        return bool(result.rowcount)

    # ---------------------------------------------------- friend relationships

    def get_friend_relation(self, a: str, b: str) -> str:
        """a's view of the relationship (check order is the priority).

        none | self | friends | pending_out | pending_in | blocked_by_me |
        blocked_me.  Matches the legacy db.get_friend_relation verbatim.
        """
        a, b = str(a or ""), str(b or "")
        if not a or not b:
            return "none"
        if a == b:
            return "self"
        rows = self.session.execute(
            select(UserFriend.user_id, UserFriend.status).where(
                or_(
                    and_(UserFriend.user_id == a, UserFriend.friend_id == b),
                    and_(UserFriend.user_id == b, UserFriend.friend_id == a),
                )
            )
        ).all()
        out_status = in_status = None
        for row in rows:
            if str(row.user_id) == a:
                out_status = row.status
            elif str(row.user_id) == b:
                in_status = row.status
        if out_status == "blocked":
            return "blocked_by_me"
        if in_status == "blocked":
            return "blocked_me"
        if out_status == "accepted" or in_status == "accepted":
            return "friends"
        if out_status == "pending":
            return "pending_out"
        if in_status == "pending":
            return "pending_in"
        return "none"

    def send_friend_request(self, from_uid: str, to_uid: str, *, now: int) -> str:
        """sent | already_friends | already_pending | blocked | self | error."""
        from_uid, to_uid = str(from_uid or ""), str(to_uid or "")
        if not from_uid or not to_uid:
            return "error"
        relation = self.get_friend_relation(from_uid, to_uid)
        if relation == "self":
            return "self"
        if relation in ("blocked_by_me", "blocked_me"):
            return "blocked"
        if relation == "friends":
            return "already_friends"
        if relation in ("pending_out", "pending_in"):
            return "already_pending"
        statement = sqlite_insert(UserFriend).values(
            user_id=from_uid,
            friend_id=to_uid,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        self.session.execute(statement.on_conflict_do_nothing(
            index_elements=["user_id", "friend_id"]
        ))
        self.session.flush()
        return "sent"

    def accept_friend_request(self, me_uid: str, other_uid: str, *, now: int) -> bool:
        """Accept the other -> me pending edge; write both accepted edges at once."""
        me_uid, other_uid = str(me_uid or ""), str(other_uid or "")
        if not me_uid or not other_uid or me_uid == other_uid:
            return False
        if self.get_friend(me_uid, other_uid) is not None:
            existing = self.get_friend(me_uid, other_uid)
            if existing is not None and existing.status == "accepted":
                return True
        pending = self.get_friend(other_uid, me_uid)
        if pending is None or pending.status != "pending":
            return False
        pending.status = "accepted"
        pending.updated_at = now
        for source, target in ((me_uid, other_uid), (other_uid, me_uid)):
            edge = self.get_friend(source, target)
            if edge is None:
                self.session.add(
                    UserFriend(
                        user_id=source,
                        friend_id=target,
                        status="accepted",
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                edge.status = "accepted"
                edge.updated_at = now
        self.session.flush()
        return True

    def remove_friend(self, a_uid: str, b_uid: str) -> bool:
        """Delete the accepted edges in both directions (idempotent)."""
        a_uid, b_uid = str(a_uid or ""), str(b_uid or "")
        if not a_uid or not b_uid:
            return False
        self.session.execute(
            delete(UserFriend).where(
                UserFriend.status == "accepted",
                or_(
                    and_(UserFriend.user_id == a_uid, UserFriend.friend_id == b_uid),
                    and_(UserFriend.user_id == b_uid, UserFriend.friend_id == a_uid),
                ),
            )
        )
        self.session.flush()
        return True

    def remove_friend_request(self, a_uid: str, b_uid: str) -> bool:
        """Delete pending edges in both directions; never touches other states."""
        a_uid, b_uid = str(a_uid or ""), str(b_uid or "")
        if not a_uid or not b_uid:
            return False
        self.session.execute(
            delete(UserFriend).where(
                UserFriend.status == "pending",
                or_(
                    and_(UserFriend.user_id == a_uid, UserFriend.friend_id == b_uid),
                    and_(UserFriend.user_id == b_uid, UserFriend.friend_id == a_uid),
                ),
            )
        )
        self.session.flush()
        return True

    def block_user(self, me_uid: str, other_uid: str, *, now: int) -> bool:
        """Clear pending/accepted in both directions, then write me -> other blocked."""
        me_uid, other_uid = str(me_uid or ""), str(other_uid or "")
        if not me_uid or not other_uid or me_uid == other_uid:
            return False
        self.session.execute(
            delete(UserFriend).where(
                UserFriend.status.in_(["pending", "accepted"]),
                or_(
                    and_(UserFriend.user_id == me_uid, UserFriend.friend_id == other_uid),
                    and_(UserFriend.user_id == other_uid, UserFriend.friend_id == me_uid),
                ),
            )
        )
        edge = self.get_friend(me_uid, other_uid)
        if edge is None:
            self.session.add(
                UserFriend(
                    user_id=me_uid,
                    friend_id=other_uid,
                    status="blocked",
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            edge.status = "blocked"
            edge.updated_at = now
        self.session.flush()
        return True

    def count_friends(self, user_id: str) -> int:
        statement = (
            select(func.count())
            .select_from(UserFriend)
            .where(UserFriend.user_id == user_id, UserFriend.status == "accepted")
        )
        return int(self.session.scalar(statement) or 0)

    def friends_of(self, user_id: str) -> list[dict[str, Any]]:
        statement = (
            select(UserFriend.friend_id, UserFriend.created_at)
            .where(UserFriend.user_id == user_id, UserFriend.status == "accepted")
            .order_by(UserFriend.created_at.desc(), UserFriend.friend_id)
        )
        return [
            {"user_id": str(row.friend_id or ""), "created_at": int(row.created_at or 0)}
            for row in self.session.execute(statement)
            if row.friend_id
        ]

    def incoming_requests(self, user_id: str) -> list[dict[str, Any]]:
        statement = (
            select(UserFriend.user_id, UserFriend.created_at)
            .where(UserFriend.friend_id == user_id, UserFriend.status == "pending")
            .order_by(UserFriend.created_at.desc(), UserFriend.user_id)
        )
        return [
            {"user_id": str(row.user_id or ""), "created_at": int(row.created_at or 0)}
            for row in self.session.execute(statement)
            if row.user_id
        ]

    def outgoing_requests(self, user_id: str) -> list[dict[str, Any]]:
        statement = (
            select(UserFriend.friend_id, UserFriend.created_at)
            .where(UserFriend.user_id == user_id, UserFriend.status == "pending")
            .order_by(UserFriend.created_at.desc(), UserFriend.friend_id)
        )
        return [
            {"user_id": str(row.friend_id or ""), "created_at": int(row.created_at or 0)}
            for row in self.session.execute(statement)
            if row.friend_id
        ]

    def count_requests_since(self, user_id: str, since: int) -> int:
        """Only pending edges count; accepted/rejected requests free the quota."""
        statement = (
            select(func.count())
            .select_from(UserFriend)
            .where(
                UserFriend.user_id == user_id,
                UserFriend.status == "pending",
                UserFriend.created_at >= int(since),
            )
        )
        return int(self.session.scalar(statement) or 0)

    # ------------------------------------------------------- friend messages

    def add_friend_message(
        self, from_uid: str, to_uid: str, body: str, *, created_at: int
    ) -> int:
        message = FriendMessage(
            from_uid=from_uid, to_uid=to_uid, body=body, created_at=created_at, read_at=0
        )
        self.session.add(message)
        self.session.flush()
        return int(message.id)

    def list_friend_messages(
        self,
        me: str,
        other: str,
        *,
        limit: int = 50,
        before_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Oldest first (the UI appends); fetch newest N then reverse."""
        if not me or not other:
            return []
        safe_limit = min(max(1, int(limit)), 100)
        statement = (
            select(
                FriendMessage.id,
                FriendMessage.from_uid,
                FriendMessage.to_uid,
                FriendMessage.body,
                FriendMessage.created_at,
                FriendMessage.read_at,
            )
            .where(
                or_(
                    and_(FriendMessage.from_uid == me, FriendMessage.to_uid == other),
                    and_(FriendMessage.from_uid == other, FriendMessage.to_uid == me),
                )
            )
            .order_by(FriendMessage.id.desc())
            .limit(safe_limit)
        )
        if before_id is not None:
            statement = statement.where(FriendMessage.id < int(before_id))
        rows = list(self.session.execute(statement))
        return [dict(row._mapping) for row in reversed(rows)]

    def unread_count(self, to_uid: str) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(FriendMessage)
                .where(FriendMessage.to_uid == to_uid, FriendMessage.read_at == 0)
            )
            or 0
        )

    def count_unread_messages(self, me: str, other: str | None = None) -> int:
        statement = select(func.count()).select_from(FriendMessage).where(
            FriendMessage.to_uid == me, FriendMessage.read_at == 0
        )
        if other:
            statement = statement.where(FriendMessage.from_uid == other)
        return int(self.session.scalar(statement) or 0)

    def unread_by_friend(self, me: str) -> dict[str, int]:
        statement = (
            select(FriendMessage.from_uid, func.count())
            .where(FriendMessage.to_uid == me, FriendMessage.read_at == 0)
            .group_by(FriendMessage.from_uid)
        )
        return {
            str(sender): int(count)
            for sender, count in self.session.execute(statement)
            if sender and int(count) > 0
        }

    def has_more_friend_messages(self, me: str, other: str, before_id: int) -> bool:
        statement = (
            select(FriendMessage.id)
            .where(
                or_(
                    and_(FriendMessage.from_uid == me, FriendMessage.to_uid == other),
                    and_(FriendMessage.from_uid == other, FriendMessage.to_uid == me),
                ),
                FriendMessage.id < int(before_id),
            )
            .limit(1)
        )
        return self.session.scalar(statement) is not None

    def count_friend_messages_since(self, from_uid: str, since: int) -> int:
        statement = (
            select(func.count())
            .select_from(FriendMessage)
            .where(
                FriendMessage.from_uid == from_uid,
                FriendMessage.created_at >= int(since),
            )
        )
        return int(self.session.scalar(statement) or 0)

    def get_friend_message(self, message_id: int) -> dict[str, Any] | None:
        message = self.session.get(FriendMessage, int(message_id))
        if message is None:
            return None
        return {
            "id": int(message.id),
            "from_uid": str(message.from_uid or ""),
            "to_uid": str(message.to_uid or ""),
            "body": str(message.body or ""),
            "created_at": int(message.created_at or 0),
            "read_at": int(message.read_at or 0),
        }

    def mark_friend_messages_read(self, *, to_uid: str, from_uid: str, read_at: int) -> int:
        result = self.session.execute(
            update(FriendMessage)
            .where(
                FriendMessage.to_uid == to_uid,
                FriendMessage.from_uid == from_uid,
                FriendMessage.read_at == 0,
            )
            .values(read_at=read_at)
        )
        return int(result.rowcount or 0)
