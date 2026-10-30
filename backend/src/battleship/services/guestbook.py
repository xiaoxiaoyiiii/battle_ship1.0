"""Guestbook / reaction use cases (ticket #19).

The route layer only translates HTTP; every read/write and the permission
decision live here so the same rules could be reused by a future client. The
limits and wire shape come from `domain.social.guestbook`.
"""

from __future__ import annotations

import time
from typing import Any

from ..domain.social import guestbook
from ..repositories import Database


class GuestbookService:
    def __init__(self, database: Database) -> None:
        self.database = database

    # ------------------------------------------------------------- reactions

    def reaction_view(self, target_id: str, viewer_id: str | None) -> dict[str, Any]:
        with self.database.unit_of_work() as uow:
            counts = uow.social.reaction_counts(target_id)
            mine = uow.social.my_reactions(viewer_id or "", target_id)
        return guestbook.reaction_view(counts, mine)

    def set_reaction(self, viewer_id: str, target_id: str, kind: str, on: bool) -> bool:
        with self.database.unit_of_work() as uow:
            if on:
                uow.social.add_reaction(
                    viewer_id, target_id, kind, created_at=int(time.time())
                )
            else:
                uow.social.remove_reaction(viewer_id, target_id, kind)
        return True

    # -------------------------------------------------------------- guestbook

    def _show_guestbook(self, uow, owner_id: str) -> bool:
        profile = uow.social.get_profile(owner_id) or {}
        raw = profile.get("show_guestbook")
        return True if raw is None else bool(int(raw))

    def page(self, owner_id: str, viewer_id: str | None, *,
             limit: int = guestbook.DEFAULT_PAGE_SIZE,
             before_id: int | None = None) -> dict[str, Any]:
        is_self = bool(viewer_id) and viewer_id == owner_id
        with self.database.unit_of_work() as uow:
            visible = self._show_guestbook(uow, owner_id)
            counts = uow.social.reaction_counts(owner_id)
            mine = uow.social.my_reactions(viewer_id or "", owner_id)
            if not is_self and not visible:
                result = {"messages": [], "has_more": False, "total": 0}
            else:
                result = uow.social.wall_message_page(
                    owner_id, limit=limit, before_id=before_id
                )
        view = guestbook.reaction_view(counts, mine)
        return {
            "messages": [
                guestbook.public_message(item, viewer_id, owner_id)
                for item in result["messages"]
            ],
            "has_more": bool(result["has_more"]),
            "total": int(result["total"]),
            "guestbook_private": bool(not is_self and not visible),
            **view,
        }

    def add(self, owner_id: str, author_id: str, author_name: str,
            content: str) -> dict[str, Any] | None:
        now = int(time.time())
        with self.database.unit_of_work() as uow:
            message_id = uow.social.add_wall_message(
                to_user_id=owner_id,
                from_user_id=author_id,
                from_name=author_name,
                content=content,
                created_at=now,
            )
            return uow.social.get_wall_message(message_id)

    def count_today(self, author_id: str, owner_id: str) -> int:
        with self.database.unit_of_work() as uow:
            return uow.social.count_wall_messages_since(
                author_id, owner_id, guestbook.day_start_ts()
            )

    def delete(self, message_id: Any, viewer_id: str) -> tuple[int, dict[str, Any]]:
        with self.database.unit_of_work() as uow:
            message = uow.social.get_wall_message(message_id)
            if message is None:
                return 404, {"success": False, "error": "留言不存在"}
            author = message.get("from_user_id") or ""
            owner = message.get("to_user_id") or ""
            if viewer_id not in (author, owner):
                return 403, {"success": False, "error": "你没有权限删除这条留言"}
            uow.social.soft_delete_wall_message(int(message["id"]), owner)
        # Idempotent: deleting an already-deleted message is still success.
        return 200, {"success": True}
