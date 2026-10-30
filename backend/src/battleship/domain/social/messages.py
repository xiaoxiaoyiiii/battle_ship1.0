"""Friend direct messages: pure data and pure functions, no IO.

Ported from the legacy dm.py, which was the single source of the body limit,
the rate window, the display timestamp and the socket push shape. Keeping it
pure is what lets the HTTP route validate while the socket layer only delivers.

The rate state is NOT here: the route counts real rows in the database
(count_friend_messages_since), so one spammer can never consume another
player's quota and a rejected message never takes a slot.
"""

from __future__ import annotations

import time
from typing import Any, Iterable, Mapping

#: Maximum body length in characters (the route rejects, never truncates).
MAX_BODY_LEN = 300
#: Messages per sender per minute.
PER_MINUTE = 20
#: Rate window length in seconds.
RATE_WINDOW_SECONDS = 60
#: Default / maximum page size for a conversation.
PAGE_SIZE = 50
MAX_PAGE_SIZE = 50

#: Frozen socket payload shape for the friend_message push. The HTTP response
#: carries sender-perspective fields (mine / to_uid); the push must not.
PUSH_PAYLOAD_KEYS = (
    "id",
    "from_uid",
    "from_username",
    "from_avatar",
    "body",
    "created_at",
    "stamp",
)

_SHORT_FORMAT = "%m-%d %H:%M"
_FULL_FORMAT = "%Y-%m-%d %H:%M"


def push_payload(message: Mapping[str, Any] | None) -> dict[str, Any]:
    """Trim one message dict to the push shape with JSON-safe values."""
    source = dict(message or {})
    out: dict[str, Any] = {}
    for key in PUSH_PAYLOAD_KEYS:
        raw = source.get(key)
        if key in ("id", "created_at"):
            try:
                out[key] = int(raw or 0)
            except (TypeError, ValueError):
                out[key] = 0
        else:
            out[key] = "" if raw is None else str(raw)
    return out


def normalize_body(text: Any) -> str:
    """Strip control characters, flatten newlines, trim. Never truncates."""
    if not isinstance(text, str):
        return ""
    cleaned = "".join(ch for ch in text if ch == "\n" or ord(ch) >= 32)
    return cleaned.replace("\n", " ").strip()


def body_error(text: str) -> str:
    """Return the legacy rejection text, or empty when the body is valid."""
    if not text:
        return "消息不能为空"
    if len(text) > MAX_BODY_LEN:
        return f"消息最多 {MAX_BODY_LEN} 字（当前 {len(text)} 字）"
    return ""


def too_long(text: str) -> bool:
    return len(text or "") > MAX_BODY_LEN


def check_rate(timestamps: Iterable[Any], now: float | None = None) -> bool:
    """True = reject: PER_MINUTE messages already sent inside the window."""
    current = time.time() if now is None else now
    count = 0
    for stamp in timestamps or ():
        try:
            if current - float(stamp) < RATE_WINDOW_SECONDS:
                count += 1
        except (TypeError, ValueError):
            continue
    return count >= PER_MINUTE


def stamp(epoch: Any, now: float | None = None) -> str:
    """Display timestamp: short inside the current year, full across years."""
    try:
        value = int(epoch)
    except (TypeError, ValueError):
        return ""
    try:
        when = time.localtime(value)
    except (OverflowError, OSError, ValueError):
        return ""
    reference = time.time() if now is None else now
    try:
        reference_year = time.localtime(reference).tm_year
    except (OverflowError, OSError, ValueError):
        reference_year = when.tm_year
    fmt = _SHORT_FORMAT if when.tm_year == reference_year else _FULL_FORMAT
    return time.strftime(fmt, when)


def conversation_key(me: Any, other: Any) -> tuple[str, str]:
    """Conversation identity (log/debug only; there is no conversation table)."""
    return tuple(sorted((str(me or ""), str(other or ""))))  # type: ignore[return-value]
