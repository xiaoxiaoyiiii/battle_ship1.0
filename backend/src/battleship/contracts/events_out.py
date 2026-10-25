"""Socket.IO 出站事件清单、事件信封与 ack 形状。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# 旧栈服务端 -> 客户端事件（从 server.py 的 emit('...') 字面量冻结而来）。
OUTBOUND_EVENTS: tuple[str, ...] = (
    "achievements_unlocked",
    "active_effects",
    "attack_result",
    "attacks_updated",
    "board_attacks_updated",
    "chain_request",
    "chain_resolved",
    "chat_message",
    "dice_discard_complete",
    "dice_discard_request",
    "dice_rolled",
    "error",
    "field_magic_updated",
    "frozen_area",
    "game_canceled",
    "game_log",
    "game_message",
    "game_over",
    "game_state",
    "hand_updated",
    "holy_heart_activated",
    "holy_heart_interrupted",
    "holy_heart_turn_updated",
    "lanyu_recalled",
    "last_stand_cells",
    "lingqi_complete",
    "lingqi_waiting",
    "lobby_chat",
    "lobby_chat_history",
    "lobby_hello",
    "lobby_state",
    "magic_chain_updated",
    "match_canceled",
    "match_queued",
    "message",
    "opponent_disconnected",
    "opponent_reconnected",
    "phase_updated",
    "placement_done",
    "placement_request",
    "player_ships_updated",
    "priority_request",
    "priority_setting_updated",
    "priority_waiting",
    "priority_waiting_end",
    "quick_chat",
    "rank_changed",
    "reconnect_token",
    "reconnect_warning",
    "reinforcement_activated",
    "reinforcement_turn_updated",
    "reset_gameboard",
    "resume_game",
    "revealed_positions",
    "revived_positions",
    "room_sync",
    "rps_result",
    "sacrifice_cancelled",
    "sacrifice_request",
    "shenji_waiting",
    "shenji_waiting_end",
    "shenwei_hole",
    "shenwei_hole_restored",
    "shield_absorbed",
    "shields_added",
    "ship_sacrificed",
    "ships_updated",
    "spectate_board",
    "spectate_chat",
    "spectate_count_changed",
    "spectate_ended",
    "spectate_roster",
    "spectate_sync",
    "spectate_you",
    "taoyuan_complete",
    "taoyuan_waiting",
    "trap_expired",
    "trap_set",
    "trap_triggered",
    "turn_change",
    "turn_skipped",
    "wangyang_complete",
    "xp_gained",
)


#: Events emitted through parameterised helpers (socketio.emit(name, ...)), so a
#: freeze built from emit('...') literals could not see them. They are recorded
#: legacy events (port map 10 sections 4.3 and 3.4), not new names; they are
#: listed separately so OUTBOUND_EVENTS keeps its frozen 82 entries.
#: Ticket #14 delivers the friend pushes; ticket #17 delivers the spectator
#: presence announcements. Total outbound baseline (D21): 82 + 7 = 89.
PARAMETERISED_OUTBOUND_EVENTS: tuple[str, ...] = (
    "friend_request",
    "friend_accepted",
    "friend_invite",
    "friend_message",
    "recent_opponent",
    "spectate_joined",
    "spectate_left",
)


class OutboundEventEnvelope(BaseModel):
    """出站信封。to 与 room 都是 Socket.IO 的目标语义，二者可只填一个。"""

    event: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)
    namespace: str = "/"
    to: str | None = None
    room: str | None = None
    skip_sid: str | None = None


class RoomSync(BaseModel):
    """The reconnect snapshot (`room_sync`).

    Frozen at the top-level keys below: the recorded legacy `_build_room_sync`
    (server.py:10498-10639) 45 keys in their original order, plus the additive
    fields: ticket #43 (`turn_deadline`, `turn_timeout_seconds`,
    `opponent_ready`, `opponent_online`) and `opponent_registered`.
    The legacy client reads every legacy key; a missing legacy key shows up as a blank board/hand after reconnect.
    The model is the single freeze point, and additions are appended so the
    recorded key order stays a prefix.
    """

    room_id: str
    state: str
    current_phase: str | None
    current_attacker: str
    attacks_remaining: int
    round: int
    attack_order: list[str]
    player_id: str
    player_seat: str
    player_name: str | None
    opponent_name: str | None
    is_ai_room: bool
    ranked: bool
    mode: str
    winner: str
    game_over_reason: str | None
    field_magic: str
    remaining_ships: int
    ships: list[dict[str, Any]]
    opponent_shielded_ships: list[list[dict[str, Any]]]
    hand: list[dict[str, Any]]
    attacks: list[dict[str, Any]]
    opponent_attacks: list[dict[str, Any]]
    opponent_remaining_ships: int
    shenwei_holes: list[Any]
    chain: dict[str, Any]
    chain_waiting: bool
    chain_window: str | None
    priority_waiting: dict[str, Any] | None
    shenji_waiting: dict[str, Any] | None
    active_effects: list[str]
    last_stand_lock: bool
    last_stand_win: bool
    # `self`/`opponent` are badge lists; `field` is the public card payload
    # and `field_owner` is its caster.  They travel together so a reconnect
    # snapshot cannot overwrite the live `active_effects` frame with a
    # field-less shape.
    effect_badges: dict[str, Any]
    pending_placement: dict[str, Any] | None
    pending_placement_blocked: list[dict[str, Any]]
    pending_placement_allowed: list[Any]
    last_stand_cells: list[dict[str, Any]]
    last_stand_owner: str | None
    frozen_area: dict[str, Any] | None
    magic_blocked: bool
    effect_flags: dict[str, Any]
    pending_sacrifice: dict[str, Any] | None
    pending_sacrifice_ships: list[dict[str, Any]]
    rps_choices: dict[str, str]
    # Ticket #43 (additive): the countdown's single truth is the watchdog's own
    # anchor (`turn_started_at`) plus the configured timeout, so the client
    # never derives a second deadline. Both fields are always present;
    # `turn_deadline` is null when no timed turn is running.
    turn_deadline: int | None
    turn_timeout_seconds: int
    # Ticket #43 (additive): placement / RPS waiting visibility. Derived from
    # the existing seat + disconnect state; no new state machine.
    opponent_ready: bool
    opponent_online: bool
    # 新增字段：对手座位是登录账号（由服务端可信判定，不来自客户端自述）。
    opponent_registered: bool
    # 重连恢复：整盘重布要知道布船数量与「这盘已经作废」；
    # `magic_temp` 只回给发起者（对手/观战为 None），`dice_discard_pending`
    # 同理只回给正在等弃牌的本人。
    max_ships: int
    needs_reset: bool
    reset_allowed_cells: list[dict[str, int]] | None
    interaction_waiting: str | None
    magic_temp: dict[str, Any] | None
    dice_discard_pending: bool


#: Authoritative key order/count for the reconnect snapshot.
ROOM_SYNC_KEYS: tuple[str, ...] = tuple(RoomSync.model_fields)


class AckResponse(BaseModel):
    """Socket.IO ack 的通用形状；旧前端按 status 判断成功/失败。

    Ticket #52 removed the optional `code` this ack declared: nothing
    produced it, so it was a dead contract slot. Stable codes ride the
    `error` frame (contracts.errors) and the frontend maps them there.
    """

    status: Literal["success", "error"] = "success"
    message: str | None = None
    data: dict[str, Any] | None = None
