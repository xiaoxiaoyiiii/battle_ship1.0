"""Frozen legacy HTTP route register (the 49 routes of port map note 11).

This module is the *only* place that states which legacy route names are part of
the migration contract. The executable definition still lives in the FastAPI
routers (that is what actually serves traffic), but the route-coverage gate reads
this tuple to prove, one method/path at a time, that:

* all 46 routes from the legacy `api.py` plus the 3 from `server.py`
  (`/api/online_count`, `/api/home_stats`, `/lobby`) are still served;
* no route name was added or renamed (the list is frozen);
* the page entry points keep returning the legacy SPA shell.

Adding a route here without a router (or renaming one) is a contract break, not
a refactor. New rewrite-only routes (health, metrics, contract schema, /legacy)
are deliberately not listed -- they are additive and were never part of the
frozen client surface.

Auth classes:
  public  -- anonymous is enough (a signed session is optional)
  login   -- a valid session cookie is required (401 otherwise)
  admin   -- login + DEBUG_ADMIN_USER_IDS allowlist (403 otherwise)
  local   -- loopback-only for the interactive part (the legacy behaviour)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LegacyRoute:
    methods: tuple[str, ...]
    path: str
    auth: str
    domain: str
    origin: str


LEGACY_ROUTES: tuple[LegacyRoute, ...] = (
    # ---------------------------------------------------------- pages/session
    LegacyRoute(("GET",), "/", "public", "pages", "api.py:index"),
    LegacyRoute(("GET", "POST"), "/register", "public", "pages", "api.py:register"),
    LegacyRoute(("GET", "POST"), "/login", "public", "pages", "api.py:login"),
    LegacyRoute(("GET",), "/logout", "public", "pages", "api.py:logout"),
    LegacyRoute(("GET",), "/leaderboard", "public", "pages", "api.py:leaderboard"),
    LegacyRoute(("GET",), "/lobby", "public", "pages", "server.py:lobby"),
    LegacyRoute(("POST",), "/api/login", "public", "auth", "api.py:api_login"),
    # ------------------------------------------------------------- profile
    LegacyRoute(("GET",), "/user_stats", "public", "stats", "api.py:user_stats_view"),
    LegacyRoute(("GET",), "/api/profile", "login", "profile", "api.py:get_profile"),
    LegacyRoute(("POST",), "/api/profile/card", "login", "profile", "api.py:save_profile_card"),
    LegacyRoute(("POST",), "/api/profile/signature", "login", "profile", "api.py:update_signature"),
    LegacyRoute(("POST",), "/api/profile/avatar", "login", "profile", "api.py:upload_avatar"),
    LegacyRoute(("POST",), "/api/change_password", "login", "auth", "api.py:change_password"),
    LegacyRoute(("GET",), "/api/achievements", "login", "progression", "api.py:achievements_view"),
    LegacyRoute(("POST",), "/api/profile/like", "login", "profile", "api.py:profile_like"),
    LegacyRoute(("GET",), "/api/profile/messages", "login", "profile", "api.py:profile_messages"),
    LegacyRoute(("POST",), "/api/profile/message", "login", "profile", "api.py:post_profile_message"),
    LegacyRoute(("POST",), "/api/profile/message/delete", "login", "profile", "api.py:delete_profile_message"),
    # ------------------------------------------------------ privacy/replay
    LegacyRoute(("GET",), "/api/spectate/setting", "login", "spectate", "api.py:get_spectate_setting"),
    LegacyRoute(("POST",), "/api/spectate/setting", "login", "spectate", "api.py:save_spectate_setting"),
    LegacyRoute(("GET",), "/api/replay/setting", "login", "replay", "api.py:get_replay_setting"),
    LegacyRoute(("POST",), "/api/replay/setting", "login", "replay", "api.py:save_replay_setting"),
    LegacyRoute(("GET",), "/api/replay/{match_id}", "login", "replay", "api.py:get_match_replay"),
    # ------------------------------------------------------ public reads
    LegacyRoute(("GET",), "/api/leaderboard", "public", "leaderboard", "api.py:api_leaderboard"),
    LegacyRoute(("GET",), "/api/ranked_leaderboard", "public", "leaderboard", "api.py:api_ranked_leaderboard"),
    LegacyRoute(("GET",), "/api/rank_constants", "public", "progression", "api.py:api_rank_constants"),
    LegacyRoute(("GET",), "/api/card_usage", "public", "stats", "api.py:api_card_usage"),
    LegacyRoute(("GET",), "/api/quick_chat", "public", "chat", "api.py:api_quick_chat"),
    LegacyRoute(("GET",), "/api/changelog", "public", "changelog", "api.py:api_changelog"),
    LegacyRoute(("GET",), "/api/online_count", "public", "lobby", "server.py:api_online_count"),
    LegacyRoute(("GET",), "/api/home_stats", "public", "lobby", "server.py:api_home_stats"),
    # ------------------------------------------------------------- wallpaper
    LegacyRoute(("GET",), "/api/wallpapers", "local", "wallpapers", "api.py:api_wallpapers"),
    LegacyRoute(("POST",), "/api/wallpaper/scan_path", "local", "wallpapers", "api.py:api_wallpaper_scan_path"),
    LegacyRoute(("GET",), "/api/wallpaper/media/{wid}", "public", "wallpapers", "api.py:api_wallpaper_media"),
    LegacyRoute(("GET",), "/api/wallpaper/preview/{wid}", "public", "wallpapers", "api.py:api_wallpaper_preview"),
    # ---------------------------------------------------------------- friends
    LegacyRoute(("GET",), "/api/friends", "login", "friends", "api.py:api_friends_list"),
    LegacyRoute(("POST",), "/api/friends/request", "login", "friends", "api.py:api_friend_request"),
    LegacyRoute(("POST",), "/api/friends/respond", "login", "friends", "api.py:api_friend_respond"),
    LegacyRoute(("POST",), "/api/friends/remove", "login", "friends", "api.py:api_friend_remove"),
    LegacyRoute(("POST",), "/api/friends/block", "login", "friends", "api.py:api_friend_block"),
    LegacyRoute(("POST",), "/api/friends/invite", "login", "friends", "api.py:api_friend_invite"),
    LegacyRoute(("GET",), "/api/friends/messages", "login", "friends", "api.py:api_friend_messages"),
    LegacyRoute(("POST",), "/api/friends/messages", "login", "friends", "api.py:api_friend_message_send"),
    LegacyRoute(("POST",), "/api/friends/messages/read", "login", "friends", "api.py:api_friend_messages_read"),
    # ------------------------------------------------------------------ admin
    LegacyRoute(("GET",), "/api/admin/suspicion", "admin", "admin", "api.py:admin_suspicion_list"),
    LegacyRoute(("GET",), "/api/admin/player/{uid}", "admin", "admin", "api.py:admin_player_detail"),
    LegacyRoute(("POST",), "/api/admin/player/{uid}/override", "admin", "admin", "api.py:admin_player_override"),
    LegacyRoute(("GET",), "/api/admin/player/{uid}/history", "admin", "admin", "api.py:admin_player_history"),
    LegacyRoute(("GET",), "/api/admin/me", "public", "admin", "api.py:admin_me"),
)

__all__ = ["LEGACY_ROUTES", "LegacyRoute"]
