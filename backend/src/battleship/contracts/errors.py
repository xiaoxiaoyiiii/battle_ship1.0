"""Stable, machine-readable socket error codes (ticket #43, catalog #52).

The frontend maps a code to a player-facing sentence and only falls back to the
server `message` when a code is absent (UI redesign spec section 9). Codes are
additive: every existing payload keeps its `message`, and a missing code is a
legitimate legacy shape, not an error.

One catalog only. The wire vocabulary is spelled once (`SOCKET_ERROR_CATALOG`);
the importable constants, `SOCKET_ERROR_CODES` and `__all__` are derived from
it, so a code cannot drift between the error frame (`error`) and the ack.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

#: constant name -> wire code. The single place a code string is written.
#: Group comments mark intent only; order is not a contract.
SOCKET_ERROR_CATALOG: dict[str, str] = {
    # Fallback for an error ack that carries no more specific code yet.
    "OPERATION_FAILED": "operation_failed",
    # Seats / rooms
    "INVALID_SEAT": "invalid_seat",
    "INVALID_ROOM": "invalid_room",
    "ROOM_NOT_FOUND": "room_not_found",
    "ROOM_FULL": "room_full",
    "IDENTITY_FAILED": "identity_failed",
    "GAME_OVER": "game_over",
    "NOT_IN_ROOM": "not_in_room",
    # Placement / RPS / turn
    "PLACEMENT_INVALID": "placement_invalid",
    "NO_PENDING_PLACEMENT": "no_pending_placement",
    "INVALID_RPS_CHOICE": "invalid_rps_choice",
    "OPPONENT_DISCONNECTED": "opponent_disconnected",
    "CHAIN_BUSY": "chain_busy",
    "INVALID_TURN": "invalid_turn",
    # Lobby / matchmaking / spectate
    "NOT_IN_LOBBY": "not_in_lobby",
    "CHAT_TOO_FAST": "chat_too_fast",
    "EMPTY_MESSAGE": "empty_message",
    "ROOM_CREATE_FAILED": "room_create_failed",
    "ALREADY_QUEUED": "already_queued",
    "SPECTATE_DENIED": "spectate_denied",
    # Protocol
    "UNKNOWN_EVENT": "unknown_event",
    "DEBUG_DISABLED": "debug_disabled",
    "DEBUG_FORBIDDEN": "debug_forbidden",
}

OPERATION_FAILED = SOCKET_ERROR_CATALOG["OPERATION_FAILED"]
INVALID_SEAT = SOCKET_ERROR_CATALOG["INVALID_SEAT"]
INVALID_ROOM = SOCKET_ERROR_CATALOG["INVALID_ROOM"]
ROOM_NOT_FOUND = SOCKET_ERROR_CATALOG["ROOM_NOT_FOUND"]
ROOM_FULL = SOCKET_ERROR_CATALOG["ROOM_FULL"]
IDENTITY_FAILED = SOCKET_ERROR_CATALOG["IDENTITY_FAILED"]
GAME_OVER = SOCKET_ERROR_CATALOG["GAME_OVER"]
NOT_IN_ROOM = SOCKET_ERROR_CATALOG["NOT_IN_ROOM"]
PLACEMENT_INVALID = SOCKET_ERROR_CATALOG["PLACEMENT_INVALID"]
NO_PENDING_PLACEMENT = SOCKET_ERROR_CATALOG["NO_PENDING_PLACEMENT"]
INVALID_RPS_CHOICE = SOCKET_ERROR_CATALOG["INVALID_RPS_CHOICE"]
OPPONENT_DISCONNECTED = SOCKET_ERROR_CATALOG["OPPONENT_DISCONNECTED"]
CHAIN_BUSY = SOCKET_ERROR_CATALOG["CHAIN_BUSY"]
INVALID_TURN = SOCKET_ERROR_CATALOG["INVALID_TURN"]
NOT_IN_LOBBY = SOCKET_ERROR_CATALOG["NOT_IN_LOBBY"]
CHAT_TOO_FAST = SOCKET_ERROR_CATALOG["CHAT_TOO_FAST"]
EMPTY_MESSAGE = SOCKET_ERROR_CATALOG["EMPTY_MESSAGE"]
ROOM_CREATE_FAILED = SOCKET_ERROR_CATALOG["ROOM_CREATE_FAILED"]
ALREADY_QUEUED = SOCKET_ERROR_CATALOG["ALREADY_QUEUED"]
SPECTATE_DENIED = SOCKET_ERROR_CATALOG["SPECTATE_DENIED"]
UNKNOWN_EVENT = SOCKET_ERROR_CATALOG["UNKNOWN_EVENT"]
DEBUG_DISABLED = SOCKET_ERROR_CATALOG["DEBUG_DISABLED"]
DEBUG_FORBIDDEN = SOCKET_ERROR_CATALOG["DEBUG_FORBIDDEN"]

#: Every stable code the server may put on the wire (derived; do not edit).
SOCKET_ERROR_CODES: tuple[str, ...] = tuple(SOCKET_ERROR_CATALOG.values())


class SocketError(BaseModel):
    """One error on the socket: the code is stable, the message is for humans."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


def error_detail(code: str, message: str) -> dict[str, str]:
    """The single shape used by both an `error` frame and an operation ack."""

    return {"code": code, "message": message}


__all__ = [
    "SOCKET_ERROR_CATALOG",
    "SOCKET_ERROR_CODES",
    "SocketError",
    "error_detail",
    *SOCKET_ERROR_CATALOG.keys(),
]
