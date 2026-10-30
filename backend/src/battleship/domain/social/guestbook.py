"""Profile guestbook and reactions: pure rules, no IO (ticket #19).

Ported from the legacy `api.py` helpers so the limits, the on/off coercion and
the public message shape exist exactly once:

* single guestbook message: at most 100 characters, never silently truncated;
* same author -> same page: at most 20 messages per local calendar day;
* reaction kinds are exactly `like` / `flower`;
* deleting is allowed for the message author or the page owner;
* reaction counts are "popularity", never hidden by the guestbook privacy flag.
"""

from __future__ import annotations

import re
import time
from typing import Any, Mapping

KINDS: tuple[str, ...] = ("like", "flower")
MAX_CONTENT_LEN = 100
DAILY_LIMIT = 20
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50

# C0 (except tab/newline) and C1 control characters. Newlines are kept: the
# guestbook is a multi-line textarea and eating them collapses the layout.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def clean_content(raw: Any) -> str:
    text = "" if raw is None else str(raw)
    return _CONTROL_CHARS.sub("", text).strip()


def content_error(content: str) -> str:
    if not content:
        return "留言内容不能为空"
    if len(content) > MAX_CONTENT_LEN:
        return f"留言不能超过 {MAX_CONTENT_LEN} 字（当前 {len(content)} 字）"
    return ""


def reaction_on(raw: Any) -> bool:
    """Legacy coercion: truthy values mean "add", everything else "remove"."""
    if isinstance(raw, str):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return bool(raw)


def page_size(raw: Any) -> int:
    try:
        value = int(raw or DEFAULT_PAGE_SIZE)
    except (TypeError, ValueError):
        value = DEFAULT_PAGE_SIZE
    return max(1, min(value, MAX_PAGE_SIZE))


def before_id(raw: Any) -> int | None:
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def reaction_view(counts: Mapping[str, Any], mine: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "counts": {
            "like": int(counts.get("like") or 0),
            "flower": int(counts.get("flower") or 0),
        },
        "mine": {
            "like": bool(mine.get("like")),
            "flower": bool(mine.get("flower")),
        },
    }


def public_message(message: Mapping[str, Any], viewer_uid: str | None,
                   owner_uid: str | None) -> dict[str, Any]:
    """Wire shape plus the server-computed `can_delete` (never client-side)."""
    author = str(message.get("from_user_id") or message.get("from_uid") or "")
    return {
        "id": int(message.get("id") or 0),
        "from_name": message.get("from_name") or "匿名",
        "content": message.get("content") or "",
        "created_at": int(message.get("created_at") or 0),
        "can_delete": bool(viewer_uid) and (viewer_uid == author or viewer_uid == owner_uid),
    }


def day_start_ts(now: float | None = None) -> int:
    """Local midnight (the player's sense of "today", not a rolling 24h)."""
    current = time.time() if now is None else now
    local = time.localtime(current)
    return int(time.mktime((local.tm_year, local.tm_mon, local.tm_mday, 0, 0, 0, 0, 0, -1)))
