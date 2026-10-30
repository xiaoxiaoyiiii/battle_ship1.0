"""Profile reads and card writes (ticket #6 privacy + ticket #15 projections).

The privacy contract from DECISIONS D13 is unchanged:

* show_stats / show_fav_cards are only flags -- the stats and favourite-card
  data are still sent, exactly like the legacy /user_stats;
* show_history really does filter the history payload (the legacy endpoint did
  that, and only the server can enforce it);
* show_rank nulls rank_info for other users, but never hides it from oneself;
* missing profile rows fall back to the legacy defaults without writing a row.

Ticket #15 adds the projections the legacy API built from ranks / leveling /
achievements / profile_spec. Rules stay in domain/progression; this module only
assembles facts and applies the read-path cosmetic filter.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..domain.progression import profile_spec
from ..repositories import Database
from .progression import ProgressionService

PROFILE_USER_FIELDS = (
    "id",
    "username",
    "signature",
    "avatar",
    "wins",
    "losses",
    "current_streak",
    "longest_streak",
    "created_at",
)

PUBLIC_STATS_FIELDS = (
    "id",
    "username",
    "wins",
    "losses",
    "current_streak",
    "longest_streak",
    "created_at",
    "signature",
    "avatar",
)

# Same defaults as the legacy db._PROFILE_DEFAULTS (show_history defaults to 0).
PROFILE_DEFAULTS: dict[str, Any] = {
    "title_id": "",
    "tags": [],
    "status_text": "",
    "avatar_alt": "",
    "frame_id": "none",
    "card_bg_id": "deep",
    "profile_bg_id": "deep_ocean",
    "pointer_effect_id": "none",
    "title_effect_id": "glint",
    "show_stats": 1,
    "show_fav_cards": 1,
    "show_history": 0,
    "show_guestbook": 1,
    "show_rank": 1,
    "friend_requests_open": 1,
    "updated_at": 0,
}

_FLAG_FIELDS = (
    "show_stats",
    "show_fav_cards",
    "show_history",
    "show_guestbook",
    "show_rank",
    "friend_requests_open",
)

# Public stats carry exactly the five legacy display flags.  The friend-request
# switch is owner-only (legacy comment: "只下发给本人，不进 public_stats").
_PUBLIC_FLAG_FIELDS = _FLAG_FIELDS[:5]


def _parse_tags(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item) for item in raw if item]
    try:
        data = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in data if item] if isinstance(data, list) else []


def profile_extra(uow, user_id: str) -> dict[str, Any]:
    """Read the profile row, filling legacy defaults in memory (never writing)."""

    row = uow.social.get_profile(user_id) or {}
    data = dict(PROFILE_DEFAULTS)
    data.update({key: value for key, value in row.items() if value is not None})
    data["tags"] = _parse_tags(row.get("tags"))
    data["avatar_alt"] = " ".join(str(data.get("avatar_alt") or "").split())[:160]
    for flag in _FLAG_FIELDS:
        value = row.get(flag)
        data[flag] = int(PROFILE_DEFAULTS[flag] if value is None else value)
    data["updated_at"] = int(row.get("updated_at") or 0)
    return data


def build_own_profile(database: Database, user_id: str) -> dict[str, Any] | None:
    progression = ProgressionService(database)
    with database.unit_of_work() as uow:
        user = uow.users.get(user_id)
        if user is None:
            return None
        profile = {
            field: getattr(user, field, None)
            for field in PROFILE_USER_FIELDS
        }
        extra = profile_extra(uow, user_id)
        unlock_stats = progression.unlock_stats(uow, user_id, user=user)
        title_id, frame_id, card_bg_id = profile_spec.effective_equipped(
            unlock_stats,
            extra.get("title_id"),
            extra.get("frame_id"),
            extra.get("card_bg_id"),
        )
        profile_bg_id, pointer_effect_id, title_effect_id = profile_spec.effective_effects(
            unlock_stats,
            extra.get("profile_bg_id"),
            extra.get("pointer_effect_id"),
            extra.get("title_effect_id"),
        )
        rank = uow.users.wins_rank(user_id)
        badges, badge_count = progression.badge_view(
            uow, user_id, user=user, rank=rank
        )

        profile.update(extra)
        profile.update({
            "rank": rank,
            "counters": uow.stats.get_counters(user_id),
            "name_style": progression.name_style(uow, user_id),
            "level_info": progression.level_view_for(uow, user_id),
            "title_id": title_id,
            "frame_id": frame_id,
            "card_bg_id": card_bg_id,
            "profile_bg_id": profile_bg_id,
            "pointer_effect_id": pointer_effect_id,
            "title_effect_id": title_effect_id,
            "rank_info": progression.rank_view_for(uow, user_id),
            "fav_cards": progression.fav_cards(uow, user_id),
            "catalog": profile_spec.catalog(unlock_stats),
            "effects_catalog": profile_spec.effects_catalog(unlock_stats),
            "achievements": badges,
            "badge_count": badge_count,
        })
        # Interaction counters are read-only here; the viewer is the owner, so
        # "mine" is always false for both kinds (legacy: you cannot like your own
        # card).  The legacy payload is an object, not a bool.
        counts = uow.social.reaction_counts(user_id)
        profile["counts"] = {
            "like": int(counts.get("like") or 0),
            "flower": int(counts.get("flower") or 0),
        }
        profile["mine"] = {"like": False, "flower": False}
        # /api/profile builds its own key set; updated_at is internal bookkeeping
        # and was never part of the legacy response.
        profile.pop("updated_at", None)
    return profile


def public_stats(database: Database, user: Any, viewer_id: str | None,
                 limit: int = 20) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Legacy /user_stats projection with the D13 privacy flags preserved."""

    progression = ProgressionService(database)
    user_id = str(user.id)
    is_self = bool(viewer_id) and str(viewer_id) == user_id
    with database.unit_of_work() as uow:
        stats = {field: getattr(user, field, None) for field in PUBLIC_STATS_FIELDS}
        extra = profile_extra(uow, user_id)
        unlock_stats = progression.unlock_stats(uow, user_id, user=user)
        title_id, frame_id, card_bg_id = profile_spec.effective_equipped(
            unlock_stats,
            extra.get("title_id"),
            extra.get("frame_id"),
            extra.get("card_bg_id"),
        )
        profile_bg_id, pointer_effect_id, title_effect_id = profile_spec.effective_effects(
            unlock_stats,
            extra.get("profile_bg_id"),
            extra.get("pointer_effect_id"),
            extra.get("title_effect_id"),
        )
        stats["rank"] = uow.users.wins_rank(user_id)
        for flag in _PUBLIC_FLAG_FIELDS:
            stats[flag] = extra[flag]
        stats["title_id"] = title_id
        stats["title_name"] = profile_spec.title_name(title_id)
        stats["tags"] = extra["tags"]
        stats["tag_names"] = [profile_spec.tag_name(tag) for tag in extra["tags"]]
        stats["status_text"] = extra["status_text"]
        stats["avatar_alt"] = extra["avatar_alt"]
        stats["frame_id"] = frame_id
        stats["card_bg_id"] = card_bg_id
        stats["profile_bg_id"] = profile_bg_id
        stats["pointer_effect_id"] = pointer_effect_id
        stats["title_effect_id"] = title_effect_id
        # D13: flags are sent for the frontend to draw/hide the section, but the
        # data itself keeps flowing exactly as it did in the legacy stack.
        stats["fav_cards"] = progression.fav_cards(uow, user_id)
        counts = uow.social.reaction_counts(user_id)
        stats["counts"] = {
            "like": int(counts.get("like") or 0),
            "flower": int(counts.get("flower") or 0),
        }
        # Legacy /user_stats put the viewer's own reaction state here (an object
        # with two bools), not a single bool.
        stats["mine"] = uow.social.my_reactions(str(viewer_id or ""), user_id)
        stats["name_style"] = progression.name_style(uow, user_id)
        stats["level_info"] = progression.level_view_for(uow, user_id)
        stats["rank_info"] = (
            progression.rank_view_for(uow, user_id)
            if (is_self or stats["show_rank"])
            else None
        )
        # Legacy /user_stats never sends locked badges -- not even to the owner.
        # The full catalogue is only exposed by /api/achievements and /api/profile.
        badges, badge_count = progression.badge_view(
            uow, user_id, user=user, rank=stats["rank"], unlocked_only=True
        )
        stats["achievements"] = badges
        stats["badge_count"] = badge_count
        if is_self or stats["show_history"]:
            history = uow.matches.history_for_user(user_id, limit)
        else:
            history = []
    return stats, history


