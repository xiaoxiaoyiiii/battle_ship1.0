"""调试事件门禁。

旧栈 14 个 `test_*` 事件默认拒绝；只有显式 `ENABLE_TEST_EVENTS=1` 才放行。
新栈保留同样的开关，并且额外支持 `DEBUG_ADMIN_USER_IDS` 白名单（开关打开时
仍只允许名单里的登录账号）。

实现策略：**开关关闭时一个调试 handler 都不注册**；未登记事件由 realtime 的
catch-all 返回明确的 ack 错误（见 `realtime/server.py`），而不是 Socket.IO 的
未知事件静默超时。开关打开后，14 个 handler 才注册，并且仍要过白名单。

本模块只做"事件名 -> 服务方法"的映射；每个调试动作都写在拥有那份状态的
service 里（布船/炮击在 battle、卡牌与效果在 magic、阶段与重置在 gameplay），
所以调试路径与产品路径不会各自长出第二份规则。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from ...contracts.events_in import DEBUG_EVENTS
from ...domain.room import RoomState

if TYPE_CHECKING:
    import socketio

    from ...config import Settings
    from ...infra.metrics import MetricsRegistry

DEBUG_EVENT_DISABLED_MESSAGE = "调试事件未启用"
DEBUG_EVENT_FORBIDDEN_MESSAGE = "调试事件未对你的账号开放"
DEBUG_EVENT_UNIMPLEMENTED_MESSAGE = "调试事件 {event} 尚未实现"

# 事件名 -> 实现。14 个事件全部登记；仍然保留"未登记即明确报错"的兜底，
# 绝不假装成功（旧栈 `test_win_game` 的"成功但毫无反应"就是这种坑）。
DEBUG_IMPLEMENTATIONS: dict[str, Callable[..., Awaitable[Any]]] = {}


async def debug_actor_allowed(
    sio: "socketio.AsyncServer",
    sid: str,
    settings: "Settings",
) -> bool:
    whitelist = settings.debug_admin_user_ids
    if not whitelist:
        return True  # 未配白名单：与旧行为一致（仅本地/自建环境应打开开关）
    try:
        session = await sio.get_session(sid)
    except Exception:
        return False
    user_id = session.get("user_id") if isinstance(session, dict) else None
    return user_id is not None and str(user_id) in whitelist


def _make_handler(
    event: str,
    sio: "socketio.AsyncServer",
    settings: "Settings",
    metrics: "MetricsRegistry",
):
    async def handler(sid: str, data: dict[str, Any] | None = None, *args: Any):
        started = time.perf_counter()
        error = False
        try:
            if not settings.enable_test_events:
                error = True
                return {"status": "error", "message": DEBUG_EVENT_DISABLED_MESSAGE}
            if not await debug_actor_allowed(sio, sid, settings):
                error = True
                return {"status": "error", "message": DEBUG_EVENT_FORBIDDEN_MESSAGE}

            implementation = DEBUG_IMPLEMENTATIONS.get(event)
            if implementation is None:
                error = True
                return {
                    "status": "error",
                    "message": DEBUG_EVENT_UNIMPLEMENTED_MESSAGE.format(event=event),
                }
            result = await implementation(sid, data or {}, sio=sio, settings=settings)
            return result
        finally:
            metrics.record_socket_event(
                event, (time.perf_counter() - started) * 1000, error=error
            )

    return handler


def register_debug_implementations(battle: Any, magic: Any = None,
                                   rooms: Any = None,
                                   gameplay: Any = None) -> None:
    """Map every legacy `test_*` event to the service method that owns it."""

    async def test_win_game(sid: str, data: dict[str, Any], *,
                            sio: "socketio.AsyncServer", settings: "Settings") -> dict:
        return await battle.debug_win(data.get("room_id"), data.get("player_id"))

    async def test_lose_game(sid: str, data: dict[str, Any], *,
                             sio: "socketio.AsyncServer", settings: "Settings") -> dict:
        return await battle.debug_lose(data.get("room_id"), data.get("player_id"))

    async def test_set_player_ships(
        sid: str, data: dict[str, Any], *,
        sio: "socketio.AsyncServer", settings: "Settings",
    ) -> dict:
        return await battle.debug_set_player_ships(
            data.get("room_id"), data.get("player_id"), data.get("ship_count")
        )

    async def test_set_opponent_ships(
        sid: str, data: dict[str, Any], *,
        sio: "socketio.AsyncServer", settings: "Settings",
    ) -> dict:
        return await battle.debug_set_opponent_ships(
            data.get("room_id"), data.get("player_id"), data.get("ship_count")
        )

    async def test_auto_attack(
        sid: str, data: dict[str, Any], *,
        sio: "socketio.AsyncServer", settings: "Settings",
    ) -> dict:
        return await battle.debug_auto_attack(
            data.get("room_id"), data.get("player_id"), data.get("count", 1)
        )

    async def test_get_game_state(
        sid: str, data: dict[str, Any], *,
        sio: "socketio.AsyncServer", settings: "Settings",
    ) -> dict:
        return battle.debug_get_game_state(data.get("room_id"))

    DEBUG_IMPLEMENTATIONS["test_win_game"] = test_win_game
    DEBUG_IMPLEMENTATIONS["test_lose_game"] = test_lose_game
    DEBUG_IMPLEMENTATIONS["test_set_player_ships"] = test_set_player_ships
    DEBUG_IMPLEMENTATIONS["test_set_opponent_ships"] = test_set_opponent_ships
    DEBUG_IMPLEMENTATIONS["test_auto_attack"] = test_auto_attack
    DEBUG_IMPLEMENTATIONS["test_get_game_state"] = test_get_game_state

    if rooms is not None:
        async def test_set_ai_rps_choice(
            sid: str, data: dict[str, Any], *,
            sio: "socketio.AsyncServer", settings: "Settings",
        ) -> dict:
            """Pin the next AI RPS choice (deterministic contract recoding).

            Legacy parity: only an AI room in the RPS phase may be pinned, and
            an illegal choice is rejected instead of being stored.
            """

            room = rooms.get_room(data.get("room_id"))
            choice = data.get("choice")
            if room is None or not getattr(room, "is_ai_room", False) \
                    or room.state != RoomState.ROCK_PAPER_SCISSORS:
                return {"status": "error", "message": "房间不在 AI 猜拳阶段"}
            if choice not in ("rock", "paper", "scissors"):
                return {"status": "error", "message": "无效的出拳"}
            room.test_ai_rps_choice = choice
            return {"status": "success"}

        DEBUG_IMPLEMENTATIONS["test_set_ai_rps_choice"] = test_set_ai_rps_choice

    if magic is not None:
        async def test_add_specific_magic_card(
            sid: str, data: dict[str, Any], *,
            sio: "socketio.AsyncServer", settings: "Settings",
        ) -> dict:
            return await magic.debug_add_card(
                data.get("room_id"), data.get("player_id"), data.get("card_name")
            )

        async def test_add_all_magic_cards(
            sid: str, data: dict[str, Any], *,
            sio: "socketio.AsyncServer", settings: "Settings",
        ) -> dict:
            return await magic.debug_add_all_cards(
                data.get("room_id"), data.get("player_id")
            )

        async def test_clear_all_effects(
            sid: str, data: dict[str, Any], *,
            sio: "socketio.AsyncServer", settings: "Settings",
        ) -> dict:
            return await magic.debug_clear_all_effects(data.get("room_id"))

        async def test_get_multi_area_chain(
            sid: str, data: dict[str, Any], *,
            sio: "socketio.AsyncServer", settings: "Settings",
        ) -> dict:
            return await magic.debug_get_multi_area_chain(
                data.get("room_id"), data.get("player_id")
            )

        async def test_get_magic_cards_list(
            sid: str, data: dict[str, Any], *,
            sio: "socketio.AsyncServer", settings: "Settings",
        ) -> dict:
            return magic.debug_get_magic_cards_list()

        DEBUG_IMPLEMENTATIONS["test_add_specific_magic_card"] = test_add_specific_magic_card
        DEBUG_IMPLEMENTATIONS["test_add_all_magic_cards"] = test_add_all_magic_cards
        DEBUG_IMPLEMENTATIONS["test_clear_all_effects"] = test_clear_all_effects
        DEBUG_IMPLEMENTATIONS["test_get_multi_area_chain"] = test_get_multi_area_chain
        DEBUG_IMPLEMENTATIONS["test_get_magic_cards_list"] = test_get_magic_cards_list

    if gameplay is not None:
        async def test_end_turn(
            sid: str, data: dict[str, Any], *,
            sio: "socketio.AsyncServer", settings: "Settings",
        ) -> dict:
            return await gameplay.debug_end_turn(data.get("room_id"))

        async def test_reset_game(
            sid: str, data: dict[str, Any], *,
            sio: "socketio.AsyncServer", settings: "Settings",
        ) -> dict:
            return await gameplay.debug_reset_game(data.get("room_id"))

        DEBUG_IMPLEMENTATIONS["test_end_turn"] = test_end_turn
        DEBUG_IMPLEMENTATIONS["test_reset_game"] = test_reset_game


def register_debug_handlers(
    sio: "socketio.AsyncServer",
    settings: "Settings",
    metrics: "MetricsRegistry",
) -> None:
    # 默认拒绝：开关没开就完全不注册，避免公网玩家通过 test_* 事件作弊。
    if not settings.enable_test_events:
        return
    for event in DEBUG_EVENTS:
        sio.on(event, _make_handler(event, sio, settings, metrics))
