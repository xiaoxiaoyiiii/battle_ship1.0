"""Socket adapters for magic-card use cases (ticket #10).

Only protocol translation: trusted identity -> MagicService -> ack. Target
selection (area/line/cells) travels inside use_magic_card; the choice channels
(select/confirm/get temp/discard pile) are adapted one-for-one so ticket #11 can
add choice cards without touching the socket layer.
"""

from __future__ import annotations

from typing import Any

import socketio

from ..identity import connection_from_sio
from ...services.magic import MagicService


def register_magic_handlers(sio: socketio.AsyncServer, magic: MagicService) -> None:
    @sio.on("chain_animation_complete")
    async def chain_animation_complete(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await magic.chain_animation_complete(connection, data)

    @sio.on("use_magic_card")
    async def use_magic_card(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await magic.use_magic_card(connection, data)

    @sio.on("select_magic_target")
    async def select_magic_target(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await magic.select_magic_target(connection, data)

    @sio.on("confirm_magic_target")
    async def confirm_magic_target(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await magic.confirm_magic_target(connection, data)

    @sio.on("get_magic_temp_data")
    async def get_magic_temp_data(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await magic.get_magic_temp_data(connection, data)

    @sio.on("get_discard_pile")
    async def get_discard_pile(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await magic.get_discard_pile(connection, data)

    @sio.on("cancel_magic_selection")
    async def cancel_magic_selection(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await magic.cancel_magic_selection(connection, data)

    @sio.on("confirm_reinforcement_position")
    async def confirm_reinforcement_position(
        sid: str, data: dict[str, Any] | None = None
    ) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await magic.confirm_reinforcement_position(connection, data)

    @sio.on("confirm_sacrifice")
    async def confirm_sacrifice(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await magic.confirm_sacrifice(connection, data)

    @sio.on("dice_discard_choose")
    async def dice_discard_choose(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await magic.dice_discard_choose(connection, data)

    @sio.on("confirm_shenji_declare")
    async def confirm_shenji_declare(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await magic.confirm_shenji_declare(connection, data)

    @sio.on("remove_field_magic")
    async def remove_field_magic(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await magic.remove_field_magic(connection, data)

    @sio.on("papal_discard")
    async def papal_discard(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        return await magic.papal_discard(connection, data)

    @sio.on("papal_attack")
    async def papal_attack(sid: str, data: dict[str, Any] | None = None) -> dict:
        connection = await connection_from_sio(sio, sid)
        result = await magic.papal_discard(connection, data)
        if result.get("status") == "success":
            result["message"] = (
                str(result.get("message") or "") + "（旧入口：x/y 已不再使用，请用普通攻击点选格子）"
            )
        return result