def save_profile_card(database: Database, user_id: str,
                      payload: Any) -> tuple[int, dict[str, Any]]:
    """Validate and persist the 11 card fields; reject the whole save on error."""

    if not isinstance(payload, dict):
        return 400, {"success": False, "error": "请求体必须是 JSON 对象"}
    with database.unit_of_work() as uow:
        user = uow.users.get(user_id)
        if user is None:
            return 401, {"success": False, "error": "账号不存在"}
        unlock_stats = ProgressionService(database).unlock_stats(
            uow, user_id, user=user
        )
        fields, errors = profile_spec.validate_payload(payload, unlock_stats)
        if errors:
            return 400, {"success": False, "error": "；".join(errors)}
        stored = dict(fields)
        stored["tags"] = json.dumps(stored.get("tags") or [], ensure_ascii=False)
        uow.social.save_profile(user_id, stored, updated_at=int(time.time()))
    profile = build_own_profile(database, user_id)
    return 200, {"success": True, "profile": profile}


def save_profile_effects(database: Database, user_id: str,
                         payload: Any) -> tuple[int, dict[str, Any]]:
    """保存独立的个人资料背景、指针特效和称号动效槽位。"""

    if not isinstance(payload, dict):
        return 400, {"success": False, "error": "请求体必须是 JSON 对象"}
    with database.unit_of_work() as uow:
        user = uow.users.get(user_id)
        if user is None:
            return 401, {"success": False, "error": "账号不存在"}
        unlock_stats = ProgressionService(database).unlock_stats(
            uow, user_id, user=user
        )
        fields, errors = profile_spec.validate_effects_payload(payload, unlock_stats)
        if errors:
            return 400, {"success": False, "error": "；".join(errors)}
        uow.social.save_profile(user_id, fields, updated_at=int(time.time()))
    profile = build_own_profile(database, user_id)
    return 200, {"success": True, "profile": profile}
