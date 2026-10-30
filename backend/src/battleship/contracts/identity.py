"""座位 / player_id / sid 的身份语义（唯一一份，realtime 与 http 共用）。

旧栈的两套 key 约定（见 CLAUDE.md §6）必须原样保留：

* 自定义房 / 人机房：登录用户 = session user_id，游客 = 入队时的 socket sid；
* 匹配房：座位 key **一律**是入队时的 socket sid，真实 user_id 只存 Player.user_id。

客户端自己的 `sio.sid` 与匹配房座位 key 不一定相同，因此客户端只能使用
服务端下发的 `player_id`；任何"我自己算一个 id"的行为都在这里被拒绝。
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

SPECTATE_ROOM_PREFIX = "spectate:"


class RoomKind(str, Enum):
    """房间类型决定座位 key 的生成方式。"""

    MATCHMAKING = "matchmaking"
    CUSTOM = "custom"
    AI = "ai"
    SPECTATE = "spectate"


class SocketIdentity(BaseModel):
    """一次连接上可信的身份事实（由服务端会话/座位记录填充）。"""

    player_id: str | None = None
    user_id: int | str | None = None


class IdentityClaim(BaseModel):
    """客户端 payload 里声明的身份。永远只是 claim，不是事实。"""

    player_id: str | None = None
    user_id: int | str | None = None


class SeatIdentity(BaseModel):
    """服务端座位记录。player_id 是 room.players 的 key。"""

    room_id: str
    room_kind: RoomKind
    player_id: str
    user_id: int | str | None = None
    socket_id: str | None = None
    seat: int | None = Field(default=None, ge=0, le=1)


# 旧代码里的名字；保留别名让迁移期的调用点读起来一致。
SeatRecord = SeatIdentity


class IdentityDecision(BaseModel):
    """身份校验结果。失败必须带可区分的原因码，不能静默返回 None。"""

    ok: bool
    code: Literal[
        "ok",
        "player_id_mismatch",
        "user_id_mismatch",
        "session_mismatch",
        "seat_socket_unknown",
        "socket_mismatch",
    ] = "ok"
    detail: str | None = None


def build_player_key(room_kind: RoomKind, *, user_id: int | str | None, socket_id: str) -> str:
    """按旧栈规则生成座位 key。

    匹配房永远用入队 sid；自定义/人机房优先登录 user_id，游客退回 sid。
    AI 座位不走这里（见 :func:`ai_player_id`）。
    """
    if room_kind is RoomKind.MATCHMAKING:
        return socket_id
    if room_kind is RoomKind.AI:
        raise ValueError("AI 座位请使用 ai_player_id(room_id)")
    if room_kind is RoomKind.SPECTATE:
        raise ValueError("观众不是座位，禁止生成 player key")
    if user_id is not None:
        return str(user_id)
    return socket_id


def ai_player_id(room_id: str) -> str:
    """人机房 AI 座位 id：旧栈固定为 `ai-<room_id>`。"""

    return f"ai-{room_id}"


def spectate_room_name(room_id: str) -> str:
    """观众房间名。观众只进这个房间，绝不进对局 room。"""

    if room_id.startswith(SPECTATE_ROOM_PREFIX):
        return room_id
    return f"{SPECTATE_ROOM_PREFIX}{room_id}"


def is_spectate_room(name: str) -> bool:
    return name.startswith(SPECTATE_ROOM_PREFIX)


def verify_identity(
    claim: IdentityClaim,
    seat: SeatIdentity,
    *,
    session_user_id: int | str | None,
    current_socket_id: str | None,
) -> IdentityDecision:
    """校验一次操作是否由座位本人发出。

    * player_id 必须等于服务端座位 key；
    * 登录态 claim 必须同时等于座位 user_id 与当前 session user_id；
    * 有请求上下文时必须校验"座位登记的 sid == 当前连接"；
    * `current_socket_id is None` 表示无请求上下文（单测/后台重放），
      此时跳过连接校验 —— 这是旧栈 `_identity_ok` 的既有口子，不是漏洞。
    """

    if not claim.player_id or claim.player_id != seat.player_id:
        return IdentityDecision(ok=False, code="player_id_mismatch",
                                detail="player_id 与服务端座位不一致")

    if claim.user_id is not None:
        if seat.user_id is not None and claim.user_id != seat.user_id:
            return IdentityDecision(ok=False, code="user_id_mismatch",
                                    detail="登录用户与座位登记不一致")
        if session_user_id is not None and claim.user_id != session_user_id:
            return IdentityDecision(ok=False, code="session_mismatch",
                                    detail="登录态 claim 与当前 session 不一致")

    if session_user_id is not None and seat.user_id is not None and session_user_id != seat.user_id:
        return IdentityDecision(ok=False, code="session_mismatch",
                                detail="当前 session 不属于该座位")

    if current_socket_id is not None:
        if not seat.socket_id:
            return IdentityDecision(ok=False, code="seat_socket_unknown",
                                    detail="座位没有登记 socket，无法校验当前连接")
        if seat.socket_id != current_socket_id:
            return IdentityDecision(ok=False, code="socket_mismatch",
                                    detail="座位登记的 sid 与当前连接不一致")

    return IdentityDecision(ok=True)