"""Suspicion accumulation and stepped bans (pure functions, no database).

Ported from the old stack's suspicion.py. The old module is the only place that
defines the math; this is the only definition in the new stack, so a threshold
change happens here and nowhere else.

The key invariant is stated in DECISIONS / CLAUDE #27: a ban level is NEVER
stored. match_suspicion stores per-match scores and anticheat_overrides stores an
explicit human decision; the effective level is always recomputed from those two
inputs by effective_level().
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

SCORE_DIVISOR = 5.0
DECAY_HALF_LIFE_DAYS = 14.0
MAX_ACCUMULATED = 1000.0
DECAY_FLOOR = 1e-6

LEVEL_THRESHOLDS = (
    (300.0, 3),  # all room features
    (200.0, 2),  # matchmaking
    (100.0, 1),  # ranked
)

LEVEL_NONE = 0
LEVEL_NO_RANKED = 1
LEVEL_NO_MATCH = 2
LEVEL_NO_ROOM = 3

LEVEL_NAMES = {
    LEVEL_NONE: "正常",
    LEVEL_NO_RANKED: "禁止排位",
    LEVEL_NO_MATCH: "禁止匹配",
    LEVEL_NO_ROOM: "禁止房间",
}

CAP_RANKED = "ranked"
CAP_MATCH = "match"
CAP_ROOM = "room"

_CAP_REQUIRED_MAX_LEVEL = {
    CAP_RANKED: LEVEL_NO_RANKED - 1,
    CAP_MATCH: LEVEL_NO_MATCH - 1,
    CAP_ROOM: LEVEL_NO_ROOM - 1,
}


def decay_factor(age_days: float) -> float:
    try:
        age = max(0.0, float(age_days))
    except (TypeError, ValueError):
        age = 0.0
    return max(DECAY_FLOOR, 0.5 ** (age / DECAY_HALF_LIFE_DAYS))


def match_contribution(match_score: Any, age_days: float = 0.0) -> float:
    try:
        score = float(match_score or 0)
    except (TypeError, ValueError):
        score = 0.0
    if score <= 0:
        return 0.0
    return (score / SCORE_DIVISOR) * decay_factor(age_days)


def accumulate(matches: Iterable[Mapping[str, Any]]) -> float:
    total = 0.0
    for match in matches or ():
        try:
            total += match_contribution(match.get("score"), match.get("age_days", 0.0))
        except Exception:
            continue
    return min(total, MAX_ACCUMULATED)


def level_from_score(score: Any) -> int:
    try:
        value = float(score or 0)
    except (TypeError, ValueError):
        value = 0.0
    for threshold, level in LEVEL_THRESHOLDS:
        if value >= threshold:
            return level
    return LEVEL_NONE


def level_name(level: Any) -> str:
    try:
        return LEVEL_NAMES.get(int(level), "未知")
    except (TypeError, ValueError):
        return "未知"


def next_threshold(score: Any) -> float:
    try:
        value = float(score or 0)
    except (TypeError, ValueError):
        value = 0.0
    for threshold, _level in reversed(LEVEL_THRESHOLDS):
        if value < threshold:
            return round(threshold - value, 1)
    return 0.0


def capability_allowed(level: Any, cap: str) -> bool:
    try:
        value = int(level or 0)
    except (TypeError, ValueError):
        value = 0
    limit = _CAP_REQUIRED_MAX_LEVEL.get(cap)
    if limit is None:
        return True
    return value <= limit


def blocked_capabilities(level: Any) -> list[str]:
    return [cap for cap in (CAP_RANKED, CAP_MATCH, CAP_ROOM)
            if not capability_allowed(level, cap)]


def denial_message(level: Any, cap: str) -> str:
    if capability_allowed(level, cap):
        return ""
    what = {CAP_RANKED: "排位赛", CAP_MATCH: "匹配", CAP_ROOM: "房间"}.get(cap, "该功能")
    return (f"你的账号暂时无法使用{what}。"
            f"这通常是因为系统检测到异常对局。如有疑问请联系管理员。")


def effective_level(score: Any, override: Mapping[str, Any] | None = None) -> int:
    """Effective ban level: an explicit admin override wins, otherwise the score."""
    try:
        if isinstance(override, Mapping):
            if override.get("cleared"):
                return LEVEL_NONE
            if override.get("level") is not None:
                level = int(override["level"])
                return max(0, min(level, LEVEL_NO_ROOM))
    except (TypeError, ValueError):
        pass
    return level_from_score(score)


def match_age_days(created_at: Any, now: float) -> float:
    """Age in days, computed at read time (never stored)."""
    try:
        # Legacy parity: a falsy created_at is treated as "now", not as 1970.
        stamp = float(created_at or now)
    except (TypeError, ValueError):
        stamp = now
    return max(0.0, (now - stamp) / 86400.0)


def build_report(uid: str, matches: Iterable[Mapping[str, Any]],
                 override: Mapping[str, Any] | None = None,
                 username: str | None = None) -> dict[str, Any]:
    score = accumulate(matches)
    level = effective_level(score, override)
    return {
        "user_id": uid,
        "username": username,
        "suspicion": round(score, 1),
        "level": level,
        "level_name": level_name(level),
        "next_threshold": next_threshold(score),
        "blocked": blocked_capabilities(level),
        "overridden": bool(isinstance(override, Mapping) and
                           (override.get("cleared") or override.get("level") is not None)),
        "override_reason": (override or {}).get("reason") if isinstance(override, Mapping) else None,
        "match_count": len(list(matches or ())),
    }
