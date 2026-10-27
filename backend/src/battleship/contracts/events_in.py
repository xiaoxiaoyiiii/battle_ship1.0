"""Socket.IO 入站事件清单与事件信封。

事件名是线上协议的一部分，**只增不改**；具体 payload 模型由后续票逐事件补充。
这里先冻结事件清单、调试事件集合与通用信封。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from .identity import SocketIdentity

# 旧栈 14 个仅测试用事件（全部由 @_test_event 包裹）。默认必须拒绝。
DEBUG_EVENTS: tuple[str, ...] = (
    "test_set_ai_rps_choice",
    "test_add_all_magic_cards",
    "test_set_player_ships",
    "test_clear_all_effects",
    "test_add_specific_magic_card",
    "test_get_game_state",
    "test_reset_game",
    "test_set_opponent_ships",
    "test_end_turn",
    "test_win_game",
    "test_lose_game",
    "test_get_multi_area_chain",
    "test_get_magic_cards_list",
    "test_auto_attack",
)

# 旧栈 server.py 注册的全部入站事件（含调试事件与连接生命周期）。
INBOUND_EVENTS: tuple[str, ...] = (
    "connect",
    "disconnect",
    "debug_status",
    "create_room",
    "join_room",
    "create_ai_room",
    "find_match",
    "cancel_match",
    "place_ships",
    "rps_choice",
    "attack",
    "enter_battle_phase",
    "enter_end_phase",
    "end_turn",
    "papal_discard",
    "papal_attack",
    "surrender",
    "chat_message",
    "quick_chat",
    "request_revealed_positions",
    "confirm_reinforcement_position",
    "confirm_sacrifice",
    "cancel_placement",
    "use_magic_card",
    "select_magic_target",
    "confirm_magic_target",
    "cancel_magic_selection",
    "get_magic_temp_data",
    "get_discard_pile",
    "chain_response",
    "chain_animation_complete",
    "remove_field_magic",
    "confirm_shenji_declare",
    "dice_discard_choose",
    "priority_response",
    "set_decline_priority",
    "get_reconnect_token",
    "rejoin_room",
    "request_hand_sync",
    "spectate_join",
    "spectate_leave",
    "spectate_chat_send",
    "lobby_subscribe",
    "lobby_unsubscribe",
    "lobby_refresh",
    "lobby_create_room",
    "lobby_chat_send",
    "close_room",
) + DEBUG_EVENTS


class InboundEventEnvelope(BaseModel):
    """通用入站信封。真实 Socket.IO payload 仍是扁平 dict，由适配层填入信封。"""

    event: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)
    namespace: str = "/"
    identity: SocketIdentity | None = None

    @field_validator("event")
    @classmethod
    def _known_event(cls, value: str) -> str:
        # 拼写错误不能静默变成"未知事件被忽略"；新增事件必须先登记清单。
        if value not in INBOUND_EVENTS:
            raise ValueError(f"未登记的事件名: {value}")
        return value


def is_debug_event(name: str) -> bool:
    return name in DEBUG_EVENTS
