"""In-game quick chat: the frozen phrase table and the rate rule.

The frontend never hardcodes a phrase; GET /api/quick_chat returns this catalog
and the socket event only accepts an id. Rate state lives on the room (the two
players of a room constrain each other), this module only judges.
"""

from __future__ import annotations

from typing import Any

#: Group order is the UI order.
GROUPS = ["开局", "催促", "交手", "被击沉", "投降前", "结束"]

#: Order is the UI order; the texts are frozen (one specific phrase is
#: asserted end-to-end by the legacy acceptance tools).
QUICK_CHAT: list[dict[str, str]] = [
    {"id": "hi", "group": "开局", "text": "你好，开打吧！"},
    {"id": "lets_go", "group": "开局", "text": "来，先手我拿走了"},
    {"id": "hurry_flowers", "group": "催促", "text": "快点儿吧，我等的花都谢了"},
    {"id": "think_fast", "group": "催促", "text": "想好了没呀？"},
    {"id": "nice_shot", "group": "交手", "text": "打得漂亮！"},
    {"id": "oops", "group": "交手", "text": "哎呀，手滑了"},
    {"id": "lucky", "group": "交手", "text": "这运气也没谁了"},
    {"id": "almost", "group": "交手", "text": "就差一点"},
    {"id": "watch_this", "group": "交手", "text": "看我这手"},
    {"id": "ouch", "group": "被击沉", "text": "我的船！"},
    {"id": "surrender_soon", "group": "投降前", "text": "我快撑不住了…"},
    {"id": "gg", "group": "结束", "text": "GG，打得好"},
    {"id": "rematch", "group": "结束", "text": "再来一局？"},
    {"id": "thanks", "group": "结束", "text": "多谢指教"},
]

_BY_ID: dict[str, dict[str, str]] = {item["id"]: item for item in QUICK_CHAT}

WINDOW_SECONDS = 10
MAX_PER_WINDOW = 3


def by_id(msg_id: Any) -> dict[str, str] | None:
    item = _BY_ID.get(msg_id) if isinstance(msg_id, str) else None
    return dict(item) if item else None


def catalog() -> list[dict[str, str]]:
    return [
        {"id": item["id"], "group": item["group"], "text": item["text"]}
        for item in QUICK_CHAT
    ]


def is_valid(msg_id: Any) -> bool:
    return isinstance(msg_id, str) and msg_id in _BY_ID


def _last_of(last: Any) -> tuple[Any, Any]:
    if not last:
        return None, None
    if isinstance(last, dict):
        return last.get("id"), last.get("ts")
    if isinstance(last, (tuple, list)) and len(last) == 2:
        return last[0], last[1]
    return last, None


def _count_in_window(recent: Any, now: float) -> int:
    count = 0
    for value in recent or []:
        try:
            if now - float(value) < WINDOW_SECONDS:
                count += 1
        except (TypeError, ValueError):
            continue
    return count


def check_rate(recent: Any, now: float, last_id: Any,
               msg_id: str, *, noun: str = "快捷语",
               duplicate_reason: str | None = None) -> tuple[bool, str]:
    """Pure judgement: (ok, reason). Rejected messages must not be recorded.

    The rule lives here once (trap #14). Free-text chat passes its own wording
    so the player reads "消息" rather than "快捷语"; the thresholds are shared.
    """
    if _count_in_window(recent, now) >= MAX_PER_WINDOW:
        return False, f"发得太快了，{WINDOW_SECONDS} 秒内最多发 {MAX_PER_WINDOW} 条{noun}"

    last_msg, last_ts = _last_of(last_id)
    if last_msg is not None and last_msg == msg_id:
        if last_ts is None or now - last_ts < WINDOW_SECONDS:
            if duplicate_reason:
                return False, duplicate_reason
            return False, f"同一句{noun} {WINDOW_SECONDS} 秒内不能重复发送"

    return True, ""
