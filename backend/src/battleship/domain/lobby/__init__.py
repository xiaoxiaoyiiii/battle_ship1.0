"""Lobby domain: pure rules for names, statuses and visible waiting rooms."""

from .rules import (
    LOBBY_CHAT_BACKLOG,
    LOBBY_CHAT_MAX_LEN,
    LOBBY_CHAT_MIN_INTERVAL,
    LOBBY_MAX_PLAYERS,
    LOBBY_NAME_MAX_LEN,
    LOBBY_ROOM,
    LOBBY_STATE_TICK_SECONDS,
    STATUS_IDLE,
    STATUS_IN_GAME,
    STATUS_IN_ROOM,
    STATUS_MATCHING,
    chat_text,
    clean_name,
    player_status,
    rooms_by_socket,
    visible_rooms,
)

__all__ = [
    "LOBBY_CHAT_BACKLOG",
    "LOBBY_CHAT_MAX_LEN",
    "LOBBY_CHAT_MIN_INTERVAL",
    "LOBBY_MAX_PLAYERS",
    "LOBBY_NAME_MAX_LEN",
    "LOBBY_ROOM",
    "LOBBY_STATE_TICK_SECONDS",
    "STATUS_IDLE",
    "STATUS_IN_GAME",
    "STATUS_IN_ROOM",
    "STATUS_MATCHING",
    "chat_text",
    "clean_name",
    "player_status",
    "rooms_by_socket",
    "visible_rooms",
]
